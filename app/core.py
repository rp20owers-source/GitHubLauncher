from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

USER_AGENT = "GitHubLauncher/1.0"
CHUNK_SIZE = 64 * 1024
SKIP_KEYWORDS = (
    "arm64",
    "aarch64",
    "linux",
    "macos",
    "darwin",
    ".pdb",
    ".sha256",
    "sha256sums",
    "checksums.txt",
)
GITHUB_DOWNLOAD_HOSTS = {"api.github.com", "github.com", "www.github.com"}


class _GitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected:
            old_url = urllib.parse.urlsplit(req.full_url)
            new_url_parts = urllib.parse.urlsplit(newurl)
            if (old_url.scheme, old_url.hostname, old_url.port) != (
                new_url_parts.scheme,
                new_url_parts.hostname,
                new_url_parts.port,
            ):
                redirected.remove_header("Authorization")
        return redirected


_URL_OPENER = urllib.request.build_opener(_GitHubRedirectHandler())


def safe_urlopen(request, timeout=30):
    return _URL_OPENER.open(request, timeout=timeout)


def parse_github_url(url: str) -> tuple[str | None, str | None, str | None]:
    """Return owner, repository, and optional release tag."""
    clean = url.strip()
    short = re.fullmatch(r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", clean)
    if short and short.group(1).lower() not in ("github.com", "www.github.com"):
        return short.group(1), short.group(2).removesuffix(".git"), None

    try:
        parsed = urllib.parse.urlsplit(clean)
    except ValueError:
        return None, None, None
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
        "github.com",
        "www.github.com",
    ):
        return None, None, None

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None, None, None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", repo
    ):
        return None, None, None
    tag = None
    if len(parts) >= 4 and parts[2:4] == ["releases", "tag"] and len(parts) >= 5:
        tag = urllib.parse.unquote(parts[4])
    return owner, repo, tag


def select_best_asset(assets: list[dict]) -> tuple[str | None, str | None]:
    """Select a Windows installer or portable archive, excluding other platforms."""
    ranked: list[tuple[int, int, str, str]] = []
    for index, asset in enumerate(assets):
        name = asset.get("name", "")
        url = asset.get("browser_download_url")
        if not isinstance(name, str) or not isinstance(url, str):
            continue
        lowered = name.lower()
        if any(keyword in lowered for keyword in SKIP_KEYWORDS):
            continue

        if lowered.endswith(".msi"):
            score = 110
        elif lowered.endswith(".exe"):
            score = 95
        elif lowered.endswith(".zip"):
            score = 50
        else:
            continue

        if any(word in lowered for word in ("x64", "win64", "amd64", "x86_64")):
            score += 30
        elif any(word in lowered for word in ("windows", "win-", "win_", "win.")):
            score += 20
        if "setup" in lowered or "installer" in lowered:
            score += 10
        ranked.append((score, -index, url, name))

    if not ranked:
        return None, None
    _, _, url, name = max(ranked)
    return url, name


