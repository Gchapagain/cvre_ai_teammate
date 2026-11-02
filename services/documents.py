"""A deal's documents: upload, type detection, locked files, "Read it now" and what was read.

- Uploads are saved under uploads/<deal_id>/ (git-ignored) and start as Received. A file that is
  password-protected gets "Needs password". Photos are also added to the OM photo sorter.
- The type (rent roll, T-12, BOV, OM, appraisal, photo, other) is worked out from the file's name and,
  where possible, its content. No AI is used. The broker can change it.
- A locked PDF is unlocked with a password the person types. The password is used in memory only: it is
  never saved, logged or shown again. An unlocked copy is saved next to the original.
- "Read it now" reads a Received rent roll with the existing extraction (pipeline.process_deal): one
  Gemini request.
- "What we read" is built only from saved rows (units, flags, T-12 lines, OM slots). Never invented.
"""

import io
import re
from pathlib import Path

import db
from services import deals, extraction, gemini, new_deal, om_assets, pipeline

TYPES = ("Rent roll", "T-12", "BOV", "OM", "Appraisal", "Photo", "Other")
EXTENSIONS = (".xlsx", ".csv", ".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp")
IMAGES = (".png", ".jpg", ".jpeg", ".webp")
MAX_BYTES = 25 * 1024 * 1024
NOT_READABLE = {"T-12": "Reading T-12 files is not built yet.",
                "BOV": "The app does not read BOVs for numbers; it is kept for reference.",
                "OM": "The app does not read OMs for numbers; it is kept for reference.",
                "Appraisal": "The app does not read appraisals for numbers; it is kept for reference.",
                "Other": "The app does not read this kind of file for numbers; it is kept for reference."}
# Words in a file name (or a PDF's first page) that say what it is, checked in this order.
NAME_HINTS = (("T-12", r"(?<![a-z])t[-_ ]?12(?!\d)|trailing[-_ ]?12|operating[-_ ]statement|\bp ?& ?l\b"),
              ("Rent roll", r"rent[-_ ]?roll"),
              ("BOV", r"\bbov\b|broker[-_ ]opinion"),
              ("Appraisal", r"apprais"),
              ("OM", r"\bom\b|offering[-_ ]memo"))
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # how a password-protected .xlsx / .docx starts


class DocumentError(ValueError):
    """A plain sentence a person can act on."""


# ---------- looking at a file ----------

def _hint(text):
    lowered = (text or "").lower()
    return next((kind for kind, pattern in NAME_HINTS if re.search(pattern, lowered)), None)


