# wiki.ps1 - PATH launcher for PowerShell. Resolves tools\wiki.pyz relative to
# this script and runs it with py -3 or python.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pyz  = Join-Path $root "tools\wiki.pyz"
if (-not (Test-Path $pyz)) {
  Write-Error "wiki: cannot find $pyz. Build it once with: python `"$root\tools\build_pyz.py`""
  exit 1
}
$py = (Get-Command py -ErrorAction SilentlyContinue)
if ($py) { & py -3 $pyz @args; exit $LASTEXITCODE }
$py = (Get-Command python -ErrorAction SilentlyContinue)
if ($py) { & python $pyz @args; exit $LASTEXITCODE }
Write-Error "wiki: no python interpreter found on PATH."
exit 1
