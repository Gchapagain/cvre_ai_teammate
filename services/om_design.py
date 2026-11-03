"""The "Editorial" OM design: how each slide of templates/om_v2_editorial.json is drawn in PowerPoint.

Our own design, made for this app (no reference document was used). US Letter landscape, 0.6 in margins, a
12-column grid, left-aligned text and one focal point per slide. Two typefaces (Georgia for titles, numerals and
facts; Arial for body) and six colours (PALETTE). Signature details: a slim gold rule down the left of content
slides with the section name along it, an italic section label over a hairline, the page number in a small gold
circle, photos in a white mat with an italic caption, a facts strip of large numerals, Roman section numbers.

Everything on a slide is a native PowerPoint object: text boxes, tables and vector shapes. Photos appear only
where the broker placed them, always whole unless the broker chose Fill. Nothing is ever shrunk below the type
scale: text that would not fit is reported by too_long() (and blocks a client-ready export). No AI is used here.
"""

import re
from datetime import date
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from services import om_assets, om_calc, om_engine, om_template

ROOT = Path(__file__).resolve().parent.parent
PALETTE = {"paper": "FBFAF7", "forest": "1D3C2F", "gold": "C9A227", "stone": "E7E3DA", "ink": "2E2E2C", "muted": "6B6B66"}
PAPER, FOREST, GOLD, STONE, INK, MUTED = (RGBColor.from_string(PALETTE[k]) for k in
                                          ("paper", "forest", "gold", "stone", "ink", "muted"))
WHITE = RGBColor(0xFF, 0xFF, 0xFF)  # the mat around a photo and white type on the forest panels
HEAD, BODY = "Georgia", "Arial"
# The type scale, in points. Text is never set smaller than these.
SIZE = {"cover": 40, "title": 27, "lede": 14, "body": 12, "small_body": 11.5, "table": 10, "dense": 9, "caption": 9, "footer": 8}

W, H = 11.0, 8.5
M = 0.6                          # page margin
X0, X1 = 1.0, W - M              # content columns (the gold rule and section name sit in the left margin)
COLS, GUT = 12, 0.2
COL = (X1 - X0 - GUT * (COLS - 1)) / COLS
Y0, Y1 = 1.85, 7.6               # content top and bottom on a content slide
MAT, CAPTION = 0.08, 0.3         # white border inside a mat; room for the caption line under it
RENT_ROLL_ROWS = 14              # rows per rent roll page; more units continue on the next, header repeated
DENSE_ROWS = 13                  # a financial table with more rows than this is set at 9 pt


def gx(col):
    """Left edge of a grid column (0-11)."""
    return X0 + col * (COL + GUT)


def gw(span):
    """Width of `span` grid columns."""
    return span * COL + (span - 1) * GUT


# ---------- drawing helpers ----------

def _plain(shape):
    """Drop PowerPoint's default shape style (its theme shadow and outline): only what we set is drawn."""
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    return shape


def _rect(slide, x, y, w, h, fill=None, line=None, width=0.75, dash=False, shape=MSO_SHAPE.RECTANGLE):
    box = _plain(slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h)))
    if fill is None:
        box.fill.background()
    else:
        box.fill.solid()
        box.fill.fore_color.rgb = fill
    if line is None:
        box.line.fill.background()
    else:
        box.line.color.rgb = line
        box.line.width = Pt(width)
        if dash:
            box.line.dash_style = MSO_LINE.DASH
    return box


def _rule(slide, x, y, w, h=0.0, color=STONE, width=0.75):
    """A hairline: horizontal when h is 0, vertical when w is 0."""
    line = _plain(slide.shapes.add_connector(1, Inches(x), Inches(y), Inches(x + w), Inches(y + h)))
    line.line.color.rgb = color
    line.line.width = Pt(width)
    return line


def _style(run, font=BODY, size=None, color=INK, bold=False, italic=False):
    run.font.name = font
    run.font.size = Pt(size or SIZE["body"])
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color


def _bullet(paragraph, char="•", indent=0.18):
    """A real bullet glyph (not typed into the text), hanging so wrapped lines align."""
    p_pr = paragraph._p.get_or_add_pPr()
    p_pr.set("marL", str(int(Inches(indent))))
    p_pr.set("indent", str(-int(Inches(indent))))
    for tag in ("a:buClr", "a:buFont", "a:buChar", "a:buNone"):
        for old in p_pr.findall(qn(tag)):
            p_pr.remove(old)
    colour = etree.SubElement(p_pr, qn("a:buClr"))
    etree.SubElement(colour, qn("a:srgbClr")).set("val", PALETTE["gold"])
    etree.SubElement(p_pr, qn("a:buFont")).set("typeface", BODY)
    etree.SubElement(p_pr, qn("a:buChar")).set("char", char)


