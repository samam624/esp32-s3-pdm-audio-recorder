"""Export presentation-ready context slides from the wind-tunnel test photos."""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass


WIDTH, HEIGHT = 1920, 1080
BG = "#f5f7fa"
INK = "#17212b"
NAVY = "#17324d"
ORANGE = "#d06b16"
MUTED = "#52616f"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["arialbd.ttf", "calibrib.ttf"] if bold else ["arial.ttf", "calibri.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def open_photo(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def place_contained(canvas: Image.Image, photo: Image.Image, box: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = box
    fitted = ImageOps.contain(photo, (x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    x = x0 + (x1 - x0 - fitted.width) // 2
    y = y0 + (y1 - y0 - fitted.height) // 2
    canvas.paste(fitted, (x, y))


def place_covered(
    canvas: Image.Image,
    photo: Image.Image,
    box: tuple[int, int, int, int],
    centering: tuple[float, float] = (0.5, 0.5),
) -> None:
    x0, y0, x1, y1 = box
    fitted = ImageOps.fit(
        photo,
        (x1 - x0, y1 - y0),
        Image.Resampling.LANCZOS,
        centering=centering,
    )
    canvas.paste(fitted, (x0, y0))


def title(draw: ImageDraw.ImageDraw, heading: str, subtitle: str) -> None:
    draw.text((70, 42), heading, font=font(58, True), fill=INK)
    draw.text((72, 112), subtitle, font=font(28), fill=MUTED)
    draw.rounded_rectangle((70, 158, 310, 168), radius=5, fill=ORANGE)


def caption(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str) -> None:
    x0, _, x1, y1 = box
    draw.rectangle((x0, y1 - 62, x1, y1), fill=(13, 25, 36, 218))
    draw.text(((x0 + x1) // 2, y1 - 31), text, font=font(23, True), fill="white", anchor="mm")


def save_selected(photo_dir: Path, selected_dir: Path, names: list[str]) -> dict[str, Image.Image]:
    selected_dir.mkdir(parents=True, exist_ok=True)
    photos: dict[str, Image.Image] = {}
    for name in names:
        photo = open_photo(photo_dir / f"{name}.HEIC")
        photos[name] = photo
        photo.save(selected_dir / f"{name}.jpg", quality=94, subsampling=0)
    return photos


def setup_slide(photos: dict[str, Image.Image], output: Path) -> None:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(canvas, "RGBA")
    title(
        draw,
        "Wind-tunnel test: hardware, installation, and live acquisition",
        "The same eight-channel flex array was documented before installation, on the wing, and while recording.",
    )
    boxes = [(70, 205, 625, 930), (680, 205, 1235, 930), (1290, 205, 1845, 930)]
    for box in boxes:
        draw.rounded_rectangle((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), radius=12, fill="white", outline="#cbd3da", width=3)
    place_covered(canvas, photos["IMG_6670"], boxes[0], (0.50, 0.52))
    place_covered(canvas, photos["IMG_6678"], boxes[1], (0.50, 0.52))
    place_covered(canvas, photos["IMG_6674"], boxes[2], (0.57, 0.46))
    caption(draw, boxes[0], "ARRAY + CONTROLLER BEFORE INSTALLATION")
    caption(draw, boxes[1], "ARRAY INSTALLED ACROSS THE WING CHORD")
    caption(draw, boxes[2], "LIVE MULTIBAND LEVEL MONITORING")
    draw.text(
        (WIDTH // 2, 1005),
        "Steady 30 mph  →  30–60 mph ramp  →  steady 60 mph    |    48 kHz, eight microphone channels",
        font=font(25, True),
        fill=NAVY,
        anchor="mm",
    )
    canvas.save(output)


def quality_slide(photos: dict[str, Image.Image], output: Path) -> None:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(canvas, "RGBA")
    title(
        draw,
        "Live monitoring also exposed the main 60 mph limitation",
        "The recorder displayed per-channel, per-band levels and raised an explicit clipping warning during the run.",
    )
    left = (70, 210, 925, 860)
    right = (995, 210, 1850, 860)
    for box in (left, right):
        draw.rounded_rectangle((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), radius=12, fill="white", outline="#cbd3da", width=3)
    place_covered(canvas, photos["IMG_6674"], left, (0.58, 0.48))
    place_covered(canvas, photos["IMG_6675"], right, (0.55, 0.42))
    caption(draw, left, "LIVE EIGHT-CHANNEL BAND-LEVEL TABLE")
    caption(draw, right, "CLIPPING WARNING OBSERVED DURING TESTING")
    draw.rounded_rectangle((90, 905, 1830, 1030), radius=22, fill="#fff1e5", outline="#e6a56d", width=3)
    draw.text(
        (WIDTH // 2, 946),
        "Analysis consequence: mic0–mic2 are clipped at 60 mph.",
        font=font(31, True),
        fill="#8a3f00",
        anchor="mm",
    )
    draw.text(
        (WIDTH // 2, 991),
        "Use the 30 mph case as the cleaner quantitative result; treat 60 mph Lp and fμ magnitudes cautiously.",
        font=font(25),
        fill=INK,
        anchor="mm",
    )
    canvas.save(output)


def takeaway_slide(photos: dict[str, Image.Image], output: Path) -> None:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(canvas, "RGBA")
    title(
        draw,
        "What the wind-tunnel test established",
        "The photographic reference and both acoustic methods identify the same microphone-scale region at 60 mph.",
    )
    photo_box = (70, 205, 760, 1010)
    draw.rounded_rectangle((66, 201, 764, 1014), radius=12, fill="white", outline="#cbd3da", width=3)
    place_covered(canvas, photos["IMG_6676"], photo_box, (0.50, 0.53))
    caption(draw, photo_box, "INSTALLED MMSA ARRAY IN THE TEST SECTION")

    cards = [
        ("4–8 kHz", "produced the clearest spatial separation during the 30–60 mph ramp."),
        ("mic2–mic3", "contains the 60 mph fluorescent-flow boundary and the measured acoustic level break."),
        ("x/c = 0.486–0.581", "is the 60 mph paper-style Lp and fμ derivative interval supported by the mic spacing."),
    ]
    y = 225
    for value, explanation in cards:
        draw.rounded_rectangle((835, y, 1845, y + 205), radius=20, fill="white", outline="#ccd5dd", width=3)
        draw.text((880, y + 42), value, font=font(39, True), fill=ORANGE)
        draw.multiline_text(
            (880, y + 103),
            textwrap.fill(explanation, width=70),
            font=font(27),
            fill=INK,
            spacing=9,
        )
        y += 235
    draw.rounded_rectangle((835, 930, 1845, 1015), radius=16, fill=NAVY)
    draw.text(
        (1340, 972),
        "Report this as an acoustic transition estimate—not independent proof of boundary-layer state.",
        font=font(22, True),
        fill="white",
        anchor="mm",
    )
    canvas.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected_dir = args.output_dir / "selected_test_photos"
    names = ["IMG_6670", "IMG_6674", "IMG_6675", "IMG_6676", "IMG_6678"]
    photos = save_selected(args.photo_dir, selected_dir, names)

    outputs = [
        args.output_dir / "context_test_setup.png",
        args.output_dir / "context_data_quality.png",
        args.output_dir / "context_key_takeaways.png",
    ]
    setup_slide(photos, outputs[0])
    quality_slide(photos, outputs[1])
    takeaway_slide(photos, outputs[2])
    for output in outputs:
        print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
