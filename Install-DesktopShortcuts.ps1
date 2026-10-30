[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectDeskDesktop = [Environment]::GetFolderPath('Desktop')
$projectDeskShell = New-Object -ComObject WScript.Shell
$projectDeskPowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$projectDeskArguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\Open-ProjectDesk.ps1`""
$projectDeskOriginal = Join-Path $projectDeskDesktop 'Codex (OpenAI).lnk'
$projectDeskBackupDir = Join-Path $PSScriptRoot 'data\shortcut-backups'
New-Item -ItemType Directory -Path $projectDeskBackupDir -Force | Out-Null
$projectDeskBackup = Join-Path $projectDeskBackupDir 'Codex (OpenAI).lnk'
if ((Test-Path -LiteralPath $projectDeskOriginal) -and -not (Test-Path -LiteralPath $projectDeskBackup)) {
    Copy-Item -LiteralPath $projectDeskOriginal -Destination $projectDeskBackup
}

$projectDeskIcon = Join-Path $PSScriptRoot 'assets\project-desk.ico'
if (-not (Test-Path -LiteralPath $projectDeskIcon)) { throw 'Create the Project desk icon first.' }
$projectDeskShortcut = $projectDeskShell.CreateShortcut((Join-Path $projectDeskDesktop 'Project desk.lnk'))
$projectDeskShortcut.TargetPath = $projectDeskPowerShell
$projectDeskShortcut.Arguments = $projectDeskArguments
$projectDeskShortcut.WorkingDirectory = $PSScriptRoot
$projectDeskShortcut.IconLocation = "$projectDeskIcon,0"
$projectDeskShortcut.WindowStyle = 7
$projectDeskShortcut.Description = 'Open Project desk in its own window'
$projectDeskShortcut.Save()

if (Test-Path -LiteralPath $projectDeskOriginal) {
    $projectDeskCodex = $projectDeskShell.CreateShortcut($projectDeskOriginal)
    $projectDeskCodex.TargetPath = $projectDeskPowerShell
    $projectDeskCodex.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSScriptRoot\Open-CodexWithProjectDesk.ps1`""
    $projectDeskCodex.WorkingDirectory = $PSScriptRoot
    $projectDeskCodex.Description = 'Open Codex and a separate Project desk window'
    $projectDeskCodex.WindowStyle = 7
    $projectDeskPackage = Get-AppxPackage -Name 'OpenAI.Codex' | Select-Object -First 1
    if ($projectDeskPackage) {
        $projectDeskCodexExe = Join-Path $projectDeskPackage.InstallLocation 'app\ChatGPT.exe'
        if (Test-Path -LiteralPath $projectDeskCodexExe) { $projectDeskCodex.IconLocation = "$projectDeskCodexExe,0" }
    }
    $projectDeskCodex.Save()
}
Write-Output "Project desk.lnk opens a standalone window. Codex desktop shortcut opens both apps. Original shortcut: $projectDeskBackup"
