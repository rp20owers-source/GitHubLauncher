import hashlib
import io
import json
import threading
import urllib.error
import urllib.request
import zipfile
from email.message import Message
from pathlib import Path
from unittest.mock import Mock

import pytest

import app.core as core
from app.core import (
    GitHubClient,
    InstallHistory,
    download_file,
    find_executable,
    get_github_token,
    parse_github_url,
    safe_extract_zip,
    select_best_asset,
    verify_sha256,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/owner/repo", ("owner", "repo", None)),
        ("https://github.com/owner/repo.git", ("owner", "repo", None)),
        (
            "https://github.com/owner/repo/releases/tag/v1.2.0",
            ("owner", "repo", "v1.2.0"),
        ),
        ("owner/repo", ("owner", "repo", None)),
        ("owner/repo.git", ("owner", "repo", None)),
        ("https://notgithub.com/owner/repo", (None, None, None)),
        ("github.com/owner", (None, None, None)),
        ("https://github.com.evil.example/owner/repo", (None, None, None)),
        ("", (None, None, None)),
    ],
)
def test_parse_github_url(url, expected):
    assert parse_github_url(url) == expected


def _asset(name):
    return {"name": name, "browser_download_url": f"https://downloads.example/{name}"}


def test_select_best_asset_prefers_windows_setup_over_archive_and_other_platforms():
    assets = [
        _asset("app-linux-x64.tar.gz"),
        _asset("app-macos.dmg"),
        _asset("app-arm64-setup.exe"),
        _asset("app-win-x64.zip"),
        _asset("app-win-x64-setup.exe"),
        _asset("app-win-x64.pdb"),
        _asset("app.sha256"),
        _asset("app-win-x64.msi"),
    ]
    assert select_best_asset(assets) == (
        "https://downloads.example/app-win-x64.msi",
        "app-win-x64.msi",
    )


def test_select_best_asset_uses_portable_windows_zip_when_no_installer():
    assets = [
        _asset("app-linux-x64.zip"),
        _asset("app-macos.zip"),
        _asset("app-win-x64.zip"),
        _asset("app-arm64.zip"),
    ]
    assert select_best_asset(assets) == (
        "https://downloads.example/app-win-x64.zip",
        "app-win-x64.zip",
    )


class _Response:
    def __init__(self, value, headers=None):
        self.payload = json.dumps(value).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return self.payload


def _http_error(code):
    return urllib.error.HTTPError(
        "https://api.github.com/test", code, "not found", {}, io.BytesIO()
    )


class _ByteResponse:
    def __init__(self, content):
        self.content = io.BytesIO(content)
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size=-1):
        return self.content.read(size)


def test_latest_404_falls_back_to_prereleases():
    release = {
        "tag_name": "v2.0.0-rc1",
        "assets": [_asset("app-win-x64.zip")],
    }
    opener = Mock(side_effect=[_http_error(404), _Response([release])])
    client = GitHubClient(opener=opener)
    assert client.download_choice("owner", "repo") == (
        "https://downloads.example/app-win-x64.zip",
        "app-win-x64.zip",
        release["assets"],
    )
    assert opener.call_count == 2
    assert "/releases?per_page=5" in opener.call_args.args[0].full_url


def test_missing_latest_and_releases_falls_back_to_zipball():
    opener = Mock(side_effect=[_http_error(404), _http_error(404)])
    client = GitHubClient(opener=opener)
    assert client.download_choice("owner", "repo") == (
        "https://api.github.com/repos/owner/repo/zipball",
        "repo-main.zip",
        [],
    )
    assert opener.call_count == 2


def test_release_without_windows_assets_uses_its_zipball():
    release = {
        "tag_name": "v1",
        "assets": [_asset("app-linux-x64.tar.gz")],
        "zipball_url": "https://api.github.com/repos/owner/repo/zipball/v1",
    }
    client = GitHubClient(opener=Mock(return_value=_Response(release)))
    assert client.download_choice("owner", "repo") == (
        release["zipball_url"],
        "repo-v1.zip",
        release["assets"],
    )


def test_private_release_asset_uses_authenticated_api_download_url():
    asset = {
        "name": "app-win-x64-setup.exe",
        "browser_download_url": "https://github.com/owner/repo/releases/download/v1/setup.exe",
        "url": "https://api.github.com/repos/owner/repo/releases/assets/42",
    }
    release = {"assets": [asset]}
    client = GitHubClient(
        token="test-token", opener=Mock(return_value=_Response(release))
    )

    url, filename, _assets = client.download_choice("owner", "repo", "v1")

    assert url == asset["url"]
    assert filename == asset["name"]
    headers = client.download_headers(url)
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["Accept"] == "application/octet-stream"


