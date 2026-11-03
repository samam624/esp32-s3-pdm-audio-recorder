"""Build a labeled contact sheet from the wind-tunnel test HEIC photographs."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    photos = sorted(args.photo_dir.glob("*.HEIC"))
    if not photos:
        raise FileNotFoundError(f"No HEIC photos found in {args.photo_dir}")

    columns = 2
    thumb_size = (720, 520)
    label_height = 52
    margin = 24
    rows = (len(photos) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (
            columns * thumb_size[0] + (columns + 1) * margin,
            rows * (thumb_size[1] + label_height) + (rows + 1) * margin,
        ),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=26)

    for index, path in enumerate(photos):
        with Image.open(path) as source:
            photo = ImageOps.exif_transpose(source).convert("RGB")
            thumb = ImageOps.contain(photo, thumb_size, Image.Resampling.LANCZOS)
        row, column = divmod(index, columns)
        cell_x = margin + column * (thumb_size[0] + margin)
        cell_y = margin + row * (thumb_size[1] + label_height + margin)
        image_x = cell_x + (thumb_size[0] - thumb.width) // 2
        image_y = cell_y + (thumb_size[1] - thumb.height) // 2
        sheet.paste(thumb, (image_x, image_y))
        label = f"{path.stem}  |  {photo.width} x {photo.height}"
        draw.text(
            (cell_x + thumb_size[0] // 2, cell_y + thumb_size[1] + 10),
            label,
            fill="#111111",
            font=font,
            anchor="ma",
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=94)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
