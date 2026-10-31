param()
$root = Split-Path -Parent $PSScriptRoot
python (Join-Path $root 'tools\validate_system.py')
exit $LASTEXITCODE
