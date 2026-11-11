"""Core poster generation: overlay dynamic text on the JangSanj template.

This module is independent of FastAPI / n8n — it just exposes
`generate_poster(values, config_path) -> bytes` returning PNG bytes, and a
`generate_poster_to_file(values, out_path, config_path)` helper that writes
a file. The FastAPI wrapper in `app.py` calls the bytes variant.

Text elements supported (defined in config.json):
  - percent_24h   : big red percentage shown in the central red box
  - percent_7d    : red percentage shown in the right small red box
  - percent_30d   : red percentage shown in the left small red box
  - date_en       : English Gregorian date (e.g. "November 01, 2026")
  - date_fa       : Persian Jalali date with weekday (e.g. "یکشنبه ۱۰ آبان ۱۴۰۵")

Each element config supports:
  font            : key into config["fonts"]
  size            : font size in px
  color           : [R, G, B]
  anchor          : PIL text anchor (mm = middle-middle, lm = left-middle,
                    rm = right-middle, la = left-ascender, etc.)
  position        : [x, y] in template pixels (anchor point)
  persian_digits  : convert 0-9 to ۰-۹
  reshape         : run arabic_reshaper + bidi for proper Persian rendering
  stroke          : null or {"width": int, "fill": [R,G,B]}
  text_template   : optional, e.g. "{value}%" — used for percentages
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

from PIL import Image, ImageDraw, ImageFont, features as pil_features

# When Pillow is compiled with libraqm (HarfBuzz + FriBidi), PIL handles
# Arabic shaping and bidi in one pass via the `direction="rtl"` parameter —
# no need for arabic_reshaper or python-bidi. The fallback below is only
# used on older Pillow builds without raqm.
_HAS_RAQM = bool(pil_features.check("raqm"))
if not _HAS_RAQM:
    import arabic_reshaper
    from bidi.algorithm import get_display

from date_utils import format_english_date, format_persian_date


Number = Union[int, float, str]


def _resolve_path(base_dir: Path, raw: str) -> Path:
    """Resolve a path that may be relative (to the config file's dir)."""
    p = Path(raw)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()


def _load_config(config_path: Union[str, Path]) -> Dict[str, Any]:
    config_path = Path(config_path).resolve()
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_base_dir"] = config_path.parent
    # Resolve template path
    cfg["_template_path"] = _resolve_path(cfg["_base_dir"], cfg["template_path"])
    # Resolve font paths
    fonts = {}
    for key, rel in cfg["fonts"].items():
        fonts[key] = _resolve_path(cfg["_base_dir"], rel)
    cfg["_fonts_resolved"] = fonts
    return cfg


def _get_font(cfg: Dict[str, Any], font_key: str, size: int) -> ImageFont.FreeTypeFont:
    path = cfg["_fonts_resolved"].get(font_key)
    if path is None or not path.exists():
        # Fallback to default PIL font
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size)


def _prepare_text(text: str, persian_digits: bool, reshape: bool) -> str:
    """Apply Persian digit conversion and (only as fallback) Arabic shaping.

    When PIL has libraqm, shaping + bidi happen inside draw.text() via the
    `direction="rtl"` parameter, so this function only does digit conversion.
    The legacy `reshape=True` path is kept for Pillow builds without raqm.
    """
    if persian_digits:
        from date_utils import to_persian_digits
        text = to_persian_digits(text)
    if reshape and not _HAS_RAQM:
        text = get_display(arabic_reshaper.reshape(text))
    return text


def _format_percent(value: Number, template: Optional[str]) -> str:
    """Render a percentage value into the configured template."""
    if isinstance(value, str):
        s = value.strip().rstrip("%").strip()
        try:
            f = float(s)
        except ValueError:
            f = None
    else:
        f = float(value)
    if f is None:
        s = str(value)
    elif f == int(f):
        # No decimals for whole percentages (e.g. 28, not 28.0)
        s = str(int(f))
    else:
        # Trim trailing zeros for fractional values (e.g. 5.25, 12.5)
        s = f"{f:.4f}".rstrip("0").rstrip(".")
    if template:
        return template.format(value=s)
    return s


