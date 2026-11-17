$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location $Root
try {
    python scripts\generate_icon.py
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name GitHubLauncher --icon assets\githublauncher.ico main.py

    $Compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $Compiler)) {
        $Compiler = "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    }
    if (-not (Test-Path $Compiler)) {
        throw "Inno Setup 6 compiler (ISCC.exe) was not found."
    }
    $Version = $env:GITHUB_REF_NAME -replace '^v', ''
    if (-not $Version) {
        $Version = "1.0.0"
    }
    & $Compiler "/DAppVersion=$Version" installer.iss
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
