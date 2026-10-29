"""Property pictures: a person's own photo if one was saved, otherwise the illustration for the type.

The illustrations are static files in static/property/, drawn for this app. No outside image sources.
Pictures are put into the page as data URIs, so nothing has to be served separately.
"""

import base64
from pathlib import Path

import db

ILLUSTRATIONS = Path(__file__).resolve().parent.parent / "static" / "property"
ILLUSTRATED_TYPES = {"Industrial": "industrial", "Flex": "flex", "Retail": "retail"}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}


def illustration_path(property_type):
    return ILLUSTRATIONS / f"{ILLUSTRATED_TYPES.get(property_type, 'other')}.svg"


def _data_uri(path):
    return f"data:{MIME[path.suffix.lower()]};base64,{base64.b64encode(path.read_bytes()).decode()}"


def picture(deal):
    """(data URI, is_photo) for a deal. A saved photo that has gone missing falls back to the illustration."""
    if deal.get("photo_path"):
        path = db.project_path(deal["photo_path"])
        if path.is_file() and path.suffix.lower() in MIME:
            return _data_uri(path), True
    return _data_uri(illustration_path(deal.get("property_type"))), False
