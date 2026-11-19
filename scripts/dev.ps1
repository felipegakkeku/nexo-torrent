$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$viteProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev' -WorkingDirectory (Join-Path $root 'ui') -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 2

try {
  $env:VORTEX_DEV_URL = 'http://127.0.0.1:5173'
  Push-Location (Join-Path $root 'desktop')
  npm start
  Pop-Location
} finally {
  Remove-Item Env:VORTEX_DEV_URL -ErrorAction SilentlyContinue
  if ($viteProc -and -not $viteProc.HasExited) {
    Stop-Process -Id $viteProc.Id -Force -ErrorAction SilentlyContinue
  }
}