def _draw_element(draw: ImageDraw.ImageDraw,
                  cfg: Dict[str, Any],
                  name: str,
                  text: str) -> None:
    """Draw a single text element on the canvas using its config.

    Supports an optional `suffix` block that draws a second text (e.g. the
    "%" sign) separately from the main value, so its font/size/offset can
    differ — useful when a font's "%" glyph is unusually large or off-baseline.
    """
    el = cfg["elements"].get(name)
    if el is None or text is None or text == "":
        return
    prepared = _prepare_text(
        text,
        el.get("persian_digits", False),
        el.get("reshape", False),
    )
    font = _get_font(cfg, el["font"], el["size"])
    color = tuple(el.get("color", [255, 255, 255]))
    anchor = el.get("anchor", "la")
    x, y = el["position"]
    stroke = el.get("stroke")
    stroke_width = stroke["width"] if stroke else 0
    stroke_fill = tuple(stroke["fill"]) if stroke else None
    # `direction` lets PIL+raqm do proper Arabic shaping + bidi. When raqm
    # is available, this is all that's needed for correct Persian rendering.
    direction = el.get("direction")
    kwargs = dict(
        font=font,
        fill=color,
        anchor=anchor,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    if direction and _HAS_RAQM:
        kwargs["direction"] = direction

    # Strip the suffix from the main text if a suffix block is defined —
    # the suffix will be drawn separately below.
    suffix_cfg = el.get("suffix")
    main_text = prepared
    if suffix_cfg:
        # If text_template produced e.g. "28%", strip the trailing "%"
        # so the main draw shows only "28" and the suffix draws "%".
        suffix_text = suffix_cfg.get("text", "")
        if suffix_text and main_text.endswith(suffix_text):
            main_text = main_text[: -len(suffix_text)]

    draw.text((x, y), main_text, **kwargs)

    # Draw the suffix separately with its own font / size / offset.
    # Offset is relative to the anchor point of the main text — so e.g.
    # offset_x=180 means 180px to the right of the main anchor.
    if suffix_cfg:
        suffix_text = suffix_cfg.get("text", "")
        if not suffix_text:
            return
        suffix_font = _get_font(cfg, suffix_cfg.get("font", el["font"]),
                                suffix_cfg.get("size", el["size"]))
        suffix_color = tuple(suffix_cfg.get("color", el.get("color", [255, 255, 255])))
        suffix_anchor = suffix_cfg.get("anchor", "lm")
        ox = suffix_cfg.get("offset_x", 0)
        oy = suffix_cfg.get("offset_y", 0)
        sx, sy = x + ox, y + oy
        suffix_kwargs = dict(
            font=suffix_font,
            fill=suffix_color,
            anchor=suffix_anchor,
        )
        # Measure the width of the main text to position the suffix right
        # after it (only relevant if offset_x is meant to be "after text").
        if suffix_cfg.get("attach_to_text", False):
            try:
                bbox = draw.textbbox((x, y), main_text, font=font,
                                      anchor=anchor,
                                      stroke_width=stroke_width)
                text_right = bbox[2]
                sx = text_right + ox
            except Exception:
                pass
        draw.text((sx, sy), suffix_text, **suffix_kwargs)


def generate_poster(
    values: Dict[str, Any],
    config_path: Union[str, Path] = "config.json",
) -> bytes:
    """Generate the poster as PNG bytes.

    `values` may contain any of:
        percent_24h, percent_7d, percent_30d  : number or string
        date_en                                : pre-formatted string OR ISO date
        date_fa                                : pre-formatted string OR ISO date
        date                                   : ISO date string applied to both
                                                 date_en and date_fa if those are
                                                 not explicitly provided.

    Missing fields are skipped (nothing drawn for them).
    """
    cfg = _load_config(config_path)

    # Normalize date inputs
    if "date" in values and values["date"] is not None:
        if "date_en" not in values or values.get("date_en") in (None, ""):
            values["date_en"] = values["date"]
        if "date_fa" not in values or values.get("date_fa") in (None, ""):
            values["date_fa"] = values["date"]

    # Format dates if ISO/raw date given
    date_en_raw = values.get("date_en")
    if isinstance(date_en_raw, str) and len(date_en_raw) <= 10 and \
       date_en_raw and "-" in date_en_raw:
        # Looks like an ISO date — format it
        values["date_en"] = format_english_date(date_en_raw)
    elif date_en_raw is None:
        # Default to today
        values["date_en"] = format_english_date()

    date_fa_raw = values.get("date_fa")
    if isinstance(date_fa_raw, str) and len(date_fa_raw) <= 10 and \
       date_fa_raw and "-" in date_fa_raw:
        values["date_fa"] = format_persian_date(date_fa_raw)
    elif date_fa_raw is None:
        values["date_fa"] = format_persian_date()

    # Load template
    img = Image.open(str(cfg["_template_path"])).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Draw each element
    for name in ("date_en", "date_fa",
                 "percent_24h", "percent_7d", "percent_30d"):
        if name not in values:
            continue
        v = values[name]
        if name.startswith("percent_"):
            el = cfg["elements"].get(name, {})
            text = _format_percent(v, el.get("text_template"))
        else:
            text = str(v)
        _draw_element(draw, cfg, name, text)

    # Export PNG
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_poster_to_file(
    values: Dict[str, Any],
    out_path: Union[str, Path],
    config_path: Union[str, Path] = "config.json",
) -> Path:
    """Generate the poster and write it to a file. Returns the file path."""
    data = generate_poster(values, config_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    return out_path


# ---------------------------------------------------------------------------
# CLI entrypoint — for quick testing without the FastAPI server.
# Usage:
#   python3 poster.py --out /tmp/test.png \
#       --p24 28 --p7 35 --p30 47 --date 2026-11-01
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Generate a JangSanj poster.")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--out", default="output/poster.png",
                    help="Output PNG path")
    ap.add_argument("--p24", default=None, help="24h percentage")
    ap.add_argument("--p7", default=None, help="7d percentage")
    ap.add_argument("--p30", default=None, help="30d percentage")
    ap.add_argument("--date-en", default=None,
                    help="English date string (or ISO YYYY-MM-DD)")
    ap.add_argument("--date-fa", default=None,
                    help="Persian date string (or ISO YYYY-MM-DD)")
    ap.add_argument("--date", default=None,
                    help="ISO date applied to both date_en and date_fa")
    args = ap.parse_args()

    values: Dict[str, Any] = {}
    if args.p24 is not None:
        values["percent_24h"] = args.p24
    if args.p7 is not None:
        values["percent_7d"] = args.p7
    if args.p30 is not None:
        values["percent_30d"] = args.p30
    if args.date_en is not None:
        values["date_en"] = args.date_en
    if args.date_fa is not None:
        values["date_fa"] = args.date_fa
    if args.date is not None:
        values["date"] = args.date

    out = generate_poster_to_file(values, args.out, args.config)
    print(f"Poster saved to: {out}")
    print(f"Size: {out.stat().st_size} bytes")
