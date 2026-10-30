[CmdletBinding()]
param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\Open-ProjectDesk.ps1" -CheckOnly:$CheckOnly
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if (-not $CheckOnly) {
    # Activate the installed Codex app normally; leave its current chat alone.
    Start-Process -FilePath "$env:SystemRoot\explorer.exe" -ArgumentList 'shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App'
}
Write-Output 'Codex launcher: installed Windows app, with Project desk in a separate window.'
