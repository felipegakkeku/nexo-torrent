$ErrorActionPreference = 'Stop'

$magnetBase = 'HKCU:\Software\Classes\magnet'
if (Test-Path "$magnetBase\shell\open\command") {
  $val = (Get-ItemProperty -Path "$magnetBase\shell\open\command" -Name '(Default)' -ErrorAction SilentlyContinue).'(Default)'
  if ($val -like '*NexoTorrent*' -or $val -like '*VortexTorrent*') {
    Remove-Item -Path $magnetBase -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$extBase = 'HKCU:\Software\Classes\.torrent'
if (Test-Path $extBase) {
  $extVal = (Get-ItemProperty -Path $extBase -Name '(Default)' -ErrorAction SilentlyContinue).'(Default)'
  if ($extVal -eq 'NexoTorrent.File' -or $extVal -eq 'VortexTorrent.File') {
    Remove-Item -Path $extBase -Recurse -Force -ErrorAction SilentlyContinue
  }
}

foreach ($legacyProgId in @('HKCU:\Software\Classes\NexoTorrent.File', 'HKCU:\Software\Classes\VortexTorrent.File')) {
  if (Test-Path $legacyProgId) {
    Remove-Item -Path $legacyProgId -Recurse -Force -ErrorAction SilentlyContinue
  }
}

Write-Output 'Handlers do Nexo Torrent removidos do Registro.'
