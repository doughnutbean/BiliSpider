[CmdletBinding()]
param(
    [string]$Version = "0.2.0",
    [switch]$SkipInstall,
    [switch]$PortableOneFile
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VenvPip = Join-Path $ProjectRoot ".venv\Scripts\pip.exe"
$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path $VenvPython)) {
        py -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create virtual environment."
        }
    }

    if (-not $SkipInstall) {
        Invoke-Checked $VenvPython -m pip install --upgrade pip
        Invoke-Checked $VenvPip install -r requirements.txt pyinstaller
    }

    Invoke-Checked $PyInstaller --clean --noconfirm packaging\BiliSpider.spec

    if ($PortableOneFile) {
        Invoke-Checked $PyInstaller --clean --noconfirm --onefile --windowed --name BiliSpiderPortable gui.py
    }

    $Iscc = Get-Command iscc -ErrorAction SilentlyContinue
    $IsccPath = if ($Iscc) { $Iscc.Source } else { $null }
    if (-not $IsccPath) {
        $CandidatePaths = @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        )
        $IsccPath = $CandidatePaths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    }
    if (-not $IsccPath) {
        throw "Inno Setup compiler 'iscc' was not found. Install Inno Setup 6 and make sure iscc.exe is on PATH."
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "release") | Out-Null
    Invoke-Checked $IsccPath "/DAppVersion=$Version" packaging\BiliSpider.iss

    Write-Host ""
    Write-Host "Build complete:"
    Write-Host "  release\BiliSpiderSetup-$Version.exe"
    if ($PortableOneFile) {
        Write-Host "  dist\BiliSpiderPortable.exe"
    }
}
finally {
    Pop-Location
}
