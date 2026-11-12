param([int]$Port = 8791)

$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PAINEL_PORT = "$Port"

$candidates = @(
  "$env:LOCALAPPDATA\hermes\tools\python-3.14.9+20261021-win32-x64\python.exe",
  "C:\Users\PAULA\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
) | Where-Object { Test-Path $_ }

$python = $candidates | Select-Object -First 1
if (-not $python) {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { $python = $cmd.Source }
}
if (-not $python) { throw "Python nao encontrado. Ajuste o caminho em start_painel.ps1." }

Start-Process -FilePath $python -ArgumentList @("$dir\server.py") -WindowStyle Hidden
Write-Host "Painel: http://127.0.0.1:$Port"
