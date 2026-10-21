[CmdletBinding()]
param([string]$PythonExe = '')
$ErrorActionPreference = 'Stop'
$project = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (!$PythonExe) {
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Source -notlike '*WindowsApps*') { $PythonExe = $candidate.Source }
}
if (!$PythonExe) {
    $bundled = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) { $PythonExe = $bundled }
}
if (!$PythonExe) { throw 'Supply -PythonExe with a real Python interpreter. Firmware builds do not require Python.' }
$savedTemp = $env:TEMP; $savedTmp = $env:TMP
Push-Location -LiteralPath $project
try {
    $tempDir = Join-Path $project 'Build\host-tests'
    New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    $env:TEMP = $tempDir; $env:TMP = $tempDir
    & $PythonExe -B Tools\protocol_test.py
    if ($LASTEXITCODE) { throw 'Protocol tests failed' }
    & .\Tests\imu_test.cmd
    if ($LASTEXITCODE) { throw 'IMU tests failed' }
    & .\Tests\control_table_test.cmd
    if ($LASTEXITCODE) { throw 'Control table tests failed' }
    & $PythonExe -B Tests\probe_test.py
    if ($LASTEXITCODE) { throw 'PC probe tests failed' }
    Write-Host 'All host tests passed (no hardware required).'
} finally {
    Pop-Location
    $env:TEMP = $savedTemp; $env:TMP = $savedTmp
}