def pdf_text(data, password=None):
    """The first pages' text of a PDF, or None when it is locked (and no password was given)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(password or ""):
        return None
    return "\n".join((page.extract_text() or "") for page in reader.pages[:2])


def is_locked(name, data):
    """True when the file needs a password to open."""
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        try:
            return pdf_text(data) is None
        except Exception:
            return False
    if suffix in (".xlsx", ".docx"):
        return data[:8] == OLE_MAGIC
    return False


def detect_type(name, data, path=None):
    """The document type from the name and, where possible, the content. Never uses AI."""
    suffix = Path(name).suffix.lower()
    if suffix in IMAGES:
        return "Photo"
    if suffix in (".xlsx", ".csv") and path is not None and data[:8] != OLE_MAGIC:
        kind = new_deal.classify(path)
        if kind in ("Rent roll", "T-12"):
            return kind
    hint = _hint(Path(name).stem)
    if hint:
        return hint
    if suffix == ".pdf":
        try:
            return _hint(pdf_text(data)) or "Other"
        except Exception:
            return "Other"
    return "Other"


# ---------- writes (each on a person's click) ----------

def _connect(db_path):
    db.init_db(db_path)
    return db.get_connection(db_path)


def _update(document_id, db_path, **fields):
    conn = _connect(db_path)
    try:
        with conn:
            sets = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(f"UPDATE documents SET {sets} WHERE id = ?", (*fields.values(), document_id))
    finally:
        conn.close()


def add_documents(deal_id, files, db_path=None, upload_dir=None):
    """Save uploaded files [(name, bytes)]. Returns [{"filename", "type", "status", "message"}]; a bad file never
    stops the others."""
    results = []
    for name, data in files:
        suffix = Path(name).suffix.lower()
        if suffix not in EXTENSIONS:
            results.append({"filename": name, "status": None, "type": None,
                            "message": "Not added: use xlsx, csv, pdf, docx or a photo (png, jpg, webp)."})
            continue
        if len(data) > MAX_BYTES:
            results.append({"filename": name, "status": None, "type": None,
                            "message": f"Not added: the file is {len(data) / 1024 / 1024:.0f} MB; the limit is "
                                       f"{MAX_BYTES // 1024 // 1024} MB. Ask for a smaller copy or split it."})
            continue
        document_id, path = deals.save_upload(deal_id, name, data, db_path, upload_dir)
        locked = is_locked(name, data)
        kind = detect_type(name, data, path)
        status, used_for, message = "Received", None, "Added. " + NOT_READABLE.get(kind, "Not read yet.")
        if locked:
            status, message = "Needs password", "Added. It is locked: type its password below to unlock it."
        elif kind == "Photo":
            saved, problems = om_assets.add_photos(deal_id, [(path.name, data)], "Broker", db_path=db_path)
            status, used_for = "Reference only", "OM photos"
            message = "Added to the OM photo sorter." if saved else f"Added, but not as an OM photo: {' '.join(problems)}"
        elif kind == "Rent roll":
            message = "Added. Press Read it now to read it (1 AI request)."
        _update(document_id, db_path, doc_type=kind, status=status, used_for=used_for)
        results.append({"id": document_id, "filename": path.name, "type": kind, "status": status, "message": message})
    return results


def set_type(document_id, doc_type, db_path=None):
    if doc_type not in TYPES:
        raise DocumentError("Choose one of the listed types.")
    _update(document_id, db_path, doc_type=doc_type)


def mark_reference(document_id, db_path=None):
    _update(document_id, db_path, status="Reference only")


def _document(document_id, db_path):
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def unlock(document_id, password, db_path=None):
    """Unlock a password-protected PDF with the password a person typed. The password stays in memory only.

    Saves an unlocked copy next to the original and sets the document to Received. Raises DocumentError
    with a friendly message for a wrong password or a file type that cannot be unlocked here.
    """
    import pikepdf
    doc = _document(document_id, db_path)
    if doc is None or doc["status"] != "Needs password":
        raise DocumentError("This document is not waiting for a password.")
    path = Path(doc["file_path"] or "")
    if not path.is_file():
        raise DocumentError("The file is not on this server, so it cannot be unlocked. Ask for an unlocked copy.")
    if path.suffix.lower() != ".pdf":
        raise DocumentError("Only PDFs can be unlocked here. Ask the sender for an unlocked copy of this file.")
    if not password:
        raise DocumentError("Type the password first.")
    try:
        with pikepdf.open(path, password=password) as pdf:
            unlocked = path.with_name(f"{path.stem} (unlocked).pdf")
            pdf.save(unlocked)
    except pikepdf.PasswordError:
        raise DocumentError("That password did not open the file. Check it with the sender and try again.") from None
    except pikepdf.PdfError:
        raise DocumentError("The file could not be opened. Ask the sender for a new copy.") from None
    data = unlocked.read_bytes()
    kind = doc["doc_type"] if doc["doc_type"] not in (None, "Other") else detect_type(doc["filename"], data)
    _update(document_id, db_path, file_path=str(unlocked), status="Received", doc_type=kind)
    return kind


def read_now(document_id, client=None, db_path=None):
    """Read a Received rent roll with the AI (1 request) and validate it. Returns process_deal's summary.

    Raises DocumentError for anything that cannot be read, and gemini errors for quota or connection problems.
    """
    doc = _document(document_id, db_path)
    if doc is None:
        raise DocumentError("That document could not be found.")
    if doc["status"] != "Received" or doc["doc_type"] != "Rent roll":
        raise DocumentError("Only a rent roll that has not been read yet can be read here.")
    path = Path(doc["file_path"] or "")
    if not path.is_file():
        raise DocumentError("The file is not on this server (it came from an email without the attachment). "
                            "Upload the file here, then read it.")
    try:
        summary = pipeline.process_deal(path, doc["deal_id"], client=client, db_path=db_path, document_id=document_id)
    except extraction.ExtractionError as error:
        raise DocumentError(f"It could not be read: {str(error).replace(' Nothing was saved.', '')} Nothing was saved.") from None
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("UPDATE deals SET status = 'Needs Review', updated_at = CURRENT_TIMESTAMP "
                         "WHERE id = ? AND status IN ('New', 'Extracting')", (doc["deal_id"],))
    finally:
        conn.close()
    return summary


# ---------- what the list shows (read-only) ----------

def size_text(doc):
    path = Path(doc.get("file_path") or "")
    if not doc.get("file_path") or not path.is_file():
        return "No file"
    size = path.stat().st_size
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{max(size // 1024, 1)} KB"


def what_we_read(doc, units, flags, t12, photo_slots=0):
    """One line from saved rows only. units/flags/t12 are this deal's rows."""
    status, kind = doc["status"], doc.get("doc_type")
    if status == "Needs password":
        return "Locked: needs a password before it can be read."
    if status == "Read" and kind == "Rent roll":
        mine = [u for u in units if u.get("document_id") == doc["id"]]
        ids = {u["id"] for u in mine}
        flagged = {f["rent_roll_unit_id"] for f in flags if f.get("status") == "open" and f.get("rent_roll_unit_id") in ids}
        return f"{len(mine)} unit{'s' if len(mine) != 1 else ''} extracted, {len(flagged)} flagged."
    if status == "Read" and kind == "T-12":
        lines = {(t["category"], t["line_item"]) for t in t12 if t.get("document_id") == doc["id"]}
        return f"{len(lines)} T-12 line{'s' if len(lines) != 1 else ''} saved." if lines else "Read."
    if kind == "Photo" or doc.get("used_for") == "OM photos":
        return f"Used as an OM photo{' on ' + str(photo_slots) + ' slide item' + ('s' if photo_slots != 1 else '') if photo_slots else ' (not placed on a slide yet)'}."
    if status == "Reference only":
        return "Reference only - not used for numbers."
    if not doc.get("file_path"):
        return "Not read yet. No file on this server: it was listed from an email or the sample data."
    if kind == "Rent roll":
        return "Not read yet."
    return ("Not read yet. " if kind == "T-12" else "") + NOT_READABLE.get(kind or "Other", NOT_READABLE["Other"])


def summary_line(docs):
    """'3 documents: 2 read, 1 needs a password'."""
    if not docs:
        return "No documents yet."
    counts = {}
    for doc in docs:
        counts[doc["status"]] = counts.get(doc["status"], 0) + 1
    words = {"Read": "read", "Received": "not read yet", "Reference only": "reference only", "Needs password": "needs a password"}
    parts = [f"{counts[s]} {words[s]}" if s != "Needs password" else
             f"{counts[s]} need{'s' if counts[s] == 1 else ''} a password" for s in words if counts.get(s)]
    return f"{len(docs)} document{'s' if len(docs) != 1 else ''}: " + ", ".join(parts)
