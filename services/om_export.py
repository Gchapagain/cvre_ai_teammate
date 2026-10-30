"""Export the OM as PowerPoint (the master file) and PDF (converted from the PowerPoint by LibreOffice).

- The slides are drawn from the live OM state (services/om_engine.py): native text boxes, tables and
  shapes, letter landscape 11 x 8.5 in, Georgia headings, Arial body, footer "<Property> | <City, ST>"
  and page numbers. No animations. Our own design; no company logo is embedded.
- A draft export is always allowed: every slide carries the DRAFT mark and anything missing is a red
  MISSING box naming what is needed. A final export is allowed only when the OM is 100% approved.
- Numbers are shown exactly as the engine calculated them; nothing here calls the AI.
- Files go to om_exports/ (git-ignored) as <deal>_OM_v<n>_<draft|final>.pptx / .pdf and every export is
  logged in om_exports and om_events.
"""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from services import om_calc, om_engine, om_slots, om_template

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "om_exports"
SOFFICE_PLACES = ("/Applications/LibreOffice.app/Contents/MacOS/soffice", "/usr/bin/soffice", "/usr/local/bin/soffice")

GREEN, DARK, GOLD = RGBColor(0x1D, 0x3C, 0x2F), RGBColor(0x13, 0x27, 0x1E), RGBColor(0xC9, 0xA2, 0x27)
SAGE, INK, GREY = RGBColor(0x30, 0x65, 0x4F), RGBColor(0x22, 0x22, 0x22), RGBColor(0x6B, 0x6B, 0x6B)
LIGHT, WHITE, RED = RGBColor(0xF3, 0xF1, 0xEC), RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xB4, 0x23, 0x18)
PINK = RGBColor(0xFD, 0xEC, 0xEA)
HEAD, BODY = "Georgia", "Arial"
W, H = 11.0, 8.5          # inches
MARGIN = 0.6
RENT_ROLL_ROWS = 14       # rows per rent roll slide; more units continue on the next slide


class ExportError(Exception):
    """Something a person can act on, in plain words."""


# ---------- small drawing helpers ----------

def _box(slide, x, y, w, h, fill=None, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.shadow.inherit = False
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1.5)
    return shape


