$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host "1. Configurando ambiente Python 3.13..."
$venv = Join-Path $root 'engine\.venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
  py -3.13 -m venv $venv
}
& (Join-Path $venv 'Scripts\python.exe') -m pip install --upgrade pip
& (Join-Path $venv 'Scripts\pip.exe') install -r (Join-Path $root 'engine\requirements.txt')

Write-Host "2. Gerando icones..."
& (Join-Path $venv 'Scripts\python.exe') (Join-Path $root 'scripts\generate_icons.py')

Write-Host "3. Instalando dependencias UI e buildando..."
Push-Location (Join-Path $root 'ui')
npm install
npm run build
Pop-Location

Write-Host "4. Instalando Electron..."
Push-Location (Join-Path $root 'desktop')
npm install
Pop-Location

Write-Host "Setup concluido com sucesso."
