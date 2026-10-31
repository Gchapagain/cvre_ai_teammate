"""The broker's own logo for the OM cover, uploaded on the Settings page.

Saved under branding/ (git-ignored), one file per broker. No company logo is ever in the code or the repo.
"""

import hashlib
from pathlib import Path

from services import om_assets

ROOT = Path(__file__).resolve().parent.parent
BRANDING_DIR = ROOT / "branding"
MAX_BYTES = 5 * 1024 * 1024


def _stem(email):
    return "logo_" + hashlib.sha256((email or "").lower().encode()).hexdigest()[:12]


def logo_path(email, folder=None):
    """The broker's logo file, or None."""
    folder = Path(folder or BRANDING_DIR)
    return next((p for p in sorted(folder.glob(f"{_stem(email)}.*")) if p.suffix in (".png", ".jpg")), None)


def save_logo(email, name, data, folder=None):
    """Check, resize and save a PNG / JPEG / WebP logo up to 5 MB. Replaces any earlier logo."""
    if len(data) > MAX_BYTES:
        raise ValueError("The logo is larger than 5 MB.")
    clean, suffix = om_assets._clean_image(name, data)
    remove_logo(email, folder)
    folder = Path(folder or BRANDING_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_stem(email)}{suffix}"
    path.write_bytes(clean)
    return path


def remove_logo(email, folder=None):
    folder = Path(folder or BRANDING_DIR)
    for path in folder.glob(f"{_stem(email)}.*"):
        path.unlink()
