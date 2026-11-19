$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$electronExe = Join-Path $root 'desktop\node_modules\electron\dist\electron.exe'
$desktopDir = Join-Path $root 'desktop'
$uiDist = Join-Path $root 'ui\dist\index.html'

if (-not (Test-Path $uiDist)) {
  Write-Host "Build da UI nao encontrado. Executando build..."
  Push-Location (Join-Path $root 'ui')
  npm run build
  Pop-Location
}

if (-not (Test-Path $electronExe)) {
  throw "Electron nao encontrado em $electronExe. Execute scripts\setup.ps1 primeiro."
}

Start-Process -FilePath $electronExe -ArgumentList "`"$desktopDir`"" -WindowStyle Normal
