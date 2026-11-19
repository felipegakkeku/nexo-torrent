"""Gera icones PNG (256x256) e ICO (16/24/32/48/64/128/256) com a Orbe NEXO Mineral."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

STOPS = (
    (0.0, (255.0, 255.0, 255.0)),
    (0.24, (101.0, 183.0, 170.0)),  # --nexo-brand
    (0.65, (10.0, 29.0, 18.0)),     # nucleo escuro NEXO
    (1.0, (4.0, 5.0, 5.0)),
)
RING_COLOR = (101.0, 183.0, 170.0)


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


def _sample_grad(t: float) -> tuple[float, float, float]:
    d = max(0.0, min(1.0, t))
    for i in range(len(STOPS) - 1):
        p0, c0 = STOPS[i]
        p1, c1 = STOPS[i + 1]
        if p0 <= d <= p1:
            k = (d - p0) / max(1e-6, p1 - p0)
            return (
                c0[0] + (c1[0] - c0[0]) * k,
                c0[1] + (c1[1] - c0[1]) * k,
                c0[2] + (c1[2] - c0[2]) * k,
            )
    return STOPS[-1][1]


def _render_nexo_orb(size: int) -> bytearray:
    buf = bytearray(size * size * 4)
    half = (size - 1) / 2.0
    aa = 2.0 / max(16.0, float(size))
    ring_outer = 0.96
    ring_inner = 0.90

    for y in range(size):
        ny = (y - half) / half
        for x in range(size):
            nx = (x - half) / half
            rad = math.hypot(nx, ny)
            if rad > 0.985:
                continue

            alpha = 1.0 if rad <= 0.95 else max(0.0, min(1.0, (0.985 - rad) / 0.035))

            # Luz especular superior esquerda (-0.28, -0.28)
            dist = math.hypot(nx + 0.28, ny + 0.28) / 1.15
            r, g, b = _sample_grad(dist)

            # Halo externo --nexo-brand (#65b7aa)
            if ring_inner - aa <= rad <= ring_outer + aa:
                ring_k = 0.85
                if rad < ring_inner:
                    ring_k *= max(0.0, (rad - (ring_inner - aa)) / aa)
                elif rad > ring_outer:
                    ring_k *= max(0.0, (ring_outer + aa - rad) / aa)
                r = r * (1.0 - ring_k) + RING_COLOR[0] * ring_k
                g = g * (1.0 - ring_k) + RING_COLOR[1] * ring_k
                b = b * (1.0 - ring_k) + RING_COLOR[2] * ring_k

            # Glifo discreto de seta de download centralizada
            ax = abs(nx)
            in_stem = ax <= 0.068 and -0.24 <= ny <= 0.11
            in_head = 0.05 <= ny <= 0.29 and ax <= max(0.0, (0.29 - ny) * 1.12)
            in_bar = ax <= 0.24 and 0.34 <= ny <= 0.42
            if in_stem or in_head or in_bar:
                k_glyph = 0.90
                r = r * (1.0 - k_glyph) + 246.0 * k_glyph
                g = g * (1.0 - k_glyph) + 245.0 * k_glyph
                b = b * (1.0 - k_glyph) + 241.0 * k_glyph

            idx = (y * size + x) * 4
            buf[idx] = max(0, min(255, int(r)))
            buf[idx + 1] = max(0, min(255, int(g)))
            buf[idx + 2] = max(0, min(255, int(b)))
            buf[idx + 3] = max(0, min(255, int(alpha * 255)))
    return buf


def main() -> None:
    assets_dir = Path(__file__).resolve().parents[1] / "desktop" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    png_256 = _encode_png(256, 256, _render_nexo_orb(256))
    (assets_dir / "icon.png").write_bytes(png_256)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    png_blobs: list[tuple[int, bytes]] = []
    for sz in sizes:
        blob = png_256 if sz == 256 else _encode_png(sz, sz, _render_nexo_orb(sz))
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
    print("Icones Orbe NEXO Mineral gerados em:", assets_dir)


if __name__ == "__main__":
    main()
