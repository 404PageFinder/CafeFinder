"""Generate synthetic screenshot fixtures for OCR testing.

Run this once to populate tests/fixtures/screenshots/. The fixtures
simulate three types of input the app will encounter:

1. Signboard — large cafe name on a clean background
2. Menu — multi-line text with prices
3. Address card — name + address + phone

These are NOT meant to test PaddleOCR's accuracy on real-world photos.
For that, add real screenshots to tests/fixtures/screenshots/real/ and
write integration tests that opt-in via env flag (RUN_REAL_OCR=1).

Usage:
    python -m tests.fixtures.generate_screenshots
"""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent / "screenshots"


def _font(size: int):
    """Try to load a system font, fall back to PIL default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_signboard():
    """A simple cafe signboard image."""
    img = Image.new("RGB", (800, 400), color=(245, 240, 230))
    draw = ImageDraw.Draw(img)

    # Cafe name
    draw.text((50, 80), "ROASTERY COFFEE HOUSE", fill=(60, 40, 30), font=_font(54))
    # Tagline
    draw.text((50, 180), "Coffee | Brunch | Desserts", fill=(100, 80, 70), font=_font(28))
    # Location
    draw.text((50, 280), "Banjara Hills, Hyderabad", fill=(80, 60, 50), font=_font(32))

    out = OUT_DIR / "signboard_roastery.png"
    img.save(out)
    return out


def make_menu():
    """A menu screenshot with multiple text lines."""
    img = Image.new("RGB", (600, 700), color=(255, 255, 250))
    draw = ImageDraw.Draw(img)

    draw.text((40, 30), "CAFE NILOUFER", fill=(0, 0, 0), font=_font(40))
    draw.text((40, 90), "Lakdikapul, Hyderabad", fill=(80, 80, 80), font=_font(20))
    draw.line([(40, 130), (560, 130)], fill=(0, 0, 0), width=2)

    items = [
        ("Irani Chai", "₹40"),
        ("Osmania Biscuit", "₹25"),
        ("Bun Maska", "₹60"),
        ("Salt Biscuit", "₹30"),
        ("Plum Cake", "₹120"),
    ]
    y = 160
    for name, price in items:
        draw.text((50, y), name, fill=(0, 0, 0), font=_font(28))
        draw.text((480, y), price, fill=(0, 0, 0), font=_font(28))
        y += 50

    out = OUT_DIR / "menu_niloufer.png"
    img.save(out)
    return out


def make_address_card():
    """An address card / contact info screenshot."""
    img = Image.new("RGB", (700, 500), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    draw.text((40, 40), "Driftwood Cafe", fill=(20, 20, 20), font=_font(46))
    draw.text((40, 120), "Plot No. 1289, Road No. 36", fill=(50, 50, 50), font=_font(24))
    draw.text((40, 160), "Jubilee Hills, Hyderabad - 500033", fill=(50, 50, 50), font=_font(24))
    draw.text((40, 200), "Telangana, India", fill=(50, 50, 50), font=_font(24))
    draw.text((40, 280), "Phone: +91 98765 43210", fill=(50, 50, 50), font=_font(22))
    draw.text((40, 320), "Open: 9 AM - 11 PM", fill=(50, 50, 50), font=_font(22))

    out = OUT_DIR / "address_driftwood.png"
    img.save(out)
    return out


def make_low_signal():
    """An image with no useful text — for testing low-confidence handling."""
    img = Image.new("RGB", (500, 300), color=(200, 200, 200))
    draw = ImageDraw.Draw(img)
    # Just a few unrelated words
    draw.text((50, 100), "Welcome", fill=(150, 150, 150), font=_font(40))
    draw.text((50, 180), "Thank you", fill=(150, 150, 150), font=_font(30))

    out = OUT_DIR / "low_signal.png"
    img.save(out)
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        make_signboard(),
        make_menu(),
        make_address_card(),
        make_low_signal(),
    ]
    print("Generated fixtures:")
    for p in paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
