from __future__ import annotations

import ctypes
import json
import os
import shutil
import string
import subprocess
from pathlib import Path
from typing import Literal
from pydantic import BaseModel

from config import AppConfig


MediaType = Literal["NVMe", "SSD", "HDD", "Unknown"]


class DriveInfo(BaseModel):
    drive: str
    media_type: MediaType = "Unknown"
    disk_model: str = ""
    bus_type: str = ""
    free_gb: float = 0.0
    total_gb: float = 0.0
    free_bytes: int = 0
    total_bytes: int = 0


class NetworkInterfaceInfo(BaseModel):
    name: str
    description: str = ""
    ip: str = ""
    link_speed_mbps: int = 0
    is_vpn: bool = False
    is_virtual: bool = False


class HardwareInfo(BaseModel):
    cpu_count: int
    ram_total_gb: float
    drives: list[DriveInfo]
    interfaces: list[NetworkInterfaceInfo]
    primary_link_mbps: int = 1000
    suggested_staging_path: str = ""


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _get_ram_total_gb() -> float:
    try:
        mem = _MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            return round(mem.ullTotalPhys / (1024**3), 1)
    except Exception:
        pass
    return 16.0


def _fallback_drives() -> list[DriveInfo]:
    drives: list[DriveInfo] = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            try:
                usage = shutil.disk_usage(root)
                drives.append(
                    DriveInfo(
                        drive=letter,
                        media_type="Unknown",
                        disk_model="",
                        bus_type="",
                        free_gb=round(usage.free / (1024**3), 1),
                        total_gb=round(usage.total / (1024**3), 1),
                        free_bytes=usage.free,
                        total_bytes=usage.total,
                    )
                )
            except OSError:
                pass
    return drives


def _parse_link_mbps(link_str: str) -> int:
    if not link_str:
        return 0
    s = str(link_str).strip().lower()
    try:
        parts = s.split()
        val = float(parts[0].replace(",", "."))
        if "gbps" in s:
            return int(val * 1000)
        if "mbps" in s:
            return int(val)
        if "kbps" in s:
            return max(1, int(val / 1000))
        if val > 10000:
            return int(val / 1_000_000)
    except Exception:
        pass
    return 0


