$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot\..
& "$PSScriptRoot/.venv/Scripts/python.exe" -m field_analyst.app
