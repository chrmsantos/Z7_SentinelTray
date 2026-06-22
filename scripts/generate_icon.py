"""Generate assets/icon.ico -- green eye icon for Z7_SentinelTray.

Run from the repository root:
    python scripts/generate_icon.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


# -- Palette ------------------------------------------------------------------
_BG_DARK = (11, 17, 27, 255)   # deep navy background


def _draw_iris_fibers(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    inner_r: int,
    outer_r: int,
    s: int,
) -> None:
    """Radial fiber lines inside the iris for a realistic texture."""
    num_spokes = 28
    spoke_w = max(1, int(s * 0.005))
    for i in range(num_spokes):
        angle = math.radians(i * 360 / num_spokes)
        x0 = int(cx + inner_r * math.cos(angle))
        y0 = int(cy + inner_r * math.sin(angle))
        x1 = int(cx + outer_r * math.cos(angle))
        y1 = int(cy + outer_r * math.sin(angle))
        draw.line([x0, y0, x1, y1], fill=(12, 50, 16, 60), width=spoke_w)


def _make_icon(size: int) -> Image.Image:
    """Render a green eye icon on a transparent background at *size* x *size*."""
    scale = 12                      # 12× supersampling for smooth anti-aliased edges
    s = size * scale
    cx, cy = s // 2, s // 2

    # Start with a transparent canvas
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    # 2. Two-layer glow: wide cool haze + tight warm core
    for glow_color, radius_base, step, alpha_base, blur_factor in (
        ((40, 160, 60), 0.28, 0.022, 3, 0.08),   # wide cool haze
        ((80, 220, 100), 0.16, 0.016, 6, 0.04),  # tight warm core
    ):
        glow_layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow_layer)
        for i in range(12):
            gr = int(s * (radius_base + i * step))
            alpha = alpha_base + i * 3
            gd.ellipse(
                [cx - gr, cy - gr, cx + gr, cy + gr],
                fill=(*glow_color, alpha),
            )
        glow_layer = glow_layer.filter(
            ImageFilter.GaussianBlur(radius=int(s * blur_factor))
        )
        img = Image.alpha_composite(img, glow_layer)

    # 3. Eye shape
    ew = int(s * 0.78)
    eh = int(s * 0.48)
    ex0, ey0 = cx - ew // 2, cy - eh // 2
    ex1, ey1 = ex0 + ew, ey0 + eh
    ea, eb = ew // 2, eh // 2          # semi-axes for parametric lash placement

    # Drop shadow beneath eye
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd_off = int(s * 0.025)
    ImageDraw.Draw(shadow).ellipse(
        [ex0 + sd_off, ey0 + sd_off * 2, ex1 + sd_off, ey1 + sd_off * 2],
        fill=(0, 0, 0, 90),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=int(s * 0.025)))
    img = Image.alpha_composite(img, shadow)

    # Eye contents layer
    eye_layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ed = ImageDraw.Draw(eye_layer)

    # Sclera — very slightly warm white
    ed.ellipse([ex0, ey0, ex1, ey1], fill=(248, 250, 246, 255))

    # Limbal ring (very dark outermost iris ring for depth)
    limbal_r = int(s * 0.200)
    ed.ellipse(
        [cx - limbal_r, cy - limbal_r, cx + limbal_r, cy + limbal_r],
        fill=(6, 32, 8, 255),
    )
    # Outer iris — deep forest green
    iris_r = int(s * 0.185)
    ed.ellipse(
        [cx - iris_r, cy - iris_r, cx + iris_r, cy + iris_r],
        fill=(22, 88, 30, 255),
    )
    # Mid iris — vibrant green
    mid_r = int(s * 0.148)
    ed.ellipse(
        [cx - mid_r, cy - mid_r, cx + mid_r, cy + mid_r],
        fill=(46, 196, 106, 255),
    )
    # Inner iris ring — slightly darker for dimension
    inner_r = int(s * 0.110)
    ed.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=(36, 162, 86, 255),
    )

    # Iris radial fiber texture
    _draw_iris_fibers(ed, cx, cy, int(mid_r * 0.30), int(mid_r * 0.90), s)

    # Pupil
    pupil_r = int(s * 0.072)
    ed.ellipse(
        [cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r],
        fill=(8, 8, 10, 255),
    )

    # Primary catchlight — top-right
    hl_r = max(3, int(s * 0.033))
    hl_x = cx + int(s * 0.060)
    hl_y = cy - int(s * 0.063)
    ed.ellipse(
        [hl_x - hl_r, hl_y - hl_r, hl_x + hl_r, hl_y + hl_r],
        fill=(255, 255, 255, 255),
    )
    # Secondary catchlight — bottom-left, dimmer
    hl2_r = max(2, int(s * 0.018))
    hl2_x = cx - int(s * 0.055)
    hl2_y = cy + int(s * 0.042)
    ed.ellipse(
        [hl2_x - hl2_r, hl2_y - hl2_r, hl2_x + hl2_r, hl2_y + hl2_r],
        fill=(255, 255, 255, 120),
    )

    # Clip eye contents to the lens shape
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([ex0, ey0, ex1, ey1], fill=255)
    clipped = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    clipped.paste(eye_layer, mask=mask)

    # Eyelid border
    border_w = max(2, int(s * 0.018))
    ImageDraw.Draw(clipped).ellipse(
        [ex0, ey0, ex1, ey1], outline=(8, 52, 10, 255), width=border_w
    )

    # Upper eyelid arc — darker thicker stroke on the top half only
    lid_d = ImageDraw.Draw(clipped)
    lid_w = max(3, int(s * 0.028))
    lid_d.arc(
        [ex0 - int(s * 0.004), ey0 - int(s * 0.004),
         ex1 + int(s * 0.004), ey1 + int(s * 0.004)],
        start=195, end=345, fill=(5, 28, 7, 230), width=lid_w,
    )

    # Upper eyelash lines — variable length, radiating outward
    lash_color = (10, 52, 12, 215)
    lash_w = max(2, int(s * 0.013))
    ld = ImageDraw.Draw(clipped)
    lash_specs = [
        (218, 0.075), (232, 0.068), (248, 0.078),
        (265, 0.072), (282, 0.078), (298, 0.068), (312, 0.072),
    ]
    for angle_deg, lash_frac in lash_specs:
        angle_rad = math.radians(angle_deg)
        sx = int(cx + ea * math.cos(angle_rad))
        sy = int(cy + eb * math.sin(angle_rad))
        lash_len = int(s * lash_frac)
        ex_end = int(sx + lash_len * math.cos(angle_rad))
        ey_end = int(sy + lash_len * math.sin(angle_rad))
        ld.line([sx, sy, ex_end, ey_end], fill=lash_color, width=lash_w)

    img = Image.alpha_composite(img, clipped)

    # Inner iris-edge soft green glow (subtle halo inside the sclera)
    inner_glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ig_r = limbal_r + int(s * 0.018)
    ImageDraw.Draw(inner_glow).ellipse(
        [cx - ig_r, cy - ig_r, cx + ig_r, cy + ig_r],
        outline=(60, 200, 90, 40),
        width=max(2, int(s * 0.014)),
    )
    inner_glow = inner_glow.filter(
        ImageFilter.GaussianBlur(radius=max(1, int(s * 0.012)))
    )
    img = Image.alpha_composite(img, inner_glow)

    return img.resize((size, size), Image.LANCZOS)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256, 512]

    assets_dir = Path(__file__).resolve().parents[1] / "assets"
    assets_dir.mkdir(exist_ok=True)

    ico_path = assets_dir / "icon.ico"
    png_256_path = assets_dir / "icon_256.png"
    png_512_path = assets_dir / "icon_512.png"

    frames = [_make_icon(sz) for sz in sizes]

    frames[0].save(
        ico_path,
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=frames[1:],
    )
    print(f"[OK] {ico_path}")

    frames[sizes.index(256)].save(png_256_path, format="PNG")
    print(f"[OK] {png_256_path}")

    frames[sizes.index(512)].save(png_512_path, format="PNG")
    print(f"[OK] {png_512_path}")


if __name__ == "__main__":
    main()