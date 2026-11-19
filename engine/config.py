from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field


ProfileType = Literal["turbo_max", "balanced", "quiet"]


def get_data_dir() -> Path:
    override = os.environ.get("VORTEX_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    else:
        local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        base = Path(local_app) / "VortexTorrent"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_state_dir() -> Path:
    d = get_data_dir() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cache_dir() -> Path:
    d = get_data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_config_path() -> Path:
    return get_data_dir() / "config.json"


class AppConfig(BaseModel):
    profile: ProfileType = "turbo_max"
    default_save_path: str = r"D:\Downloads\Torrents"
    nvme_staging_enabled: bool = True
    staging_path: str = ""
    staging_min_free_gb: float = Field(default=20.0, ge=1.0, le=500.0)
    listen_port: int = Field(default=51413, ge=1024, le=65535)
    random_port: bool = False
    network_interface: str = ""
    prefer_tcp: bool = True
    enable_utp: bool = True
    enable_dht: bool = True
    enable_lsd: bool = True
    enable_upnp: bool = True
    auto_boost_public_trackers: bool = True
    anti_stall_enabled: bool = True
    download_limit_kbps: int = Field(default=0, ge=0)
    upload_limit_kbps: int = Field(default=0, ge=0)
    max_active_downloads: int = Field(default=12, ge=1, le=100)
    max_active_seeds: int = Field(default=12, ge=0, le=100)
    preallocate_files: bool = True
    minimize_to_tray: bool = True
    client_fingerprint: str = "VortexTorrent/1.0"


def load_config() -> AppConfig:
    path = get_config_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return AppConfig.model_validate(raw)
        except Exception:
            pass
    cfg = AppConfig()
    save_config(cfg)
    return cfg


def save_config(cfg: AppConfig) -> AppConfig:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return cfg
