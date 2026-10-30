[CmdletBinding()]
param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
try {
    & "$PSScriptRoot\Start-ProjectDesk.ps1"
    $projectDeskBrowser = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $projectDeskBrowser) { throw 'Microsoft Edge or Google Chrome is needed for the Project desk window.' }
    $projectDeskProfile = Join-Path $PSScriptRoot 'data\window-profile'
    $projectDeskWindowArgs = @('--app=http://127.0.0.1:8789/', "--user-data-dir=`"$projectDeskProfile`"", '--no-first-run', '--no-default-browser-check', '--window-size=1100,850')
    if (-not $CheckOnly) {
        $projectDeskActivated = $false
        $projectDeskBrowserName = [System.IO.Path]::GetFileName($projectDeskBrowser)
        $projectDeskProcesses = Get-CimInstance Win32_Process -Filter "Name='$projectDeskBrowserName'" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($projectDeskProfile) }
        $projectDeskShell = New-Object -ComObject WScript.Shell
        if ($projectDeskProcesses) {
            # A browser process can own multiple windows; focus the app title,
            # rather than whichever ordinary browser window it reports as main.
            $projectDeskActivated = $projectDeskShell.AppActivate('Project Desk')
        }
        if (-not $projectDeskActivated) {
            # This is the visible app window requested by Michael, not a background helper.
            Start-Process -FilePath $projectDeskBrowser -ArgumentList $projectDeskWindowArgs
        }
    }
    Write-Output "Project desk window: http://127.0.0.1:8789/ ($projectDeskBrowser)"
} catch {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Project desk could not open.`n$($_.Exception.Message)", 'Project desk') | Out-Null
    exit 1
}
