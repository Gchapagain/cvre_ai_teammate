"""OM photos: a person uploads them, code checks and resizes them, and they are placed on photo slots.

- Photos come from the broker (or the client). The AI never makes aerials, maps or site plans.
- Files are saved under om_assets/ (git-ignored): the upload exactly as received (originals/, never changed) and a
  high-quality copy for the slides (long side at most MAX_SIDE pixels, JPEG quality 92 or PNG, only ever shrunk).
- Photos are never cropped automatically: fit is 'whole' (shown entire inside its frame) unless the broker picks
  'fill', which crops to the frame.
- "Sort my photos" asks Gemini once per batch of up to BATCH photos what each one shows (aerial, exterior,
  interior, site plan, map). That is only a proposal: nothing changes until a person clicks Apply.
- "Place photos" fills empty photo slots in template order with photos of the right kind (code only).
- Sample photos (sample = 1) are made-up drawings for the demo, labelled "Sample illustration"; any that
  have gone missing on disk are drawn again.
"""

import io
import json
from pathlib import Path

from google.genai import types
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, ConfigDict, ValidationError

import db
from services import gemini, om_slots, om_template

ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "om_assets"
TYPES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
MAX_BYTES = 15 * 1024 * 1024
MAX_SIDE = 2400
JPEG_QUALITY = 92
GOOD_DPI = 150       # at print size; below this a photo gets a "Low resolution" chip (never blocked)
FITS = ("whole", "fill")
BATCH = 8            # photos per "Sort my photos" request
KIND_NAMES = {"aerial": "Aerial", "exterior": "Exterior", "interior": "Interior", "site_plan": "Site plan", "map": "Map"}


def _connect(db_path):
    return om_slots._connect(db_path)


def stored_path(path):
    """Paths are saved relative to the project folder, so the database works on any machine."""
    path = Path(path)
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def full_path(stored):
    path = Path(stored)
    return path if path.is_absolute() else ROOT / path


def _clean_image(name, data):
    """(image bytes, suffix) for the slides, after checking the file really is a picture. Only ever shrunk."""
    suffix = Path(name or "").suffix.lower()
    if suffix not in TYPES:
        raise ValueError(f"{name}: use a PNG, JPEG or WebP picture.")
    if len(data) > MAX_BYTES:
        raise ValueError(f"{name}: the picture is larger than 15 MB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)  # does nothing to a smaller picture
            out = io.BytesIO()
            if suffix in (".jpg", ".jpeg", ".webp"):
                image.convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY)
                suffix = ".jpg"
            else:
                image.save(out, "PNG")
                suffix = ".png"
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError(f"{name}: that file is not a readable picture.") from None
    return out.getvalue(), suffix


