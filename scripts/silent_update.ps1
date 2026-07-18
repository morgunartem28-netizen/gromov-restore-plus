#Requires -Version 5.1
<#
.SYNOPSIS
  Silently download and install the latest GROMOV Restore+ Setup.

.DESCRIPTION
  Practical one-shot for fleets stuck on 1.1.x / ≤1.2.1 when
  raw.githubusercontent.com is blocked: those binaries never ask for mirrors,
  so no new release can auto-update them. Run this once remotely (AnyDesk /
  RMM / PsExec) — no browser UI.

  After 1.2.7+ is installed, further updates are in-app automatic if any
  manifest/Setup mirror works.

.PARAMETER ManifestUrl
  Optional primary version.json URL. Defaults to multi-mirror list.

.PARAMETER SkipInstall
  Download + SHA256 verify only; do not run Inno Setup.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File silent_update.ps1
#>
[CmdletBinding()]
param(
    [string]$ManifestUrl = "",
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Repo = "morgunartem28-netizen/gromov-restore-plus"
$SetupName = "GROMOV-RestorePlus-Setup.exe"
$RawManifest = "https://raw.githubusercontent.com/$Repo/main/release/version.json"

$ManifestCandidates = @(
    $ManifestUrl
    "https://cdn.jsdelivr.net/gh/$Repo@main/release/version.json"
    "https://github.com/$Repo/raw/main/release/version.json"
    $RawManifest
    "https://gh-proxy.com/$RawManifest"
    "https://edgeone.gh-proxy.com/$RawManifest"
    "https://ghproxy.net/$RawManifest"
    "https://ghfast.top/$RawManifest"
) | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique

function Write-Step([string]$Message) {
    Write-Host "[silent_update] $Message"
}

function Get-ProxyPrefixes {
    @(
        "https://gh-proxy.com/"
        "https://edgeone.gh-proxy.com/"
        "https://ghproxy.net/"
        "https://ghfast.top/"
    )
}

function Get-Manifest {
    $errors = New-Object System.Collections.Generic.List[string]
    foreach ($url in $ManifestCandidates) {
        $bust = if ($url -match '\?') { "&t=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())" }
                else { "?t=$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())" }
        $tryUrl = "$url$bust"
        try {
            Write-Step "manifest try: $url"
            $resp = Invoke-WebRequest -Uri $tryUrl -UseBasicParsing -TimeoutSec 25
            $json = $resp.Content | ConvertFrom-Json
            if (-not $json.version) { throw "no version field" }
            Write-Step "manifest ok version=$($json.version)"
            return $json
        }
        catch {
            $errors.Add("$url :: $($_.Exception.Message)") | Out-Null
            Write-Step "manifest fail: $($_.Exception.Message)"
        }
    }
    throw ("Could not fetch version.json from any mirror:`n" + ($errors -join "`n"))
}

function Get-SetupCandidates([string]$SetupUrl, [string]$Version) {
    $list = New-Object System.Collections.Generic.List[string]
    $canonical = "https://github.com/$Repo/releases/download/$Version/$SetupName"
    foreach ($u in @($SetupUrl, $canonical)) {
        $t = [string]$u
        if ($t -and -not $list.Contains($t)) { $list.Add($t) | Out-Null }
    }
    foreach ($base in @($list.ToArray())) {
        if ($base -notmatch '^https://github\.com/.+/releases/download/') { continue }
        foreach ($prefix in Get-ProxyPrefixes) {
            $mirrored = "$prefix$base"
            if (-not $list.Contains($mirrored)) { $list.Add($mirrored) | Out-Null }
        }
    }
    return $list
}

function Test-Sha256([string]$Path, [string]$Expected) {
    $expected = ($Expected -replace '\s', '').ToLowerInvariant()
    if ($expected.StartsWith("sha256:")) { $expected = $expected.Substring(7) }
    if ($expected -notmatch '^[0-9a-f]{64}$') {
        throw "Manifest SHA256 missing or invalid: $Expected"
    }
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "SHA256 mismatch. Expected $expected, got $actual"
    }
    return $actual
}

function Get-SetupFile([System.Collections.IEnumerable]$Urls, [string]$Dest, [string]$ExpectedSha) {
    $errors = New-Object System.Collections.Generic.List[string]
    foreach ($url in $Urls) {
        try {
            Write-Step "download try: $url"
            if (Test-Path $Dest) { Remove-Item -Force $Dest }
            Invoke-WebRequest -Uri $url -OutFile $Dest -UseBasicParsing -TimeoutSec 300
            if (-not (Test-Path $Dest) -or ((Get-Item $Dest).Length -lt 1MB)) {
                throw "downloaded file missing or too small"
            }
            $hash = Test-Sha256 -Path $Dest -Expected $ExpectedSha
            Write-Step "download ok sha256=$hash bytes=$((Get-Item $Dest).Length)"
            return $Dest
        }
        catch {
            $errors.Add("$url :: $($_.Exception.Message)") | Out-Null
            Write-Step "download fail: $($_.Exception.Message)"
            if (Test-Path $Dest) {
                try { Remove-Item -Force $Dest } catch { }
            }
        }
    }
    throw ("Could not download Setup.exe from any mirror:`n" + ($errors -join "`n"))
}

# Elevate if needed (Inno Setup requires admin).
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Step "re-launching elevated..."
    $argList = @(
        "-NoProfile"
        "-ExecutionPolicy", "Bypass"
        "-File", "`"$PSCommandPath`""
    )
    if ($ManifestUrl) { $argList += @("-ManifestUrl", "`"$ManifestUrl`"") }
    if ($SkipInstall) { $argList += "-SkipInstall" }
    $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argList -Wait -PassThru
    exit $proc.ExitCode
}

$work = Join-Path $env:TEMP "GROMOV-RestorePlus-silent-update"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$setupPath = Join-Path $work $SetupName

Write-Step "work dir: $work"
$manifest = Get-Manifest
$version = [string]$manifest.version
$setupUrl = [string]($manifest.setup_url)
$sha = [string]($manifest.sha256)
if (-not $version) { throw "version.json has no version" }
if (-not $sha) { throw "version.json has no sha256" }

$candidates = Get-SetupCandidates -SetupUrl $setupUrl -Version $version
Write-Step ("setup mirrors: " + ($candidates -join " | "))
Get-SetupFile -Urls $candidates -Dest $setupPath -ExpectedSha $sha | Out-Null

if ($SkipInstall) {
    Write-Step "SkipInstall set — file ready: $setupPath"
    exit 0
}

Write-Step "running Inno: /VERYSILENT /NORESTART"
$p = Start-Process -FilePath $setupPath -ArgumentList "/VERYSILENT", "/NORESTART" -Wait -PassThru
if ($p.ExitCode -ne 0) {
    throw "Inno Setup exited with code $($p.ExitCode)"
}
Write-Step "installed version $version OK"
exit 0
