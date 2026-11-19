$ErrorActionPreference = 'Stop'

$magnetBase = 'HKCU:\Software\Classes\magnet'
if (Test-Path "$magnetBase\shell\open\command") {
  $val = (Get-ItemProperty -Path "$magnetBase\shell\open\command" -Name '(Default)' -ErrorAction SilentlyContinue).'(Default)'
  if ($val -like '*VortexTorrent*') {
    Remove-Item -Path $magnetBase -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$extBase = 'HKCU:\Software\Classes\.torrent'
if (Test-Path $extBase) {
  $extVal = (Get-ItemProperty -Path $extBase -Name '(Default)' -ErrorAction SilentlyContinue).'(Default)'
  if ($extVal -eq 'VortexTorrent.File') {
    Remove-Item -Path $extBase -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$progId = 'HKCU:\Software\Classes\VortexTorrent.File'
if (Test-Path $progId) {
  Remove-Item -Path $progId -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output 'Handlers do VortexTorrent removidos do Registro.'
