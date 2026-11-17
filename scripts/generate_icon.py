from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return (
        struct.pack(">I", len(data))
        + body
        + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    )


def _png(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inset = max(1, size // 16)
            radius = size * 0.19
            cx = min(max(x, inset + radius), size - inset - radius)
            cy = min(max(y, inset + radius), size - inset - radius)
            inside = (x - cx) ** 2 + (y - cy) ** 2 <= radius**2
            color = (30, 42, 68, 255) if inside else (0, 0, 0, 0)

            scale = size / 64
            center_x = center_y = size / 2
            stroke = max(1.0, 4 * scale)
            shaft_x = center_x
            if (
                abs(x - shaft_x) <= stroke / 2
                and center_y - 15 * scale <= y <= center_y + 7 * scale
            ):
                color = (137, 180, 250, 255)
            left = (center_x - 8 * scale, center_y - 1 * scale)
            tip = (center_x, center_y + 7 * scale)
            right = (center_x + 8 * scale, center_y - 1 * scale)
            if _near_segment(x, y, left, tip, stroke) or _near_segment(
                x, y, tip, right, stroke
            ):
                color = (137, 180, 250, 255)
            if _near_segment(
                x,
                y,
                (center_x - 13 * scale, center_y + 16 * scale),
                (center_x + 13 * scale, center_y + 16 * scale),
                stroke,
            ):
                color = (137, 180, 250, 255)
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def _near_segment(x, y, start, end, width):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if not length_squared:
        return math.hypot(x - start[0], y - start[1]) <= width / 2
    fraction = max(
        0, min(1, ((x - start[0]) * dx + (y - start[1]) * dy) / length_squared)
    )
    closest = (start[0] + fraction * dx, start[1] + fraction * dy)
    return math.hypot(x - closest[0], y - closest[1]) <= width / 2


def main():
    sizes = (16, 32, 48, 64, 128, 256)
    images = [_png(size) for size in sizes]
    offset = 6 + 16 * len(sizes)
    entries = []
    for size, image in zip(sizes, images):
        entries.append(
            struct.pack(
                "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), offset
            )
        )
        offset += len(image)
    icon = struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(images)
    destination = (
        Path(__file__).resolve().parent.parent / "assets" / "githublauncher.ico"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(icon)
    print(f"Generated {destination}")


if __name__ == "__main__":
    main()
