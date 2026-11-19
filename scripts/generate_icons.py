"""Gera icones PNG (256x256) e ICO (16/32/48/256) em Python puro para o VortexTorrent."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _encode_png(width: int, height: int, rgba: bytearray) -> bytes:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride : (y + 1) * stride])
    compressed = zlib.compress(bytes(raw), level=9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def _render_icon(size: int) -> bytearray:
    buf = bytearray(size * size * 4)
    cx = (size - 1) / 2.0
    cy = (size - 1) / 2.0
    half = size / 2.0
    corner_r = size * 0.22
    inner_half = half - corner_r

    for y in range(size):
        for x in range(size):
            dx = abs(x - cx) - inner_half
            dy = abs(y - cy) - inner_half
            ox = max(dx, 0.0)
            oy = max(dy, 0.0)
            sdf_box = math.hypot(ox, oy) + min(max(dx, dy), 0.0) - corner_r

            if sdf_box > 1.2:
                continue

            alpha = 1.0 if sdf_box <= -0.5 else max(0.0, min(1.0, (1.2 - sdf_box) / 1.7))

            # Fundo escuro profundo com leve gradiente diagonal
            t_bg = (x + y) / (2.0 * size)
            r = 11.0 + 9.0 * t_bg
            g = 13.0 + 13.0 * t_bg
            b = 18.0 + 20.0 * t_bg

            # Borda sutil ciano escuro
            if -2.5 * (size / 256.0) <= sdf_box <= 0.5:
                r = r * 0.55 + 34.0 * 0.45
                g = g * 0.55 + 211.0 * 0.45
                b = b * 0.55 + 238.0 * 0.45

            # Vortice espiral duplo em ciano (#22D3EE) e violeta (#A78BFA)
            vx = (x - cx) / half
            vy = (y - cy) / half
            rad = math.hypot(vx, vy)
            if 0.06 <= rad <= 0.78:
                ang = math.atan2(vy, vx)
                swirl = ang + rad * 5.2
                # Tres bracos de vortice
                wave = math.cos(swirl * 3.0)
                ring_fade = math.sin(max(0.0, min(1.0, (rad - 0.06) / 0.72)) * math.pi)
                intensity = max(0.0, (wave - 0.32) / 0.68) * ring_fade
                if intensity > 0.0:
                    mix = max(0.0, min(1.0, (rad - 0.12) / 0.6))
                    cr = 34.0 * (1.0 - mix) + 167.0 * mix
                    cg = 211.0 * (1.0 - mix) + 139.0 * mix
                    cb = 238.0 * (1.0 - mix) + 250.0 * mix
                    k = min(1.0, intensity * 1.15)
                    r = r * (1.0 - k) + cr * k
                    g = g * (1.0 - k) + cg * k
                    b = b * (1.0 - k) + cb * k

            # Seta central de download nitida no miolo
            ax = abs(vx)
            in_stem = ax <= 0.075 and -0.24 <= vy <= 0.10
            in_head = 0.06 <= vy <= 0.28 and ax <= max(0.0, (0.28 - vy) * 1.1)
            if in_stem or in_head:
                r, g, b = 240.0, 250.0, 255.0

            idx = (y * size + x) * 4
            buf[idx] = max(0, min(255, int(r)))
            buf[idx + 1] = max(0, min(255, int(g)))
            buf[idx + 2] = max(0, min(255, int(b)))
            buf[idx + 3] = max(0, min(255, int(alpha * 255)))
    return buf


def main() -> None:
    assets_dir = Path(__file__).resolve().parents[1] / "desktop" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    png_256 = _encode_png(256, 256, _render_icon(256))
    (assets_dir / "icon.png").write_bytes(png_256)

    # Multi-resolucao ICO com payloads PNG (suportado nativamente no Vista+/Win11)
    sizes = [16, 32, 48, 256]
    png_blobs: list[tuple[int, bytes]] = []
    for sz in sizes:
        blob = png_256 if sz == 256 else _encode_png(sz, sz, _render_icon(sz))
        png_blobs.append((sz, blob))

    header = struct.pack("<HHH", 0, 1, len(png_blobs))
    offset = 6 + 16 * len(png_blobs)
    entries = bytearray()
    payload = bytearray()
    for sz, blob in png_blobs:
        dim = 0 if sz >= 256 else sz
        entries.extend(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset))
        payload.extend(blob)
        offset += len(blob)

    (assets_dir / "icon.ico").write_bytes(header + bytes(entries) + bytes(payload))
    print("Icones gerados em:", assets_dir)


if __name__ == "__main__":
    main()