def _text(slide, x, y, w, h, paragraphs, size=12, font=BODY, color=INK, bold=False, align=PP_ALIGN.LEFT,
          anchor=MSO_ANCHOR.TOP, space=6):
    """A text box. paragraphs: a string or a list of strings / (text, {size, bold, color, font}) pairs."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = Inches(0.05)
    for i, item in enumerate([paragraphs] if isinstance(paragraphs, str) else paragraphs):
        text, opts = item if isinstance(item, tuple) else (item, {})
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.alignment = align
        para.space_after = Pt(opts.get("space", space))
        run = para.add_run()
        run.text = str(text)
        run.font.name = opts.get("font", font)
        run.font.size = Pt(opts.get("size", size))
        run.font.bold = opts.get("bold", bold)
        run.font.color.rgb = opts.get("color", color)
    return box


def _missing(slide, x, y, w, h, state):
    """A red box that says what is missing and what it needs. Only ever on a draft."""
    _box(slide, x, y, w, h, fill=PINK, line=RED)
    if h < 0.8:  # a small box (a table row): one line only, so nothing spills out
        _text(slide, x + 0.05, y, w - 0.1, h, f"MISSING · {state.slot.label}", size=9, color=RED, bold=True,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, space=0)
        return
    lines =[("MISSING", {"bold": True, "color": RED, "size": 13}), (state.slot.label, {"bold": True, "size": 11})]
    if state.needs:
        lines.append(("Needs: " + "; ".join(state.needs), {"size": 9, "color": GREY}))
    _text(slide, x + 0.1, y + 0.08, w - 0.2, h - 0.16, lines, size=10, color=RED, align=PP_ALIGN.CENTER,
          anchor=MSO_ANCHOR.MIDDLE, space=3)


def _picture(slide, path, x, y, w, h):
    """Place an image filling the frame, cropped in the centre (never stretched)."""
    with Image.open(path) as image:
        iw, ih = image.size
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    frame, ratio = w / h, iw / ih
    if ratio > frame:
        cut = (1 - frame / ratio) / 2
        pic.crop_left = pic.crop_right = cut
    elif ratio < frame:
        cut = (1 - ratio / frame) / 2
        pic.crop_top = pic.crop_bottom = cut
    return pic


def _asset_path(asset):
    path = Path(asset["file_path"])
    return path if path.is_absolute() else ROOT / path


def _photos(slide, state, x, y, w, h, cols=1, gap=0.15, show_missing=True):
    """The slot's photos in a grid; any photo still needed is a MISSING box (or left out when optional)."""
    count = max(state.slot.count, 1)
    rows = -(-count // cols)
    cw, ch = (w - gap * (cols - 1)) / cols, (h - gap * (rows - 1)) / rows
    photos = [a for a in state.photos if _asset_path(a).exists()]
    for i in range(count):
        cx, cy = x + (i % cols) * (cw + gap), y + (i // cols) * (ch + gap)
        if i < len(photos):
            _picture(slide, _asset_path(photos[i]), cx, cy, cw, ch)
            if photos[i].get("sample"):
                _text(slide, cx + 0.08, cy + ch - 0.35, 2.2, 0.3, "Sample illustration", size=8, color=WHITE, bold=True)
        elif show_missing and state.slot.required:
            _missing(slide, cx, cy, cw, ch, state)


def _title(slide, title, section=None):
    if section:
        _text(slide, MARGIN, 0.45, 6, 0.3, f"{section['number']}  {section['title'].upper()}", size=9, color=SAGE, bold=True)
    _text(slide, MARGIN, 0.7, W - 2 * MARGIN, 0.7, title, size=26, font=HEAD, color=GREEN)
    _box(slide, MARGIN, 1.42, 0.9, 0.05, fill=GOLD)


def _footer(slide, footer, number, dark=False):
    color = RGBColor(0xD8, 0xE2, 0xDC) if dark else GREY
    _text(slide, MARGIN, H - 0.5, 7, 0.3, footer, size=8, color=color)
    _text(slide, W - MARGIN - 1, H - 0.5, 1, 0.3, str(number), size=8, color=color, align=PP_ALIGN.RIGHT)


def _draft_mark(slide, text):
    band = _box(slide, W - 3.7, 0.12, 3.5, 0.3, fill=RED)
    band.text_frame.text = text
    para = band.text_frame.paragraphs[0]
    para.alignment = PP_ALIGN.CENTER
    para.runs[0].font.size, para.runs[0].font.bold = Pt(9), True
    para.runs[0].font.name, para.runs[0].font.color.rgb = BODY, WHITE


# ---------- values ----------

def _filled(state):
    return state is not None and state.status != "empty" and state.value not in (None, "", [])


def _show(state):
    """How a slot's value reads on a slide."""
    if state.calc is not None and state.calc.ready and state.source.get("kind") in ("calculated", "document_field"):
        return state.calc.display
    if (state.slot.validation or {}).get("kind") == "currency" and isinstance(state.value, (int, float)):
        return om_calc.money(state.value)
    return om_engine.display(state.value)


def _value_or_missing(slide, state, x, y, w, h, **text):
    if _filled(state):
        _text(slide, x, y, w, h, _show(state), **text)
    else:
        _missing(slide, x, y, w, h, state)


def _money_cell(value, label):
    if label.endswith("%"):
        return f"{value:.1f}%"
    if abs(value) < 0.5:
        return "-"
    return f"({om_calc.money(-value)})" if value < 0 else om_calc.money(value)


def _table(slide, x, y, w, header, rows, widths, size=9, bold_rows=(), align_right_from=1):
    shape = slide.shapes.add_table(len(rows) + 1, len(header), Inches(x), Inches(y), Inches(w), Inches(0.28 * (len(rows) + 1)))
    table = shape.table
    for i, part in enumerate(widths):
        table.columns[i].width = Inches(w * part)
    for r, row in enumerate([header] + rows):
        table.rows[r].height = Inches(0.28)
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.fill.solid()
            cell.fill.fore_color.rgb = GREEN if r == 0 else (LIGHT if r % 2 == 0 else WHITE)
            cell.text = "" if value is None else str(value)
            para = cell.text_frame.paragraphs[0]
            para.alignment = PP_ALIGN.RIGHT if c >= align_right_from else PP_ALIGN.LEFT
            font = para.runs[0].font if para.runs else para.font
            font.size, font.name = Pt(size), BODY
            font.bold = r == 0 or (r - 1) in bold_rows
            font.color.rgb = WHITE if r == 0 else INK
    return shape


# ---------- one function per layout ----------

def _cover(slide, ctx, slide_def):
    s = ctx["slots"]
    _box(slide, 0, 0, 4.6, H, fill=GREEN)
    _box(slide, 0.6, 1.2, 0.9, 0.05, fill=GOLD)
    _text(slide, 0.6, 0.6, 3.6, 0.5, om_template.boilerplate()["cover_title"].upper(), size=10, color=GOLD, bold=True)
    if _filled(s["property.name"]):
        _text(slide, 0.6, 1.5, 3.6, 2.4, _show(s["property.name"]), size=30, font=HEAD, color=WHITE)
    else:
        _missing(slide, 0.6, 1.5, 3.6, 1.6, s["property.name"])
    for slot_id, top in (("property.address", 4.3), ("property.city_state", 4.9)):
        if _filled(s[slot_id]):
            _text(slide, 0.6, top, 3.6, 0.5, _show(s[slot_id]), size=14, color=WHITE)
        else:
            _missing(slide, 0.6, top, 3.6, 0.5, s[slot_id])
    broker = (ctx["facts"].get("profile") or {}).get("full_name")
    if broker:
        _text(slide, 0.6, H - 1.3, 3.6, 0.6, [("Offered by", {"size": 9, "color": GOLD, "bold": True}), broker],
              size=12, color=WHITE, space=2)
    _photos(slide, s["photo.hero"], 4.6, 0, W - 4.6, H)


def _boilerplate(slide, ctx, slide_def):
    _title(slide, slide_def.title)
    paragraphs = om_template.boilerplate()["disclosures"]
    _text(slide, MARGIN, 1.75, W - 2 * MARGIN, H - 2.5, paragraphs, size=10.5, color=INK, space=10)


def _contents(slide, ctx, slide_def):
    _title(slide, slide_def.title)
    for i, section in enumerate(ctx["template"].sections):
        y = 2.0 + i * 0.95
        _text(slide, MARGIN, y, 1.2, 0.8, section["number"], size=34, font=HEAD, color=GOLD)
        _text(slide, MARGIN + 1.3, y + 0.18, 6, 0.6, section["title"], size=20, font=HEAD, color=GREEN)
    _box(slide, W - 3.6, 1.75, 3.0, H - 2.6, fill=GREEN)


def _divider(slide, ctx, slide_def):
    section = ctx["template"].section(slide_def.section)
    photo = ctx["slots"][slide_def.slots[0]]
    _box(slide, 0, 0, W, H, fill=GREEN)
    if photo.photos:
        _photos(slide, photo, W / 2, 0, W / 2, H, show_missing=False)
    _text(slide, 0.9, 2.6, 4.5, 1.4, section["number"], size=72, font=HEAD, color=GOLD)
    _text(slide, 0.9, 4.1, 4.5, 1.4, section["title"], size=34, font=HEAD, color=WHITE)


def _narrative_photo(slide, ctx, slide_def):
    _title(slide, slide_def.title, ctx["template"].section(slide_def.section))
    text, photo = (ctx["slots"][i] for i in slide_def.slots)
    _value_or_missing(slide, text, MARGIN, 1.8, 5.2, 4.8, size=13, space=10)
    _photos(slide, photo, 6.2, 1.8, W - 6.2 - MARGIN, 5.6)


def _bullets_photo(slide, ctx, slide_def):
    _title(slide, slide_def.title, ctx["template"].section(slide_def.section))
    *groups, photo = (ctx["slots"][i] for i in slide_def.slots)
    y = 1.75
    for group in groups:
        heading = group.slot.label.split(": ", 1)[-1].upper()
        _text(slide, MARGIN, y, 5.4, 0.3, heading, size=10, color=SAGE, bold=True)
        if _filled(group):
            items = group.value if isinstance(group.value, list) else [group.value]
            _text(slide, MARGIN, y + 0.3, 5.4, 1.5, [f"•  {item}" for item in items], size=11, space=4)
        else:
            _missing(slide, MARGIN, y + 0.35, 5.4, 1.2, group)
        y += 1.85
    _photos(slide, photo, 6.4, 1.75, W - 6.4 - MARGIN, 5.6)


def _features_photo(slide, ctx, slide_def):
    _title(slide, slide_def.title, ctx["template"].section(slide_def.section))
    *fields, photo = (ctx["slots"][i] for i in slide_def.slots)
    y = 1.8
    for field in fields:
        if not field.slot.required and not _filled(field):
            continue  # optional and unknown: left off the slide
        _text(slide, MARGIN, y, 2.4, 0.4, field.slot.label, size=10, color=GREY, bold=True)
        _value_or_missing(slide, field, MARGIN + 2.5, y, 3.3, 0.38, size=11)
        _box(slide, MARGIN, y + 0.42, 5.8, 0.01, fill=RGBColor(0xDD, 0xDD, 0xDD))
        y += 0.47
    _photos(slide, photo, 6.8, 1.8, W - 6.8 - MARGIN, 5.6)


def _full_photo(slide, ctx, slide_def):
    _title(slide, slide_def.title, ctx["template"].section(slide_def.section))
    _photos(slide, ctx["slots"][slide_def.slots[0]], MARGIN, 1.75, W - 2 * MARGIN, H - 2.45)


def _photo_grid(slide, ctx, slide_def):
    _title(slide, slide_def.title, ctx["template"].section(slide_def.section))
    _photos(slide, ctx["slots"][slide_def.slots[0]], MARGIN, 1.75, W - 2 * MARGIN, H - 2.45, cols=2)


def _kpi_tiles(slide, ctx, slide_def):
    _title(slide, slide_def.title, ctx["template"].section(slide_def.section))
    *tiles, photo = (ctx["slots"][i] for i in slide_def.slots)
    for i, tile in enumerate(tiles):
        x, y = MARGIN + (i % 2) * 2.95, 1.9 + (i // 2) * 2.6
        if _filled(tile):
            _box(slide, x, y, 2.75, 2.35, fill=GREEN)
            _text(slide, x + 0.15, y + 0.45, 2.45, 0.9, _show(tile), size=24, font=HEAD, color=WHITE, align=PP_ALIGN.CENTER)
            _text(slide, x + 0.15, y + 1.4, 2.45, 0.6, tile.slot.label.upper(), size=9, color=GOLD, bold=True,
                  align=PP_ALIGN.CENTER)
        else:
            _missing(slide, x, y, 2.75, 2.35, tile)
    if photo.photos:  # optional: without one the right side stays empty
        _photos(slide, photo, 6.7, 1.9, W - 6.7 - MARGIN, 4.95, show_missing=False)


def _financial_table(slide, ctx, slide_def):
    _title(slide, slide_def.title, ctx["template"].section(slide_def.section))
    flow, note = (ctx["slots"][i] for i in slide_def.slots)
    if _filled(flow) and flow.calc is not None and flow.calc.ready:
        rows = [[label] + [_money_cell(v, label) for v in values] for label, values in flow.calc.value]
        bold = [i for i, (label, _) in enumerate(flow.calc.value)
                if label in ("Effective gross income", "Total expenses", "Net operating income")]
        header = ["", "In-place"] + [f"Year {n}" for n in range(1, om_calc.YEARS + 1)]
        _table(slide, MARGIN, 1.75, W - 2 * MARGIN, header, rows, [0.28] + [0.12] * 6, size=8.5, bold_rows=bold)
    else:
        _missing(slide, MARGIN, 1.75, W - 2 * MARGIN, 3.6, flow)
    _value_or_missing(slide, note, MARGIN, H - 1.45, W - 2 * MARGIN, 0.8, size=9, color=GREY)


def _rent_roll_table(slide, ctx, slide_def, rows=None):
    _title(slide, slide_def.title + (" (continued)" if rows and rows[0] != ctx["rent_roll_first"] else ""),
           ctx["template"].section(slide_def.section))
    roll, note = (ctx["slots"][i] for i in slide_def.slots)
    if not _filled(roll) or rows is None:
        _missing(slide, MARGIN, 1.75, W - 2 * MARGIN, 3.6, roll)
        return
    header = ["Unit", "Tenant", "SF", "Lease start", "Lease end", "Annual rent", "Rent / SF", "Type"]
    body = [[r["unit"], r["tenant"], f"{r['sf']:,.0f}" if isinstance(r["sf"], (int, float)) else r["sf"],
             r["start"] or "", r["end"] or "",
             om_calc.money(r["annual_rent"]) if isinstance(r["annual_rent"], (int, float)) else "",
             om_calc.money(r["rent_psf"], True) if isinstance(r["rent_psf"], (int, float)) else "", r["lease_type"] or ""]
            for r in rows]
    _table(slide, MARGIN, 1.75, W - 2 * MARGIN, header, body, [0.07, 0.27, 0.09, 0.12, 0.12, 0.13, 0.1, 0.1],
           size=8.5, align_right_from=2)
    if _filled(note):
        _text(slide, MARGIN, H - 1.2, W - 2 * MARGIN, 0.6, _show(note), size=8, color=GREY)


def _contacts(slide, ctx, slide_def):
    contacts, notice = (ctx["slots"][i] for i in slide_def.slots)
    _box(slide, 0, 0, W, H, fill=GREEN)
    _text(slide, MARGIN + 0.3, 1.0, 8, 0.8, slide_def.title, size=30, font=HEAD, color=WHITE)
    _box(slide, MARGIN + 0.3, 1.8, 0.9, 0.05, fill=GOLD)
    if _filled(contacts):
        y = 2.3
        for person in contacts.value:
            _text(slide, MARGIN + 0.3, y, 6, 1.4, [(person["name"], {"size": 18, "font": HEAD, "bold": False}),
                                                   (person["title"], {"size": 11, "color": GOLD}),
                                                   person["phone"], person["email"]], size=11, color=WHITE, space=3)
            y += 1.6
    else:
        _missing(slide, MARGIN + 0.3, 2.3, 5, 1.3, contacts)
    _text(slide, MARGIN + 0.3, H - 1.8, W - 2 * MARGIN - 0.6, 0.8, notice.display, size=9,
          color=RGBColor(0xD8, 0xE2, 0xDC))


LAYOUTS = {"cover": _cover, "boilerplate": _boilerplate, "contents": _contents, "divider": _divider,
           "narrative_photo": _narrative_photo, "bullets_photo": _bullets_photo, "features_photo": _features_photo,
           "full_photo": _full_photo, "photo_grid": _photo_grid, "kpi_tiles": _kpi_tiles,
           "financial_table": _financial_table, "rent_roll_table": _rent_roll_table, "contacts": _contacts}
DARK_LAYOUTS = {"cover", "divider", "contacts"}


# ---------- building the file ----------

def footer_text(state):
    parts = [_show(state.slots[i]) for i in ("property.name", "property.city_state") if _filled(state.slots.get(i))]
    return " | ".join(parts)


def _pages(state):
    """(slide definition, extra) per page; a long rent roll continues over several pages."""
    pages = []
    for _, slide_def in state.slides:
        if slide_def.layout == "rent_roll_table":
            roll = state.slots[slide_def.slots[0]]
            rows = roll.calc.value if roll.calc is not None and roll.calc.ready and _filled(roll) else None
            chunks = [rows[i:i + RENT_ROLL_ROWS] for i in range(0, len(rows), RENT_ROLL_ROWS)] if rows else [None]
            pages += [(slide_def, chunk) for chunk in chunks]
        else:
            pages.append((slide_def, None))
    return pages


def build_pptx(state, facts, kind, out_path):
    """Write the PowerPoint for this OM state. kind: 'draft' (DRAFT mark, MISSING boxes) or 'final'."""
    if kind == "final":
        problems = final_blockers(state)
        if problems:
            raise ExportError("The client-ready export unlocks at 100% approved. Still to do: " + "; ".join(problems[:5])
                              + (f" and {len(problems) - 5} more" if len(problems) > 5 else "") + ".")
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(W), Inches(H)
    blank = deck.slide_layouts[6]
    roll = state.slots.get("tenant.rent_roll")
    ctx = {"slots": state.slots, "facts": facts, "template": state.template,
           "rent_roll_first": roll.calc.value[0] if roll and roll.calc is not None and roll.calc.ready else None}
    footer, mark = footer_text(state), om_template.boilerplate()["draft_mark"]
    for number, (slide_def, extra) in enumerate(_pages(state), start=1):
        slide = deck.slides.add_slide(blank)
        if slide_def.layout == "rent_roll_table":
            _rent_roll_table(slide, ctx, slide_def, extra)
        else:
            LAYOUTS[slide_def.layout](slide, ctx, slide_def)
        if number > 1:
            _footer(slide, footer, number, dark=slide_def.layout in DARK_LAYOUTS)
        if kind == "draft":
            _draft_mark(slide, mark)
    deck.core_properties.title = f"Offering Memorandum - {footer}" if footer else "Offering Memorandum"
    deck.core_properties.author = (facts.get("profile") or {}).get("full_name") or "Broker"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(out_path)
    return len(deck.slides)


def final_blockers(state):
    """Why a final export is not allowed yet (empty list when it is)."""
    blockers = [f"{s.slot.label} is missing" for s in state.counted if s.status == "empty"]
    blockers += [f"{s.slot.label} needs your approval" for s in state.counted if s.status in om_engine.FILLED]
    return blockers


# ---------- PDF and previews ----------

def soffice_path():
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return found or next((p for p in SOFFICE_PLACES if Path(p).exists()), None)


def to_pdf(pptx_path, timeout=180):
    """Convert the PowerPoint to PDF with LibreOffice (headless). Returns the PDF path."""
    soffice = soffice_path()
    if not soffice:
        raise ExportError("PDF needs LibreOffice, which is not installed here. The PowerPoint is ready to download.")
    with tempfile.TemporaryDirectory() as profile:
        # A private LibreOffice profile, so a copy the person has open never blocks the conversion.
        command = [soffice, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
                   "--outdir", str(pptx_path.parent), str(pptx_path)]
        try:
            subprocess.run(command, capture_output=True, timeout=timeout, check=True)
        except (subprocess.SubprocessError, OSError) as error:
            raise ExportError("LibreOffice could not convert the PowerPoint to PDF. The PowerPoint is ready to download.") from error
    pdf = pptx_path.with_suffix(".pdf")
    if not pdf.exists():
        raise ExportError("LibreOffice did not produce a PDF. The PowerPoint is ready to download.")
    return pdf


def page_images(pdf_path, zoom=1.0):
    """PNG previews of each PDF page, cached by the file's hash so a page is drawn once."""
    import pymupdf as fitz

    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()[:16]
    folder = EXPORT_DIR / "previews" / f"{digest}_{zoom:g}"
    if folder.exists():
        cached = sorted(folder.glob("page-*.png"))
        if cached:
            return cached
    folder.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as pdf:
        for i, page in enumerate(pdf, start=1):
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(folder / f"page-{i:02d}.png")
    return sorted(folder.glob("page-*.png"))


# ---------- the export a person asks for ----------

def file_stem(deal_name, version, kind):
    name = re.sub(r"[^A-Za-z0-9]+", "_", deal_name or "Deal").strip("_")
    return f"{name}_OM_v{version}_{kind}"


def _next_version(conn, deal_id):
    row = conn.execute("SELECT MAX(version) FROM om_exports WHERE deal_id = ?", (deal_id,)).fetchone()
    return (row[0] or 0) + 1


def export(deal_id, facts, kind, user, want_pdf=True, db_path=None, out_dir=None):
    """Build the PowerPoint (and the PDF from it), log both, and return what was made.

    Returns {"version", "pptx", "pdf" (or None), "pdf_error" (or None), "slides", "completion"}.
    """
    if kind not in ("draft", "final"):
        raise ValueError("kind is 'draft' or 'final'")
    state = om_engine.build(facts)
    conn = om_slots._connect(db_path)
    try:
        version = _next_version(conn, deal_id)
        folder = Path(out_dir or EXPORT_DIR) / f"deal_{deal_id}"
        pptx_path = folder / f"{file_stem((facts.get('deal') or {}).get('name'), version, kind)}.pptx"
        slides = build_pptx(state, facts, kind, pptx_path)
        pdf_path, pdf_error = None, None
        if want_pdf:
            try:
                pdf_path = to_pdf(pptx_path)
            except ExportError as error:
                pdf_error = str(error)
        unapproved = json.dumps([s.slot.id for s in state.counted if not s.approved])
        with conn:
            for fmt, path in (("pptx", pptx_path), ("pdf", pdf_path)):
                if path:
                    conn.execute("INSERT INTO om_exports (deal_id, version, kind, format, completion, unapproved, created_by, "
                                 "file_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                 (deal_id, version, kind, fmt, state.percent, unapproved, user, str(path)))
            om_slots.log(conn, deal_id, "export", f"v{version} {kind} ({state.percent}% approved)", user)
    finally:
        conn.close()
    return {"version": version, "kind_label": "client-ready" if kind == "final" else "draft", "pptx": pptx_path,
            "pdf": pdf_path, "pdf_error": pdf_error, "slides": slides, "completion": state.percent}
