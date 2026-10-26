# Thin wrapper: implementation is scripts/seed_db.py (needs downloads first:
# scripts/download_data.ps1 predictions.zip gadm41_LAO_1.json gadm41_KHM_1.json gadm41_VNM_1.json).
$ErrorActionPreference = 'Stop'
# Strip any \\?\ long-path prefix: PS 5.1 providers and GetFullPath choke on it.
$scriptDir = $PSScriptRoot -replace '^\\\\\?\\', ''
Set-Location -LiteralPath ([System.IO.Path]::GetFullPath("$scriptDir\.."))
if (Get-Command uv -ErrorAction SilentlyContinue) { uv run python scripts/seed_db.py }
else { python scripts/seed_db.py }
exit $LASTEXITCODE
