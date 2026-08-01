#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$root = Get-Location
$tools = Join-Path $root "tools"
$drivers = Join-Path $root "drivers"
New-Item -ItemType Directory -Force -Path $tools, $drivers | Out-Null

function Ensure-GoIos {
    $ios = Join-Path $tools "ios.exe"
    $lockPath = Join-Path $root "config\tools_lock.json"
    if (-not (Test-Path $ios)) {
        throw "tools\ios.exe missing. Place the pinned go-ios binary manually — auto-download of latest is disabled."
    }
    if (Test-Path $lockPath) {
        $lock = Get-Content $lockPath -Raw | ConvertFrom-Json
        $expected = [string]$lock.'ios.exe'.sha256
        if ($expected) {
            $actual = (Get-FileHash $ios -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $expected.ToLowerInvariant()) {
                throw "tools\ios.exe SHA256 mismatch. Expected $expected, got $actual"
            }
            Write-Host "go-ios: pinned hash OK"
            return
        }
    }
    Write-Host "go-ios: present (no hash pin found)"
}

function Ensure-Ipatool {
    $ipatool = Join-Path $tools "ipatool.exe"
    $src = Join-Path $root "build\ipatool-src"
    # Always rebuild from patched sources when available — never auto-download "latest".
    if (Test-Path $src) {
        $go = Get-Command go -ErrorAction SilentlyContinue
        if (-not $go) { throw "Go toolchain required to build patched ipatool from build\ipatool-src" }
        Write-Host "Building patched ipatool from source..."
        Push-Location $src
        & go build -o $ipatool .
        $code = $LASTEXITCODE
        Pop-Location
        if ($code -ne 0 -or -not (Test-Path $ipatool)) {
            throw "Failed to build ipatool from source"
        }
        $hash = (Get-FileHash $ipatool -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Host "ipatool: built ($hash)"
        $lockPath = Join-Path $root "config\tools_lock.json"
        if (Test-Path $lockPath) {
            $lock = Get-Content $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($lock.'ipatool.exe') {
                $lock.'ipatool.exe'.sha256 = $hash
                $json = $lock | ConvertTo-Json -Depth 5
                [System.IO.File]::WriteAllText($lockPath, $json, [System.Text.UTF8Encoding]::new($false))
                Write-Host "tools_lock.json: ipatool.exe hash updated"
            }
        }
        return
    }
    if (Test-Path $ipatool) {
        Write-Host "ipatool: using existing tools\ipatool.exe (no ipatool-src)"
        return
    }
    throw "ipatool.exe not found. Place patched build in tools\ipatool.exe or provide build\ipatool-src"
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

    $batSrc = Join-Path $DriversRoot "install_drivers.bat"
    if (-not (Test-Path $batSrc)) {
        throw "Missing drivers\install_drivers.bat — Setup would fail with error 267 on driver step."
    }

    # Always copy entire drivers folder (bat + optional MSI).
    Copy-Item -Path (Join-Path $DriversRoot "*") -Destination $distDrivers -Recurse -Force
    Get-ChildItem $distDrivers -File | ForEach-Object {
        Write-Host "Copied driver file -> dist\drivers\$($_.Name) ($($_.Length) bytes)"
    }

    $msiCount = @(Get-ChildItem $distDrivers -Filter "*.msi" -ErrorAction SilentlyContinue).Count
    if ($msiCount -lt 2) {
        Write-Warning "Apple MSI not bundled ($msiCount found). install_drivers.bat will fall back to winget / Store."
    } else {
        Write-Host "Apple drivers: $msiCount MSI file(s) bundled"
    }
}

function Assert-DistBeforeInno {
    param([string]$DistRoot)
    $required = @(
        (Join-Path $DistRoot "GROMOV-RestorePlus.exe"),
        (Join-Path $DistRoot "tools\ipatool.exe"),
        (Join-Path $DistRoot "tools\ios.exe"),
        (Join-Path $DistRoot "drivers\install_drivers.bat")
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
    Get-ChildItem $drv -File | ForEach-Object { Write-Host "  drivers\$($_.Name) ($($_.Length) bytes)" }
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

    $setup = Join-Path $root "dist\GROMOV-RestorePlus-Setup.exe"
    if (Test-Path $setup) {
        $sha = (Get-FileHash -Path $setup -Algorithm SHA256).Hash.ToLowerInvariant()
        $versionPy = Get-Content (Join-Path $root "src\version.py") -Raw
        if ($versionPy -match 'APP_VERSION\s*=\s*"([^"]+)"') {
            $appVersion = $Matches[1]
        } else {
            $appVersion = "0.0.0"
        }
        $setupUrl = "https://github.com/morgunartem28-netizen/gromov-restore-plus/releases/download/$appVersion/GROMOV-RestorePlus-Setup.exe"
        $manifest = [ordered]@{
            version    = $appVersion
            setup_url  = $setupUrl
            setup_urls = @(
                $setupUrl
                "https://gh-proxy.com/$setupUrl"
                "https://edgeone.gh-proxy.com/$setupUrl"
                "https://ghproxy.net/$setupUrl"
                "https://ghfast.top/$setupUrl"
            )
            sha256     = $sha
            notes      = "Провели улучшение дизайна, изменили каталог и добавили 3 новых приложения!"
        }
        $manifestPath = Join-Path $root "release\version.json"
        $json = ($manifest | ConvertTo-Json -Depth 5)
        [System.IO.File]::WriteAllText($manifestPath, $json, [System.Text.UTF8Encoding]::new($false))
        Write-Host "Update manifest: $manifestPath"
        Write-Host "Setup SHA256: $sha"
    }
} else {
    Write-Host "Inno Setup not found - portable ZIP created instead."
}

Write-Host ""
Write-Host "Build complete: $dist"
Write-Host "Portable ZIP: $zip"