def get_github_token() -> str | None:
    """Read a token from the environment, app config, or authenticated gh CLI."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    local_app_data = os.environ.get("LOCALAPPDATA")
    config_path = (
        Path(local_app_data) / "GitHubLauncher" / "config.json"
        if local_app_data
        else Path.home() / ".config" / "GitHubLauncher" / "config.json"
    )
    if config_path.exists():
        with config_path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
        configured_token = config.get("github_token")
        if isinstance(configured_token, str) and configured_token.strip():
            return configured_token.strip()

    gh = shutil.which("gh")
    if not gh and os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        installed_gh = program_files / "GitHub CLI" / "gh.exe"
        if installed_gh.is_file():
            gh = str(installed_gh)
    if gh:
        result = subprocess.run(
            [gh, "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        opener: Callable = safe_urlopen,
    ):
        self.token = token
        self.opener = opener
        self.rate_limit_remaining: int | None = None

    @property
    def headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @property
    def rate_limit_warning(self) -> str | None:
        if self.rate_limit_remaining == 0:
            return "GitHub API rate limit reached. Set GITHUB_TOKEN to continue."
        if self.rate_limit_remaining is not None and self.rate_limit_remaining < 5:
            return f"GitHub API rate limit is low ({self.rate_limit_remaining} requests remaining)."
        return None

    def download_headers(self, url: str) -> dict[str, str]:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in GITHUB_DOWNLOAD_HOSTS:
            raise ValueError("Refusing to send GitHub credentials to a non-GitHub URL")
        headers = {"User-Agent": USER_AGENT}
        if parsed.hostname == "api.github.com":
            headers["Accept"] = "application/octet-stream"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _read_json(self, url: str) -> dict | list:
        request = urllib.request.Request(url, headers=self.headers)
        try:
            with self.opener(request, timeout=15) as response:
                self._record_rate_limit(response.headers)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            self._record_rate_limit(error.headers)
            raise

    def _record_rate_limit(self, headers) -> None:
        remaining = headers.get("X-RateLimit-Remaining") if headers else None
        if remaining is not None:
            try:
                self.rate_limit_remaining = int(remaining)
            except ValueError:
                self.rate_limit_remaining = None

    def find_release(
        self, owner: str, repo: str, tag: str | None = None
    ) -> dict | None:
        base = f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
        if tag:
            try:
                result = self._read_json(
                    f"{base}/releases/tags/{urllib.parse.quote(tag, safe='')}"
                )
                return result if isinstance(result, dict) else None
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                return None

        try:
            result = self._read_json(f"{base}/releases/latest")
            if isinstance(result, dict):
                return result
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise

        try:
            releases = self._read_json(f"{base}/releases?per_page=5")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            return None
        if isinstance(releases, list):
            for release in releases:
                if (
                    isinstance(release, dict)
                    and select_best_asset(release.get("assets", []))[0]
                ):
                    return release
            if releases:
                return releases[0] if isinstance(releases[0], dict) else None
        return None

    def download_choice(self, owner: str, repo: str, tag: str | None = None):
        release = self.find_release(owner, repo, tag)
        if release:
            assets = release.get("assets", [])
            url, name = select_best_asset(assets)
            if url and name:
                asset = next(
                    (
                        item
                        for item in assets
                        if item.get("name") == name
                        and item.get("browser_download_url") == url
                    ),
                    {},
                )
                return asset.get("url", url), name, assets
            zipball = release.get("zipball_url")
            if zipball:
                release_tag = release.get("tag_name", "latest")
                return zipball, f"{repo}-{release_tag}.zip", release.get("assets", [])
        return (
            f"https://api.github.com/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/zipball",
            f"{repo}-main.zip",
            [],
        )


def download_file(
    url: str,
    destination: Path,
    headers: dict[str, str] | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancel_event: threading.Event | None = None,
    opener: Callable = safe_urlopen,
) -> int:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    try:
        with opener(request, timeout=30) as response, destination.open("wb") as output:
            raw_total = response.headers.get("Content-Length", "0")
            total = int(raw_total) if raw_total.isdigit() else 0
            while True:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Download canceled")
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total)
        return downloaded
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _validated_member_path(name: str, target: Path) -> Path:
    normalized = name.replace("\\", "/").rstrip("/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(name)
    if (
        not normalized
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in ("", ".", "..") or ":" in part for part in normalized.split("/"))
    ):
        raise ValueError(f"Unsafe zip member path: {name!r}")
    destination = target.joinpath(*posix.parts)
    if not destination.resolve().is_relative_to(target.resolve()):
        raise ValueError(f"Zip member escapes install directory: {name!r}")
    return destination


def safe_extract_zip(zip_path: Path, target_dir: Path) -> Path:
    """Validate all archive members, extract safely, and return the usable root."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        destinations = []
        for member in members:
            destination = _validated_member_path(member.filename, target_dir)
            mode = (member.external_attr >> 16) & 0xFFFF
            if mode and (mode & 0o170000) == 0o120000:
                raise ValueError(
                    f"Symbolic links are not allowed in zip files: {member.filename}"
                )
            destinations.append((member, destination))
        for member, destination in destinations:
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    while chunk := source.read(CHUNK_SIZE):
                        output.write(chunk)

    top_level = {path.relative_to(target_dir).parts[0] for _, path in destinations}
    top_files = [
        path
        for _, path in destinations
        if len(path.relative_to(target_dir).parts) == 1 and path.is_file()
    ]
    if len(top_level) == 1 and not top_files:
        root = target_dir / next(iter(top_level))
        if root.is_dir():
            return root
    return target_dir


def find_executable(root: Path, repo_name: str) -> Path | None:
    candidates = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() == ".exe"
        and "unins" not in path.name.lower()
        and "crash" not in path.name.lower()
    ]
    return next(
        (path for path in candidates if repo_name.lower() in path.stem.lower()),
        candidates[0] if candidates else None,
    )


def matching_checksum_asset(assets: list[dict], filename: str) -> dict | None:
    for asset in assets:
        name = asset.get("name", "").lower()
        if name == f"{filename.lower()}.sha256" or name in (
            "checksums.txt",
            "sha256sums.txt",
            "sha256sum.txt",
        ):
            return asset
    return None


def verify_sha256(path: Path, checksum_text: str, filename: str) -> bool:
    expected = None
    for line in checksum_text.splitlines():
        match = re.match(r"^\s*([a-fA-F0-9]{64})\s+[* ]?(.+?)\s*$", line)
        if match and Path(match.group(2)).name.lower() == filename.lower():
            expected = match.group(1).lower()
            break
    if expected is None and len(checksum_text.strip()) == 64:
        expected = checksum_text.strip().lower()
    if expected is None:
        raise ValueError(f"No SHA-256 checksum found for {filename}")

    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest() == expected


class InstallHistory:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as history_file:
            history = json.load(history_file)
        if not isinstance(history, list):
            raise ValueError("History file must contain a JSON list")
        return [item for item in history if isinstance(item, str)][:10]

    def add(self, repo: str) -> list[str]:
        history = [repo] + [
            item for item in self.load() if item.casefold() != repo.casefold()
        ]
        history = history[:10]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(history, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return history
