$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$pythonExe = Join-Path $projectRoot '.venv312\Scripts\python.exe'

if (-not (Test-Path $pythonExe)) {
	throw "Python executable not found: $pythonExe"
}

Push-Location $scriptDir
try {
	& $pythonExe .\manage.py runserver 127.0.0.1:8001
}
finally {
	Pop-Location
}