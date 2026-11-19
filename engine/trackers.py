from __future__ import annotations

import time
from pathlib import Path
import httpx

from config import get_cache_dir


FALLBACK_TRACKERS: list[str] = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "http://tracker.openbittorrent.com:80/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
    "udp://tracker.theoks.net:6969/announce",
    "udp://tracker.dump.cl:6969/announce",
    "udp://p4p.arenabg.com:1337/announce",
    "udp://retracker01-msk-virt.corbina.net:80/announce",
    "https://tracker.tamersunion.org:443/announce",
    "https://tracker.gbitt.info:443/announce",
    "http://tracker.gbitt.info:80/announce",
    "udp://bt1.archive.org:6969/announce",
    "udp://bt2.archive.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
]

TRACKER_SOURCE_URL = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"
CACHE_TTL_SECONDS = 24 * 3600


def _normalize_trackers(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in lines:
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        if not url.startswith(("udp://", "http://", "https://", "wss://", "ws://")):
            continue
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def _cache_file() -> Path:
    return get_cache_dir() / "trackers_best.txt"


def get_cached_trackers() -> list[str]:
    path = _cache_file()
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            parsed = _normalize_trackers(lines)
            if parsed:
                return _normalize_trackers(parsed + FALLBACK_TRACKERS)
        except Exception:
            pass
    return list(FALLBACK_TRACKERS)


def is_cache_stale() -> bool:
    path = _cache_file()
    if not path.exists():
        return True
    try:
        age = time.time() - path.stat().st_mtime
        return age > CACHE_TTL_SECONDS
    except OSError:
        return True


async def refresh_trackers_async(force: bool = False) -> list[str]:
    if not force and not is_cache_stale():
        return get_cached_trackers()
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(TRACKER_SOURCE_URL)
            if resp.status_code == 200 and resp.text.strip():
                parsed = _normalize_trackers(resp.text.splitlines())
                if len(parsed) >= 5:
                    _cache_file().write_text("\n".join(parsed), encoding="utf-8")
                    return _normalize_trackers(parsed + FALLBACK_TRACKERS)
    except Exception:
        pass
    return get_cached_trackers()
