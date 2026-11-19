from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import libtorrent as lt

ROOT_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = ROOT_DIR / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from config import AppConfig  # noqa: E402
from engine import VortexEngine, get_info_hash  # noqa: E402


UBUNTU_TORRENT_URL = (
    "https://releases.ubuntu.com/24.04/ubuntu-24.04.4-desktop-amd64.iso.torrent"
)
C_TMP = Path(r"C:\_vortex_bench_tmp")
D_TMP = Path(r"D:\_vortex_bench_tmp")


def _fmt_mbps(bytes_per_sec: float) -> str:
    mb_s = bytes_per_sec / (1024 * 1024)
    mbps = (bytes_per_sec * 8) / 1_000_000
    return f"{mb_s:.2f} MB/s ({mbps:.1f} Mbps)"


def _apply_safe_settings(ses: lt.session, pack: dict[str, Any]) -> None:
    valid = set(ses.get_settings().keys())
    ses.apply_settings({k: v for k, v in pack.items() if k in valid})


def _generate_payload(target: Path, size_mb: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    chunk_size = 8 * 1024 * 1024
    total_bytes = size_mb * 1024 * 1024
    written = 0
    with target.open("wb") as fp:
        while written < total_bytes:
            to_write = min(chunk_size, total_bytes - written)
            fp.write(os.urandom(to_write))
            written += to_write


def _build_torrent(payload_file: Path) -> tuple[bytes, str, lt.torrent_info]:
    fs = lt.file_storage()
    lt.add_files(fs, str(payload_file))
    ct = lt.create_torrent(fs, piece_size=512 * 1024)
    ct.set_creator("VortexBenchmark")
    lt.set_piece_hashes(ct, str(payload_file.parent))
    raw = lt.bencode(ct.generate())
    ti = lt.torrent_info(lt.bdecode(raw))
    ih = str(ti.info_hashes().get_best()).lower()
    return raw, ih, ti


def _start_local_seeders(
    ti: lt.torrent_info,
    seed_dir: Path,
    ports: list[int],
) -> list[tuple[lt.session, lt.torrent_handle, int]]:
    seeders: list[tuple[lt.session, lt.torrent_handle, int]] = []
    for port in ports:
        ses = lt.session()
        cfg = dict(lt.high_performance_seed())
        cfg.update(
            {
                "listen_interfaces": f"127.0.0.1:{port}",
                "enable_dht": False,
                "enable_lsd": False,
                "enable_upnp": False,
                "enable_natpmp": False,
                "allow_multiple_connections_per_ip": True,
                "send_buffer_low_watermark": 4 * 1024 * 1024,
                "send_buffer_watermark": 16 * 1024 * 1024,
                "send_buffer_watermark_factor": 200,
                "max_allowed_in_request_queue": 4000,
                "aio_threads": 16,
            }
        )
        _apply_safe_settings(ses, cfg)
        atp = lt.add_torrent_params()
        atp.ti = ti
        atp.save_path = str(seed_dir)
        atp.flags |= lt.torrent_flags.seed_mode
        handle = ses.add_torrent(atp)
        seeders.append((ses, handle, port))
    return seeders


def _stop_seeders(seeders: list[tuple[lt.session, lt.torrent_handle, int]]) -> None:
    for ses, _h, _p in seeders:
        try:
            ses.pause()
        except Exception:
            pass


def _connect_all_seeders(
    client_handle: lt.torrent_handle,
    client_port: int,
    seeders: list[tuple[lt.session, lt.torrent_handle, int]],
) -> None:
    for _ses, sh, sp in seeders:
        try:
            client_handle.connect_peer(("127.0.0.1", sp))
            sh.connect_peer(("127.0.0.1", client_port))
        except Exception:
            pass


def _run_local_baseline(
    ti: lt.torrent_info,
    save_dir: Path,
    client_port: int,
    seeders: list[tuple[lt.session, lt.torrent_handle, int]],
    total_bytes: int,
) -> dict[str, Any]:
    save_dir.mkdir(parents=True, exist_ok=True)
    ses = lt.session()
    cfg = dict(lt.default_settings())
    cfg.update(
        {
            "connection_speed": 30,
            "connections_limit": 200,
            "max_out_request_queue": 500,
            "hashing_threads": 1,
            "aio_threads": 4,
            "mixed_mode_algorithm": int(lt.bandwidth_mixed_algo_t.peer_proportional),
            "allow_multiple_connections_per_ip": True,
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "listen_interfaces": f"127.0.0.1:{client_port}",
            "alert_mask": int(lt.alert_category.stats | lt.alert_category.status | lt.alert_category.error),
        }
    )
    _apply_safe_settings(ses, cfg)

    atp = lt.add_torrent_params()
    atp.ti = ti
    atp.save_path = str(save_dir)
    atp.storage_mode = lt.storage_mode_t.storage_mode_sparse
    t0 = time.perf_counter()
    handle = ses.add_torrent(atp)
    _connect_all_seeders(handle, client_port, seeders)

    peak_rate = 0
    max_queued_bytes = 0
    last_reconnect = 0.0
    finished = False

    deadline = time.time() + 85.0
    try:
        while time.time() < deadline:
            ses.post_session_stats()
            for alert in ses.pop_alerts():
                if isinstance(alert, lt.session_stats_alert):
                    vals = alert.values
                    if isinstance(vals, dict):
                        q = int(vals.get("disk.queued_write_bytes", 0))
                        max_queued_bytes = max(max_queued_bytes, q)
            st = handle.status()
            peak_rate = max(peak_rate, int(st.download_payload_rate))
            if st.is_finished:
                finished = True
                break
            now = time.time()
            if st.num_peers < len(seeders) and now - last_reconnect > 1.0:
                last_reconnect = now
                _connect_all_seeders(handle, client_port, seeders)
            time.sleep(0.1)
    finally:
        ses.pause()

    elapsed = max(0.001, time.perf_counter() - t0)
    avg_bps = total_bytes / elapsed if finished else 0.0
    return {
        "name": "Baseline Padrao (NVMe)",
        "finished": finished,
        "elapsed_s": round(elapsed, 2),
        "avg_bps": avg_bps,
        "peak_bps": float(peak_rate),
        "max_disk_queue_mb": round(max_queued_bytes / (1024 * 1024), 1),
    }


def _run_local_vortex(
    raw_torrent: bytes,
    ih: str,
    save_dir: Path,
    staging_dir: Path | None,
    use_staging: bool,
    client_port: int,
    seeders: list[tuple[lt.session, lt.torrent_handle, int]],
    total_bytes: int,
    data_dir: Path,
    label: str,
) -> dict[str, Any]:
    os.environ["VORTEX_DATA_DIR"] = str(data_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    if staging_dir:
        staging_dir.mkdir(parents=True, exist_ok=True)

    engine = VortexEngine()
    engine.apply_config(
        AppConfig(
            profile="turbo_max",
            default_save_path=str(save_dir),
            staging_path=str(staging_dir) if staging_dir else "",
            nvme_staging_enabled=use_staging,
            listen_port=client_port,
            enable_dht=False,
            enable_lsd=False,
            enable_upnp=False,
            auto_boost_public_trackers=False,
        )
    )

    t0 = time.perf_counter()
    t_network_done: float | None = None
    peak_rate = 0
    max_queued_bytes = 0
    last_reconnect = 0.0
    finished_all = False

    try:
        engine.add_torrent_bytes(
            raw_torrent,
            save_path=str(save_dir),
            use_staging=use_staging,
            boost_trackers=False,
        )
        handle = engine._find_handle(ih)
        assert handle is not None
        _connect_all_seeders(handle, client_port, seeders)

        deadline = time.time() + 85.0
        while time.time() < deadline:
            snap = engine.tick()
            g = snap["global"]
            max_queued_bytes = max(max_queued_bytes, int(g.get("queued_write_bytes", 0)))
            items = [t for t in snap["torrents"] if t["info_hash"] == ih]
            if items:
                item = items[0]
                peak_rate = max(peak_rate, int(item["download_rate"]))
                if item["is_finished"] and t_network_done is None:
                    t_network_done = time.perf_counter()
                if item["is_finished"] and not item["staging_active"] and not item["moving_storage"]:
                    finished_all = True
                    break
                now = time.time()
                if not item["is_finished"] and item["num_peers"] < len(seeders) and now - last_reconnect > 1.0:
                    last_reconnect = now
                    _connect_all_seeders(handle, client_port, seeders)
            time.sleep(0.1)
    finally:
        engine.shutdown()

    t_end = time.perf_counter()
    total_elapsed = max(0.001, t_end - t0)
    net_elapsed = max(0.001, (t_network_done - t0) if t_network_done else total_elapsed)
    move_elapsed = max(0.0, total_elapsed - net_elapsed) if use_staging and t_network_done else 0.0

    return {
        "name": label,
        "finished": finished_all,
        "elapsed_s": round(total_elapsed, 2),
        "net_elapsed_s": round(net_elapsed, 2),
        "move_elapsed_s": round(move_elapsed, 2),
        "avg_bps": (total_bytes / total_elapsed) if finished_all else 0.0,
        "net_bps": (total_bytes / net_elapsed) if t_network_done else 0.0,
        "move_bps": (total_bytes / move_elapsed) if move_elapsed > 0 else 0.0,
        "peak_bps": float(peak_rate),
        "max_disk_queue_mb": round(max_queued_bytes / (1024 * 1024), 1),
    }


def _run_hash_recheck(
    ti: lt.torrent_info,
    seed_dir: Path,
    total_bytes: int,
    hashing_threads: int,
    checking_mem_usage: int,
    aio_threads: int,
    label: str,
) -> dict[str, Any]:
    ses = lt.session()
    cfg = dict(lt.default_settings())
    cfg.update(
        {
            "hashing_threads": hashing_threads,
            "checking_mem_usage": checking_mem_usage,
            "aio_threads": aio_threads,
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "listen_interfaces": "127.0.0.1:0",
        }
    )
    _apply_safe_settings(ses, cfg)

    atp = lt.add_torrent_params()
    atp.ti = ti
    atp.save_path = str(seed_dir)
    atp.flags |= lt.torrent_flags.paused

    t0 = time.perf_counter()
    h = ses.add_torrent(atp)
    h.force_recheck()

    done = False
    deadline = time.time() + 60.0
    try:
        while time.time() < deadline:
            st = h.status()
            if st.state not in (
                lt.torrent_status.states.checking_files,
                lt.torrent_status.states.checking_resume_data,
            ) and st.progress >= 0.999:
                done = True
                break
            time.sleep(0.02)
    finally:
        ses.pause()

    elapsed = max(0.001, time.perf_counter() - t0)
    mb_s = (total_bytes / (1024 * 1024)) / elapsed if done else 0.0
    proj_100gb_s = round((100 * 1024) / mb_s, 1) if mb_s > 0 else 0.0
    return {
        "name": label,
        "done": done,
        "elapsed_s": round(elapsed, 3),
        "mb_per_sec": round(mb_s, 1),
        "proj_100gb_s": proj_100gb_s,
    }


def _run_live_baseline(raw_torrent: bytes, save_dir: Path, duration_s: int) -> dict[str, Any]:
    save_dir.mkdir(parents=True, exist_ok=True)
    ti = lt.torrent_info(lt.bdecode(raw_torrent))
    ses = lt.session()
    cfg = dict(lt.default_settings())
    cfg.update(
        {
            "connection_speed": 30,
            "connections_limit": 200,
            "max_out_request_queue": 500,
            "announce_to_all_trackers": False,
            "announce_to_all_tiers": False,
            "mixed_mode_algorithm": int(lt.bandwidth_mixed_algo_t.peer_proportional),
            "hashing_threads": 1,
            "listen_interfaces": "0.0.0.0:55201,[::]:55201",
            "alert_mask": int(lt.alert_category.stats | lt.alert_category.status | lt.alert_category.error),
        }
    )
    _apply_safe_settings(ses, cfg)

    atp = lt.add_torrent_params()
    atp.ti = ti
    atp.save_path = str(save_dir)
    atp.storage_mode = lt.storage_mode_t.storage_mode_sparse
    h = ses.add_torrent(atp)

    t0 = time.perf_counter()
    first_1mbs_s: float | None = None
    peers_at = {5: 0, 15: 0, duration_s: 0}
    peak_peers = 0
    peak_rate = 0
    samples: list[tuple[float, int]] = []
    payload_bytes = 0
    overhead_bytes = 0
    downloaded_bytes = 0

    try:
        while True:
            elapsed = time.perf_counter() - t0
            if elapsed >= duration_s:
                break
            ses.post_session_stats()
            for alert in ses.pop_alerts():
                if isinstance(alert, lt.session_stats_alert) and isinstance(alert.values, dict):
                    payload_bytes = int(alert.values.get("net.recv_payload_bytes", payload_bytes))
                    overhead_bytes = int(alert.values.get("net.recv_ip_overhead_bytes", overhead_bytes))

            st = h.status()
            rate = int(st.download_payload_rate)
            peers = int(st.num_peers)
            downloaded_bytes = int(st.total_wanted_done)
            peak_rate = max(peak_rate, rate)
            peak_peers = max(peak_peers, peers)
            samples.append((elapsed, rate))

            if first_1mbs_s is None and rate >= 1024 * 1024:
                first_1mbs_s = round(elapsed, 2)
            for mark in (5, 15, duration_s):
                if elapsed >= mark and peers_at[mark] == 0:
                    peers_at[mark] = peers

            time.sleep(0.25)
    finally:
        ses.pause()

    peers_at[duration_s] = peers_at[duration_s] or (samples and peak_peers) or 0
    avg_bps = sum(r for _, r in samples) / max(1, len(samples))
    tail_samples = [r for t, r in samples if t >= max(0.0, duration_s - 15.0)]
    tail_bps = sum(tail_samples) / max(1, len(tail_samples))
    eff = (payload_bytes / (payload_bytes + overhead_bytes) * 100.0) if (payload_bytes + overhead_bytes) > 0 else 100.0

    return {
        "name": "Baseline Padrao (Swarm Real)",
        "first_1mbs_s": first_1mbs_s,
        "peers_5s": peers_at[5],
        "peers_15s": peers_at[15],
        "peers_end": peers_at[duration_s],
        "peak_peers": peak_peers,
        "downloaded_mb": round(downloaded_bytes / (1024 * 1024), 1),
        "avg_bps": avg_bps,
        "tail_bps": tail_bps,
        "peak_bps": float(peak_rate),
        "efficiency_pct": round(eff, 2),
    }


def _run_live_vortex(
    raw_torrent: bytes,
    save_dir: Path,
    duration_s: int,
    data_dir: Path,
) -> dict[str, Any]:
    os.environ["VORTEX_DATA_DIR"] = str(data_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    engine = VortexEngine()
    engine.apply_config(
        AppConfig(
            profile="turbo_max",
            default_save_path=str(save_dir),
            nvme_staging_enabled=False,
            listen_port=55202,
            prefer_tcp=True,
            auto_boost_public_trackers=True,
        )
    )

    t0 = time.perf_counter()
    first_1mbs_s: float | None = None
    peers_at = {5: 0, 15: 0, duration_s: 0}
    peak_peers = 0
    peak_rate = 0
    samples: list[tuple[float, int]] = []
    downloaded_bytes = 0
    eff = 100.0

    try:
        added = engine.add_torrent_bytes(
            raw_torrent,
            save_path=str(save_dir),
            use_staging=False,
            boost_trackers=True,
        )
        ih = added["info_hash"]
        while True:
            elapsed = time.perf_counter() - t0
            if elapsed >= duration_s:
                break
            snap = engine.tick()
            eff = float(snap["global"].get("payload_efficiency", eff))
            items = [t for t in snap["torrents"] if t["info_hash"] == ih]
            if items:
                item = items[0]
                rate = int(item["download_rate"])
                peers = int(item["num_peers"])
                downloaded_bytes = int(item["downloaded"])
                peak_rate = max(peak_rate, rate)
                peak_peers = max(peak_peers, peers)
                samples.append((elapsed, rate))

                if first_1mbs_s is None and rate >= 1024 * 1024:
                    first_1mbs_s = round(elapsed, 2)
                for mark in (5, 15, duration_s):
                    if elapsed >= mark and peers_at[mark] == 0:
                        peers_at[mark] = peers

            time.sleep(0.25)
    finally:
        engine.shutdown()

    peers_at[duration_s] = peers_at[duration_s] or peak_peers
    avg_bps = sum(r for _, r in samples) / max(1, len(samples))
    tail_samples = [r for t, r in samples if t >= max(0.0, duration_s - 15.0)]
    tail_bps = sum(tail_samples) / max(1, len(tail_samples))

    return {
        "name": "VortexTorrent (Turbo Max + Boost)",
        "first_1mbs_s": first_1mbs_s,
        "peers_5s": peers_at[5],
        "peers_15s": peers_at[15],
        "peers_end": peers_at[duration_s],
        "peak_peers": peak_peers,
        "downloaded_mb": round(downloaded_bytes / (1024 * 1024), 1),
        "avg_bps": avg_bps,
        "tail_bps": tail_bps,
        "peak_bps": float(peak_rate),
        "efficiency_pct": round(eff, 2),
    }


def _cleanup_temp_dirs() -> None:
    for root in (C_TMP, D_TMP):
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark comparativo VortexTorrent")
    parser.add_argument(
        "--scenarios",
        default="all",
        choices=["all", "local", "disk", "hash", "live"],
    )
    parser.add_argument("--size-mb", type=int, default=512)
    parser.add_argument("--live-seconds", type=int, default=25)
    args = parser.parse_args()

    selected = {"local", "disk", "hash", "live"} if args.scenarios == "all" else {args.scenarios}
    results: dict[str, Any] = {}

    _cleanup_temp_dirs()
    try:
        need_local_payload = bool(selected & {"local", "disk", "hash"})
        seed_dir = C_TMP / "seed_src"
        payload_file = seed_dir / "bench_payload.bin"
        total_bytes = args.size_mb * 1024 * 1024
        raw_torrent = b""
        ih = ""
        ti = None

        if need_local_payload:
            print(f"[Preparando] Gerando payload de {args.size_mb} MB em {seed_dir}...")
            _generate_payload(payload_file, args.size_mb)
            raw_torrent, ih, ti = _build_torrent(payload_file)

        if selected & {"local", "disk"}:
            assert ti is not None
            seeders = _start_local_seeders(ti, seed_dir, [55101, 55102, 55103, 55104])
            try:
                if "local" in selected:
                    print("\n=== Cenario 1: Motor e Protocolo Local (4 seeders em NVMe C:) ===")
                    r1a = _run_local_baseline(
                        ti, C_TMP / "local_baseline", 55110, seeders, total_bytes
                    )
                    print(
                        f"  1A {r1a['name']}: {r1a['elapsed_s']}s | Media {_fmt_mbps(r1a['avg_bps'])} | Pico {_fmt_mbps(r1a['peak_bps'])} | Fila disco max: {r1a['max_disk_queue_mb']} MB"
                    )
                    r1b = _run_local_vortex(
                        raw_torrent,
                        ih,
                        C_TMP / "local_vortex",
                        None,
                        False,
                        55111,
                        seeders,
                        total_bytes,
                        C_TMP / "appdata_1b",
                        "VortexTorrent Turbo Max (NVMe)",
                    )
                    print(
                        f"  1B {r1b['name']}: {r1b['elapsed_s']}s | Media {_fmt_mbps(r1b['avg_bps'])} | Pico {_fmt_mbps(r1b['peak_bps'])} | Fila disco max: {r1b['max_disk_queue_mb']} MB"
                    )
                    results["local"] = {"baseline": r1a, "vortex": r1b}

                if "disk" in selected:
                    print("\n=== Cenario 2: Gargalo de Disco Real (HDD D: vs Turbo Staging NVMe C: -> D:) ===")
                    r2a = _run_local_vortex(
                        raw_torrent,
                        ih,
                        D_TMP / "hdd_direct",
                        None,
                        False,
                        55112,
                        seeders,
                        total_bytes,
                        C_TMP / "appdata_2a",
                        "Direto no HDD D: (sem staging)",
                    )
                    print(
                        f"  2A {r2a['name']}: {r2a['elapsed_s']}s | Media {_fmt_mbps(r2a['avg_bps'])} | Pico {_fmt_mbps(r2a['peak_bps'])} | Fila disco max: {r2a['max_disk_queue_mb']} MB"
                    )

                    stg_dir = C_TMP / "nvme_staging"
                    dst_dir = D_TMP / "hdd_staged"
                    r2b = _run_local_vortex(
                        raw_torrent,
                        ih,
                        dst_dir,
                        stg_dir,
                        True,
                        55113,
                        seeders,
                        total_bytes,
                        C_TMP / "appdata_2b",
                        "Vortex Turbo Staging (C: NVMe -> D: HDD)",
                    )
                    final_ok = (dst_dir / "bench_payload.bin").exists() and not (stg_dir / ih).exists()
                    r2b["staging_cleanup_ok"] = final_ok
                    print(
                        f"  2B {r2b['name']}: Total {r2b['elapsed_s']}s (Rede NVMe: {r2b['net_elapsed_s']}s a {_fmt_mbps(r2b['net_bps'])} | Move seq -> D: {r2b['move_elapsed_s']}s a {_fmt_mbps(r2b['move_bps'])}) | Fila max: {r2b['max_disk_queue_mb']} MB | Limpeza ok: {final_ok}"
                    )
                    results["disk"] = {"hdd_direct": r2a, "turbo_staging": r2b}
            finally:
                _stop_seeders(seeders)

        if "hash" in selected:
            assert ti is not None
            print("\n=== Cenario 3: Verificacao SHA (Recheck no Ryzen 7 5700X3D) ===")
            with payload_file.open("rb") as fp:
                while fp.read(8 * 1024 * 1024):
                    pass
            r3a = _run_hash_recheck(ti, seed_dir, total_bytes, 1, 256, 4, "Padrao (1 thread hash)")
            print(
                f"  3A {r3a['name']}: {r3a['elapsed_s']}s | {r3a['mb_per_sec']} MB/s | Projecao 100 GB: {r3a['proj_100gb_s']}s"
            )
            r3b = _run_hash_recheck(ti, seed_dir, total_bytes, 8, 4096, 16, "Vortex Turbo Max (8 threads hash)")
            print(
                f"  3B {r3b['name']}: {r3b['elapsed_s']}s | {r3b['mb_per_sec']} MB/s | Projecao 100 GB: {r3b['proj_100gb_s']}s"
            )
            results["hash"] = {"baseline": r3a, "vortex": r3b}

        if "live" in selected:
            print(f"\n=== Cenario 4: Swarm Real na Internet (Ubuntu 24.04.4 ISO, {args.live_seconds}s por perfil) ===")
            resp = httpx.get(UBUNTU_TORRENT_URL, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            ubuntu_raw = resp.content

            r4a = _run_live_baseline(ubuntu_raw, C_TMP / "live_baseline", args.live_seconds)
            print(
                f"  4A {r4a['name']}: Baixado={r4a['downloaded_mb']} MB | 1MB/s em={r4a['first_1mbs_s']}s | Peers(5s/15s/fim)={r4a['peers_5s']}/{r4a['peers_15s']}/{r4a['peers_end']} (pico {r4a['peak_peers']}) | Media={_fmt_mbps(r4a['avg_bps'])} | Pos-rampa={_fmt_mbps(r4a['tail_bps'])} | Pico={_fmt_mbps(r4a['peak_bps'])} | Efic={r4a['efficiency_pct']}%"
            )
            time.sleep(2.0)
            r4b = _run_live_vortex(
                ubuntu_raw,
                C_TMP / "live_vortex",
                args.live_seconds,
                C_TMP / "appdata_4b",
            )
            print(
                f"  4B {r4b['name']}: Baixado={r4b['downloaded_mb']} MB | 1MB/s em={r4b['first_1mbs_s']}s | Peers(5s/15s/fim)={r4b['peers_5s']}/{r4b['peers_15s']}/{r4b['peers_end']} (pico {r4b['peak_peers']}) | Media={_fmt_mbps(r4b['avg_bps'])} | Pos-rampa={_fmt_mbps(r4b['tail_bps'])} | Pico={_fmt_mbps(r4b['peak_bps'])} | Efic={r4b['efficiency_pct']}%"
            )
            results["live"] = {"baseline": r4a, "vortex": r4b}

        print("\n=== RESUMO_JSON ===")
        print(json.dumps(results, indent=2, ensure_ascii=False))
    finally:
        _cleanup_temp_dirs()
        print("\nLimpeza concluida: pastas temporarias removidas.")


if __name__ == "__main__":
    main()
