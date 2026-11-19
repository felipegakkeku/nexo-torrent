from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import libtorrent as lt
import pytest

from config import AppConfig
from engine import VortexEngine, _resolve_interface_bind, build_settings_pack
from hardware import (
    DriveInfo,
    HardwareInfo,
    NetworkInterfaceInfo,
    classify_path_drive,
    detect_hardware,
    should_use_staging,
)


def _make_torrent_bytes(source_path: Path, private: bool = False) -> tuple[bytes, str]:
    fs = lt.file_storage()
    lt.add_files(fs, str(source_path))
    ct = lt.create_torrent(fs, piece_size=256 * 1024)
    ct.set_creator("VortexTest")
    if private:
        ct.set_priv(True)
    lt.set_piece_hashes(ct, str(source_path.parent))
    entry = ct.generate()
    raw = lt.bencode(entry)
    ti = lt.torrent_info(lt.bdecode(raw))
    ih = str(ti.info_hashes().get_best()).lower()
    return raw, ih


def test_turbo_settings_pack_valid():
    hw = detect_hardware()
    for profile in ("turbo_max", "balanced", "quiet"):
        ses = lt.session()
        cfg = AppConfig(profile=profile)
        pack = build_settings_pack(cfg, hw, ses.get_settings())
        ses.apply_settings(pack)
        applied = ses.get_settings()

        if profile == "turbo_max":
            assert applied["connection_speed"] == 500
            assert applied["announce_to_all_trackers"] is True
            assert applied["announce_to_all_tiers"] is True
            assert applied["max_out_request_queue"] == 2500
            assert applied["hashing_threads"] >= 4
            assert applied["aio_threads"] >= 8
            assert applied["allow_multiple_connections_per_ip"] is True
            assert applied["smooth_connects"] is False
            assert applied["coalesce_writes"] is True
            assert applied["coalesce_reads"] is True
            assert applied["piece_extent_affinity"] is True
            assert applied["dht_upload_rate_limit"] == 64000
            assert applied["max_pex_peers"] == 200
            assert applied["max_peer_recv_buffer_size"] == 8 * 1024 * 1024
            assert applied["peer_connect_timeout"] == 7
            assert applied["piece_timeout"] == 10
        elif profile == "balanced":
            assert applied["connection_speed"] == 200
            assert applied["connections_limit"] == 500
        else:
            assert applied["connection_speed"] == 80
            assert applied["connections_limit"] == 220


def test_hardware_detection():
    hw = detect_hardware()
    assert hw.cpu_count >= 4
    assert hw.ram_total_gb >= 8.0
    c_drive = classify_path_drive(r"C:\Windows", hw)
    assert c_drive is not None
    assert c_drive.drive == "C"
    assert c_drive.media_type in ("NVMe", "SSD")

    d_drive = classify_path_drive(r"D:\Downloads", hw)
    assert d_drive is not None
    assert d_drive.drive == "D"
    assert d_drive.media_type == "HDD"


def test_private_torrent_never_boosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VORTEX_DATA_DIR", str(tmp_path / "appdata"))
    src_file = tmp_path / "privado.bin"
    src_file.write_bytes(os.urandom(512 * 1024))
    raw, ih = _make_torrent_bytes(src_file, private=True)

    engine = VortexEngine()
    try:
        info = engine.add_torrent_bytes(
            raw,
            save_path=str(tmp_path / "dest"),
            use_staging=False,
            start_paused=True,
            boost_trackers=True,
        )
        assert info["is_private"] is True
        assert info["boosted_trackers"] is False

        boost_res = engine.boost_trackers(ih)
        assert boost_res["ok"] is False
        assert boost_res["added"] == 0

        details = engine.get_torrent_details(ih)
        assert details is not None
        assert details["trackers"] == []
    finally:
        engine.shutdown()


