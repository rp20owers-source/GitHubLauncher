$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BuildDist = Join-Path $Root "build\installer"
$BuildWork = Join-Path $Root "build\pyinstaller"
Push-Location $Root
try {
    $Python = (Get-Command python -ErrorAction Stop).Source
    $PythonVersion = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
    if ($LASTEXITCODE -ne 0 -or [version]$PythonVersion -lt [version]"3.10") {
        throw "Python 3.10 or later is required to build GitHubLauncher."
    }

    & $Python scripts\generate_icon.py
    if ($LASTEXITCODE -ne 0) {
        throw "Icon generation failed with exit code $LASTEXITCODE."
    }
    & $Python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name GitHubLauncher --icon assets\githublauncher.ico `
        --add-data "assets\githublauncher.ico;assets" `
        --distpath $BuildDist --workpath $BuildWork main.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

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
