# GitHubLauncher

GitHubLauncher is a compact Windows desktop app for downloading a GitHub
repository's latest Windows release. It has a normal titled window and taskbar
button. It can launch an `.exe` or `.msi`, or safely extract a portable `.zip` under
`%LOCALAPPDATA%\Programs\<RepoName>`. The backend uses only Python's standard
library.

## Use

Install with `GitHubLauncher-Setup.exe` or launch `GitHubLauncher.exe`, paste a GitHub repository URL (or enter
`owner/repo`), then:

- **Enter** downloads and launches/installs the selected release.
- **Shift+Enter** downloads the selected asset to your Downloads folder without
  installing it.
- **Esc** cancels an active download, or closes the bar when idle.
- **Up/Down** cycles through the last 10 installed repositories.

The app has a normal Windows title bar and taskbar button. Right-click its
taskbar button and choose **Pin to taskbar** to keep it there.

The bar also detects a GitHub repository URL in the clipboard when it opens or
receives focus. Right-click the input to paste.

The latest stable release is preferred. If none is published, GitHubLauncher
checks recent releases (including pre-releases), then falls back to the
repository's source zipball. Asset selection filters non-Windows and ARM
artifacts. When a matching `.sha256` or checksum-list asset is available, the
download is verified before it is launched or extracted.

## GitHub API token

GitHubLauncher uses `GITHUB_TOKEN`, the local config below, or the token from
an authenticated GitHub CLI installation (`gh auth login`). This also enables
private repository releases when the token has read access to that repository.
Without a token, GitHub may report private repositories as not found.

`%LOCALAPPDATA%\GitHubLauncher\config.json`

```json
{
  "github_token": "your-token"
}
```

The environment variable takes precedence over local config, which takes
precedence over GitHub CLI authentication. The token is sent only to HTTPS
GitHub hosts; authorization is stripped when a download redirects to a
different host. A low or exhausted API quota is reported in the bar.

## Development

Requires Python 3.10 or later.

```powershell
py -3 -m pip install -r requirements-dev.txt
py -3 -m black .
py -3 -m pytest -v
```

To build on Windows, install Inno Setup 6, then run:

```powershell
.\scripts\build_installer.ps1
```

The script generates a multi-resolution ICO from vector-drawn artwork, builds
the standalone executable with PyInstaller, and creates
`dist\GitHubLauncher-Setup.exe`. Push a version tag such as `v1.0.0` to run the
tagged installer workflow.

Downloaded release binaries are executable content from the repository's
publisher. SHA-256 files help detect transfer/corruption issues, but do not
establish that a publisher or release is trustworthy.