def text(slide, x, y, w, h, paras, anchor=MSO_ANCHOR.TOP, align=PP_ALIGN.LEFT, spacing=1.2):
    """A native text box. paras: a list of paragraphs; each is a list of (text, style) runs, or a dict with
    "runs" and optional "bullet", "after" (points), "align". Margins are zero so text sits on the grid."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    for i, para in enumerate(paras):
        spec = para if isinstance(para, dict) else {"runs": para}
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.alignment = spec.get("align", align)
        p.line_spacing = spec.get("spacing", spacing)
        p.space_after = Pt(spec.get("after", 0))
        if spec.get("bullet"):
            _bullet(p)
        for run_text, style in spec["runs"]:
            run = p.add_run()
            run.text = str(run_text)
            _style(run, **style)
    return box


def one(value, **style):
    """One paragraph of one run."""
    return [[(value, style)]]


# ---------- fitting text (never shrink: report instead) ----------

WIDTH_FACTOR = {HEAD: 0.52, BODY: 0.53}   # average character width as a share of the point size


def lines_needed(value, width_in, size, font=BODY):
    per_line = max(1, int(width_in * 72 / (size * WIDTH_FACTOR[font])))
    lines = 0
    for paragraph in str(value).split("\n"):
        words, line = paragraph.split(), 0
        current = 0
        for word in words:  # wrap by whole words, the way PowerPoint does
            extra = len(word) + (1 if current else 0)
            if current + extra > per_line:
                line, current = line + 1, len(word)
            else:
                current += extra
        lines += line + 1
    return lines


def height_needed(paragraphs, width_in, size, font=BODY, spacing=1.2, after=0):
    lines = sum(lines_needed(p, width_in, size, font) for p in paragraphs)
    return lines * size * spacing / 72 + after * max(0, len(paragraphs) - 1) / 72


def _sentences(value):
    """(lede, rest): the first sentence is the lede; the rest is body text."""
    parts = re.split(r"(?<=[.!?])\s+", str(value).strip(), maxsplit=1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


# Where long text lives: slot id -> (width, height, how it is set). Used by too_long() and by the layouts.
NARRATIVE_BOX = (gw(6), Y1 - Y0)
OFFERING_BOX = (gw(7), 3.3)
HIGHLIGHT_COLUMN = (gw(4), 2.35)
COVER_TITLE_LINES = 5


def _narrative_fits(value, box):
    lede, rest = _sentences(value)
    used = height_needed([lede], box[0], SIZE["lede"], spacing=1.25) + 0.12
    used += height_needed([p for p in rest.split("\n") if p.strip()] or [], box[0], SIZE["body"], spacing=1.3, after=6)
    return used <= box[1]


def too_long(state):
    """[(slot id, plain message)] for text that would not fit its place at the set type size."""
    problems = []
    for slot_id, box in (("offering.narrative", OFFERING_BOX), ("location.narrative", NARRATIVE_BOX)):
        item = state.slots.get(slot_id)
        if _filled(item) and not _narrative_fits(_show(item), box):
            problems.append((slot_id, f"{item.slot.label} is too long for its slide; shorten it to about "
                                      f"{_words_that_fit(box)} words."))
    for slot_id in ("highlights.upside", "highlights.location_building", "highlights.rare"):
        item = state.slots.get(slot_id)
        if not _filled(item):
            continue
        bullets = item.value if isinstance(item.value, list) else [item.value]
        if height_needed(bullets, HIGHLIGHT_COLUMN[0] - 0.18, SIZE["small_body"], spacing=1.2, after=5) > HIGHLIGHT_COLUMN[1]:
            problems.append((slot_id, f"{item.slot.label} is too long for its column; keep it to 3 short points."))
    name = state.slots.get("property.name")
    if _filled(name) and lines_needed(_show(name), 3.3, SIZE["cover"], HEAD) > COVER_TITLE_LINES:
        problems.append(("property.name", "The property name is too long for the cover title; a shorter marketing "
                                          "name would fit (about 60 characters)."))
    return problems


def _words_that_fit(box):
    lines = int(box[1] * 72 / (SIZE["body"] * 1.3)) - 2
    return max(20, lines * int(box[0] * 72 / (SIZE["body"] * WIDTH_FACTOR[BODY])) // 6)


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


def money_cell(value, label):
    if label.endswith("%"):
        return f"{value:.1f}%"
    if abs(value) < 0.5:
        return "-"
    return f"({om_calc.money(-value)})" if value < 0 else om_calc.money(value)


def footer_text(state):
    parts = [_show(state.slots[i]) for i in ("property.name", "property.city_state") if _filled(state.slots.get(i))]
    return " | ".join(parts)


# ---------- the signature details ----------

def _section(ctx, slide_def):
    return ctx["template"].section(slide_def.section)


def _header(slide, ctx, slide_def, title=None):
    """Gold rule with the section name along it, an italic section label over a hairline, and the slide title."""
    section = _section(ctx, slide_def)
    _rect(slide, M, M, 0.035, H - 2 * M, fill=GOLD)
    length = H - 2 * M - 1.2
    name = slide.shapes.add_textbox(Inches(M + 0.17 - length / 2), Inches(H / 2 - 0.11), Inches(length), Inches(0.22))
    name.rotation = 270
    frame = name.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.word_wrap = False
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    _style(p.add_run(), font=HEAD, size=SIZE["caption"], color=GOLD, italic=True)
    p.runs[0].text = section["title"]
    text(slide, X0, 0.55, gw(8), 0.26, [[(section["number"] + "    ", {"font": HEAD, "size": 10.5, "color": GOLD, "italic": True}),
                                         (section["title"], {"size": 10.5, "color": MUTED, "italic": True})]])
    _rule(slide, X0, 0.88, X1 - X0)
    text(slide, X0, 1.0, X1 - X0, 0.6, one(title or slide_def.title, font=HEAD, size=SIZE["title"], color=FOREST),
         anchor=MSO_ANCHOR.TOP)


def _footer(slide, footer, number, dark=False):
    colour = STONE if dark else MUTED
    if footer:
        text(slide, X0 if not dark else 1.0, H - 0.5, 6.5, 0.2, one(footer, size=SIZE["footer"], color=colour))
    circle = _rect(slide, X1 - 0.32, H - 0.6, 0.32, 0.32, fill=GOLD, shape=MSO_SHAPE.OVAL)
    frame = circle.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = str(number)
    _style(run, size=SIZE["footer"], color=FOREST, bold=True)


def _draft_tag(slide, mark):
    tag = _rect(slide, X1 - 2.1, 0.2, 2.1, 0.24, fill=GOLD)
    frame = tag.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = mark
    _style(run, size=SIZE["footer"], color=FOREST, bold=True)


def _placeholder(slide, ctx, x, y, w, h, label, dark=False):
    """An empty slot on a draft: a dashed muted outline and a short label. Nothing at all on a client-ready export."""
    if not ctx["draft"]:
        return
    _rect(slide, x, y, w, h, line=STONE if dark else MUTED, width=0.75, dash=True)
    text(slide, x + 0.1, y, w - 0.2, h, one(label, size=SIZE["caption"] + 1, color=STONE if dark else MUTED, italic=True),
         anchor=MSO_ANCHOR.MIDDLE, align=PP_ALIGN.CENTER)


def _photo_label(slot):
    words = {"aerial": "aerial", "exterior": "exterior", "interior": "interior", "site_plan": "site plan", "map": "map"}
    return "Add photo: " + " or ".join(words[k] for k in slot.photo_kinds)


def _asset_path(asset):
    path = Path(asset["file_path"])
    return path if path.is_absolute() else ROOT / path


def caption_for(asset, slot):
    """The photo's one-line caption: the broker's caption, or the slot's name when it is only a file name."""
    caption = (asset.get("caption") or "").strip()
    if not caption or re.fullmatch(r"(photo|img|image|dsc|camera-photo|front|sample)?[_ -]?\d*", caption, re.I):
        caption = slot.label
    return caption + (" (sample illustration)" if asset.get("sample") and "sample" not in caption.lower() else "")


