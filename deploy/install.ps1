# Installs or updates Thimbleby from a downloaded package file, then tells you how to start.
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 thimbleby-<version>-py3-none-any.whl [constraints.txt]
# Needs uv (the Python package tool). Running it again with a newer file updates the app; workspaces are untouched
# except that an update first copies the records and, if it fails, puts the version and the records back.
# The libraries are the exact versions the release was tested with, from the constraints file that comes with it
# (by default the one beside the package file).
param([Parameter(Mandatory = $true)][string]$Package, [string]$Constraints = "")
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Package -PathType Leaf)) {
    Write-Error "Usage: install.ps1 <the downloaded .whl file> [the downloaded constraints.txt]"
    exit 2
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "This needs uv, the Python package tool. Install it from its documentation, open a new terminal, and run this again."
    exit 1
}
if (-not $Constraints) { $Constraints = Join-Path (Split-Path -Parent (Resolve-Path $Package)) "constraints.txt" }
if (-not (Test-Path $Constraints -PathType Leaf)) {
    Write-Error "The constraints file that comes with this release isn't beside the package file. Download constraints.txt from the same release, put it next to the package file, and run this again."
    exit 2
}
# The packages already installed are kept here, so a failed update can put the one before back.
# The same choice as engine/legacy_names.py: the environment's folder (THIMBLEBY_PACKAGES, else the earlier name
# COCKPIT_PACKAGES), else the per-person folder, or the one an earlier version made when there is no new one.
$Store = if ($env:THIMBLEBY_PACKAGES) { $env:THIMBLEBY_PACKAGES } elseif ($env:COCKPIT_PACKAGES) { $env:COCKPIT_PACKAGES } else { Join-Path $HOME ".thimbleby\packages" }
$OldStore = Join-Path $HOME ".pm-cockpit\packages"
if (-not $env:THIMBLEBY_PACKAGES -and -not $env:COCKPIT_PACKAGES -and (Test-Path $OldStore) -and -not (Test-Path $Store)) { $Store = $OldStore }
New-Item -ItemType Directory -Force -Path $Store | Out-Null
$Current = Join-Path $Store "current"
$Before = if (Test-Path $Current) { (Get-Content $Current -Raw).Trim() } else { "" }
# The program already installed, which makes the copy of the records first: `thimbleby`, or `cockpit` for a version from
# before the rename. Checking and putting the records back are done by the new program, once it is installed.
$Installed = if (Get-Command thimbleby -ErrorAction SilentlyContinue) { "thimbleby" } elseif (Get-Command cockpit -ErrorAction SilentlyContinue) { "cockpit" } else { "" }
$HadCockpit = [bool]$Installed

if ($HadCockpit) {
    $Version = (uv tool list 2>$null | Where-Object { $_ -match '^(thimbleby|pm-cockpit) ' } | ForEach-Object { ($_ -split ' ')[1] } | Select-Object -First 1)
    if (-not $Version) { $Version = "unknown" }
    & $Installed update-step backup --version $Version
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Nothing was changed: the copy of your records made first couldn't be made, or the app is open. Close it, then run this again."
        exit 1
    }
}

$Checked = $false
$Worked = $false
uv tool install --force --python 3.12 --constraints $Constraints $Package
if ($LASTEXITCODE -eq 0) {
    if ($HadCockpit) {
        $Checked = $true
        thimbleby update-step check
        $Worked = ($LASTEXITCODE -eq 0)
    } else {
        $Worked = $true
    }
}
if ($Worked) {
    $Name = Split-Path -Leaf $Package
    Copy-Item $Package (Join-Path $Store $Name) -Force
    Copy-Item $Constraints (Join-Path $Store "$Name.constraints.txt") -Force
    Set-Content -Path $Current -Value $Name
    # A copy installed before the package was renamed is a second tool with the same commands. Its folder is removed
    # here directly, because `uv tool uninstall` would also remove the commands the new copy now owns.
    $ToolDir = (uv tool dir 2>$null)
    if ($ToolDir -and (Test-Path (Join-Path $ToolDir "pm-cockpit"))) { Remove-Item -Recurse -Force (Join-Path $ToolDir "pm-cockpit") }
} else {
    Write-Host "The update didn't work, so it was not kept."
    if ($Checked) {
        thimbleby update-step restore
        if ($LASTEXITCODE -eq 0) { Write-Host "Put back the copy of your records made before updating." }
    }
    $Kept = if ($Before) { Join-Path $Store $Before } else { "" }
    if ($Kept -and (Test-Path $Kept)) {
        Write-Host "Putting back the version you had ($Before)."
        uv tool install --force --python 3.12 --constraints "$Kept.constraints.txt" $Kept | Out-Null
    }
    exit 1
}
uv tool update-shell | Out-Null
Write-Host ""
Write-Host "Installed. Open a new terminal, then:"
Write-Host "  thimbleby demo                       try it on made-up data"
Write-Host "  thimbleby                            start your workspace (made the first time) and open it"
Write-Host "To update later, run this script again with the newer file."
