from __future__ import annotations

import ipaddress
import json
import logging
import os
import shutil
import socket
import struct
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import libtorrent as lt

from config import AppConfig, get_state_dir, load_config, save_config
from hardware import (
    HardwareInfo,
    classify_path_drive,
    detect_hardware,
    refresh_drive_usage,
    should_use_staging,
)
from trackers import get_cached_trackers

logger = logging.getLogger("nexo.torrent.engine")


def get_info_hash(obj: Any) -> str:
    if hasattr(obj, "info_hashes"):
        ih_attr = obj.info_hashes
        try:
            ih = ih_attr() if callable(ih_attr) else ih_attr
            best = ih.get_best()
            s = str(best).lower()
            if s and set(s) != {"0"}:
                return s
        except Exception:
            pass
    if hasattr(obj, "info_hash"):
        h_attr = obj.info_hash
        h_val = h_attr() if callable(h_attr) else h_attr
        return str(h_val).lower()
    return ""


def _resolve_interface_bind(cfg: AppConfig, hw: HardwareInfo) -> tuple[str, str]:
    port = 0 if cfg.random_port else int(cfg.listen_port)
    iface_sel = (cfg.network_interface or "").strip()
    if iface_sel:
        try:
            ip_obj = ipaddress.ip_address(iface_sel)
            formatted = f"[{iface_sel}]:{port}" if ip_obj.version == 6 else f"{iface_sel}:{port}"
            return formatted, iface_sel
        except ValueError:
            pass
        for iface in hw.interfaces:
            if iface.name == iface_sel or iface.ip == iface_sel:
                if iface.ip:
                    return f"{iface.ip}:{port}", iface.ip

    routable: list[str] = []
    seen: set[str] = set()
    for iface in hw.interfaces:
        ip = (iface.ip or "").strip()
        if not ip or iface.is_virtual:
            continue
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        if ip not in seen:
            seen.add(ip)
            routable.append(ip)
    if routable:
        return ",".join(f"{ip}:{port}" for ip in routable), ""
    return f"0.0.0.0:{port},[::]:{port}", ""