def mat(slide, asset, slot, x, y, w, h, valign="top", halign="left", dark=False):
    """A photo in a mat: white border, stone hairline, whole photo (or cropped only if the broker chose Fill),
    and a one-line italic caption under it. Returns the mat's (x, y, w, h)."""
    path = _asset_path(asset)
    with Image.open(path) as image:
        size = image.size
    pad, room = MAT, (x, y, w, h - CAPTION)
    if (asset.get("fit") or "whole") == "fill":
        mx, my, mw, mh = room
    else:
        px, py, pw, ph = om_assets.fitted(size, (room[0] + pad, room[1] + pad, room[2] - 2 * pad, room[3] - 2 * pad))
        mw, mh = pw + 2 * pad, ph + 2 * pad
        mx = {"left": x, "center": x + (w - mw) / 2, "right": x + w - mw}[halign]
        my = {"top": y, "middle": y + (h - CAPTION - mh) / 2, "bottom": y + h - CAPTION - mh}[valign]
    _rect(slide, mx, my, mw, mh, fill=WHITE, line=STONE, width=0.75)
    ix, iy, iw, ih = mx + pad, my + pad, mw - 2 * pad, mh - 2 * pad
    picture = slide.shapes.add_picture(str(path), Inches(ix), Inches(iy), Inches(iw), Inches(ih))
    if (asset.get("fit") or "whole") == "fill":
        frame, ratio = iw / ih, size[0] / size[1]
        if ratio > frame:
            picture.crop_left = picture.crop_right = (1 - frame / ratio) / 2
        elif ratio < frame:
            picture.crop_top = picture.crop_bottom = (1 - ratio / frame) / 2
    caption = caption_for(asset, slot)
    text(slide, mx, my + mh + 0.07, max(mw, 2.0), 0.2,
         one(_clip(caption, max(mw, 2.0), SIZE["caption"]), size=SIZE["caption"], italic=True, color=STONE if dark else MUTED))
    return mx, my, mw, mh


def _clip(value, width_in, size):
    """One caption line: cut at a word with an ellipsis if it is longer than the line."""
    room = int(width_in * 72 / (size * WIDTH_FACTOR[BODY]))
    if len(value) <= room:
        return value
    return value[:room - 1].rsplit(" ", 1)[0] + "…"


def photos_of(state):
    return [a for a in state.photos if _asset_path(a).exists()]


def photo_or_placeholder(slide, ctx, state, x, y, w, h, valign="top", halign="left", dark=False):
    """The slot's first photo in a mat, or (draft only) a dashed placeholder. Optional and empty: nothing."""
    found = photos_of(state)
    if found:
        return mat(slide, found[0], state.slot, x, y, w, h, valign, halign, dark)
    if state.slot.required:
        _placeholder(slide, ctx, x, y, w, h - CAPTION, _photo_label(state.slot), dark)
    return None


def _what_to_add(state, prefix="Add"):
    """'Add: Land size' for something a person gives; 'Needs: a rent roll' for something calculated."""
    if state.slot.auto and state.needs:
        return "Needs: " + state.needs[0]
    return f"{prefix}: {state.slot.label}"


def _missing_text(slide, ctx, state, x, y, w, h, dark=False):
    _placeholder(slide, ctx, x, y, w, h, _what_to_add(state, "Add text"), dark)


# ---------- layouts ----------

def _cover(slide, ctx, slide_def):
    s, facts = ctx["slots"], ctx["facts"]
    panel = W * 0.4
    _rect(slide, 0, 0, panel, H, fill=FOREST)
    _rect(slide, panel, 0, W - panel, H, fill=STONE)
    left, width = M, panel - 2 * M + 0.1
    text(slide, left, 0.7, width, 0.3, one(om_template.boilerplate()["cover_title"], font=HEAD, size=12, color=GOLD, italic=True))
    _rect(slide, left, 1.12, 0.55, 0.03, fill=GOLD)
    title_top, name = 1.35, s["property.name"]
    if _filled(name):
        lines = min(lines_needed(_show(name), width, SIZE["cover"], HEAD), COVER_TITLE_LINES)
        title_h = lines * SIZE["cover"] * 1.08 / 72
        text(slide, left, title_top, width, title_h + 0.1, one(_show(name), font=HEAD, size=SIZE["cover"], color=WHITE), spacing=1.0)
    else:
        title_h = 1.2
        _missing_text(slide, ctx, name, left, title_top, width, title_h, dark=True)
    y = title_top + title_h + 0.35
    for slot_id in ("property.address", "property.city_state"):
        if _filled(s[slot_id]):
            high = height_needed([_show(s[slot_id])], width, SIZE["lede"], spacing=1.15)
            text(slide, left, y, width, high + 0.05, one(_show(s[slot_id]), size=SIZE["lede"], color=WHITE), spacing=1.15)
            y += high + 0.1
        else:
            _missing_text(slide, ctx, s[slot_id], left, y, width, 0.3, dark=True)
            y += 0.4
    broker = (facts.get("profile") or {}).get("full_name")
    lines = [[(date.today().strftime("%B %Y"), {"size": SIZE["small_body"], "color": STONE})]]
    if broker:
        lines.append({"runs": [("Prepared by ", {"size": SIZE["small_body"], "color": STONE, "italic": True}),
                               (broker, {"size": SIZE["small_body"], "color": WHITE})]})
    text(slide, left, H - 1.55, width, 0.6, lines)
    logo = facts.get("logo")
    if logo and Path(logo).exists():
        with Image.open(logo) as image:
            ratio = image.width / image.height
        lw = min(2.0, 0.55 * ratio)
        slide.shapes.add_picture(str(logo), Inches(left), Inches(H - 0.95), Inches(lw), Inches(lw / ratio))
    photo_or_placeholder(slide, ctx, s["photo.hero"], panel + M, M, W - panel - 2 * M, H - 2 * M,
                         valign="middle", halign="center")


