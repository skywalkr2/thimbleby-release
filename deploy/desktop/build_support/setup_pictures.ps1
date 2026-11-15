# Run the built setup as a person does (Enter moves from page to page), take a picture of each page, then run the
# uninstaller the same way and take a picture of its first page. It installs for the runner's own user, in the setup's
# own folder, and quits the app the setup starts.
#
# Usage: pwsh setup_pictures.ps1 -Setup <the setup .exe> -Pictures <folder for the pictures>
param(
    [Parameter(Mandatory = $true)][string]$Setup,
    [Parameter(Mandatory = $true)][string]$Pictures
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
New-Item -ItemType Directory -Force -Path $Pictures | Out-Null
$shell = New-Object -ComObject WScript.Shell
$installed = Join-Path $env:LOCALAPPDATA 'Programs\Thimbleby'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8B79A062-067C-46D5-94D7-A27CBAA00C33}_is1'

function Take([string]$Name) {
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save((Join-Path $Pictures $Name), [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Host "took $Name"
}

function Press([string]$Title, [string]$Keys) {
    [void]$shell.AppActivate($Title)
    Start-Sleep -Milliseconds 500
    $shell.SendKeys($Keys)
}

# Setup: Welcome, A couple of choices (its button is Install), the progress page, Installed.
$process = Start-Process -FilePath $Setup -PassThru
Start-Sleep -Seconds 6
Take 'setup-1-welcome.png'
Press 'Setup - Thimbleby' '{ENTER}'
Start-Sleep -Seconds 2
Take 'setup-2-choices.png'
Press 'Setup - Thimbleby' '{ENTER}'
Start-Sleep -Seconds 1
Take 'setup-3-progress.png'
# The setup writes its uninstall entry when the files are all in place; wait for it, for up to two minutes.
for ($i = 0; $i -lt 120 -and -not (Test-Path $uninstallKey); $i++) { Start-Sleep -Seconds 1 }
Start-Sleep -Seconds 3
Take 'setup-4-installed.png'
Press 'Setup - Thimbleby' '{ENTER}'
[void]$process.WaitForExit(30000)
Start-Sleep -Seconds 5
Stop-Process -Name 'Thimbleby' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# The uninstaller's first page (its answer is Yes, with the key).
$uninstaller = Start-Process -FilePath (Join-Path $installed 'unins000.exe') -PassThru
Start-Sleep -Seconds 4
Take 'remove-1-first.png'
Press 'Thimbleby Uninstall' 'y'
Start-Sleep -Seconds 8
Take 'remove-2-done.png'
Press 'Thimbleby Uninstall' '{ENTER}'
[void]$uninstaller.WaitForExit(60000)