def test_local_loopback_swarm_and_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VORTEX_DATA_DIR", str(tmp_path / "appdata"))

    seed_dir = tmp_path / "seed_src"
    seed_dir.mkdir(parents=True, exist_ok=True)
    payload_file = seed_dir / "vortex_32mb_test.bin"
    payload_bytes = os.urandom(32 * 1024 * 1024)
    payload_file.write_bytes(payload_bytes)
    expected_sha256 = hashlib.sha256(payload_bytes).hexdigest()

    raw_torrent, ih = _make_torrent_bytes(payload_file, private=False)

    seeder_ses = lt.session()
    seeder_cfg = dict(lt.high_performance_seed())
    seeder_cfg.update(
        {
            "listen_interfaces": "127.0.0.1:54101",
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "allow_multiple_connections_per_ip": True,
        }
    )
    seeder_ses.apply_settings(seeder_cfg)

    ti = lt.torrent_info(lt.bdecode(raw_torrent))
    seed_atp = lt.add_torrent_params()
    seed_atp.ti = ti
    seed_atp.save_path = str(seed_dir)
    seed_atp.flags |= lt.torrent_flags.seed_mode
    seeder_handle = seeder_ses.add_torrent(seed_atp)

    staging_root = tmp_path / "staging"
    dest_root = tmp_path / "dest"
    staging_root.mkdir(parents=True, exist_ok=True)
    dest_root.mkdir(parents=True, exist_ok=True)

    engine = VortexEngine()
    engine.apply_config(
        AppConfig(
            profile="turbo_max",
            default_save_path=str(dest_root),
            staging_path=str(staging_root),
            nvme_staging_enabled=True,
            listen_port=54102,
            network_interface="127.0.0.1",
            enable_dht=False,
            enable_lsd=False,
            enable_upnp=False,
            auto_boost_public_trackers=False,
        )
    )

    t_start = time.perf_counter()
    done_snapshot = None
    try:
        added = engine.add_torrent_bytes(
            raw_torrent,
            save_path=str(dest_root),
            use_staging=True,
            boost_trackers=False,
        )
        assert added["staging_active"] is True

        handle = engine._find_handle(ih)
        assert handle is not None
        handle.connect_peer(("127.0.0.1", 54101))
        seeder_handle.connect_peer(("127.0.0.1", 54102))

        deadline = time.time() + 30.0
        reconnected_at = 0.0
        while time.time() < deadline:
            snap = engine.tick()
            items = [t for t in snap["torrents"] if t["info_hash"] == ih]
            if items:
                item = items[0]
                if item["is_finished"] and not item["staging_active"] and not item["moving_storage"]:
                    done_snapshot = item
                    break
                if item["num_peers"] == 0 and time.time() - reconnected_at > 1.0:
                    reconnected_at = time.time()
                    handle.connect_peer(("127.0.0.1", 54101))
                    seeder_handle.connect_peer(("127.0.0.1", 54102))
            time.sleep(0.05)

        elapsed = max(0.001, time.perf_counter() - t_start)
        assert done_snapshot is not None, "Download local com staging não concluiu no tempo esperado."
        mbps = 32.0 / elapsed
        print(f"\n[BENCHMARK LOOPBACK 32MB + STAGING] tempo={elapsed:.2f}s taxa={mbps:.1f} MB/s")

        final_file = dest_root / "vortex_32mb_test.bin"
        assert final_file.exists(), "Arquivo movido não existe no destino final."
        actual_sha256 = hashlib.sha256(final_file.read_bytes()).hexdigest()
        assert actual_sha256 == expected_sha256

        staged_subdir = staging_root / ih
        assert not staged_subdir.exists(), "Subdiretório de staging deveria ter sido removido após move_storage."
    finally:
        engine.shutdown()
        seeder_ses.pause()

    state_dir = tmp_path / "appdata" / "state"
    assert (state_dir / f"{ih}.torrent").exists()
    assert (state_dir / f"{ih}.fastresume").exists()

    engine_reload = VortexEngine()
    try:
        reloaded = []
        reload_deadline = time.time() + 5.0
        while time.time() < reload_deadline:
            snap2 = engine_reload.tick()
            reloaded = [t for t in snap2["torrents"] if t["info_hash"] == ih]
            if reloaded and reloaded[0]["raw_state"] not in ("checking_resume_data", "checking_files"):
                break
            time.sleep(0.05)
        assert len(reloaded) == 1
        assert reloaded[0]["progress"] == 100.0
        assert reloaded[0]["is_finished"] or reloaded[0]["is_seeding"]
    finally:
        engine_reload.shutdown()


def test_virtual_interfaces_excluded_from_auto_bind():
    mock_hw = HardwareInfo(
        cpu_count=16,
        ram_total_gb=32.0,
        drives=[],
        interfaces=[
            NetworkInterfaceInfo(
                name="vEthernet (Default Switch)",
                description="Hyper-V Virtual Ethernet Adapter",
                ip="172.26.176.1",
                is_virtual=True,
            ),
            NetworkInterfaceInfo(
                name="vEthernet (WSL (Hyper-V firewall))",
                description="Hyper-V Virtual Ethernet Adapter #2",
                ip="172.22.224.1",
                is_virtual=True,
            ),
            NetworkInterfaceInfo(
                name="Loopback Pseudo-Interface",
                description="Software Loopback",
                ip="127.0.0.1",
                is_virtual=True,
            ),
            NetworkInterfaceInfo(
                name="Ethernet",
                description="Realtek PCIe GbE Family Controller",
                ip="192.168.0.3",
                link_speed_mbps=1000,
                is_virtual=False,
            ),
        ],
    )
    listen_str, out_str = _resolve_interface_bind(
        AppConfig(network_interface="", listen_port=51413), mock_hw
    )
    assert listen_str == "192.168.0.3:51413"
    assert out_str == ""


def test_smart_staging_threshold():
    hw = detect_hardware()
    cfg = AppConfig(
        nvme_staging_enabled=True,
        staging_path=r"C:\VortexStaging",
        staging_min_size_gb=2.0,
        staging_min_free_gb=20.0,
    )
    small_ok, small_reason = should_use_staging(r"D:\Downloads", 512 * 1024 * 1024, cfg, hw)
    assert small_ok is False
    assert "cache em RAM" in small_reason

    large_ok, _ = should_use_staging(r"D:\Downloads", 5 * (1024**3), cfg, hw)
    assert large_ok is True


def test_dht_session_state_persisted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VORTEX_DATA_DIR", str(tmp_path / "appdata"))
    e1 = VortexEngine()
    try:
        assert e1._dht_state_loaded is False
    finally:
        e1.shutdown()

    state_file = tmp_path / "appdata" / "state" / "session.state"
    assert state_file.exists() and state_file.stat().st_size > 0

    e2 = VortexEngine()
    try:
        assert e2._dht_state_loaded is True
        snap = e2.get_state_snapshot()
        assert snap["global"]["dht_state_loaded"] is True
    finally:
        e2.shutdown()