def _legal(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    words = om_template.boilerplate()
    text(slide, X0, Y0, X1 - X0, 0.3, one(words["legal_notice"], size=SIZE["small_body"], color=FOREST, italic=True, bold=True))
    paragraphs = words["legal"]
    half = (len(paragraphs) + 1) // 2
    for col, chunk in ((0, paragraphs[:half]), (6, paragraphs[half:])):
        text(slide, gx(col), Y0 + 0.5, gw(6), Y1 - Y0 - 0.5,
             [{"runs": [(p, {"size": SIZE["small_body"]})], "after": 9} for p in chunk], spacing=1.3)


def _contents(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    sections, pages = ctx["template"].sections, ctx["section_pages"]
    step = (Y1 - Y0 - 0.3) / len(sections)
    first, last = Y0 + 0.28, Y0 + 0.28 + step * (len(sections) - 1)
    _rule(slide, X0 + 0.2, first, 0, last - first, color=STONE, width=1.25)
    for i, section in enumerate(sections):
        y = Y0 + i * step
        _rect(slide, X0 + 0.13, y + 0.21, 0.14, 0.14, fill=GOLD, shape=MSO_SHAPE.OVAL)
        text(slide, X0 + 0.55, y, 0.9, 0.5, one(section["number"], font=HEAD, size=22, color=GOLD))
        text(slide, gx(2), y, gw(8), 0.45, one(section["title"], font=HEAD, size=20, color=FOREST))
        text(slide, gx(2), y + 0.46, gw(8), 0.3, one(section.get("description", ""), size=SIZE["small_body"], color=MUTED))
        page = pages.get(section["id"])
        if page:
            text(slide, gx(10), y + 0.04, gw(2), 0.4, one(str(page), font=HEAD, size=16, color=FOREST), align=PP_ALIGN.RIGHT)


def _opener(slide, ctx, slide_def):
    section = _section(ctx, slide_def)
    _rect(slide, 0, 0, W, H, fill=FOREST)
    photo = ctx["slots"][slide_def.slots[0]]
    has_photo = bool(photos_of(photo))
    width = 4.6 if has_photo else 7.5
    text(slide, 1.0, 1.7, width, 1.7, one(section["number"], font=HEAD, size=96, color=GOLD), anchor=MSO_ANCHOR.BOTTOM, spacing=1.0)
    _rect(slide, 1.0, 3.65, 0.55, 0.03, fill=GOLD)
    text(slide, 1.0, 3.85, width, 1.2, one(section["title"], font=HEAD, size=36, color=WHITE), spacing=1.0)
    text(slide, 1.0, 5.0, min(width, 4.8), 1.0, one(section.get("description", ""), size=SIZE["lede"], color=STONE), spacing=1.3)
    if has_photo:  # optional: only when the broker added one; never a missing item
        photo_or_placeholder(slide, ctx, photo, 6.0, 1.1, W - 6.0 - M, H - 2.2, valign="middle", halign="center", dark=True)


def _narrative_block(slide, ctx, state, x, y, w, h):
    if not _filled(state):
        _missing_text(slide, ctx, state, x, y, w, min(h, 2.0))
        return min(h, 2.0)
    lede, rest = _sentences(_show(state))
    lede_h = height_needed([lede], w, SIZE["lede"], spacing=1.25) + 0.12
    text(slide, x, y, w, lede_h, one(lede, size=SIZE["lede"], color=FOREST), spacing=1.25)
    body = [p.strip() for p in rest.split("\n") if p.strip()]
    used = lede_h
    if body:
        text(slide, x, y + lede_h + 0.05, w, h - lede_h - 0.05,
             [{"runs": [(p, {"size": SIZE["body"]})], "after": 6} for p in body], spacing=1.3)
        used += 0.05 + height_needed(body, w, SIZE["body"], spacing=1.3, after=6)
    return used


def facts_strip(slide, slot_states, x, y, w):
    """Three or four computed key facts in large Georgia numerals with small Arial labels, between thin rules."""
    labels = {"property.total_sf": ("{:,.0f}", "Total square feet"), "property.leased_pct": ("{:.0f}%", "Leased"),
              "property.buildings": ("{}", "Buildings"), "property.avg_unit_size": ("{:,.0f}", "Average unit (SF)"),
              "unit_count": ("{}", "Units")}
    shown = []
    for state in slot_states:
        if not _filled(state):
            continue
        fmt, label = labels.get(state.slot.id, ("{}", state.slot.label))
        value = state.calc.value if state.calc is not None and state.calc.ready else state.value
        try:
            shown.append((fmt.format(value), label))
        except (ValueError, TypeError):
            shown.append((str(value), label))
    if not shown:
        return
    _rule(slide, x, y, w)
    cell = w / len(shown)
    for i, (value, label) in enumerate(shown):
        cx = x + i * cell
        if i:
            _rule(slide, cx, y + 0.22, 0, 0.85)
        pad = 0 if i == 0 else 0.2
        text(slide, cx + pad, y + 0.2, cell - pad, 0.5, one(value, font=HEAD, size=26, color=FOREST), spacing=1.0)
        text(slide, cx + pad, y + 0.78, cell - pad, 0.25, one(label, size=SIZE["caption"] + 1, color=MUTED))


def _offering(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    s = ctx["slots"]
    narrative, photo = (s[i] for i in slide_def.slots)
    used = _narrative_block(slide, ctx, narrative, gx(0), Y0, OFFERING_BOX[0], OFFERING_BOX[1])
    facts_strip(slide, [s[i] for i in slide_def.facts_strip], gx(0), min(Y0 + used + 0.5, Y1 - 1.15), gw(7))
    _stacked_photos(slide, ctx, photo, gx(8), Y0, gw(4), Y1 - Y0)


def _stacked_photos(slide, ctx, state, x, y, w, h):
    """One or two photos in mats down a column, each whole and as large as the column allows; empty places are
    dashed on a draft."""
    found, count = photos_of(state), max(state.slot.count, 1)
    if found:
        for asset, cell in zip(found, justified([_ratio(a) for a in found], x, y, w, h, rows=[1] * len(found), center=False)):
            mat(slide, asset, state.slot, *cell)
    if state.slot.required and len(found) < count:
        each = (h - 0.25 * (count - 1)) / count
        for i in range(len(found), count):
            _placeholder(slide, ctx, x, y + i * (each + 0.25), w, each - CAPTION, _photo_label(state.slot))


def _ratio(asset):
    with Image.open(_asset_path(asset)) as image:
        return image.width / image.height


def _compositions(n):
    if n == 0:
        yield []
        return
    for first in range(1, n + 1):
        for rest in _compositions(n - first):
            yield [first] + rest


def justified(ratios, x, y, w, h, gap=0.25, rows=None, center=True, middle=False):
    """Mat rectangles (with the caption room under each) for photos laid out in rows of equal height that fill
    the width, every photo whole. Tries every way of splitting them into rows and keeps the one that shows the
    photos largest within the height. Rows narrower than the width are centred (or left-aligned)."""
    best = None
    for split in ([rows] if rows else _compositions(len(ratios))):
        heights, i = [], 0
        for k in split:
            group = ratios[i:i + k]
            heights.append((w - gap * (k - 1) - 2 * MAT * k) / sum(group))
            i += k
        total = sum(heights) + len(split) * (2 * MAT + CAPTION) + gap * (len(split) - 1)
        fixed = len(split) * (2 * MAT + CAPTION) + gap * (len(split) - 1)
        scale = min(1.0, (h - fixed) / (total - fixed)) if total > h else 1.0
        area = sum(ratios[j] * (heights[r] * scale) ** 2 for r, j in _rows_index(split))
        if best is None or area > best[0]:
            best = (area, split, [hh * scale for hh in heights])
    _, split, heights = best
    block = sum(heights) + len(split) * (2 * MAT + CAPTION) + gap * (len(split) - 1)
    cells, i, top = [], 0, y + ((h - block) / 2 if middle else 0)
    for k, row_h in zip(split, heights):
        group = ratios[i:i + k]
        widths = [r * row_h + 2 * MAT for r in group]
        row_w = sum(widths) + gap * (k - 1)
        left = x + ((w - row_w) / 2 if center else 0)
        for cw in widths:
            cells.append((left, top, cw, row_h + 2 * MAT + CAPTION))
            left += cw + gap
        top += row_h + 2 * MAT + CAPTION + gap
        i += k
    return cells


def _rows_index(split):
    j = 0
    for r, k in enumerate(split):
        for _ in range(k):
            yield r, j
            j += 1


def _narrative(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    narrative, photo = (ctx["slots"][i] for i in slide_def.slots)
    _narrative_block(slide, ctx, narrative, gx(0), Y0, NARRATIVE_BOX[0], NARRATIVE_BOX[1])
    photo_or_placeholder(slide, ctx, photo, gx(6) + 0.2, Y0, gw(6) - 0.2, Y1 - Y0)


def _orientation(state):
    found = photos_of(state)
    if not found:
        return "landscape"
    with Image.open(_asset_path(found[0])) as image:
        return om_assets.orientation(image.size)


def _highlights(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    *groups, photo = (ctx["slots"][i] for i in slide_def.slots)
    beside = _orientation(photo) != "landscape" and bool(photos_of(photo))
    span = 8 if beside else 12
    col_w = (gw(span) - 2 * GUT * 2) / 3
    content = max((height_needed(g.value if isinstance(g.value, list) else [g.value], col_w - 0.18, SIZE["small_body"],
                                 after=5) if _filled(g) else 1.2) for g in groups)
    height = Y1 - Y0 if beside else 0.86 + content + 0.1
    for i, group in enumerate(groups):
        x = gx(0) + i * (col_w + 2 * GUT)
        text(slide, x, Y0, col_w, 0.42, one(["I", "II", "III"][i], font=HEAD, size=20, color=GOLD))
        heading = group.slot.label.split(": ", 1)[-1]
        text(slide, x, Y0 + 0.42, col_w, 0.34, one(heading[:1].upper() + heading[1:], font=HEAD, size=SIZE["lede"], color=FOREST))
        if _filled(group):
            items = group.value if isinstance(group.value, list) else [group.value]
            text(slide, x, Y0 + 0.86, col_w, height - 0.86,
                 [{"runs": [(item, {"size": SIZE["small_body"]})], "bullet": True, "after": 5} for item in items])
        else:
            _missing_text(slide, ctx, group, x, Y0 + 0.9, col_w, 1.2)
    if beside:
        photo_or_placeholder(slide, ctx, photo, gx(8) + 0.2, Y0, gw(4) - 0.2, Y1 - Y0)
    else:
        top = Y0 + height + 0.3
        photo_or_placeholder(slide, ctx, photo, gx(0), top, gw(12), Y1 - top, halign="center")


def _features(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    *fields, photo = (ctx["slots"][i] for i in slide_def.slots)
    rows = [f for f in fields if f.slot.required or _filled(f)]  # optional and unknown: left off, never a blank row
    label_w, value_x = 1.95, gx(0) + 2.1
    value_w = gx(0) + gw(6) - value_x
    y = Y0
    for field in rows:
        lines = max(lines_needed(field.slot.label, label_w, SIZE["table"]),
                    lines_needed(_show(field), value_w, SIZE["small_body"]) if _filled(field) else 1)
        row_h = max(0.42, lines * SIZE["small_body"] * 1.2 / 72 + 0.2)
        text(slide, gx(0), y + 0.11, label_w, row_h - 0.1, one(field.slot.label, size=SIZE["table"], color=MUTED))
        if _filled(field):
            text(slide, value_x, y + 0.09, value_w, row_h - 0.1, one(_show(field), size=SIZE["small_body"]))
        else:
            _placeholder(slide, ctx, value_x, y + 0.06, value_w, row_h - 0.14, _what_to_add(field))
        y += row_h
        _rule(slide, gx(0), y, gw(6))
    photo_or_placeholder(slide, ctx, photo, gx(7), Y0, gw(5), Y1 - Y0)


def _site_plan(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    states = [ctx["slots"][i] for i in slide_def.slots]
    photo, notes = states[0], (states[1] if len(states) > 1 else None)
    if notes is not None and _filled(notes):
        items = notes.value if isinstance(notes.value, list) else [notes.value]
        box_h = min(Y1 - Y0, 0.95 + height_needed(items, gw(3) - 0.4 - 0.18, SIZE["small_body"], after=5))
        _rect(slide, gx(9), Y0, gw(3), box_h, fill=STONE)
        text(slide, gx(9) + 0.2, Y0 + 0.18, gw(3) - 0.4, 0.35, one("Notes", font=HEAD, size=SIZE["lede"], color=FOREST))
        text(slide, gx(9) + 0.2, Y0 + 0.6, gw(3) - 0.4, box_h - 0.7,
             [{"runs": [(item, {"size": SIZE["small_body"]})], "bullet": True, "after": 5} for item in items])
        photo_or_placeholder(slide, ctx, photo, gx(0), Y0, gw(9) - 0.1, Y1 - Y0)
    else:
        photo_or_placeholder(slide, ctx, photo, gx(0), Y0, gw(12), Y1 - Y0, halign="center")


def _photo_page(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    state = ctx["slots"][slide_def.slots[0]]
    found = photos_of(state)[:4]
    if not found:
        _placeholder(slide, ctx, gx(0), Y0, gw(12), Y1 - Y0 - CAPTION, "Add photos: exterior or interior (1 to 4)")
        return
    for asset, cell in zip(found, justified([_ratio(a) for a in found], gx(0), Y0, gw(12), Y1 - Y0, middle=True)):
        mat(slide, asset, state.slot, *cell)


def _short_money(value):
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    return om_calc.money(value)


def _price(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    *figures, photo = (ctx["slots"][i] for i in slide_def.slots)
    has_photo = bool(photos_of(photo))
    top = Y0 + 0.05 if has_photo else Y0 + 1.2
    names = {"financial.sale_price": "Asking price", "property.leased_pct": "Leased", "financial.cap_rate_y4": "Year-4 cap rate",
             "financial.price_per_sf": "Price per SF"}
    notes = {"financial.sale_price": "Set by the broker."}
    cell = gw(3)
    for i, figure in enumerate(figures):
        x = gx(i * 3)
        if i:
            _rule(slide, x - GUT / 2, top + 0.05, 0, 1.45)
        text(slide, x + (0.15 if i else 0), top, cell - 0.15, 0.25, one(names.get(figure.slot.id, figure.slot.label),
                                                                     size=SIZE["caption"] + 1, color=MUTED))
        if _filled(figure):
            value = _short_money(figure.value) if figure.slot.id == "financial.sale_price" and isinstance(figure.value, (int, float)) \
                else _show(figure)
            text(slide, x + (0.15 if i else 0), top + 0.3, cell - 0.15, 0.6, one(value, font=HEAD, size=30, color=FOREST), spacing=1.0)
            how = notes.get(figure.slot.id) or (figure.calc.formula if figure.calc is not None else "")
            if figure.slot.id == "financial.sale_price" and isinstance(figure.value, (int, float)):
                how = f"Set by the broker: {om_calc.money(figure.value)}."
            text(slide, x + (0.15 if i else 0), top + 1.0, cell - 0.3, 0.5, one(how, size=SIZE["caption"], italic=True, color=MUTED),
                 spacing=1.2)
        else:
            _placeholder(slide, ctx, x + (0.15 if i else 0), top + 0.3, cell - 0.3, 0.65, _what_to_add(figure))
    if has_photo:
        photo_or_placeholder(slide, ctx, photo, gx(0), top + 1.85, gw(12), Y1 - top - 1.85, halign="center")


def _hairline_table(slide, x, y, w, header, rows, widths, size, bold_rows=(), right_from=1, total_row=None):
    """A minimal table: no fills, hairlines between rows, a deep-green header with a rule under it, numbers to the
    right, subtotals in bold with a rule above. A real PowerPoint table."""
    body = rows + ([total_row] if total_row else [])
    row_h = 0.27 if size <= SIZE["dense"] else 0.3
    shape = slide.shapes.add_table(len(body) + 1, len(header), Inches(x), Inches(y), Inches(w), Inches(row_h * (len(body) + 1)))
    table = shape.table
    _no_style(shape)
    for i, part in enumerate(widths):
        table.columns[i].width = Inches(w * part)
    bold = set(bold_rows) | ({len(body) - 1} if total_row else set())
    for r, row in enumerate([header] + body):
        table.rows[r].height = Inches(row_h)
        for c, value in enumerate(row):
            cell = table.cell(r, c)
            cell.fill.background()
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.text = "" if value is None else str(value)
            para = cell.text_frame.paragraphs[0]
            para.alignment = PP_ALIGN.RIGHT if c >= right_from else PP_ALIGN.LEFT
            for run in para.runs or [para.add_run()]:
                _style(run, size=size, color=FOREST if r == 0 else INK, bold=(r == 0) or (r - 1) in bold)
            if r == 0:
                _border(cell, "B", FOREST, 1.0)
            elif (r - 1) in bold:
                _border(cell, "T", FOREST, 0.75)
                _border(cell, "B", STONE, 0.5)
            else:
                _border(cell, "B", STONE, 0.5)
    return shape, row_h * (len(body) + 1)


def _no_style(shape):
    """'No Style, No Grid': the table draws only the rules we add."""
    tbl = shape._element.graphic.graphicData.tbl
    tbl_pr = tbl.tblPr
    for attr in ("firstRow", "bandRow"):
        tbl_pr.set(attr, "0")
    style = tbl_pr.find(qn("a:tableStyleId"))
    if style is None:
        style = etree.SubElement(tbl_pr, qn("a:tableStyleId"))
    style.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"


def _border(cell, side, colour, width):
    tc_pr = cell._tc.get_or_add_tcPr()
    tag = qn(f"a:ln{side}")
    for old in tc_pr.findall(tag):
        tc_pr.remove(old)
    line = etree.SubElement(tc_pr, tag, w=str(int(Pt(width))), cap="flat", cmpd="sng", algn="ctr")
    fill = etree.SubElement(line, qn("a:solidFill"))
    etree.SubElement(fill, qn("a:srgbClr")).set("val", str(colour))
    etree.SubElement(line, qn("a:prstDash")).set("val", "solid")
    # lnL/lnR/lnT/lnB must come before fills in tcPr: move the line to the front.
    tc_pr.remove(line)
    tc_pr.insert(0, line)


def _financials(slide, ctx, slide_def):
    _header(slide, ctx, slide_def)
    flow, note = (ctx["slots"][i] for i in slide_def.slots)
    if _filled(flow) and flow.calc is not None and flow.calc.ready:
        rows = [[label] + [money_cell(v, label) for v in values] for label, values in flow.calc.value]
        bold = [i for i, (label, _) in enumerate(flow.calc.value)
                if label in ("Effective gross income", "Total expenses", "Net operating income")]
        header = ["", "In-place"] + [f"Year {n}" for n in range(1, om_calc.YEARS + 1)]
        size = SIZE["dense"] if len(rows) > DENSE_ROWS else SIZE["table"]
        _, table_h = _hairline_table(slide, X0, Y0, X1 - X0, header, rows, [0.28] + [0.12] * 6, size, bold_rows=bold)
    else:
        table_h = 3.0
        _missing_text(slide, ctx, flow, X0, Y0, X1 - X0, 3.0)
    if _filled(note):
        text(slide, X0, Y0 + table_h + 0.3, X1 - X0, 0.55, one(_show(note), size=SIZE["caption"], italic=True, color=MUTED))


def _rent_roll(slide, ctx, slide_def, rows=None, last=True):
    continued = rows is not None and ctx["rent_roll_first"] is not None and rows[0] != ctx["rent_roll_first"]
    _header(slide, ctx, slide_def, slide_def.title + (" (continued)" if continued else ""))
    roll, note = (ctx["slots"][i] for i in slide_def.slots)
    if not _filled(roll) or rows is None:
        _missing_text(slide, ctx, roll, X0, Y0, X1 - X0, 3.0)
        return
    header = ["Unit", "Tenant", "SF", "Lease start", "Lease end", "Annual rent", "Rent / SF", "Type"]
    body = [[r["unit"], r["tenant"], f"{r['sf']:,.0f}" if isinstance(r["sf"], (int, float)) else r["sf"],
             r["start"] or "", r["end"] or "",
             om_calc.money(r["annual_rent"]) if isinstance(r["annual_rent"], (int, float)) else "",
             om_calc.money(r["rent_psf"], True) if isinstance(r["rent_psf"], (int, float)) else "", r["lease_type"] or ""]
            for r in rows]
    total = None
    if last:
        everything = roll.calc.value
        sf = sum(r["sf"] for r in everything if isinstance(r["sf"], (int, float)))
        rent = sum(r["annual_rent"] for r in everything if isinstance(r["annual_rent"], (int, float)))
        total = ["Total", f"{len(everything)} units", f"{sf:,.0f}", "", "", om_calc.money(rent), "", ""]
    _, table_h = _hairline_table(slide, X0, Y0, X1 - X0, header, body, [0.07, 0.27, 0.09, 0.12, 0.12, 0.13, 0.1, 0.1],
                                 SIZE["table"], right_from=2, total_row=total)
    if last and _filled(note):
        text(slide, X0, Y0 + table_h + 0.3, X1 - X0, 0.55, one(_show(note), size=SIZE["caption"], italic=True, color=MUTED))


def _back_cover(slide, ctx, slide_def):
    contacts, notice = (ctx["slots"][i] for i in slide_def.slots)
    _rect(slide, 0, 0, W, H, fill=FOREST)
    text(slide, 1.0, 1.0, 8.0, 0.7, one(slide_def.title, font=HEAD, size=32, color=WHITE))
    _rect(slide, 1.0, 1.85, 0.55, 0.03, fill=GOLD)
    if _filled(contacts):
        for i, person in enumerate(contacts.value[:3]):
            x = 1.0 + i * 3.2
            _rect(slide, x, 2.4, 2.95, 1.9, line=GOLD, width=0.75)
            text(slide, x + 0.25, 2.6, 2.5, 1.6, [
                {"runs": [(person["name"], {"font": HEAD, "size": 16, "color": WHITE})], "after": 2},
                {"runs": [(person.get("title") or "", {"size": SIZE["small_body"], "color": GOLD, "italic": True})], "after": 8},
                [(person.get("phone") or "", {"size": SIZE["small_body"], "color": STONE})],
                [(person.get("email") or "", {"size": SIZE["small_body"], "color": STONE})]])
    else:
        _missing_text(slide, ctx, contacts, 1.0, 2.4, 2.95, 1.9, dark=True)
    text(slide, 1.0, H - 1.25, 8.5, 0.3, one(notice.display, size=SIZE["caption"], italic=True, color=STONE))
    logo = ctx["facts"].get("logo")
    if logo and Path(logo).exists():
        with Image.open(logo) as image:
            ratio = image.width / image.height
        lw = min(2.0, 0.55 * ratio)
        slide.shapes.add_picture(str(logo), Inches(X1 - lw), Inches(1.0), Inches(lw), Inches(lw / ratio))


LAYOUTS = {"cover": _cover, "legal": _legal, "contents": _contents, "opener": _opener, "offering": _offering,
           "narrative": _narrative, "highlights": _highlights, "features": _features, "site_plan": _site_plan,
           "photo_page": _photo_page, "price": _price, "financials": _financials, "back_cover": _back_cover}
DARK = {"cover", "opener", "back_cover"}


# Each layout's photo area, (width, height) in inches, for the editor's preview shape and resolution check.
PHOTO_AREAS = {"cover": (W * 0.6 - 2 * M, H - 2 * M - CAPTION), "opener": (W - 6.0 - M, H - 2.2 - CAPTION),
               "offering": (gw(4), (Y1 - Y0 - 0.25) / 2 - CAPTION), "narrative": (gw(6) - 0.2, Y1 - Y0 - CAPTION),
               "highlights": (gw(12), Y1 - Y0 - HIGHLIGHT_COLUMN[1] - 0.9 - CAPTION),
               "features": (gw(5), Y1 - Y0 - CAPTION), "site_plan": (gw(12), Y1 - Y0 - CAPTION),
               "photo_page": ((gw(12) - 0.3) / 2, (Y1 - Y0 - 0.3) / 2 - CAPTION), "price": (gw(12), Y1 - Y0 - 2.4 - CAPTION)}


def photo_frame(layout, slot):
    """(width, height) in inches of one photo's frame on this layout."""
    w, h = PHOTO_AREAS.get(layout, (gw(12), Y1 - Y0 - CAPTION))
    return w - 2 * MAT, h - 2 * MAT


# ---------- the whole deck ----------

def pages(state):
    """(slide definition, rows or None, last page of that slide?) per page; a long rent roll runs on with its header."""
    out = []
    for _, slide_def in state.slides:
        if slide_def.layout == "rent_roll":
            roll = state.slots[slide_def.slots[0]]
            rows = roll.calc.value if roll.calc is not None and roll.calc.ready and _filled(roll) else None
            chunks = [rows[i:i + RENT_ROLL_ROWS] for i in range(0, len(rows), RENT_ROLL_ROWS)] if rows else [None]
            out += [(slide_def, chunk, i == len(chunks) - 1) for i, chunk in enumerate(chunks)]
        else:
            out.append((slide_def, None, True))
    return out


def _section_pages(page_list):
    first = {}
    for number, (slide_def, _, _) in enumerate(page_list, start=1):
        if slide_def.layout == "opener":
            first.setdefault(slide_def.section, number)
    return first


def set_theme(deck):
    """Georgia (headings) and Arial (body) as the file's theme fonts, and our palette as its theme colours."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    theme = deck.slide_master.part.part_related_by(RT.THEME)
    root = etree.fromstring(theme.blob)
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    for tag, face in (("majorFont", HEAD), ("minorFont", BODY)):
        latin = root.find(f".//a:fontScheme/a:{tag}/a:latin", ns)
        if latin is not None:
            latin.set("typeface", face)
    colours = {"dk1": "ink", "lt1": "paper", "dk2": "forest", "lt2": "stone", "accent1": "gold", "accent2": "forest",
               "accent3": "muted", "accent4": "stone", "accent5": "gold", "accent6": "forest", "hlink": "forest",
               "folHlink": "muted"}
    scheme = root.find(".//a:clrScheme", ns)
    if scheme is not None:
        scheme.set("name", "Editorial")
        for name, key in colours.items():
            slot = scheme.find(f"a:{name}", ns)
            if slot is None:
                continue
            for child in list(slot):
                slot.remove(child)
            etree.SubElement(slot, qn("a:srgbClr")).set("val", PALETTE[key])
    theme._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def build(state, facts, kind, out_path):
    """Draw the deck. kind: 'draft' (corner tag, dashed outlines for anything empty) or 'final' (none of that)."""
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(W), Inches(H)
    set_theme(deck)
    blank = deck.slide_layouts[6]
    roll = state.slots.get("tenant.rent_roll")
    page_list = pages(state)
    ctx = {"slots": state.slots, "facts": facts, "template": state.template, "draft": kind == "draft",
           "section_pages": _section_pages(page_list),
           "rent_roll_first": roll.calc.value[0] if roll and roll.calc is not None and roll.calc.ready and roll.calc.value else None}
    footer, mark = footer_text(state), om_template.boilerplate()["draft_mark"]
    for number, (slide_def, rows, last) in enumerate(page_list, start=1):
        slide = deck.slides.add_slide(blank)
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = PAPER
        if slide_def.layout == "rent_roll":
            _rent_roll(slide, ctx, slide_def, rows, last)
        else:
            LAYOUTS[slide_def.layout](slide, ctx, slide_def)
        if number > 1:
            _footer(slide, footer, number, dark=slide_def.layout in DARK)
        if kind == "draft":
            _draft_tag(slide, mark)
    deck.core_properties.title = f"Offering Memorandum - {footer}" if footer else "Offering Memorandum"
    deck.core_properties.author = (facts.get("profile") or {}).get("full_name") or "Broker"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    deck.save(out_path)
    return len(deck.slides)
