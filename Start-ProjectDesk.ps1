$projectDeskRoot = $PSScriptRoot
$projectDeskUrl = 'http://127.0.0.1:8789'
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path (Join-Path $projectDeskRoot 'data') -Force | Out-Null
$projectDeskStarted = $false
try {
    $projectDeskState = Invoke-RestMethod "$projectDeskUrl/api/projects" -TimeoutSec 2
    if ($null -eq $projectDeskState.projects) { throw 'The port is occupied by another service.' }
    $projectDeskStarted = $true
} catch {
    $projectDeskPython = (Get-Command python -ErrorAction Stop).Source
    Start-Process -FilePath $projectDeskPython -ArgumentList @("`"$projectDeskRoot\server.py`"") -WorkingDirectory $projectDeskRoot -WindowStyle Hidden -RedirectStandardOutput "$projectDeskRoot\data\server-out.log" -RedirectStandardError "$projectDeskRoot\data\server-error.log"
    for ($projectDeskAttempt = 0; $projectDeskAttempt -lt 40; $projectDeskAttempt++) {
        try {
            $projectDeskState = Invoke-RestMethod "$projectDeskUrl/api/projects" -TimeoutSec 1
            if ($null -eq $projectDeskState.projects) { throw 'Unexpected service on the tracker port.' }
            $projectDeskStarted = $true
            break
        } catch { Start-Sleep -Milliseconds 250 }
    }
}
if (-not $projectDeskStarted) { throw 'Project desk did not start. See data/server-error.log.' }
Write-Output "Project desk: $projectDeskUrl"
