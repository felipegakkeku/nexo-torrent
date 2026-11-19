$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vbsPath = Join-Path $root 'NexoTorrent.vbs'
$iconPath = Join-Path $root 'desktop\assets\icon.ico'

if (-not (Test-Path $vbsPath)) {
  throw "Launcher nao encontrado em $vbsPath"
}

$cmdStr = "wscript.exe `"$vbsPath`" `"%1`""

# Protocolo magnet:
$magnetBase = 'HKCU:\Software\Classes\magnet'
New-Item -Path "$magnetBase\DefaultIcon" -Force | Out-Null
New-Item -Path "$magnetBase\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path $magnetBase -Name '(Default)' -Value 'URL:Magnet Link (Nexo Torrent)'
Set-ItemProperty -Path $magnetBase -Name 'URL Protocol' -Value ''
Set-ItemProperty -Path "$magnetBase\DefaultIcon" -Name '(Default)' -Value "`"$iconPath`",0"
Set-ItemProperty -Path "$magnetBase\shell\open\command" -Name '(Default)' -Value $cmdStr

# Arquivos .torrent via ProgID proprio
$progId = 'HKCU:\Software\Classes\NexoTorrent.File'
New-Item -Path "$progId\DefaultIcon" -Force | Out-Null
New-Item -Path "$progId\shell\open\command" -Force | Out-Null
Set-ItemProperty -Path $progId -Name '(Default)' -Value 'Arquivo Torrent (Nexo Torrent)'
Set-ItemProperty -Path $progId\DefaultIcon -Name '(Default)' -Value "`"$iconPath`",0"
Set-ItemProperty -Path "$progId\shell\open\command" -Name '(Default)' -Value $cmdStr

$extBase = 'HKCU:\Software\Classes\.torrent'
New-Item -Path $extBase -Force | Out-Null
Set-ItemProperty -Path $extBase -Name '(Default)' -Value 'NexoTorrent.File'

Write-Output 'Handlers magnet: e .torrent registrados para o usuario atual.'
