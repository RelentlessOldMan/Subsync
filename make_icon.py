r"""
Generate subsync.ico -- a multi-size Windows icon, pure stdlib (no PIL).

The mark is the Subsync brand: a cyan play triangle over a little waveform on a
dark rounded tile, matching the app's palette. Rendered once at 768x768 (3x
supersampled) with signed-distance shapes, then area-averaged down to each icon
size for clean anti-aliasing, PNG-encoded, and packed into an .ico.

    python make_icon.py        # writes subsync.ico next to this file
"""
import os
import zlib
import struct
import math

# palette (matches subsync.py)
PANEL = (0x1b, 0x1e, 0x27)
BORDER = (0x35, 0x3c, 0x52)
CYAN = (0x4f, 0xd1, 0xff)
WAVE = (0x63, 0xd6, 0xf0)

MASTER = 768                       # divisible by every target size below
SIZES = [16, 24, 32, 48, 64, 128, 256]


def _rounded_box_sdf(px, py, half, r):
    # px,py relative to center; returns signed distance (<=0 inside)
    qx = abs(px) - half + r
    qy = abs(py) - half + r
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return min(max(qx, qy), 0.0) + outside - r


def _tri_sign(ax, ay, bx, by, cx, cy):
    return (ax - cx) * (by - cy) - (bx - cx) * (ay - cy)


def _in_triangle(x, y, v):
    (ax, ay), (bx, by), (cx, cy) = v
    d1 = _tri_sign(x, y, ax, ay, bx, by)
    d2 = _tri_sign(x, y, bx, by, cx, cy)
    d3 = _tri_sign(x, y, cx, cy, ax, ay)
    neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (neg and pos)


def _dist_to_polyline(x, y, pts):
    best = 1e9
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dx, dy = x2 - x1, y2 - y1
        t = 0.0 if (dx == 0 and dy == 0) else \
            max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return best


def render_master():
    n = MASTER
    buf = bytearray(n * n * 4)          # premultiplied RGBA
    # geometry in [0,1]
    half, radius = 0.5, 0.20
    tri = [(0.35, 0.20), (0.35, 0.585), (0.685, 0.392)]  # right-pointing play
    wave = [(0.255 + 0.49 * i / 40.0,
             0.735 + 0.058 * math.sin(i / 40.0 * math.pi * 3.0))
            for i in range(41)]
    wave_w = 0.055
    for iy in range(n):
        y = (iy + 0.5) / n
        py = y - 0.5
        row = iy * n * 4
        for ix in range(n):
            x = (ix + 0.5) / n
            sdf = _rounded_box_sdf(x - 0.5, py, half, radius)
            o = row + ix * 4
            if sdf > 0.0:
                continue                # transparent outside the tile
            # base tile (thin border ring near the edge)
            if sdf > -0.018:
                r, g, b = BORDER
            else:
                r, g, b = PANEL
            # play triangle
            if 0.30 < x < 0.72 and 0.16 < y < 0.63 and _in_triangle(x, y, tri):
                r, g, b = CYAN
            # waveform
            elif 0.66 < y < 0.82 and _dist_to_polyline(x, y, wave) < wave_w / 2:
                r, g, b = WAVE
            buf[o] = r
            buf[o + 1] = g
            buf[o + 2] = b
            buf[o + 3] = 255
    return buf


def downscale(master, size):
    n = MASTER
    block = n // size
    out = bytearray(size * size * 4)
    area = block * block
    for oy in range(size):
        for ox in range(size):
            sr = sg = sb = sa = 0
            base_y = oy * block
            base_x = ox * block
            for by in range(block):
                row = (base_y + by) * n * 4
                for bx in range(block):
                    p = row + (base_x + bx) * 4
                    a = master[p + 3]
                    sr += master[p] * a       # premultiply so edges don't darken
                    sg += master[p + 1] * a
                    sb += master[p + 2] * a
                    sa += a
            oo = (oy * size + ox) * 4
            if sa == 0:
                continue
            out[oo] = min(255, sr // sa)
            out[oo + 1] = min(255, sg // sa)
            out[oo + 2] = min(255, sb // sa)
            out[oo + 3] = sa // area
    return out


def png_encode(rgba, size):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    raw = bytearray()
    for y in range(size):
        raw.append(0)                       # filter: none
        raw += rgba[y * size * 4:(y + 1) * size * 4]
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def build_ico(pngs):
    # pngs: list of (size, png_bytes)
    out = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, blobs = bytearray(), bytearray()
    for size, data in pngs:
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    return bytes(out) + bytes(entries) + bytes(blobs)


def main():
    master = render_master()
    pngs = [(s, png_encode(downscale(master, s), s)) for s in SIZES]
    ico = build_ico(pngs)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subsync.ico")
    with open(path, "wb") as f:
        f.write(ico)
    print(f"wrote {path}  ({len(ico)} bytes, sizes {SIZES})")


if __name__ == "__main__":
    main()