def test_api_sends_token_and_reports_rate_limit():
    response = _Response({}, {"X-RateLimit-Remaining": "0"})
    opener = Mock(return_value=response)
    client = GitHubClient(token="test-token", opener=opener)
    client._read_json("https://api.github.com/test")
    request = opener.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer test-token"
    assert client.rate_limit_warning == (
        "GitHub API rate limit reached. Set GITHUB_TOKEN to continue."
    )


def test_github_client_only_sends_download_token_to_github_hosts():
    client = GitHubClient(token="test-token")
    assert (
        client.download_headers(
            "https://github.com/owner/repo/releases/download/v1/app.exe"
        )["Authorization"]
        == "Bearer test-token"
    )
    with pytest.raises(ValueError, match="non-GitHub URL"):
        client.download_headers("https://downloads.example/app.exe")


def test_github_redirect_strips_authorization_on_host_change():
    request = urllib.request.Request(
        "https://github.com/owner/repo/releases/download/v1/app.exe",
        headers={"Authorization": "Bearer test-token"},
    )
    redirected = core._GitHubRedirectHandler().redirect_request(
        request,
        None,
        302,
        "Found",
        Message(),
        "https://release-assets.githubusercontent.com/app.exe",
    )
    assert redirected is not None
    assert redirected.get_header("Authorization") is None


def test_get_github_token_falls_back_to_authenticated_cli(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(core.shutil, "which", lambda _name: "gh")
    run = Mock(return_value=Mock(returncode=0, stdout="cli-token\n"))
    monkeypatch.setattr(core.subprocess, "run", run)

    assert get_github_token() == "cli-token"
    run.assert_called_once_with(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_download_file_writes_chunks_and_reports_progress(tmp_path):
    destination = tmp_path / "Downloads" / "asset.exe"
    response = _ByteResponse(b"installer-data")
    progress = []
    assert download_file(
        "https://github.com/downloads/asset.exe",
        destination,
        progress=lambda downloaded, total: progress.append((downloaded, total)),
        opener=Mock(return_value=response),
    ) == len(b"installer-data")
    assert destination.read_bytes() == b"installer-data"
    assert progress[-1] == (len(b"installer-data"), len(b"installer-data"))


def test_download_file_removes_partial_file_on_cancel(tmp_path):
    destination = tmp_path / "asset.exe"
    cancel_event = threading.Event()
    cancel_event.set()
    with pytest.raises(InterruptedError, match="Download canceled"):
        download_file(
            "https://github.com/downloads/asset.exe",
            destination,
            cancel_event=cancel_event,
            opener=Mock(return_value=_ByteResponse(b"installer-data")),
        )
    assert not destination.exists()


def test_safe_extract_zip_finds_executable_under_single_root(tmp_path):
    archive_path = tmp_path / "release.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("release/", "")
        archive.writestr("release/MyRepo.exe", b"binary")
        archive.writestr("release/data/config.json", b"{}")
    extracted_root = safe_extract_zip(archive_path, tmp_path / "install")
    assert extracted_root == tmp_path / "install" / "release"
    assert find_executable(extracted_root, "MyRepo") == extracted_root / "MyRepo.exe"


@pytest.mark.parametrize(
    "member_name",
    [
        "../outside.txt",
        "..\\outside.txt",
        "folder\\..\\outside.txt",
        "/outside.txt",
        "C:\\outside.txt",
    ],
)
def test_safe_extract_zip_rejects_traversal(tmp_path, member_name):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(member_name, "do not write")
    destination = tmp_path / "install"
    with pytest.raises(ValueError, match="Unsafe zip member path"):
        safe_extract_zip(archive_path, destination)
    assert not (tmp_path / "outside.txt").exists()
    assert not (Path("C:/") / "outside.txt").exists()


def test_verify_sha256_matches_asset_filename(tmp_path):
    binary = tmp_path / "setup.exe"
    binary.write_bytes(b"installer")
    digest = hashlib.sha256(b"installer").hexdigest()
    assert verify_sha256(binary, f"{digest}  setup.exe\n", "setup.exe")
    assert not verify_sha256(binary, f"{'0' * 64}  setup.exe\n", "setup.exe")


def test_history_deduplicates_and_keeps_last_ten(tmp_path):
    history = InstallHistory(tmp_path / "history.json")
    for index in range(12):
        history.add(f"repo-{index}")
    assert history.add("repo-5") == [
        "repo-5",
        "repo-11",
        "repo-10",
        "repo-9",
        "repo-8",
        "repo-7",
        "repo-6",
        "repo-4",
        "repo-3",
        "repo-2",
    ]
    assert json.loads((tmp_path / "history.json").read_text()) == history.load()
