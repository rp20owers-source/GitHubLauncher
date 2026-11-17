$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BuildDist = Join-Path $Root "build\installer"
$BuildWork = Join-Path $Root "build\pyinstaller"
Push-Location $Root
try {
    py -3 scripts\generate_icon.py
    py -3 -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name GitHubLauncher --icon assets\githublauncher.ico `
        --add-data "assets\githublauncher.ico;assets" `
        --distpath $BuildDist --workpath $BuildWork main.py

    $Compiler = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $Compiler)) {
        $Compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    }
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
