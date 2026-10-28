# Thin wrapper: implementation is scripts/seed_thor.py (needs the THOR CSV extracted
# into data/thor/ first - see "python scripts/seed_thor.py --help" / spec §2.1).
# Usage: scripts/seed_thor.ps1 [--country ID] [--csv PATH] [--db PATH] [--dry-run]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$SeedArgs)
$ErrorActionPreference = 'Stop'
# Strip any \\?\ long-path prefix: PS 5.1 providers and GetFullPath choke on it.
$scriptDir = $PSScriptRoot -replace '^\\\\\?\\', ''
Set-Location -LiteralPath ([System.IO.Path]::GetFullPath("$scriptDir\.."))
if (Get-Command uv -ErrorAction SilentlyContinue) { uv run python scripts/seed_thor.py @SeedArgs }
else { python scripts/seed_thor.py @SeedArgs }
exit $LASTEXITCODE
