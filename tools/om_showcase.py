"""Build a complete, fictional OM in the Editorial design and render every page, to check the design by eye.

    .venv/bin/python tools/om_showcase.py

It uses its own throwaway database and folders (never the real ones), fills every slot of the Brindlewick sample
deal, adds generated vector-style illustrations in landscape, portrait and square shapes plus one deliberately
low-resolution picture, approves everything, and exports a draft and a client-ready deck (PPTX, and PDF when
LibreOffice is installed). Each PDF page is rendered at 200 dpi to screenshots/showcase/ (git-ignored).
No AI is used (0 Gemini requests). Every name, number and picture is made up.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "screenshots" / "showcase"

import db  # noqa: E402
import seed  # noqa: E402
from services import om_assets, om_engine, om_export, om_facts, om_slots  # noqa: E402

USER = "Avery Sample"
TEXT = {
    "property.address": "4180 Larkmoor Commerce Way (fictional)",
    "property.city_state": "Fort Worth, TX",
    "property.buildings": "2",
    "property.land_size": "11.6",
    "property.year_built": "2004 / 2021",
    "property.bay_doors": "18 dock-high, 6 drive-in (made up)",
    "property.clear_height": "28'",
    "offering.narrative": ("Brindlewick Retail Row is a fully leased neighbourhood centre offered free and clear, with a "
                           "mix of daily-needs tenants on staggered terms.\nThe centre sits on a busy local corridor with "
                           "good visibility, generous parking and two points of access. Every figure here is made up "
                           "for the demo."),
    "highlights.upside": ["Two leases roll to market within 24 months", "Room to add a pad site on the north lot"],
    "highlights.location_building": ["Signalised corner with two curb cuts", "Roofs and parking lot renewed (made up)",
                                     "Ample parking for every tenant"],
    "highlights.rare": ["A fully leased centre rarely offered in this corridor"],
    "location.narrative": ("The centre serves a growing residential area on a main east-west corridor.\nNearby rooftops, "
                           "a school campus and a grocery anchor across the road bring steady daily traffic. All of this "
                           "description is made up for the demo."),
    "site_plan.notes": ["Main entrance from the corridor", "Secondary access from the side street", "Parking for 140 cars"],
}
# slot -> [(kind, size)]: landscape, portrait, square and a deliberately small picture.
PHOTOS = {
    "photo.hero": [("exterior", (1500, 2100))],                 # portrait: the cover switches to a taller frame
    "photo.offering": [("exterior", (2400, 1600)), ("interior", (1800, 1800))],
    "photo.highlights_aerial": [("aerial", (2400, 1350))],
    "photo.features": [("interior", (1400, 2000))],
    "photo.site_plan": [("site_plan", (2400, 1600))],
    "photo.grid": [("exterior", (2400, 1600)), ("interior", (1600, 2200)), ("exterior", (1800, 1800))],
    "photo.location_aerial": [("map", (480, 320))],            # low resolution on purpose
    "photo.divider_property": [("aerial", (2000, 2000))],     # an opener with its optional photo
    "photo.financial": [("exterior", (2400, 1200))],
}


def build(work):
    db_path, assets = work / "showcase.db", work / "assets"
    with mock.patch.object(om_assets, "ASSET_DIR", assets), mock.patch("sample_om.ASSET_DIR", assets / "sample"):
        deal = seed.seed(db_path)["brindlewick"]
    conn = db.get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM om_assets WHERE deal_id = ?", (deal,))
        conn.execute("DELETE FROM om_slots WHERE deal_id = ? AND slot_id LIKE 'photo.%'", (deal,))
    conn.close()
    for slot_id, value in TEXT.items():
        om_slots.set_value(deal, slot_id, value, USER, db_path=db_path)
    number = 0
    for slot_id, shapes in PHOTOS.items():
        for kind, size in shapes:
            number += 1
            picture = om_assets.draw_sample(kind, work / "drawn" / f"{kind}_{number}.png", number, size)
            om_assets.add_to_slot(deal, slot_id, f"{kind.replace('_', ' ').title()} view {number} (illustration).png",
                                  picture.read_bytes(), USER, db_path=db_path, asset_dir=assets)
    conn = db.get_connection(db_path)
    try:
        facts = om_facts.load(conn, deal, "demo.broker@example.com")
    finally:
        conn.close()
    om_slots.approve(deal, om_engine.build(facts).waiting(), USER, db_path)
    conn = db.get_connection(db_path)
    try:
        facts = om_facts.load(conn, deal, "demo.broker@example.com")
    finally:
        conn.close()
    return om_engine.build(facts), facts


def empty(work):
    """The barely started Quillhaven sample, to see the draft's dashed placeholders for everything missing."""
    db_path = work / "showcase.db"
    conn = db.get_connection(db_path)
    try:
        deal = conn.execute("SELECT id FROM deals WHERE name LIKE 'Quillhaven%'").fetchone()["id"]
        facts = om_facts.load(conn, deal, "demo.broker@example.com")
    finally:
        conn.close()
    return om_engine.build(facts), facts


def render(pdf, folder, dpi=200):
    import pymupdf
    folder.mkdir(parents=True, exist_ok=True)
    pages = []
    with pymupdf.open(pdf) as document:
        for number, page in enumerate(document, start=1):
            path = folder / f"page_{number:02d}.png"
            page.get_pixmap(dpi=dpi).save(path)
            pages.append(path)
    return pages


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        state, facts = build(work)
        print(f"OM: {state.percent}% approved, {len(state.slides)} slides; text too long: {om_export.om_design.too_long(state) or 'none'}")
        for kind in ("final", "draft"):
            pptx = OUT / f"showcase_{kind}.pptx"
            slides = om_export.build_pptx(state, facts, kind, pptx)
            print(f"{kind}: {slides} pages -> {pptx.name}")
            try:
                pdf = om_export.to_pdf(pptx)
            except om_export.ExportError as error:
                print(f"  no PDF: {error}")
                continue
            pages = render(pdf, OUT / kind)
            print(f"  {len(pages)} pages rendered at 200 dpi -> {(OUT / kind).relative_to(ROOT)}")
        state, facts = empty(work)
        pptx = OUT / "showcase_empty_draft.pptx"
        om_export.build_pptx(state, facts, "draft", pptx)
        try:
            pages = render(om_export.to_pdf(pptx), OUT / "empty_draft")
            print(f"empty draft ({state.percent}% approved): {len(pages)} pages -> screenshots/showcase/empty_draft")
        except om_export.ExportError as error:
            print(f"  no PDF: {error}")


if __name__ == "__main__":
    main()
