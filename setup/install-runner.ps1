#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Installs the GitHub Actions self-hosted runner for investment-forecaster.

.DESCRIPTION
    Downloads the latest Windows x64 runner, configures it as 'desktop-forecaster',
    and installs it as a Windows service so it starts automatically on reboot.

.NOTES
    Run this script once from PowerShell as Administrator.
    Before running, get a registration token from:
    https://github.com/James-Kupfer/investment-forecaster/settings/actions/runners/new
    (Select Windows / x64 — the token is shown in the Configure section.)
#>

$ErrorActionPreference = "Stop"

$REPO_URL    = "https://github.com/James-Kupfer/investment-forecaster"
$RUNNER_NAME = "desktop-forecaster"
$RUNNER_DIR  = "C:\actions-runner\forecaster"

Write-Host ""
Write-Host "=== GitHub Actions Runner: $RUNNER_NAME ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Before continuing, get a registration token:" -ForegroundColor Yellow
Write-Host "  $REPO_URL/settings/actions/runners/new"
Write-Host "  -> Select Windows / x64"
Write-Host "  -> Copy the token from the Configure section"
Write-Host ""
$TOKEN = Read-Host "Paste registration token"
if (-not $TOKEN) { Write-Error "Token cannot be empty."; exit 1 }

# Required for the runner service to execute CI PowerShell scripts
Write-Host "Setting PowerShell execution policy..." -ForegroundColor Cyan
Set-ExecutionPolicy RemoteSigned -Scope LocalMachine -Force

# Fetch latest runner version from GitHub API
Write-Host ""
Write-Host "Fetching latest runner version..." -ForegroundColor Cyan
$release  = Invoke-RestMethod -Uri "https://api.github.com/repos/actions/runner/releases/latest"
$version  = $release.tag_name.TrimStart("v")
$asset    = $release.assets | Where-Object { $_.name -like "actions-runner-win-x64-*.zip" } | Select-Object -First 1
$dlUrl    = $asset.browser_download_url
Write-Host "  Runner version: $version"

# Create install directory
if (Test-Path $RUNNER_DIR) {
    Write-Host ""
    Write-Host "Directory $RUNNER_DIR already exists." -ForegroundColor Yellow
    $overwrite = Read-Host "Overwrite existing installation? (y/N)"
    if ($overwrite -ne "y") { Write-Host "Aborted."; exit 0 }
    Remove-Item -Recurse -Force $RUNNER_DIR
}
New-Item -ItemType Directory -Force -Path $RUNNER_DIR | Out-Null

# Download
Write-Host "Downloading runner..." -ForegroundColor Cyan
$zipPath = Join-Path $RUNNER_DIR "runner.zip"
Invoke-WebRequest -Uri $dlUrl -OutFile $zipPath

# Extract
Write-Host "Extracting..." -ForegroundColor Cyan
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $RUNNER_DIR)
Remove-Item $zipPath

# Configure
Write-Host "Configuring runner..." -ForegroundColor Cyan
& (Join-Path $RUNNER_DIR "config.cmd") --url $REPO_URL --token $TOKEN --name $RUNNER_NAME --unattended --replace
if ($LASTEXITCODE -ne 0) { Write-Error "config.cmd failed (exit $LASTEXITCODE)."; exit $LASTEXITCODE }

# Install as Windows service (svc.cmd was removed in runner v2.335+; use New-Service directly)
Write-Host "Installing Windows service..." -ForegroundColor Cyan
$cfg     = Get-Content (Join-Path $RUNNER_DIR ".runner") | ConvertFrom-Json
$url     = $cfg.gitHubUrl -replace "https://github.com/", ""
$svcName = "actions.runner." + ($url -replace "/", ".") + "." + $cfg.agentName
$exePath = Join-Path $RUNNER_DIR "bin\RunnerService.exe"

New-Service -Name $svcName `
    -BinaryPathName "`"$exePath`"" `
    -DisplayName "GitHub Actions Runner ($svcName)" `
    -StartupType Automatic
Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\$svcName" `
    -Name "AppDirectory" -Value $RUNNER_DIR
Start-Service $svcName

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
Write-Host "Runner '$RUNNER_NAME' is installed as a Windows service and running."
Write-Host "It will start automatically on reboot."
Write-Host ""
Write-Host "Verify at: $REPO_URL/settings/actions/runners"
