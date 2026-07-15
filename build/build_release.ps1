#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$root = Get-Location
$tools = Join-Path $root "tools"
$drivers = Join-Path $root "drivers"
New-Item -ItemType Directory -Force -Path $tools, $drivers | Out-Null

function Ensure-GoIos {
    $ios = Join-Path $tools "ios.exe"
    if (Test-Path $ios) {
        Write-Host "go-ios: already present"
        return
    }
    Write-Host "Downloading go-ios..."
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/danielpaulus/go-ios/releases/latest" -Headers @{ "User-Agent" = "DIVIZION-Build" }
    $asset = $release.assets | Where-Object { $_.name -match "windows.*amd64.*\.zip$" -or $_.name -eq "go-ios-win.zip" } | Select-Object -First 1
    if (-not $asset) {
        $asset = $release.assets | Where-Object { $_.name -like "*.zip" } | Select-Object -First 1
    }
    if (-not $asset) { throw "go-ios release asset not found" }
    $zip = Join-Path $env:TEMP "go-ios.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $env:TEMP "go-ios-extract") -Force
    $found = Get-ChildItem -Path (Join-Path $env:TEMP "go-ios-extract") -Recurse -Filter "ios.exe" | Select-Object -First 1
    if (-not $found) { throw "ios.exe not found in go-ios archive" }
    Copy-Item $found.FullName $ios -Force
    Write-Host "go-ios: saved to tools/ios.exe"
}

function Ensure-Ipatool {
    $ipatool = Join-Path $tools "ipatool.exe"
    if (Test-Path $ipatool) {
        Write-Host "ipatool: already present"
        return
    }
    $src = Join-Path $root "build\ipatool-src"
    if (Test-Path $src) {
        $go = Get-Command go -ErrorAction SilentlyContinue
        if ($go) {
            Write-Host "Building ipatool from source..."
            Push-Location $src
            & go build -o $ipatool .
            Pop-Location
            if (Test-Path $ipatool) {
                Write-Host "ipatool: built successfully"
                return
            }
        }
    }
    Write-Host "Downloading ipatool release..."
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/majd/ipatool/releases/latest" -Headers @{ "User-Agent" = "DIVIZION-Build" }
    $asset = $release.assets | Where-Object { $_.name -match "windows.*amd64" -or $_.name -like "*windows*" } | Select-Object -First 1
    if ($asset) {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $ipatool -UseBasicParsing
        Write-Host "ipatool: downloaded"
        return
    }
    throw "ipatool.exe not found. Place patched build in tools\ipatool.exe"
}

function Ensure-AppleDrivers {
    $msi1 = Join-Path $drivers "AppleMobileDeviceSupport64.msi"
    $msi2 = Join-Path $drivers "AppleApplicationSupport64.msi"
    if ((Test-Path $msi1) -and (Test-Path $msi2)) {
        Write-Host "Apple drivers: MSI files already present"
        return
    }
    $searchPaths = @(
        "${env:ProgramFiles}\iTunes",
        "${env:ProgramFiles(x86)}\iTunes",
        "$env:TEMP\iTunesExtract"
    )
    foreach ($path in $searchPaths) {
        if (Test-Path $path) {
            Get-ChildItem -Path $path -Recurse -Filter "AppleMobileDeviceSupport64.msi" -ErrorAction SilentlyContinue | ForEach-Object {
                Copy-Item $_.FullName $msi1 -Force
            }
            Get-ChildItem -Path $path -Recurse -Filter "AppleApplicationSupport64.msi" -ErrorAction SilentlyContinue | ForEach-Object {
                Copy-Item $_.FullName $msi2 -Force
            }
        }
    }
    if ((Test-Path $msi1) -and (Test-Path $msi2)) {
        Write-Host "Apple drivers: copied from local iTunes install"
        return
    }
    Write-Host "Apple drivers: MSI not bundled (installer will use winget / Microsoft Store)"
}

function Copy-ToolsAndDriversToDist {
    param(
        [string]$DistRoot,
        [string]$ToolsRoot,
        [string]$DriversRoot
    )
    $distTools = Join-Path $DistRoot "tools"
    $distDrivers = Join-Path $DistRoot "drivers"
    New-Item -ItemType Directory -Force -Path $distTools, $distDrivers | Out-Null

    foreach ($name in @("ipatool.exe", "ios.exe")) {
        $src = Join-Path $ToolsRoot $name
        if (-not (Test-Path $src)) {
            throw "Missing required tool before packaging: $src (run Ensure-* steps or place binaries in tools\)"
        }
        Copy-Item $src (Join-Path $distTools $name) -Force
        Write-Host "Copied $name -> dist\tools\$name"
    }

    if (Test-Path $DriversRoot) {
        Get-ChildItem -Path $DriversRoot -File | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $distDrivers $_.Name) -Force
            Write-Host "Copied driver file -> dist\drivers\$($_.Name)"
        }
    }

    $bat = Join-Path $distDrivers "install_drivers.bat"
    if (-not (Test-Path $bat)) {
        Write-Warning "dist\drivers\install_drivers.bat missing; Inno [Run] will skip driver install (skipifdoesntexist)"
    }
}

function Assert-DistBeforeInno {
    param([string]$DistRoot)
    $required = @(
        (Join-Path $DistRoot "GROMOV-RestorePlus.exe"),
        (Join-Path $DistRoot "tools\ipatool.exe"),
        (Join-Path $DistRoot "tools\ios.exe")
    )
    foreach ($p in $required) {
        if (-not (Test-Path $p)) {
            throw "Pre-Inno check failed: $p is missing. Do not run ISCC on PyInstaller output alone — use build\build_release.ps1 or build_release.bat."
        }
    }
    Write-Host ""
    Write-Host "Pre-Inno dist layout:"
    Get-ChildItem $DistRoot -Directory | ForEach-Object { Write-Host "  $($_.Name)\" }
    Get-ChildItem (Join-Path $DistRoot "tools") -File | ForEach-Object { Write-Host "  tools\$($_.Name) ($($_.Length) bytes)" }
    $drv = Join-Path $DistRoot "drivers"
    if (Test-Path $drv) {
        Get-ChildItem $drv -File | ForEach-Object { Write-Host "  drivers\$($_.Name) ($($_.Length) bytes)" }
    } else {
        Write-Host "  drivers\ (missing)"
    }
    Write-Host ""
}

Ensure-GoIos
Ensure-Ipatool
Ensure-AppleDrivers

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\pip.exe install -r requirements.txt -r requirements-build.txt

& .\.venv\Scripts\pyinstaller.exe --noconfirm --clean build\GROMOV-RestorePlus.spec

$dist = Join-Path $root "dist\GROMOV-RestorePlus"
if (-not (Test-Path $dist)) {
    throw "PyInstaller did not create $dist"
}

Copy-ToolsAndDriversToDist -DistRoot $dist -ToolsRoot $tools -DriversRoot $drivers
Assert-DistBeforeInno -DistRoot $dist

$zip = Join-Path $root "dist\GROMOV-RestorePlus-Portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip -Force

$iscc = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc (Join-Path $root "build\installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed with exit code $LASTEXITCODE" }
    Write-Host "Installer: dist\GROMOV-RestorePlus-Setup.exe"
} else {
    Write-Host "Inno Setup not found - portable ZIP created instead."
}

Write-Host ""
Write-Host "Build complete: $dist"
Write-Host "Portable ZIP: $zip"
