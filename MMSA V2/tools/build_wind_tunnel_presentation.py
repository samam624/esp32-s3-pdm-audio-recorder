"""Append the wind-tunnel analysis section to the existing recorder deck."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


# Raw test photographs, one per slide, opening the wind-tunnel section.
PHOTO_SLIDES = [
    ("01_photo_array_popfilters_taped.jpg", "Eight-microphone array with both pop filters taped down"),
    ("02_photo_array_on_wing.jpg", "Array installed on the wing"),
    ("03_photo_live_band_levels.jpg", "Live eight-channel band-level display during recording"),
]

SLIDES = [
    "04_wing_level_timeline.png",
    "05_ramp_spectrograms.png",
    "17_wing_30_60_broadband_psd.png",
    "06_full_scale_clipping.png",
    "07_array_rectified.png",
    "08_frequency_band_comparison.png",
    "09_60mph_flow_visualization.png",
    "10_flow_array_overlay.png",
    "11_steady_60mph_levels.png",
    "12_4_8khz_30_vs_60mph.png",
    "13_live_clipping_warning.png",
    "14_paper_metrics_2_7khz.png",
    "15_paper_spatial_derivatives.png",
    "16_key_takeaways.png",
]


def add_fitted_picture(slide, path: Path, slide_width: int, slide_height: int) -> None:
    """Place an image on a white slide without distorting or cropping it."""
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = RGBColor(255, 255, 255)
    with Image.open(path) as image:
        image_width, image_height = image.size
    scale = min(slide_width / image_width, slide_height / image_height)
    width = int(image_width * scale)
    height = int(image_height * scale)
    left = int((slide_width - width) / 2)
    top = int((slide_height - height) / 2)
    slide.shapes.add_picture(str(path), left, top, width=width, height=height)


def add_photo_slide(slide, path: Path, caption: str, slide_width: int, slide_height: int) -> None:
    """One raw photo per slide, fitted on a dark mat with a short caption."""
    background = slide.background.fill
    background.solid()
    background.fore_color.rgb = RGBColor(18, 24, 31)
    with Image.open(path) as image:
        image_width, image_height = image.size
    caption_height = Inches(0.5)
    avail_height = slide_height - caption_height - Inches(0.1)
    scale = min(slide_width / image_width, avail_height / image_height)
    width = int(image_width * scale)
    height = int(image_height * scale)
    slide.shapes.add_picture(
        str(path), int((slide_width - width) / 2), Inches(0.05), width=width, height=height
    )
    box = slide.shapes.add_textbox(0, slide_height - caption_height, slide_width, caption_height)
    paragraph = box.text_frame.paragraphs[0]
    paragraph.text = caption
    paragraph.alignment = PP_ALIGN.CENTER
    paragraph.font.name = "Arial"
    paragraph.font.size = Pt(16)
    paragraph.font.color.rgb = RGBColor(255, 255, 255)


def add_page_number(slide, number: int, slide_width: int, slide_height: int) -> None:
    box = slide.shapes.add_textbox(
        slide_width - Inches(0.65),
        slide_height - Inches(0.34),
        Inches(0.47),
        Inches(0.20),
    )
    box.text_frame.word_wrap = False
    paragraph = box.text_frame.paragraphs[0]
    paragraph.text = str(number)
    paragraph.alignment = PP_ALIGN.RIGHT
    paragraph.font.name = "Arial"
    paragraph.font.size = Pt(9)
    paragraph.font.color.rgb = RGBColor(86, 99, 111)


def update_final_slide_number(slide, old_number: int, new_number: int, slide_height: int) -> None:
    for shape in slide.shapes:
        if not hasattr(shape, "text_frame") or not shape.has_text_frame:
            continue
        if shape.text.strip() == str(old_number) and shape.top > slide_height * 0.80:
            shape.text_frame.paragraphs[0].text = str(new_number)
            shape.left -= Inches(0.18)
            shape.width += Inches(0.18)
            shape.text_frame.word_wrap = False
            return


def add_section_label(slide, slide_width: int) -> None:
    label = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(0.18),
        Inches(0.16),
        Inches(1.86),
        Inches(0.32),
    )
    label.fill.solid()
    label.fill.fore_color.rgb = RGBColor(23, 50, 77)
    label.line.fill.background()
    frame = label.text_frame
    frame.clear()
    frame.margin_left = Inches(0.08)
    frame.margin_right = Inches(0.08)
    frame.margin_top = Inches(0.01)
    frame.margin_bottom = Inches(0.01)
    paragraph = frame.paragraphs[0]
    paragraph.text = "WIND-TUNNEL ANALYSIS"
    paragraph.font.name = "Arial"
    paragraph.font.size = Pt(10)
    paragraph.font.bold = True
    paragraph.font.color.rgb = RGBColor(255, 255, 255)
    paragraph.alignment = PP_ALIGN.CENTER


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_deck", type=Path)
    parser.add_argument("asset_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    prs = Presentation(args.base_deck)
    slide_width, slide_height = prs.slide_width, prs.slide_height
    original_count = len(prs.slides)
    next_steps_slide = prs.slides[-1]
    next_steps_sld_id = list(prs.slides._sldIdLst)[-1]

    offset = 0
    for filename, caption in PHOTO_SLIDES:
        path = args.asset_dir / filename
        if not path.exists():
            raise FileNotFoundError(path)
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        add_photo_slide(slide, path, caption, slide_width, slide_height)
        add_page_number(slide, original_count + offset, slide_width, slide_height)
        offset += 1

    for filename in SLIDES:
        path = args.asset_dir / filename
        if not path.exists():
            raise FileNotFoundError(path)
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        add_fitted_picture(slide, path, slide_width, slide_height)
        add_page_number(slide, original_count + offset, slide_width, slide_height)
        offset += 1

    # Keep the original next-steps slide as the conclusion of the combined deck.
    sld_id_list = prs.slides._sldIdLst
    sld_id_list.remove(next_steps_sld_id)
    sld_id_list.append(next_steps_sld_id)
    update_final_slide_number(next_steps_slide, original_count, len(prs.slides), slide_height)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(args.output)
    print(args.output.resolve())
    print(f"slides: {len(prs.slides)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
