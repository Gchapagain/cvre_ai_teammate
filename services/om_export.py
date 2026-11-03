"""Export the OM as PowerPoint (the master file) and PDF (converted from the PowerPoint by LibreOffice).

- The slides are drawn by services/om_design.py (the Editorial design) from the live OM state: native text
  boxes, tables and vector shapes, letter landscape 11 x 8.5 in, Georgia and Arial, no animations. Our own
  design; no company logo is embedded (a logo uploaded in Settings is used if there is one).
- A draft export is always allowed: a small "DRAFT - NOT FOR DISTRIBUTION" tag on every page and a dashed
  outline for anything empty. A client-ready export is allowed only at 100% approved with no text too long.
- Numbers are shown exactly as the engine calculated them; nothing here calls the AI.
- Files go to om_exports/ (git-ignored) as <deal>_OM_v<n>_<draft|final>.pptx / .pdf and every export is
  logged in om_exports and om_events. Previews are PNG pages at 200 dpi, never logged as exports.
"""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from PIL import Image

from services import om_design, om_engine, om_slots

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "om_exports"
SOFFICE_PLACES = ("/Applications/LibreOffice.app/Contents/MacOS/soffice", "/usr/bin/soffice", "/usr/local/bin/soffice")
RENT_ROLL_ROWS = om_design.RENT_ROLL_ROWS
PREVIEW_DPI = 200         # slide previews: 11 in x 200 = 2200 px wide, PNG
THUMB_WIDTH = 360         # slide-list thumbnails, made once from the preview with a good filter
LARGE_FILE_MB = 40


class ExportError(Exception):
    """Something a person can act on, in plain words."""


# The drawing lives in services/om_design.py (the Editorial design). These names are kept for the screens and tests.
footer_text = om_design.footer_text
_money_cell = om_design.money_cell
photo_frame = om_design.photo_frame


def photo_ratio(layout, slot):
    w, h = om_design.photo_frame(layout, slot)
    return w / h


def _pages(state):
    """(slide definition, extra) per page; a long rent roll continues on the next page."""
    return [(slide_def, rows) for slide_def, rows, _ in om_design.pages(state)]


def build_pptx(state, facts, kind, out_path):
    """Write the PowerPoint for this OM state. kind: 'draft' (corner tag, dashed placeholders) or 'final'."""
    if kind == "final":
        problems = final_blockers(state)
        if problems:
            raise ExportError("The client-ready export unlocks at 100% approved. Still to do: " + "; ".join(problems[:5])
                              + (f" and {len(problems) - 5} more" if len(problems) > 5 else "") + ".")
    return om_design.build(state, facts, kind, out_path)


def final_blockers(state):
    """Why a final export is not allowed yet (empty list when it is)."""
    blockers = [f"{s.slot.label} is missing" for s in state.counted if s.status == "empty"]
    blockers += [f"{s.slot.label} needs your approval" for s in state.counted if s.status in om_engine.FILLED]
    blockers += [message for _, message in om_design.too_long(state)]
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


def page_images(pdf_path, zoom=PREVIEW_DPI / 72):
    """PNG previews of each PDF page (200 dpi by default, never JPEG), cached by the file's hash so a page is drawn once."""
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


def thumbnails(pages, width=THUMB_WIDTH):
    """Small PNGs of the preview pages for the slide list, downscaled once (Lanczos) and cached beside them."""
    out = []
    for page in pages:
        thumb = page.with_name(page.stem + f"-thumb{width}.png")
        if not thumb.exists():
            with Image.open(page) as image:
                image.thumbnail((width, width * 2), Image.Resampling.LANCZOS)
                image.save(thumb, "PNG")
        out.append(thumb)
    return out


def size_warning(path):
    """A plain warning when the PowerPoint is very large, with what to do about it."""
    megabytes = Path(path).stat().st_size / 1024 / 1024 if path and Path(path).exists() else 0
    if megabytes <= LARGE_FILE_MB:
        return None
    return (f"The PowerPoint is {megabytes:.0f} MB, which is large to email. Use fewer or smaller photos (each is kept "
            "at most 2400 px on its long side), or share it as a link instead of an attachment.")


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
            "pdf": pdf_path, "pdf_error": pdf_error, "slides": slides, "completion": state.percent,
            "size_warning": size_warning(pptx_path)}


# ---------- live preview (not an export: nothing is logged) ----------

def _state_key(state, facts):
    parts = [(slot_id, s.status, s.value) for slot_id, s in sorted(state.slots.items())]
    parts.append([(a.get("id"), a.get("file_path"), a.get("slot_id")) for a in facts.get("assets", [])])
    parts.append([str(facts.get("logo")), facts.get("profile"), [n for n, _ in state.slides]])
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def cached_preview(state, facts):
    """The preview PDF for exactly this OM state, if it was already made."""
    pdf = EXPORT_DIR / "previews" / f"live_{_state_key(state, facts)}" / "preview.pdf"
    return pdf if pdf.exists() else None


def preview_pdf(state, facts):
    """A draft PDF of the OM as it is right now, for the slide preview. Cached by the OM's content."""
    folder = EXPORT_DIR / "previews" / f"live_{_state_key(state, facts)}"
    pdf = folder / "preview.pdf"
    if not pdf.exists():
        build_pptx(state, facts, "draft", folder / "preview.pptx")
        to_pdf(folder / "preview.pptx")
    return pdf


def page_of(state, slide_id):
    """The 0-based page a slide starts on (a long rent roll takes several pages)."""
    for index, (slide_def, _) in enumerate(_pages(state)):
        if slide_def.id == slide_id:
            return index
    return 0


# ---------- the live deck: redrawn in the background whenever the OM changes ----------

_live_lock = threading.Lock()
_live = {}   # deal_id -> {"key", "running", "latest": Path, "error"}


def _build_live(deal_id, key, state, facts):
    try:
        pdf = preview_pdf(state, facts)
        thumbnails(page_images(pdf))
        with _live_lock:
            _live[deal_id].update(running=False, latest=pdf, error=None, built=key)
    except Exception as error:  # e.g. LibreOffice missing: the page says so
        with _live_lock:
            _live[deal_id].update(running=False, error=str(error) if isinstance(error, ExportError) else
                                  "The preview could not be drawn just now.")


def live_preview(deal_id, state, facts):
    """(pdf or None, up_to_date, error). Starts a background redraw when the OM changed; never blocks."""
    key = _state_key(state, facts)
    pdf = cached_preview(state, facts)
    with _live_lock:
        job = _live.setdefault(deal_id, {})
        if pdf is not None:
            job.update(latest=pdf, key=key)
            return pdf, True, None
        if not soffice_path():
            return job.get("latest"), False, "The live preview needs LibreOffice, which is not installed here."
        if not (job.get("running") and job.get("key") == key):
            job.update(running=True, key=key)
            threading.Thread(target=_build_live, args=(deal_id, key, state, facts), daemon=True,
                             name=f"om-preview-{deal_id}").start()
        return job.get("latest"), False, job.get("error")


def live_running(deal_id):
    with _live_lock:
        return bool((_live.get(deal_id) or {}).get("running"))