def add_photos(deal_id, files, user, kind=None, slot_id=None, db_path=None, asset_dir=None):
    """Save uploaded photos [(name, bytes)]. Returns (saved ids, problems). A bad file never stops the others."""
    if kind is not None and kind not in KIND_NAMES:
        raise ValueError("Unknown photo kind.")
    folder = Path(asset_dir or ASSET_DIR) / f"deal_{deal_id}"
    folder.mkdir(parents=True, exist_ok=True)
    saved, problems = [], []
    conn = _connect(db_path)
    try:
        with conn:
            position = conn.execute("SELECT COUNT(*) FROM om_assets WHERE deal_id = ? AND slot_id IS ?",
                                    (deal_id, slot_id)).fetchone()[0]
            for name, data in files:
                try:
                    clean, suffix = _clean_image(name, data)
                except ValueError as error:
                    problems.append(str(error))
                    continue
                number = 1 + conn.execute("SELECT COALESCE(MAX(id), 0) FROM om_assets").fetchone()[0]
                path = folder / f"photo_{number}{suffix}"
                while path.exists():
                    number += 1
                    path = folder / f"photo_{number}{suffix}"
                path.write_bytes(clean)
                original = folder / "originals" / f"photo_{number}{Path(name).suffix.lower()}"
                original.parent.mkdir(exist_ok=True)
                original.write_bytes(data)  # exactly as uploaded
                caption = Path(name).stem[:80]
                saved.append(conn.execute(
                    "INSERT INTO om_assets (deal_id, file_path, kind, caption, slot_id, position, sample, original_path) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                    (deal_id, stored_path(path), kind, caption, slot_id, position, stored_path(original))).lastrowid)
                position += 1
            if saved:
                om_slots.log(conn, deal_id, "photos_added", f"{len(saved)} photo(s)", user)
    finally:
        conn.close()
    return saved, problems


def assets(deal_id, db_path=None):
    conn = _connect(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM om_assets WHERE deal_id = ? ORDER BY slot_id, position, id",
                                              (deal_id,))]
    finally:
        conn.close()


def set_kind(deal_id, asset_id, kind, user, db_path=None):
    if kind not in KIND_NAMES:
        raise ValueError("Unknown photo kind.")
    _update(deal_id, asset_id, "kind = ?", (kind,), "photo_kind", user, db_path)


def place(deal_id, asset_id, slot_id, user, db_path=None, template=None):
    """Put a photo on a photo slot (or take it off with slot_id=None). The slot must accept its kind."""
    if slot_id is not None:
        slot = (template or om_template.load()).slots.get(slot_id)
        if slot is None or slot.type != "photo":
            raise ValueError("That is not a photo slot.")
        conn = _connect(db_path)
        try:
            row = conn.execute("SELECT kind FROM om_assets WHERE id = ? AND deal_id = ?", (asset_id, deal_id)).fetchone()
            position = conn.execute("SELECT COUNT(*) FROM om_assets WHERE deal_id = ? AND slot_id = ?",
                                    (deal_id, slot_id)).fetchone()[0]
        finally:
            conn.close()
        if row is None:
            raise ValueError("That photo could not be found.")
        if row["kind"] not in slot.photo_kinds:
            names = " or ".join(KIND_NAMES[k].lower() for k in slot.photo_kinds)
            raise ValueError(f"{slot.label} needs a {names} photo.")
        _update(deal_id, asset_id, "slot_id = ?, position = ?", (slot_id, position), "photo_placed", user, db_path)
    else:
        _update(deal_id, asset_id, "slot_id = NULL, position = 0", (), "photo_unplaced", user, db_path)


def remove(deal_id, asset_id, user, db_path=None):
    """Take a photo out of the OM. The file stays on disk (git-ignored); the row goes."""
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM om_assets WHERE id = ? AND deal_id = ?", (asset_id, deal_id))
            om_slots.log(conn, deal_id, "photo_removed", str(asset_id), user)
    finally:
        conn.close()


def _update(deal_id, asset_id, assignments, params, action, user, db_path):
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(f"UPDATE om_assets SET {assignments} WHERE id = ? AND deal_id = ?", (*params, asset_id, deal_id))
            om_slots.log(conn, deal_id, action, str(asset_id), user)
    finally:
        conn.close()


# ---------- the slide editor: one photo at a time, straight onto a slot (no AI) ----------

def _photo_slot(slot_id, template):
    slot = (template or om_template.load()).slots.get(slot_id)
    if slot is None or slot.type != "photo":
        raise ValueError("That is not a photo slot.")
    return slot


def _make_room(deal_id, slot, replace_id, db_path):
    """Take the photo being replaced off the slot (it stays in the deal's photos), or check there is room."""
    rows = [a for a in assets(deal_id, db_path) if a["slot_id"] == slot.id]
    if replace_id is not None:
        if replace_id not in [a["id"] for a in rows]:
            raise ValueError("The photo to replace is not on this slide any more.")
        return [a["id"] for a in rows].index(replace_id)
    if len(rows) >= slot.count:
        raise ValueError(f"{slot.label} already has {slot.count} photo{'s' if slot.count != 1 else ''}. Replace or remove one first.")
    return len(rows)


def add_to_slot(deal_id, slot_id, name, data, user, replace_id=None, db_path=None, asset_dir=None, template=None):
    """Save one photo (uploaded or taken with the camera) onto a photo slot. Returns the new photo's ID.

    The broker chose the slot, so the photo gets the slot's own kind. Replacing takes the old photo off
    the slot; it stays in the deal's photos and can be chosen again.
    """
    slot = _photo_slot(slot_id, template)
    position = _make_room(deal_id, slot, replace_id, db_path)
    saved, problems = add_photos(deal_id, [(name, data)], user, kind=slot.photo_kinds[0], db_path=db_path, asset_dir=asset_dir)
    if not saved:
        raise ValueError(problems[0] if problems else "That photo could not be saved.")
    if replace_id is not None:
        _update(deal_id, replace_id, "slot_id = NULL, position = 0", (), "photo_unplaced", user, db_path)
    _update(deal_id, saved[0], "slot_id = ?, position = ?", (slot.id, position), "photo_placed", user, db_path)
    return saved[0]


def use_on_slot(deal_id, slot_id, asset_id, user, replace_id=None, db_path=None, template=None):
    """Put a photo the deal already has onto a slot (the "Choose from this deal's photos" list)."""
    slot = _photo_slot(slot_id, template)
    position = _make_room(deal_id, slot, replace_id, db_path)
    row = next((a for a in assets(deal_id, db_path) if a["id"] == asset_id), None)
    if row is None:
        raise ValueError("That photo could not be found.")
    if replace_id is not None:
        _update(deal_id, replace_id, "slot_id = NULL, position = 0", (), "photo_unplaced", user, db_path)
    kind = row["kind"] if row["kind"] in slot.photo_kinds else slot.photo_kinds[0]
    _update(deal_id, asset_id, "kind = ?, slot_id = ?, position = ?", (kind, slot.id, position), "photo_placed", user, db_path)


def take_off_slot(deal_id, asset_id, user, db_path=None):
    """"Remove" on a slide: the photo leaves the slide but stays in the deal's photos."""
    _update(deal_id, asset_id, "slot_id = NULL, position = 0", (), "photo_unplaced", user, db_path)


def set_fit(deal_id, asset_id, fit, user, db_path=None):
    """"Show whole photo" (default) or "Fill the frame (crops)": the broker's choice for one photo."""
    if fit not in FITS:
        raise ValueError("A photo is shown whole or fills its frame.")
    _update(deal_id, asset_id, "fit = ?", (fit,), f"photo_fit_{fit}", user, db_path)


def orientation(size):
    """'landscape', 'portrait' or 'square' (within 10%)."""
    w, h = size
    return "square" if abs(w - h) <= 0.1 * max(w, h) else "landscape" if w > h else "portrait"


def fitted(size, frame):
    """Where a whole photo of `size` sits inside `frame` (x, y, w, h): (x, y, w, h), centred, never cut."""
    fx, fy, fw, fh = frame
    scale = min(fw / size[0], fh / size[1])
    w, h = size[0] * scale, size[1] * scale
    return fx + (fw - w) / 2, fy + (fh - h) / 2, w, h


def resolution(size, frame_inches, fit="whole"):
    """("Good" or "Low resolution", dpi) for a photo of `size` pixels shown in a frame (width, height) in inches."""
    fw, fh = frame_inches
    # Printed width of the photo: it fits inside the frame when whole, and covers it (and more) when filling.
    shown_w = max(fw, fh * size[0] / size[1]) if fit == "fill" else fitted(size, (0, 0, fw, fh))[2]
    dpi = size[0] / shown_w if shown_w else 0
    return ("Good" if dpi >= GOOD_DPI else "Low resolution"), round(dpi)


def preview(path_or_file, ratio, fit="whole", width=1200, backing=(231, 227, 218)):
    """PNG bytes of the photo in a frame of shape `ratio` (width / height) exactly as the slide shows it:
    whole and centred on the stone backing, or cut from the centre when the broker chose 'fill'."""
    with Image.open(path_or_file) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        frame = (width, max(1, round(width / ratio)))
        if fit == "fill":
            out = ImageOps.fit(image, frame, Image.Resampling.LANCZOS)
        else:
            out = Image.new("RGB", frame, backing)
            x, y, w, h = fitted(image.size, (0, 0, *frame))
            out.paste(image.resize((max(1, round(w)), max(1, round(h))), Image.Resampling.LANCZOS), (round(x), round(y)))
        data = io.BytesIO()
        out.save(data, "PNG")
    return data.getvalue()


def image_size(path_or_file):
    with Image.open(path_or_file) as image:
        return ImageOps.exif_transpose(image).size


def auto_place(deal_id, user, db_path=None, template=None):
    """Fill empty photo slots, required ones first, with unplaced photos of a kind the slot accepts.

    Returns the number of photos placed. Photos without a kind are left alone (sort them first).
    """
    plan = [step for step in plan_placement(deal_id, [], db_path, template) if step["slot_id"]]
    for step in plan:
        place(deal_id, step["asset_id"], step["slot_id"], user, db_path, template)
    return len(plan)


def plan_placement(deal_id, proposals, db_path=None, template=None):
    """Where each unplaced photo would go, without saving anything: [{asset_id, kind, slot_id or None}].

    proposals: [{asset_id, kind}] from sort_photos (the AI's guess of what each photo shows); photos that
    already have a kind keep it. Empty photo slots are filled required ones first, in template order.
    """
    template = template or om_template.load()
    rows = assets(deal_id, db_path)
    kinds = {p["asset_id"]: p["kind"] for p in proposals}
    loose = [dict(a, kind=kinds.get(a["id"], a["kind"])) for a in rows if a["slot_id"] is None]
    plan = {a["id"]: {"asset_id": a["id"], "kind": a["kind"], "slot_id": None} for a in loose
            if a["kind"] or a["id"] in kinds}
    loose = [a for a in loose if a["kind"]]
    slots = sorted((s for s in template.slots.values() if s.type == "photo"), key=lambda s: not s.required)
    for slot in slots:
        have = sum(1 for a in rows if a["slot_id"] == slot.id)
        for _ in range(max(0, slot.count - have)):
            # Prefer the slot's first kind (an aerial slot takes an aerial before a map).
            match = next((a for kind in slot.photo_kinds for a in loose if a["kind"] == kind), None)
            if match is None:
                break
            loose.remove(match)
            plan[match["id"]]["slot_id"] = slot.id
    return list(plan.values())


def apply_plan(deal_id, plan, user, db_path=None, template=None):
    """A person checked the proposed places and clicked Place them. Returns how many photos were placed."""
    placed = 0
    for step in plan:
        if step["kind"] in KIND_NAMES:
            set_kind(deal_id, step["asset_id"], step["kind"], user, db_path)
        if step["slot_id"]:
            try:
                place(deal_id, step["asset_id"], step["slot_id"], user, db_path, template)
            except ValueError:
                continue  # the slot filled up or the photo went since the list was shown
            placed += 1
    return placed


def needs_summary(state):
    """'Needs 3 more exterior or interior photos' lines for the required photo slots still short."""
    lines = []
    for slot_state in state.slots.values():
        if slot_state.slot.type == "photo" and slot_state.slot.required and slot_state.status == "empty":
            lines.append(f"{slot_state.slot.label}: needs {slot_state.needs[0]}" if slot_state.needs else slot_state.slot.label)
    return lines


# ---------- "Sort my photos": one vision request per batch ----------

SORT_PROMPT = """PHOTO SORT. You are labelling photos a commercial real estate broker uploaded for an offering memorandum.
For each photo, in order, say what it shows. kind is exactly one of: aerial, exterior, interior, site_plan, map.
- aerial: taken from above (drone, plane, satellite style)
- exterior: the outside of a building from ground level
- interior: inside a building
- site_plan: a drawn plan of the site (lines, labels, parking layout)
- map: a street or regional map
If you cannot tell, use "unsure". Never guess an address or a name. Describe each in at most 8 words.
Return JSON: {"photos": [{"index": <1-based number>, "kind": "...", "description": "..."}]}
There are {count} photos."""


class PhotoLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    kind: str
    description: str = ""


class SortReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photos: list[PhotoLabel]


def _thumbnail(path):
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((768, 768))
        out = io.BytesIO()
        image.save(out, "JPEG", quality=80)
    return out.getvalue()


def sort_photos(deal_id, client=None, db_path=None):
    """Propose a kind for each photo that has none. One Gemini request per batch of BATCH photos.

    Returns (proposals [{asset_id, kind, description}], requests used). Nothing is saved.
    """
    todo = [a for a in assets(deal_id, db_path) if not a["kind"] and full_path(a["file_path"]).exists()]
    proposals, requests = [], 0
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        parts = [types.Part.from_text(text=SORT_PROMPT.replace("{count}", str(len(batch))))]
        parts += [types.Part.from_bytes(data=_thumbnail(full_path(a["file_path"])), mime_type="image/jpeg") for a in batch]
        reply = gemini.generate(client or gemini.get_client(), parts, config)
        requests += 1
        try:
            labels = SortReply.model_validate(json.loads(reply)).photos
        except (ValueError, ValidationError):
            raise gemini.GeminiError("The AI's reply could not be read. Nothing was changed.") from None
        for label in labels:
            if 1 <= label.index <= len(batch) and label.kind in KIND_NAMES:
                proposals.append({"asset_id": batch[label.index - 1]["id"], "kind": label.kind,
                                  "description": label.description[:80]})
    return proposals, requests


def apply_kinds(deal_id, proposals, user, db_path=None):
    """A person clicked Apply on the sort proposals."""
    for proposal in proposals:
        set_kind(deal_id, proposal["asset_id"], proposal["kind"], user, db_path)


# ---------- sample illustrations for the demo deals ----------

SAMPLE_COLOURS = {"aerial": (96, 128, 104), "exterior": (120, 150, 170), "interior": (176, 160, 132),
                  "site_plan": (236, 234, 226), "map": (214, 222, 206)}


def draw_sample(kind, path, number=1, size=(1600, 1000)):
    """A plain made-up drawing of the given kind, marked SAMPLE ILLUSTRATION. Not a real place."""
    image = Image.new("RGB", size, SAMPLE_COLOURS[kind])
    d = ImageDraw.Draw(image)
    w, h = size
    shift = (number * 97) % 200
    if kind == "aerial":
        d.rectangle([0, h * 0.45, w, h * 0.55], fill=(150, 150, 145))
        for i in range(3):
            x = 220 + i * 420 + shift // 3
            d.rectangle([x, 160, x + 320, 380], fill=(225, 225, 220), outline=(80, 80, 80), width=4)
        d.rectangle([260, h * 0.62, w - 260, h - 140], fill=(110, 110, 110))
    elif kind == "exterior":
        d.rectangle([0, h * 0.72, w, h], fill=(150, 150, 140))
        d.rectangle([200 + shift, 380, w - 200, h * 0.74], fill=(232, 230, 222), outline=(70, 70, 70), width=4)
        left, right = 200 + shift, w - 200
        step = (right - left) / 5
        for i in range(5):
            x = left + step * i + step * 0.15
            d.rectangle([x, 520, x + step * 0.7, h * 0.74], fill=(110, 110, 115))
    elif kind == "interior":
        d.polygon([(0, h), (w * 0.3, h * 0.55), (w * 0.7, h * 0.55), (w, h)], fill=(150, 140, 120))
        for i in range(4):
            x = 260 + i * 330
            d.rectangle([x, 300, x + 40, h * 0.6], fill=(90, 90, 90))
        d.rectangle([w * 0.3, 120, w * 0.7, 160], fill=(250, 250, 240))
    elif kind == "site_plan":
        for i in range(3):
            x = 180 + i * 450
            d.rectangle([x, 200, x + 360, 560], outline=(40, 60, 50), width=6)
            d.text((x + 20, 220), f"BLDG {chr(65 + i)}", fill=(40, 60, 50))
        for i in range(20):
            d.line([140 + i * 66, 680, 140 + i * 66, 820], fill=(120, 120, 120), width=3)
    else:
        for i in range(0, w, 160):
            d.line([i, 0, i + 300, h], fill=(170, 180, 165), width=10)
        d.ellipse([w / 2 - 30, h / 2 - 30, w / 2 + 30, h / 2 + 30], fill=(180, 40, 30))
    # Centred and short, so the label survives when a slide crops the picture to a narrow frame.
    font = ImageFont.load_default(size=40)
    for line, top in (("SAMPLE ILLUSTRATION", 40), (f"{KIND_NAMES[kind]} {number} - not a real photo", 92)):
        left, _, right, _ = d.textbbox((0, 0), line, font=font)
        x = (w - (right - left)) / 2
        d.rectangle([x - 16, top - 8, x + right - left + 16, top + 48], fill=(19, 39, 30))
        d.text((x, top), line, fill=(255, 255, 255), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    return path


def ensure_sample_files(rows):
    """Draw again any sample photo whose file is missing (om_assets/ is not in git)."""
    for number, row in enumerate(rows, start=1):
        if row.get("sample") and row.get("kind") and not full_path(row["file_path"]).exists():
            draw_sample(row["kind"], full_path(row["file_path"]), number)