def _probe_windows_hardware() -> tuple[list[DriveInfo], list[NetworkInterfaceInfo]]:
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$drives = @()
$phys = @{}
Get-PhysicalDisk | ForEach-Object {
  $phys[$_.DeviceId.ToString()] = $_
}
Get-Partition | Where-Object { $_.DriveLetter } | ForEach-Object {
  $dl = $_.DriveLetter.ToString().ToUpper()
  $disk = Get-Disk -Number $_.DiskNumber
  $pd = $phys[$_.DiskNumber.ToString()]
  $media = 'Unknown'
  $bus = if ($disk) { [string]$disk.BusType } else { '' }
  $model = if ($disk) { [string]$disk.FriendlyName } else { '' }
  if ($bus -eq 'NVMe') { $media = 'NVMe' }
  elseif ($pd -and $pd.MediaType -eq 'SSD') { $media = 'SSD' }
  elseif ($pd -and $pd.MediaType -eq 'HDD') { $media = 'HDD' }
  elseif ($model -match 'NVMe') { $media = 'NVMe' }
  elseif ($model -match 'SSD') { $media = 'SSD' }
  $vol = Get-PSDrive -Name $dl -PSProvider FileSystem
  $free = if ($vol) { [int64]$vol.Free } else { 0 }
  $used = if ($vol) { [int64]$vol.Used } else { 0 }
  $total = $free + $used
  $drives += [PSCustomObject]@{
    drive = $dl
    media_type = $media
    disk_model = $model
    bus_type = $bus
    free_bytes = $free
    total_bytes = $total
  }
}
$ifaces = @()
$ipMap = @{}
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne '127.0.0.1' } | ForEach-Object {
  if (-not $ipMap.ContainsKey($_.InterfaceIndex)) { $ipMap[$_.InterfaceIndex] = $_.IPAddress }
}
Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object {
  $ifaces += [PSCustomObject]@{
    name = [string]$_.Name
    description = [string]$_.InterfaceDescription
    ip = [string]$ipMap[$_.ifIndex]
    link_speed = [string]$_.LinkSpeed
  }
}
[PSCustomObject]@{ drives = $drives; interfaces = $ifaces } | ConvertTo-Json -Compress -Depth 4
"""
    drives: list[DriveInfo] = []
    ifaces: list[NetworkInterfaceInfo] = []
    try:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creation_flags,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            raw_drives = data.get("drives") or []
            if isinstance(raw_drives, dict):
                raw_drives = [raw_drives]
            seen_letters: set[str] = set()
            for item in raw_drives:
                letter = str(item.get("drive", "")).upper()
                if not letter or letter in seen_letters:
                    continue
                seen_letters.add(letter)
                free_b = int(item.get("free_bytes") or 0)
                total_b = int(item.get("total_bytes") or 0)
                if total_b <= 0:
                    try:
                        usage = shutil.disk_usage(f"{letter}:\\")
                        free_b, total_b = usage.free, usage.total
                    except OSError:
                        pass
                media = str(item.get("media_type") or "Unknown")
                if media not in ("NVMe", "SSD", "HDD", "Unknown"):
                    media = "Unknown"
                drives.append(
                    DriveInfo(
                        drive=letter,
                        media_type=media,  # type: ignore[arg-type]
                        disk_model=str(item.get("disk_model") or "").strip(),
                        bus_type=str(item.get("bus_type") or "").strip(),
                        free_gb=round(free_b / (1024**3), 1),
                        total_gb=round(total_b / (1024**3), 1),
                        free_bytes=free_b,
                        total_bytes=total_b,
                    )
                )

            raw_ifaces = data.get("interfaces") or []
            if isinstance(raw_ifaces, dict):
                raw_ifaces = [raw_ifaces]
            for item in raw_ifaces:
                name = str(item.get("name") or "").strip()
                desc = str(item.get("description") or "").strip()
                ip = str(item.get("ip") or "").strip()
                speed = _parse_link_mbps(str(item.get("link_speed") or ""))
                joined = f"{name} {desc}".lower()
                is_vpn = any(
                    k in joined
                    for k in ("vpn", "wireguard", "wintun", "tap-", "tun", "cloudflare", "warp", "openvpn", "nord", "proton")
                )
                is_virtual = (not is_vpn) and any(
                    k in joined
                    for k in ("hyper-v", "vethernet", "wsl", "virtualbox", "vmware", "loopback", "docker", "bluetooth", "teredo", "isatap")
                )
                ifaces.append(
                    NetworkInterfaceInfo(
                        name=name,
                        description=desc,
                        ip=ip,
                        link_speed_mbps=speed,
                        is_vpn=is_vpn,
                        is_virtual=is_virtual,
                    )
                )
    except Exception:
        pass

    if not drives:
        drives = _fallback_drives()
    drives.sort(key=lambda d: d.drive)
    return drives, ifaces


def suggest_staging_path(drives: list[DriveInfo]) -> str:
    nvmes = [d for d in drives if d.media_type == "NVMe"]
    ssds = [d for d in drives if d.media_type == "SSD"]
    candidates = nvmes or ssds
    if not candidates:
        return ""
    best = max(candidates, key=lambda d: d.free_bytes)
    return f"{best.drive}:\\VortexStaging"


def detect_hardware() -> HardwareInfo:
    cpu_count = os.cpu_count() or 8
    ram_total_gb = _get_ram_total_gb()
    drives, ifaces = _probe_windows_hardware()

    physical_ifaces = [
        i for i in ifaces
        if i.ip and not i.is_virtual
    ]
    speeds = [i.link_speed_mbps for i in physical_ifaces if i.link_speed_mbps > 0]
    primary_link_mbps = max(speeds) if speeds else 1000

    return HardwareInfo(
        cpu_count=cpu_count,
        ram_total_gb=ram_total_gb,
        drives=drives,
        interfaces=ifaces,
        primary_link_mbps=primary_link_mbps,
        suggested_staging_path=suggest_staging_path(drives),
    )


def refresh_drive_usage(hw: HardwareInfo) -> HardwareInfo:
    updated: list[DriveInfo] = []
    for d in hw.drives:
        try:
            usage = shutil.disk_usage(f"{d.drive}:\\")
            updated.append(
                d.model_copy(
                    update={
                        "free_bytes": usage.free,
                        "total_bytes": usage.total,
                        "free_gb": round(usage.free / (1024**3), 1),
                        "total_gb": round(usage.total / (1024**3), 1),
                    }
                )
            )
        except OSError:
            updated.append(d)
    return hw.model_copy(update={"drives": updated})


def classify_path_drive(path: str, hw: HardwareInfo) -> DriveInfo | None:
    if not path:
        return None
    drive_str, _ = os.path.splitdrive(os.path.abspath(path))
    if not drive_str:
        return None
    letter = drive_str.rstrip(":\\/").upper()
    for d in hw.drives:
        if d.drive.upper() == letter:
            return d
    try:
        usage = shutil.disk_usage(f"{letter}:\\")
        return DriveInfo(
            drive=letter,
            media_type="Unknown",
            free_gb=round(usage.free / (1024**3), 1),
            total_gb=round(usage.total / (1024**3), 1),
            free_bytes=usage.free,
            total_bytes=usage.total,
        )
    except OSError:
        return None


def should_use_staging(
    save_path: str,
    total_size_bytes: int,
    cfg: AppConfig,
    hw: HardwareInfo,
) -> tuple[bool, str]:
    if not cfg.nvme_staging_enabled:
        return False, "Turbo Staging desativado nas configurações."

    staging_dir = (cfg.staging_path or hw.suggested_staging_path).strip()
    if not staging_dir:
        return False, "Nenhuma unidade SSD ou NVMe disponível para staging."

    dst_drive = classify_path_drive(save_path, hw)
    stg_drive = classify_path_drive(staging_dir, hw)

    if stg_drive is None:
        return False, f"Unidade de staging inacessível ({staging_dir})."

    if stg_drive.media_type == "HDD":
        return False, f"Staging ({stg_drive.drive}:) está em um HDD, sem ganho sobre o destino."

    if dst_drive is not None:
        if dst_drive.drive.upper() == stg_drive.drive.upper():
            return False, f"Destino e staging estão na mesma unidade ({dst_drive.drive}:)."
        if dst_drive.media_type in ("NVMe", "SSD"):
            return (
                False,
                f"Destino ({dst_drive.drive}: {dst_drive.media_type}) já possui gravação rápida.",
            )

    if total_size_bytes > 0 and cfg.staging_min_size_gb > 0:
        min_size_bytes = int(cfg.staging_min_size_gb * (1024**3))
        if total_size_bytes < min_size_bytes:
            return (
                False,
                f"Arquivo menor que {cfg.staging_min_size_gb:g} GB: gravação direta usa cache em RAM sem cópia extra.",
            )

    try:
        usage = shutil.disk_usage(f"{stg_drive.drive}:\\")
        free_bytes = usage.free
    except OSError:
        free_bytes = stg_drive.free_bytes

    reserve_bytes = int(cfg.staging_min_free_gb * (1024**3))
    if total_size_bytes > 0:
        needed_bytes = int(total_size_bytes * 1.15) + reserve_bytes
        if free_bytes < needed_bytes:
            free_gb = round(free_bytes / (1024**3), 1)
            need_gb = round(needed_bytes / (1024**3), 1)
            return (
                False,
                f"Espaço insuficiente no staging ({free_gb} GB livres, necessário {need_gb} GB).",
            )
    else:
        min_magnet_bytes = reserve_bytes + int(5 * (1024**3))
        if free_bytes < min_magnet_bytes:
            free_gb = round(free_bytes / (1024**3), 1)
            return (
                False,
                f"Espaço baixo no staging ({free_gb} GB livres) para iniciar magnet.",
            )

    dst_label = f"{dst_drive.drive}: ({dst_drive.media_type})" if dst_drive else save_path
    return (
        True,
        f"Turbo Staging ativo: grava no {stg_drive.media_type} ({stg_drive.drive}:) e move para {dst_label} ao concluir.",
    )