def build_settings_pack(
    cfg: AppConfig,
    hw: HardwareInfo,
    current_settings: dict[str, Any],
) -> dict[str, Any]:
    base = (
        dict(lt.high_performance_seed())
        if cfg.profile == "turbo_max"
        else dict(lt.default_settings())
    )

    listen_ifaces, outgoing_iface = _resolve_interface_bind(cfg, hw)
    prefer_tcp_val = int(lt.bandwidth_mixed_algo_t.prefer_tcp)
    proportional_val = int(lt.bandwidth_mixed_algo_t.peer_proportional)
    os_cache_val = int(lt.io_buffer_mode_t.enable_os_cache)
    fastest_upload_val = int(lt.seed_choking_algorithm_t.fastest_upload)

    aio_turbo = min(16, max(8, hw.cpu_count))
    hash_turbo = min(8, max(4, hw.cpu_count // 2))

    if cfg.profile == "turbo_max":
        queued_disk_max = (
            1024 * 1024 * 1024 if hw.ram_total_gb >= 24.0 else 512 * 1024 * 1024
        )
        profile_overrides: dict[str, Any] = {
            "connection_speed": 500,
            "connections_limit": 1200,
            "torrent_connect_boost": 100,
            "smooth_connects": False,
            "coalesce_writes": True,
            "coalesce_reads": True,
            "piece_extent_affinity": True,
            "max_out_request_queue": 2500,
            "max_allowed_in_request_queue": 3000,
            "request_queue_time": 3,
            "whole_pieces_threshold": 20,
            "strict_end_game_mode": False,
            "peer_connect_timeout": 7,
            "piece_timeout": 10,
            "request_timeout": 25,
            "max_pex_peers": 200,
            "max_peer_recv_buffer_size": 8 * 1024 * 1024,
            "peer_turnover": 8,
            "peer_turnover_cutoff": 75,
            "peer_turnover_interval": 90,
            "utp_target_delay": 250,
            "utp_gain_factor": 6000,
            "max_web_seed_connections": 16,
            "listen_queue_size": 64,
            "dht_upload_rate_limit": 64000,
            "dht_search_branching": 10,
            "dht_max_peers_reply": 200,
            "send_buffer_low_watermark": 2 * 1024 * 1024,
            "send_buffer_watermark": 8 * 1024 * 1024,
            "send_buffer_watermark_factor": 150,
            "recv_socket_buffer_size": 4 * 1024 * 1024,
            "send_socket_buffer_size": 4 * 1024 * 1024,
            "aio_threads": aio_turbo,
            "hashing_threads": hash_turbo,
            "checking_mem_usage": 4096,
            "max_queued_disk_bytes": queued_disk_max,
            "file_pool_size": 500,
            "unchoke_slots_limit": 32,
            "max_peerlist_size": 5000,
            "max_paused_peerlist_size": 2000,
        }
    elif cfg.profile == "balanced":
        profile_overrides = {
            "connection_speed": 200,
            "connections_limit": 500,
            "torrent_connect_boost": 50,
            "smooth_connects": False,
            "coalesce_writes": True,
            "coalesce_reads": True,
            "piece_extent_affinity": True,
            "max_out_request_queue": 1000,
            "max_allowed_in_request_queue": 1200,
            "request_queue_time": 3,
            "whole_pieces_threshold": 15,
            "strict_end_game_mode": False,
            "peer_connect_timeout": 10,
            "piece_timeout": 14,
            "request_timeout": 35,
            "max_pex_peers": 120,
            "max_peer_recv_buffer_size": 4 * 1024 * 1024,
            "max_web_seed_connections": 8,
            "dht_upload_rate_limit": 32000,
            "dht_search_branching": 8,
            "send_buffer_low_watermark": 1024 * 1024,
            "send_buffer_watermark": 4 * 1024 * 1024,
            "send_buffer_watermark_factor": 150,
            "recv_socket_buffer_size": 2 * 1024 * 1024,
            "send_socket_buffer_size": 2 * 1024 * 1024,
            "aio_threads": min(8, max(4, hw.cpu_count // 2)),
            "hashing_threads": max(2, hw.cpu_count // 4),
            "checking_mem_usage": 1024,
            "max_queued_disk_bytes": 128 * 1024 * 1024,
            "file_pool_size": 250,
            "unchoke_slots_limit": 16,
            "max_peerlist_size": 3000,
            "max_paused_peerlist_size": 1000,
        }
    else:  # quiet
        profile_overrides = {
            "connection_speed": 80,
            "connections_limit": 220,
            "torrent_connect_boost": 20,
            "max_out_request_queue": 400,
            "max_allowed_in_request_queue": 500,
            "request_queue_time": 3,
            "whole_pieces_threshold": 10,
            "strict_end_game_mode": True,
            "send_buffer_low_watermark": 256 * 1024,
            "send_buffer_watermark": 1024 * 1024,
            "send_buffer_watermark_factor": 120,
            "recv_socket_buffer_size": 1024 * 1024,
            "send_socket_buffer_size": 1024 * 1024,
            "aio_threads": 4,
            "hashing_threads": 2,
            "checking_mem_usage": 256,
            "max_queued_disk_bytes": 32 * 1024 * 1024,
            "file_pool_size": 100,
            "unchoke_slots_limit": 8,
            "max_peerlist_size": 1500,
            "max_paused_peerlist_size": 500,
        }

    common_overrides: dict[str, Any] = {
        "announce_to_all_trackers": True,
        "announce_to_all_tiers": True,
        "allow_multiple_connections_per_ip": True,
        "mixed_mode_algorithm": prefer_tcp_val if cfg.prefer_tcp else proportional_val,
        "enable_outgoing_tcp": True,
        "enable_incoming_tcp": True,
        "enable_outgoing_utp": bool(cfg.enable_utp),
        "enable_incoming_utp": bool(cfg.enable_utp),
        "rate_limit_ip_overhead": False,
        "disk_io_write_mode": os_cache_val,
        "disk_io_read_mode": os_cache_val,
        "seed_choking_algorithm": fastest_upload_val,
        "tracker_completion_timeout": 10,
        "tracker_receive_timeout": 7,
        "tracker_backoff": 100,
        "stop_tracker_timeout": 2,
        "active_downloads": int(cfg.max_active_downloads),
        "active_seeds": int(cfg.max_active_seeds),
        "active_limit": max(30, int(cfg.max_active_downloads) + int(cfg.max_active_seeds) + 6),
        "active_tracker_limit": 1600,
        "active_dht_limit": 88,
        "enable_dht": bool(cfg.enable_dht),
        "enable_lsd": bool(cfg.enable_lsd),
        "enable_upnp": bool(cfg.enable_upnp),
        "enable_natpmp": bool(cfg.enable_upnp),
        "dht_bootstrap_nodes": (
            "router.bittorrent.com:6881,"
            "router.utorrent.com:6881,"
            "dht.transmissionbt.com:6881,"
            "dht.aelitis.com:6881,"
            "dht.libtorrent.org:25401"
        ),
        "listen_interfaces": listen_ifaces,
        "outgoing_interfaces": outgoing_iface,
        "download_rate_limit": int(cfg.download_limit_kbps) * 1024 if cfg.download_limit_kbps > 0 else 0,
        "upload_rate_limit": int(cfg.upload_limit_kbps) * 1024 if cfg.upload_limit_kbps > 0 else 0,
        "user_agent": cfg.client_fingerprint or "NexoTorrent/1.1",
        "alert_mask": int(
            lt.alert_category.error
            | lt.alert_category.status
            | lt.alert_category.storage
            | lt.alert_category.tracker
            | lt.alert_category.stats
            | lt.alert_category.performance_warning
        ),
    }

    merged = {**base, **profile_overrides, **common_overrides}
    valid_keys = set(current_settings.keys())
    filtered: dict[str, Any] = {}
    for k, v in merged.items():
        if k in valid_keys:
            filtered[k] = v
        else:
            logger.warning("Chave de configuracao ignorada no libtorrent: %s", k)
    return filtered


_STATE_LABELS = {
    lt.torrent_status.states.checking_files: "Verificando",
    lt.torrent_status.states.downloading_metadata: "Obtendo metadados",
    lt.torrent_status.states.downloading: "Baixando",
    lt.torrent_status.states.finished: "Concluído",
    lt.torrent_status.states.seeding: "Semeando",
    lt.torrent_status.states.checking_resume_data: "Verificando retomada",
}


class NexoTorrentEngine:
    def __init__(self, on_torrent_finished: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._lock = threading.RLock()
        self.on_torrent_finished = on_torrent_finished
        self.hw: HardwareInfo = detect_hardware()
        self.cfg: AppConfig = load_config()
        if not self.cfg.staging_path and self.hw.suggested_staging_path:
            self.cfg.staging_path = self.hw.suggested_staging_path
            save_config(self.cfg)

        self.state_dir = get_state_dir()
        self.meta_path = self.state_dir / "meta.json"
        self.dht_nodes_path = self.state_dir / "dht_nodes.json"
        legacy_state = self.state_dir / "session.state"
        if legacy_state.exists():
            try:
                legacy_state.unlink()
            except OSError:
                pass
        self._meta: dict[str, dict[str, Any]] = self._load_meta()
        self._pending_dht_nodes: list[tuple[str, int]] = self._load_pending_dht_nodes()
        self._dht_inject_after = time.time() + 0.6
        self._dht_state_loaded = False

        self.ses = lt.session()

        self._metric_idx: dict[str, int] = {
            m.name: m.value_index for m in lt.session_stats_metrics()
        }
        self._session_counters: dict[str, int] = {
            "queued_write_bytes": 0,
            "recv_payload_bytes": 0,
            "recv_ip_overhead_bytes": 0,
            "dht_nodes": 0,
            "num_peers_connected": 0,
            "num_peers_half_open": 0,
        }
        self._prev_payload_bytes = 0
        self._prev_overhead_bytes = 0
        self._payload_efficiency = 100.0
        self._speed_history: deque[dict[str, Any]] = deque(maxlen=60)
        self._last_anti_stall_run = 0.0
        self._last_resume_save = time.time()
        self._last_session_state_save = time.time()
        self._last_hw_refresh = time.time()
        self._pending_removals: set[str] = set()
        self._notified_finished: set[str] = set()

        self.apply_config(self.cfg)
        self._restore_saved_torrents()

    def _load_meta(self) -> dict[str, dict[str, Any]]:
        if self.meta_path.exists():
            try:
                import json
                data = json.loads(self.meta_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _save_meta(self) -> None:
        import json
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(json.dumps(self._meta, indent=2), encoding="utf-8")

    def _load_pending_dht_nodes(self) -> list[tuple[str, int]]:
        if not self.dht_nodes_path.exists():
            return []
        try:
            raw = json.loads(self.dht_nodes_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            nodes: list[tuple[str, int]] = []
            for item in raw[:200]:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    ip_s = str(item[0]).strip()
                    port_i = int(item[1])
                    if ip_s and 0 < port_i < 65536:
                        nodes.append((ip_s, port_i))
            return nodes
        except Exception:
            return []

    def _inject_pending_dht_nodes(self, now: float) -> None:
        if not self._pending_dht_nodes or now < self._dht_inject_after:
            return
        if not self.cfg.enable_dht:
            self._pending_dht_nodes = []
            return
        injected = 0
        for ep in self._pending_dht_nodes:
            try:
                self.ses.add_dht_node(ep)
                injected += 1
            except Exception:
                pass
        self._pending_dht_nodes = []
        if injected > 0:
            self._dht_state_loaded = True

    def _save_dht_nodes(self) -> None:
        try:
            sp = self.ses.session_state(lt.save_state_flags_t.save_dht_state)
            buf = lt.write_session_params_buf(sp)
            dec = lt.bdecode(buf)
            raw_nodes = dec.get(b"dht state", {}).get(b"nodes", [])
            endpoints: list[list[Any]] = []
            seen: set[tuple[str, int]] = set()
            for item in raw_nodes:
                ip_s = ""
                port_i = 0
                if isinstance(item, bytes) and len(item) == 6:
                    ip_s = socket.inet_ntoa(item[:4])
                    port_i = struct.unpack("!H", item[4:6])[0]
                elif isinstance(item, (list, tuple)) and len(item) == 2:
                    ip_b, p = item
                    ip_s = ip_b.decode("ascii", errors="ignore") if isinstance(ip_b, bytes) else str(ip_b)
                    port_i = int(p)
                if ip_s and 0 < port_i < 65536 and (ip_s, port_i) not in seen:
                    seen.add((ip_s, port_i))
                    endpoints.append([ip_s, port_i])
                if len(endpoints) >= 200:
                    break
            if endpoints:
                self.state_dir.mkdir(parents=True, exist_ok=True)
                self.dht_nodes_path.write_text(json.dumps(endpoints), encoding="utf-8")
        except Exception as exc:
            logger.debug("Erro ao persistir dht_nodes.json: %s", exc)

    def apply_config(self, new_cfg: AppConfig) -> AppConfig:
        with self._lock:
            self.cfg = save_config(new_cfg)
            current = self.ses.get_settings()
            pack = build_settings_pack(self.cfg, self.hw, current)
            self.ses.apply_settings(pack)
            return self.cfg

    def get_hardware(self, refresh_usage: bool = True) -> HardwareInfo:
        with self._lock:
            if refresh_usage:
                self.hw = refresh_drive_usage(self.hw)
            return self.hw

    def _restore_saved_torrents(self) -> None:
        for tfile in sorted(self.state_dir.glob("*.torrent")):
            ih = tfile.stem.lower()
            resume_file = self.state_dir / f"{ih}.fastresume"
            try:
                raw_t = tfile.read_bytes()
                ti = lt.torrent_info(lt.bdecode(raw_t))
                if resume_file.exists():
                    atp = lt.read_resume_data(resume_file.read_bytes())
                    atp.ti = ti
                    meta = self._meta.get(ih, {})
                    if not meta.get("staging_active") and meta.get("final_save_path"):
                        atp.save_path = meta["final_save_path"]
                else:
                    atp = lt.add_torrent_params()
                    atp.ti = ti
                    meta = self._meta.get(ih, {})
                    save_dir = (
                        meta.get("staged_path")
                        if meta.get("staging_active") and meta.get("staged_path")
                        else meta.get("final_save_path") or self.cfg.default_save_path
                    )
                    atp.save_path = save_dir
                if not atp.save_path:
                    atp.save_path = self.cfg.default_save_path
                Path(atp.save_path).mkdir(parents=True, exist_ok=True)
                handle = self.ses.add_torrent(atp)
                st = handle.status()
                meta = self._meta.get(ih, {})
                if meta.get("completed") or st.is_finished or st.is_seeding:
                    self._notified_finished.add(ih)
            except Exception as exc:
                logger.warning("Falha ao restaurar torrent %s: %s", tfile.name, exc)

    def inspect_torrent_bytes(self, raw_bytes: bytes) -> dict[str, Any]:
        decoded = lt.bdecode(raw_bytes)
        ti = lt.torrent_info(decoded)
        ih = get_info_hash(ti)
        fs = ti.layout() if hasattr(ti, "layout") else ti.files()
        files = []
        for idx in range(fs.num_files()):
            files.append(
                {
                    "index": idx,
                    "path": fs.file_path(idx),
                    "size": fs.file_size(idx),
                }
            )
        return {
            "info_hash": ih,
            "name": ti.name(),
            "total_size": ti.total_size(),
            "num_pieces": ti.num_pieces(),
            "piece_length": ti.piece_length(),
            "is_private": bool(ti.priv()),
            "trackers": [tr.url for tr in ti.trackers()],
            "files": files,
        }

    def _prepare_staging_decision(
        self,
        info_hash: str,
        final_save_path: str,
        total_size: int,
        explicit_use_staging: bool | None,
    ) -> tuple[bool, str, str]:
        hw = self.get_hardware(refresh_usage=True)
        staging_root = (self.cfg.staging_path or hw.suggested_staging_path).strip()
        if explicit_use_staging is False:
            return False, final_save_path, "Staging desativado para este torrent."

        auto_use, reason = should_use_staging(final_save_path, total_size, self.cfg, hw)
        if explicit_use_staging is True:
            if not staging_root:
                return False, final_save_path, "Nenhuma pasta de staging SSD/NVMe disponível."
            staged_dir = str(Path(staging_root) / info_hash)
            return True, staged_dir, f"Turbo Staging forçado em {staging_root}."

        if auto_use:
            staged_dir = str(Path(staging_root) / info_hash)
            return True, staged_dir, reason
        return False, final_save_path, reason

    def _apply_prioritize_ends(self, handle: lt.torrent_handle) -> None:
        ti = handle.torrent_file()
        if not ti or not ti.is_valid():
            return
        num_pieces = ti.num_pieces()
        if num_pieces <= 4:
            return
        head_count = max(1, int(num_pieces * 0.03))
        tail_count = max(1, int(num_pieces * 0.01))
        prios = list(handle.get_piece_priorities())
        for i in range(min(head_count, len(prios))):
            if prios[i] > 0:
                prios[i] = 7
        for i in range(max(0, len(prios) - tail_count), len(prios)):
            if prios[i] > 0:
                prios[i] = 7
        handle.prioritize_pieces(prios)

    def _inject_public_trackers(
        self,
        handle: lt.torrent_handle | None,
        atp: lt.add_torrent_params | None = None,
    ) -> list[str]:
        candidates = get_cached_trackers()
        injected: list[str] = []
        if atp is not None:
            existing = set(atp.trackers or [])
            tiers = list(atp.tracker_tiers or [])
            next_tier = (max(tiers) + 1) if tiers else 0
            new_trackers = list(atp.trackers or [])
            for url in candidates:
                if url not in existing:
                    new_trackers.append(url)
                    tiers.append(next_tier)
                    injected.append(url)
                    existing.add(url)
            atp.trackers = new_trackers
            atp.tracker_tiers = tiers
            return injected

        if handle is not None and handle.is_valid():
            ti = handle.torrent_file()
            if ti and ti.priv():
                return []
            existing = {tr["url"] for tr in handle.trackers()}
            tier = 1
            for url in candidates:
                if url not in existing:
                    handle.add_tracker({"url": url, "tier": tier})
                    injected.append(url)
                    existing.add(url)
            if injected:
                handle.force_reannounce()
        return injected

    def add_magnet(
        self,
        uri: str,
        save_path: str | None = None,
        use_staging: bool | None = None,
        sequential: bool = False,
        prioritize_ends: bool = False,
        start_paused: bool = False,
        boost_trackers: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            atp = lt.parse_magnet_uri(uri.strip())
            ih = get_info_hash(atp)
            final_dir = (save_path or self.cfg.default_save_path).strip()
            Path(final_dir).mkdir(parents=True, exist_ok=True)

            staging_active, active_dir, staging_note = self._prepare_staging_decision(
                ih, final_dir, 0, use_staging
            )
            Path(active_dir).mkdir(parents=True, exist_ok=True)
            atp.save_path = active_dir
            atp.storage_mode = (
                lt.storage_mode_t.storage_mode_allocate
                if self.cfg.preallocate_files
                else lt.storage_mode_t.storage_mode_sparse
            )

            flags = atp.flags
            if sequential:
                flags |= lt.torrent_flags.sequential_download
            if start_paused:
                flags |= lt.torrent_flags.paused
                flags &= ~lt.torrent_flags.auto_managed
            else:
                flags |= lt.torrent_flags.auto_managed
                flags &= ~lt.torrent_flags.paused
            atp.flags = flags

            do_boost = self.cfg.auto_boost_public_trackers if boost_trackers is None else boost_trackers
            injected: list[str] = []
            if do_boost:
                injected = self._inject_public_trackers(None, atp=atp)

            handle = self.ses.add_torrent(atp)
            self._inject_pending_dht_nodes(time.time())
            ih = get_info_hash(handle.status()) or ih

            self._meta[ih] = {
                "final_save_path": final_dir,
                "staging_active": staging_active,
                "staged_path": active_dir if staging_active else "",
                "staging_note": staging_note,
                "added_at": time.time(),
                "peak_download_rate": 0,
                "boosted_trackers": bool(injected),
                "injected_tracker_urls": injected,
                "prioritize_ends": bool(prioritize_ends),
                "last_anti_stall_ts": 0.0,
                "last_initial_boost_ts": 0.0,
                "is_private": False,
            }
            self._save_meta()
            return self._serialize_torrent(handle.status())

    def add_torrent_bytes(
        self,
        raw_bytes: bytes,
        save_path: str | None = None,
        file_priorities: list[int] | None = None,
        use_staging: bool | None = None,
        sequential: bool = False,
        prioritize_ends: bool = False,
        start_paused: bool = False,
        boost_trackers: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            ti = lt.torrent_info(lt.bdecode(raw_bytes))
            ih = get_info_hash(ti)
            is_priv = bool(ti.priv())
            final_dir = (save_path or self.cfg.default_save_path).strip()
            Path(final_dir).mkdir(parents=True, exist_ok=True)

            staging_active, active_dir, staging_note = self._prepare_staging_decision(
                ih, final_dir, ti.total_size(), use_staging
            )
            Path(active_dir).mkdir(parents=True, exist_ok=True)

            atp = lt.add_torrent_params()
            atp.ti = ti
            atp.save_path = active_dir
            atp.storage_mode = (
                lt.storage_mode_t.storage_mode_allocate
                if self.cfg.preallocate_files
                else lt.storage_mode_t.storage_mode_sparse
            )

            flags = lt.torrent_flags.default_flags
            if sequential:
                flags |= lt.torrent_flags.sequential_download
            if start_paused:
                flags |= lt.torrent_flags.paused
                flags &= ~lt.torrent_flags.auto_managed
            else:
                flags |= lt.torrent_flags.auto_managed
                flags &= ~lt.torrent_flags.paused
            atp.flags = flags

            if file_priorities is not None:
                atp.file_priorities = [max(0, min(7, int(p))) for p in file_priorities]

            do_boost = (
                (self.cfg.auto_boost_public_trackers if boost_trackers is None else boost_trackers)
                and not is_priv
            )
            injected: list[str] = []
            if do_boost:
                injected = self._inject_public_trackers(None, atp=atp)

            handle = self.ses.add_torrent(atp)
            self._inject_pending_dht_nodes(time.time())
            if prioritize_ends:
                self._apply_prioritize_ends(handle)

            (self.state_dir / f"{ih}.torrent").write_bytes(raw_bytes)
            self._meta[ih] = {
                "final_save_path": final_dir,
                "staging_active": staging_active,
                "staged_path": active_dir if staging_active else "",
                "staging_note": staging_note,
                "added_at": time.time(),
                "peak_download_rate": 0,
                "boosted_trackers": bool(injected),
                "injected_tracker_urls": injected,
                "prioritize_ends": bool(prioritize_ends),
                "last_anti_stall_ts": 0.0,
                "last_initial_boost_ts": 0.0,
                "is_private": is_priv,
            }
            self._save_meta()
            return self._serialize_torrent(handle.status())

    def _find_handle(self, info_hash: str) -> lt.torrent_handle | None:
        target = info_hash.strip().lower()
        for h in self.ses.get_torrents():
            if not h.is_valid():
                continue
            if get_info_hash(h.status()) == target:
                return h
        return None

    def pause(self, info_hash: str) -> bool:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return False
            h.unset_flags(lt.torrent_flags.auto_managed)
            h.pause()
            return True

    def resume(self, info_hash: str) -> bool:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return False
            h.set_flags(lt.torrent_flags.auto_managed)
            h.resume()
            return True

    def pause_all(self) -> int:
        with self._lock:
            count = 0
            for h in self.ses.get_torrents():
                if h.is_valid():
                    h.unset_flags(lt.torrent_flags.auto_managed)
                    h.pause()
                    count += 1
            return count

    def resume_all(self) -> int:
        with self._lock:
            count = 0
            for h in self.ses.get_torrents():
                if h.is_valid():
                    h.set_flags(lt.torrent_flags.auto_managed)
                    h.resume()
                    count += 1
            return count

    def recheck(self, info_hash: str) -> bool:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return False
            h.force_recheck()
            return True

    def force_reannounce(self, info_hash: str) -> bool:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return False
            h.force_reannounce()
            h.force_dht_announce()
            return True

    def boost_trackers(self, info_hash: str) -> dict[str, Any]:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return {"ok": False, "added": 0, "reason": "Torrent não encontrado."}
            ti = h.torrent_file()
            if ti and ti.priv():
                return {
                    "ok": False,
                    "added": 0,
                    "reason": "Torrent privado: injeção de trackers públicos bloqueada.",
                }
            injected = self._inject_public_trackers(h)
            ih = info_hash.lower()
            meta = self._meta.setdefault(ih, {})
            prev = set(meta.get("injected_tracker_urls") or [])
            prev.update(injected)
            meta["injected_tracker_urls"] = list(prev)
            meta["boosted_trackers"] = bool(prev)
            self._save_meta()
            return {
                "ok": True,
                "added": len(injected),
                "reason": f"{len(injected)} trackers públicos adicionados." if injected else "Todos os trackers recomendados já estavam ativos.",
            }

    def set_options(
        self,
        info_hash: str,
        sequential: bool | None = None,
        prioritize_ends: bool | None = None,
        download_limit_kbps: int | None = None,
        upload_limit_kbps: int | None = None,
    ) -> bool:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return False
            ih = info_hash.lower()
            meta = self._meta.setdefault(ih, {})
            if sequential is not None:
                if sequential:
                    h.set_flags(lt.torrent_flags.sequential_download)
                else:
                    h.unset_flags(lt.torrent_flags.sequential_download)
            if prioritize_ends is not None:
                meta["prioritize_ends"] = bool(prioritize_ends)
                if prioritize_ends:
                    self._apply_prioritize_ends(h)
            if download_limit_kbps is not None:
                h.set_download_limit(max(0, int(download_limit_kbps)) * 1024)
            if upload_limit_kbps is not None:
                h.set_upload_limit(max(0, int(upload_limit_kbps)) * 1024)
            self._save_meta()
            return True

    def set_file_priorities(self, info_hash: str, priorities: list[int]) -> bool:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return False
            cleaned = [max(0, min(7, int(p))) for p in priorities]
            h.prioritize_files(cleaned)
            return True

    def remove(self, info_hash: str, delete_files: bool = False) -> bool:
        with self._lock:
            h = self._find_handle(info_hash)
            ih = info_hash.lower()
            if not h:
                return False
            self._pending_removals.add(ih)
            opts = lt.session.delete_files if delete_files else 0
            meta = self._meta.pop(ih, {})
            self._save_meta()
            self.ses.remove_torrent(h, opts)

            for suffix in (".torrent", ".fastresume"):
                p = self.state_dir / f"{ih}{suffix}"
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass

            staged = meta.get("staged_path")
            if delete_files and staged and Path(staged).exists():
                shutil.rmtree(staged, ignore_errors=True)
            return True

    def _cleanup_empty_dir(self, path_str: str) -> None:
        if not path_str:
            return
        p = Path(path_str)
        try:
            if p.exists() and p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass

    def _handle_metadata_received(self, handle: lt.torrent_handle) -> None:
        if not handle.is_valid():
            return
        st = handle.status()
        ih = get_info_hash(st)
        ti = handle.torrent_file()
        if not ti or not ti.is_valid():
            return

        meta = self._meta.setdefault(ih, {})
        is_priv = bool(ti.priv())
        meta["is_private"] = is_priv

        if is_priv and meta.get("injected_tracker_urls"):
            injected_set = set(meta.get("injected_tracker_urls") or [])
            kept = [tr for tr in handle.trackers() if tr["url"] not in injected_set]
            handle.replace_trackers(kept)
            meta["injected_tracker_urls"] = []
            meta["boosted_trackers"] = False

        try:
            ct = lt.create_torrent(ti)
            entry = ct.generate()
            (self.state_dir / f"{ih}.torrent").write_bytes(lt.bencode(entry))
        except Exception as exc:
            logger.debug("Nao foi possivel gerar .torrent de metadados %s: %s", ih, exc)

        if meta.get("prioritize_ends"):
            self._apply_prioritize_ends(handle)

        if meta.get("staging_active"):
            final_dir = meta.get("final_save_path") or self.cfg.default_save_path
            use_stg, reason = should_use_staging(final_dir, ti.total_size(), self.cfg, self.get_hardware())
            meta["staging_note"] = reason
            if not use_stg:
                Path(final_dir).mkdir(parents=True, exist_ok=True)
                handle.move_storage(final_dir, lt.move_flags_t.always_replace_files)
                meta["staging_active"] = False

        self._save_meta()
        handle.save_resume_data()

    def _handle_torrent_finished(self, handle: lt.torrent_handle) -> None:
        if not handle.is_valid():
            return
        st = handle.status()
        ih = get_info_hash(st)
        meta = self._meta.setdefault(ih, {})
        if meta.get("staging_active"):
            final_dir = meta.get("final_save_path") or self.cfg.default_save_path
            Path(final_dir).mkdir(parents=True, exist_ok=True)
            handle.move_storage(final_dir, lt.move_flags_t.always_replace_files)
            return
        meta["completed"] = True
        self._save_meta()
        if ih not in self._notified_finished:
            self._notified_finished.add(ih)
            if self.on_torrent_finished:
                self.on_torrent_finished(self._serialize_torrent(st))
        handle.save_resume_data()

    def _handle_storage_moved(self, handle: lt.torrent_handle) -> None:
        if not handle.is_valid():
            return
        st = handle.status()
        ih = get_info_hash(st)
        meta = self._meta.setdefault(ih, {})
        old_staged = meta.get("staged_path", "")
        meta["staging_active"] = False
        meta["staged_path"] = ""
        meta["staging_note"] = "Movido do NVMe para o destino final."
        if st.is_finished:
            meta["completed"] = True
        self._save_meta()
        self._cleanup_empty_dir(old_staged)
        handle.save_resume_data()
        if st.is_finished and ih not in self._notified_finished:
            self._notified_finished.add(ih)
            if self.on_torrent_finished:
                self.on_torrent_finished(self._serialize_torrent(st))

    def _process_alerts(self) -> None:
        alerts = self.ses.pop_alerts()
        for alert in alerts:
            if isinstance(alert, lt.session_stats_alert):
                vals = alert.values
                for key, metric_name in (
                    ("queued_write_bytes", "disk.queued_write_bytes"),
                    ("recv_payload_bytes", "net.recv_payload_bytes"),
                    ("recv_ip_overhead_bytes", "net.recv_ip_overhead_bytes"),
                    ("dht_nodes", "dht.dht_nodes"),
                    ("num_peers_connected", "peer.num_peers_connected"),
                    ("num_peers_half_open", "peer.num_peers_half_open"),
                ):
                    if isinstance(vals, dict):
                        if metric_name in vals:
                            self._session_counters[key] = int(vals[metric_name])
                    else:
                        idx = self._metric_idx.get(metric_name)
                        if idx is not None and 0 <= idx < len(vals):
                            self._session_counters[key] = int(vals[idx])
                cur_p = self._session_counters["recv_payload_bytes"]
                cur_o = self._session_counters["recv_ip_overhead_bytes"]
                dp = max(0, cur_p - self._prev_payload_bytes)
                do = max(0, cur_o - self._prev_overhead_bytes)
                if dp + do > 0:
                    self._payload_efficiency = round((dp / (dp + do)) * 100.0, 2)
                self._prev_payload_bytes = cur_p
                self._prev_overhead_bytes = cur_o

            elif isinstance(alert, lt.metadata_received_alert):
                self._handle_metadata_received(alert.handle)

            elif isinstance(alert, lt.torrent_finished_alert):
                self._handle_torrent_finished(alert.handle)

            elif isinstance(alert, lt.storage_moved_alert):
                self._handle_storage_moved(alert.handle)

            elif isinstance(alert, lt.save_resume_data_alert):
                h = alert.handle
                if h.is_valid():
                    ih = get_info_hash(h.status())
                    if ih and ih not in self._pending_removals:
                        try:
                            buf = lt.write_resume_data_buf(alert.params)
                            (self.state_dir / f"{ih}.fastresume").write_bytes(buf)
                        except Exception as exc:
                            logger.debug("Erro ao salvar fastresume %s: %s", ih, exc)

    def _run_anti_stall(self, now: float) -> None:
        if not self.cfg.anti_stall_enabled:
            return
        if now - self._last_anti_stall_run < 2.5:
            return
        self._last_anti_stall_run = now

        for h in self.ses.get_torrents():
            if not h.is_valid():
                continue
            st = h.status()
            if st.paused or st.is_finished or st.is_seeding:
                continue
            ih = get_info_hash(st)
            meta = self._meta.setdefault(ih, {})
            peak = max(int(meta.get("peak_download_rate") or 0), int(st.download_payload_rate))
            meta["peak_download_rate"] = peak

            added_at = float(meta.get("added_at") or now)
            age = now - added_at
            last_boost = float(meta.get("last_initial_boost_ts") or 0.0)
            if 2.5 <= age <= 25.0 and st.num_peers < 40:
                if last_boost == 0.0 or (now - last_boost) >= 6.0:
                    meta["last_initial_boost_ts"] = now
                    h.force_reannounce()
                    h.force_dht_announce()

            if (
                st.progress >= 0.92
                and peak > 500 * 1024
                and st.download_payload_rate < peak * 0.2
                and (now - float(meta.get("last_anti_stall_ts") or 0.0)) >= 9.0
            ):
                meta["last_anti_stall_ts"] = now
                h.force_reannounce()
                h.force_dht_announce()
                try:
                    queue = h.get_download_queue()
                    for item in queue[:12]:
                        p_idx = int(item.get("piece_index", -1))
                        if p_idx >= 0:
                            h.set_piece_deadline(p_idx, 1500)
                except Exception:
                    pass

    def tick(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            self._inject_pending_dht_nodes(now)
            self.ses.post_session_stats()
            self._process_alerts()
            self._run_anti_stall(now)

            if now - self._last_resume_save >= 30.0:
                self._last_resume_save = now
                for h in self.ses.get_torrents():
                    if h.is_valid() and h.need_save_resume_data():
                        h.save_resume_data()
                self._save_meta()

            if now - self._last_session_state_save >= 60.0:
                self._last_session_state_save = now
                self._save_dht_nodes()

            if now - self._last_hw_refresh >= 15.0:
                self._last_hw_refresh = now
                self.hw = refresh_drive_usage(self.hw)

            snapshot = self.get_state_snapshot(record_history=True)
            return snapshot

    def _compute_bottleneck(self, torrents: list[dict[str, Any]], total_dl: int) -> dict[str, str]:
        active_dl = [t for t in torrents if t["state"] == "Baixando" and not t["paused"]]
        if not active_dl:
            return {
                "code": "idle",
                "label": "Ocioso",
                "detail": "Nenhum download ativo no momento.",
            }

        link_bytes_sec = max(125_000, int(self.hw.primary_link_mbps) * 125_000)
        if total_dl >= int(link_bytes_sec * 0.85):
            return {
                "code": "saturating_link",
                "label": "Saturando link",
                "detail": "Download próximo da capacidade máxima da placa de rede.",
            }

        queued_bytes = self._session_counters.get("queued_write_bytes", 0)
        if queued_bytes > 256 * 1024 * 1024:
            queued_mb = round(queued_bytes / (1024 * 1024))
            return {
                "code": "disk_queue",
                "label": "Fila de disco alta",
                "detail": f"{queued_mb} MB em fila de gravação. Use SSD/NVMe ou Turbo Staging.",
            }

        has_incoming = any(t.get("has_incoming") for t in active_dl)
        total_peers = sum(t["num_peers"] for t in active_dl)
        total_seeds = sum(t["num_seeds"] for t in active_dl)
        oldest_age = max((time.time() - float(t.get("added_at") or time.time())) for t in active_dl)

        if not has_incoming and oldest_age > 30.0 and total_peers < 10:
            return {
                "code": "nat_restricted",
                "label": "NAT restrito",
                "detail": "Sem conexões de entrada até agora. Verifique UPnP ou porta aberta.",
            }

        if total_seeds < 3 and total_peers < 15:
            return {
                "code": "swarm_limited",
                "label": "Limitado pelo swarm",
                "detail": "Poucos seeds ou peers ativos disponíveis nos torrents em curso.",
            }

        return {
            "code": "optimal",
            "label": "Fluxo otimizado",
            "detail": "Motor operando sem gargalos locais detectados.",
        }

    def _serialize_torrent(self, st: lt.torrent_status) -> dict[str, Any]:
        ih = get_info_hash(st)
        meta = self._meta.get(ih, {})
        dl_rate = int(st.download_payload_rate)
        peak = max(int(meta.get("peak_download_rate") or 0), dl_rate)
        if ih in self._meta and peak > int(self._meta[ih].get("peak_download_rate") or 0):
            self._meta[ih]["peak_download_rate"] = peak

        remaining = max(0, int(st.total_wanted) - int(st.total_wanted_done))
        eta = int(remaining / dl_rate) if dl_rate > 0 and remaining > 0 else -1

        state_label = _STATE_LABELS.get(st.state, "Em fila")
        if st.paused:
            state_label = "Pausado"
        elif st.moving_storage:
            state_label = "Movendo para destino"
        elif st.errc and st.errc.value() != 0:
            state_label = "Erro"

        final_save = meta.get("final_save_path") or st.save_path
        dst_drive = classify_path_drive(final_save, self.hw)

        total_up = int(st.all_time_upload)
        total_dl = max(1, int(st.all_time_download))
        ratio = round(total_up / total_dl, 2) if st.all_time_download > 0 else 0.0

        return {
            "info_hash": ih,
            "name": st.name or ih,
            "state": state_label,
            "raw_state": str(st.state),
            "paused": bool(st.paused),
            "progress": round(float(st.progress) * 100.0, 2),
            "total_size": int(st.total_wanted),
            "downloaded": int(st.total_wanted_done),
            "uploaded": int(st.all_time_upload),
            "download_rate": dl_rate,
            "upload_rate": int(st.upload_payload_rate),
            "peak_download_rate": peak,
            "eta": eta,
            "num_peers": int(st.num_peers),
            "num_seeds": int(st.num_seeds),
            "list_peers": int(st.list_peers),
            "list_seeds": int(st.list_seeds),
            "ratio": ratio,
            "sequential": bool(st.sequential_download),
            "prioritize_ends": bool(meta.get("prioritize_ends", False)),
            "staging_active": bool(meta.get("staging_active", False)),
            "moving_storage": bool(st.moving_storage),
            "staging_note": meta.get("staging_note", ""),
            "save_path": st.save_path,
            "final_save_path": final_save,
            "dest_media_type": dst_drive.media_type if dst_drive else "Unknown",
            "boosted_trackers": bool(meta.get("boosted_trackers", False)),
            "is_private": bool(meta.get("is_private", False)),
            "has_metadata": bool(st.has_metadata),
            "has_incoming": bool(st.has_incoming),
            "is_finished": bool(st.is_finished),
            "is_seeding": bool(st.is_seeding),
            "error": st.error if st.errc and st.errc.value() != 0 else "",
            "added_at": float(meta.get("added_at") or st.added_time or time.time()),
            "download_limit_kbps": int(st.download_limit // 1024) if st.download_limit > 0 else 0,
            "upload_limit_kbps": int(st.upload_limit // 1024) if st.upload_limit > 0 else 0,
        }

    def get_state_snapshot(self, record_history: bool = False) -> dict[str, Any]:
        with self._lock:
            torrents: list[dict[str, Any]] = []
            total_dl = 0
            total_ul = 0
            for h in self.ses.get_torrents():
                if not h.is_valid():
                    continue
                st = h.status()
                item = self._serialize_torrent(st)
                torrents.append(item)
                total_dl += item["download_rate"]
                total_ul += item["upload_rate"]

            torrents.sort(key=lambda t: t["added_at"], reverse=True)

            if record_history:
                self._speed_history.append(
                    {
                        "t": int(time.time() * 1000),
                        "dl": total_dl,
                        "ul": total_ul,
                    }
                )

            bottleneck = self._compute_bottleneck(torrents, total_dl)
            cur_settings = self.ses.get_settings()
            return {
                "torrents": torrents,
                "global": {
                    "download_rate": total_dl,
                    "upload_rate": total_ul,
                    "dht_nodes": self._session_counters.get("dht_nodes", 0),
                    "dht_state_loaded": self._dht_state_loaded,
                    "listen_interfaces": str(cur_settings.get("listen_interfaces", "")),
                    "max_queued_disk_mb": round(
                        int(cur_settings.get("max_queued_disk_bytes", 0)) / (1024 * 1024)
                    ),
                    "peers_connected": self._session_counters.get("num_peers_connected", 0),
                    "peers_half_open": self._session_counters.get("num_peers_half_open", 0),
                    "queued_write_bytes": self._session_counters.get("queued_write_bytes", 0),
                    "payload_efficiency": self._payload_efficiency,
                    "primary_link_mbps": self.hw.primary_link_mbps,
                    "profile": self.cfg.profile,
                    "bottleneck": bottleneck,
                },
                "history": list(self._speed_history),
            }

    def get_torrent_details(self, info_hash: str) -> dict[str, Any] | None:
        with self._lock:
            h = self._find_handle(info_hash)
            if not h:
                return None
            st = h.status()
            ti = h.torrent_file()

            files: list[dict[str, Any]] = []
            if ti and ti.is_valid():
                fs = ti.layout() if hasattr(ti, "layout") else ti.files()
                prios = h.get_file_priorities()
                progress_bytes = h.file_progress()
                for idx in range(fs.num_files()):
                    fsize = int(fs.file_size(idx))
                    fdone = int(progress_bytes[idx]) if idx < len(progress_bytes) else 0
                    fpct = round((fdone / fsize) * 100.0, 2) if fsize > 0 else 100.0
                    files.append(
                        {
                            "index": idx,
                            "path": fs.file_path(idx),
                            "size": fsize,
                            "done": fdone,
                            "progress": fpct,
                            "priority": int(prios[idx]) if idx < len(prios) else 4,
                        }
                    )

            peers: list[dict[str, Any]] = []
            for p in h.get_peer_info():
                ip_tuple = p.ip
                endpoint = f"{ip_tuple[0]}:{ip_tuple[1]}" if isinstance(ip_tuple, tuple) else str(ip_tuple)
                is_utp = bool(getattr(p, "flags", 0) & 0x20000) or "utp" in str(p.connection_type).lower()
                flags_list = []
                if p.flags & lt.peer_info.interesting:
                    flags_list.append("I")
                if p.flags & lt.peer_info.choked:
                    flags_list.append("C")
                if p.flags & lt.peer_info.snubbed:
                    flags_list.append("S")
                if p.flags & lt.peer_info.seed:
                    flags_list.append("Seed")
                if getattr(p, "endgame_mode", False):
                    flags_list.append("Endgame")
                peers.append(
                    {
                        "endpoint": endpoint,
                        "client": p.client or "Desconhecido",
                        "proto": "uTP" if is_utp else "TCP",
                        "down_speed": int(p.payload_down_speed),
                        "up_speed": int(p.payload_up_speed),
                        "progress": round(float(p.progress) * 100.0, 1),
                        "flags": " ".join(flags_list) or "Ativo",
                        "rtt": int(getattr(p, "rtt", 0)),
                    }
                )
            peers.sort(key=lambda x: x["down_speed"], reverse=True)

            trackers: list[dict[str, Any]] = []
            for tr in h.trackers():
                endpoints = tr.get("endpoints") or []
                status_txt = "Aguardando"
                seeds = -1
                leeches = -1
                for ep in endpoints:
                    msg = ep.get("message") or ""
                    last_err = ep.get("last_error") or {}
                    if ep.get("scrape_complete", -1) >= 0:
                        seeds = ep["scrape_complete"]
                    if ep.get("scrape_incomplete", -1) >= 0:
                        leeches = ep["scrape_incomplete"]
                    if last_err and last_err.get("value", 0) != 0:
                        status_txt = msg or f"Erro ({last_err.get('value')})"
                    elif tr.get("verified"):
                        status_txt = "Ativo"
                trackers.append(
                    {
                        "url": tr.get("url", ""),
                        "tier": int(tr.get("tier", 0)),
                        "status": status_txt,
                        "seeds": seeds,
                        "leeches": leeches,
                    }
                )

            piece_buckets: list[int] = []
            pieces_bool = list(st.pieces) if st.pieces else []
            downloading_pieces = {
                int(q.get("piece_index", -1)) for q in h.get_download_queue()
            }
            num_pieces = len(pieces_bool)
            if num_pieces > 0:
                bucket_count = min(400, num_pieces)
                for b in range(bucket_count):
                    start = int(b * num_pieces / bucket_count)
                    end = max(start + 1, int((b + 1) * num_pieces / bucket_count))
                    slice_p = pieces_bool[start:end]
                    if all(slice_p):
                        piece_buckets.append(2)  # concluído
                    elif any(idx in downloading_pieces for idx in range(start, end)) or any(slice_p):
                        piece_buckets.append(1)  # baixando / parcial
                    else:
                        piece_buckets.append(0)  # pendente

            summary = self._serialize_torrent(st)
            return {
                "summary": summary,
                "files": files,
                "peers": peers[:150],
                "trackers": trackers,
                "piece_map": piece_buckets,
                "num_pieces": num_pieces,
                "piece_length": ti.piece_length() if ti and ti.is_valid() else 0,
            }

    def shutdown(self) -> None:
        with self._lock:
            self.ses.pause()
            self._process_alerts()
            pending = 0
            for h in self.ses.get_torrents():
                if h.is_valid() and h.status().has_metadata:
                    h.save_resume_data()
                    pending += 1

            deadline = time.time() + 5.0
            while pending > 0 and time.time() < deadline:
                alerts = self.ses.pop_alerts()
                for alert in alerts:
                    if isinstance(alert, lt.save_resume_data_alert):
                        h = alert.handle
                        if h.is_valid():
                            ih = get_info_hash(h.status())
                            if ih and ih not in self._pending_removals:
                                try:
                                    buf = lt.write_resume_data_buf(alert.params)
                                    (self.state_dir / f"{ih}.fastresume").write_bytes(buf)
                                except Exception:
                                    pass
                        pending -= 1
                    elif isinstance(alert, lt.save_resume_data_failed_alert):
                        pending -= 1
                if pending > 0:
                    time.sleep(0.05)

            self._save_meta()
            self._save_dht_nodes()
