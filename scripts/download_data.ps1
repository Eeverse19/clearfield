# Thin wrapper: implementation is scripts/download_data.py (stdlib only).
# Usage: scripts/download_data.ps1 [file.zip ...]  (no args = all pinned files)
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Only)
$ErrorActionPreference = 'Stop'
# Strip any \\?\ long-path prefix: PS 5.1 providers and GetFullPath choke on it.
$scriptDir = $PSScriptRoot -replace '^\\\\\?\\', ''
Set-Location -LiteralPath ([System.IO.Path]::GetFullPath("$scriptDir\.."))
if (Get-Command uv -ErrorAction SilentlyContinue) { uv run python scripts/download_data.py @Only }
else { python scripts/download_data.py @Only }
exit $LASTEXITCODE
