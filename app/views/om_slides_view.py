"""The OM tab's Slides view: the slides in the template's order and an editor for one slide at a time.

Desktop and tablet: the slide list on the left, the editor on the right. Phones: Previous / Next with
"Slide 1 of 19" (CSS hides the list). Each slide shows only what it needs, in plain words.

Gemini: "Draft with AI" uses 1 request for the slide's text; "Upload many photos at once (AI places them)"
uses 1 per 8 photos. Take photo, Upload photo, choosing a photo, Replace, Remove, Save and Approve use none.
"""

import zlib
from html import escape
from pathlib import Path

import streamlit as st

from app import queries, style
from services import om_assets, om_drafting, om_export, om_slides, om_slots

DOT = {"green": "🟢", "amber": "🟠", "red": "🔴"}
PILL = {"green": "approved", "amber": "needs-review", "red": "flag"}
PHOTO_TYPES = ["png", "jpg", "jpeg", "webp"]
PREVIEW_WIDTH, PHOTO_WIDTH = 640, 360   # pixels: the slide and a photo are shown at a readable size, not full width
FILLED_BY = {"document_field": "the deal's documents", "calculated": "a calculation in code", "broker_input": "you",
             "broker_photo": "you (your photo)", "ai_text": "an AI draft", "research": "accepted research",
             "fixed": "fixed wording", "client_reply": "the client's reply", "client_document": "a client document",
             "sourced": "the AI Teammate (a sourced fact)"}


def _tab():
    from app.views import om_tab  # here: om_tab imports this module
    return om_tab


def _key(slot_id):
    return slot_id.replace(".", "_")


def go_to(slide_id):
    st.session_state.om_slide = slide_id
    st.session_state.pop("om_photo_mode", None)


@st.cache_data(max_entries=200, show_spinner=False)
def _cropped(path, modified, ratio):
    """The photo cut to its frame on the slide (cached per file version and frame shape)."""
    return om_assets.cover_crop(path, ratio)


def _cropped_bytes(data, ratio):
    import io
    return om_assets.cover_crop(io.BytesIO(data), ratio)


# ---------- the list (desktop) and the stepper (phones, and above the editor everywhere) ----------

def _list(rows, index):
    with st.container(key="om_slide_list"):
        style.section_title(f"Slides ({len(rows)})")
        for i, row in enumerate(rows):
            badges = " ".join(f":orange-badge[{b}]" for b in row.badges)
            st.button(f"{DOT[row.colour]} {row.number}. {row.slide.title} {badges}".strip(), key=f"om_slide_btn_{row.slide.id}",
                      type="primary" if i == index else "tertiary", on_click=go_to, args=(row.slide.id,), width="stretch")


def _stepper(rows, index):
    row = rows[index]
    with st.container(key="om_stepper", horizontal=True, vertical_alignment="center", horizontal_alignment="distribute"):
        st.button("Previous", key="om_slide_prev", icon=":material/arrow_back:", disabled=index == 0,
                  on_click=go_to, args=(rows[max(index - 1, 0)].slide.id,))
        st.markdown(f'<div class="om-step"><b>{escape(row.slide.title)}</b><span>Slide {index + 1} of {len(rows)}</span></div>',
                    unsafe_allow_html=True, width="content")
        st.button("Next", key="om_slide_next", icon=":material/arrow_forward:", disabled=index >= len(rows) - 1,
                  on_click=go_to, args=(rows[min(index + 1, len(rows) - 1)].slide.id,))


# ---------- one item on the slide ----------

def _source_line(item):
    """One small line: who or what filled this item (document, calculation, AI draft, broker)."""
    if item.status == "empty":
        need = "; ".join(item.needs)
        return f"Not filled yet{': needs ' + need if need else ''}"
    source = item.source or {}
    who = FILLED_BY.get(source.get("kind"), "unknown")
    detail = f" ({source['detail']})" if source.get("detail") else ""
    approved = f" · approved by {source['approved_by']}" if source.get("approved_by") and item.approved else ""
    return f"Filled by {who}{detail}{approved}"


def _item_head(item):
    status = _tab().STATUS_LABELS[item.status]
    style.html(f'<div class="om-item-head"><span class="om-item-what">{escape(item.slot.label)}</span>'
               f'{style.pill(status, _tab().STATUS_PILLS[item.status])}'
               f'{"" if item.slot.required else style.pill("Optional", "other")}</div>')


def _text_item(deal_id, item, user):
    if item.slot.id == "property.name" and (item.source or {}).get("kind") == "document_field":
        style.html(f'<div class="om-value">{escape(str(item.display))}</div>')
        st.caption("This is the deal's name. Rename it with the pencil next to the name at the top: it changes everywhere.")
        return
    current = "\n".join(item.value) if isinstance(item.value, list) else str(item.value or "")
    version = zlib.crc32(f"{item.status}{current}".encode())  # a new value (an AI draft, an undo) gets a fresh box
    hint = "One point per line." if item.slot.type == "bullets" else None
    text = st.text_area(item.slot.label, current, key=f"om_text_{_key(item.slot.id)}_{version}", help=hint,
                        height=140 if item.slot.type == "bullets" or len(current) > 120 else 96, label_visibility="collapsed",
                        placeholder=item.slot.broker_question or f"Type the {item.slot.label.lower()}")
    if st.button("Save", key=f"om_text_save_{_key(item.slot.id)}", icon=":material/save:",
                 disabled=not text.strip() or text.strip() == current.strip()):
        try:
            om_slots.set_value(deal_id, item.slot.id, text, user)
        except om_slots.InvalidValue as error:
            _tab().flash("error", str(error))
        else:
            _tab().flash("success", f"{item.slot.label} saved. Approve the slide when it is right.")
        st.rerun()


def _number_item(item):
    if item.status != "empty":
        style.html(f'<div class="om-value">{escape(str(item.display)[:400])}</div>')
    if item.slot.id == "financial.sale_price":
        st.button("Set the price" if item.status == "empty" else "Change the price", key="om_slide_price",
                  icon=":material/sell:", on_click=_tab()._go_view, args=("Pricing",))
    _tab()._how(item)


# ---------- photos ----------

def _mode(slot_id):
    mode = st.session_state.get("om_photo_mode") or {}
    return mode if mode.get("slot") == slot_id else {}


def _set_mode(slot_id, how, replace=None):
    st.session_state.om_photo_mode = {"slot": slot_id, "how": how, "replace": replace,
                                      "round": st.session_state.get("om_photo_round", 0)}


def _done(message, kind="success"):
    st.session_state.pop("om_photo_mode", None)
    st.session_state.om_photo_round = st.session_state.get("om_photo_round", 0) + 1
    _tab().flash(kind, message)
    st.rerun()


def _photo_item(deal_id, slide, item, user, library):
    slot, key = item.slot, _key(item.slot.id)
    ratio = om_export.photo_ratio(slide.layout, slot)
    mode = _mode(slot.id)
    photos = [a for a in item.photos if om_assets.full_path(a["file_path"]).exists()]
    if photos:
        columns = st.columns(min(len(photos), 2))
        for i, asset in enumerate(photos):
            path = om_assets.full_path(asset["file_path"])
            with columns[i % len(columns)], st.container(key=f"om_slot_photo_{asset['id']}"):
                st.image(_cropped(str(path), path.stat().st_mtime, round(ratio, 3)), width=PHOTO_WIDTH,
                         caption="As it will look on the slide" + (" · Sample illustration" if asset.get("sample") else ""))
                with st.container(horizontal=True):
                    st.button("Replace", key=f"om_photo_replace_{asset['id']}", icon=":material/swap_horiz:",
                              on_click=_set_mode, args=(slot.id, "choose", asset["id"]))
                    if st.button("Remove", key=f"om_photo_remove_{asset['id']}", icon=":material/delete:"):
                        om_assets.take_off_slot(deal_id, asset["id"], user)
                        _done("Photo removed from the slide. It is still in this deal's photos.", "info")
    if len(photos) >= slot.count and not mode:
        return
    replace = mode.get("replace")
    if replace:
        st.caption("Pick the new photo. The old one stays in this deal's photos.")
    else:
        left = slot.count - len(photos)
        st.caption(f"Add {left} {' or '.join(om_slides.PHOTO_WORDS[k] for k in slot.photo_kinds)} photo{'s' if left != 1 else ''}. "
                   "It is fitted to the frame automatically (cut from the centre, never stretched).")
    with st.container(horizontal=True, key=f"om_photo_ways_{key}"):
        st.button("Take photo", key=f"om_photo_take_{key}", icon=":material/photo_camera:", type="primary",
                  on_click=_set_mode, args=(slot.id, "camera", replace))
        st.button("Upload photo", key=f"om_photo_upload_{key}", icon=":material/upload:", type="primary",
                  on_click=_set_mode, args=(slot.id, "upload", replace))
        if mode:
            st.button("Cancel", key=f"om_photo_cancel_{key}", on_click=lambda: st.session_state.pop("om_photo_mode", None))
    others = [a for a in library if a["slot_id"] != slot.id and om_assets.full_path(a["file_path"]).exists()]
    if others:
        names = {a["id"]: _photo_name(a) for a in others}
        choice = st.selectbox("Choose from this deal's photos", list(names), index=None, format_func=names.get,
                              key=f"om_photo_pick_{key}_{st.session_state.get('om_photo_round', 0)}",
                              placeholder="Pick a photo this deal already has")
        if choice is not None and st.button("Use this photo", key=f"om_photo_use_pick_{key}", type="primary"):
            try:
                om_assets.use_on_slot(deal_id, slot.id, choice, user, replace_id=replace)
            except ValueError as error:
                _done(str(error), "error")
            _done(f"Photo placed on {slot.label}. Approve the slide when it looks right.")
    _capture(deal_id, slot, key, mode, ratio, user)


def _photo_name(asset):
    where = "not on a slide" if not asset["slot_id"] else f"on {asset['slot_id'].split('.', 1)[-1].replace('_', ' ')}"
    return f"{asset.get('caption') or 'Photo ' + str(asset['id'])} ({where})"


def _capture(deal_id, slot, key, mode, ratio, user):
    """The camera or the file picker, once the person chose one, then a preview and "Use this photo"."""
    if mode.get("how") not in ("camera", "upload"):
        return
    round_ = mode.get("round", 0)
    if mode["how"] == "camera":
        shot = st.camera_input("Take a photo of the property", key=f"om_cam_{key}_{round_}",
                               help="Your browser asks for permission to use the camera. Needs https (or localhost).")
        name = "camera-photo.jpg"
    else:
        shot = st.file_uploader("Choose a photo (PNG, JPEG or WebP). On a phone this also offers the camera and your photos.",
                                type=PHOTO_TYPES, key=f"om_file_{key}_{round_}")
        name = shot.name if shot is not None else ""
    if shot is None:
        return
    data = shot.getvalue()
    try:
        st.image(_cropped_bytes(data, ratio), width=PHOTO_WIDTH, caption="Preview: how it will look on the slide")
    except Exception:
        st.warning("That file is not a readable picture. Try another one.")
        return
    if st.button("Use this photo", key=f"om_photo_save_{key}", type="primary", icon=":material/check:"):
        try:
            om_assets.add_to_slot(deal_id, slot.id, name, data, user, replace_id=mode.get("replace"))
        except ValueError as error:
            _done(str(error), "error")
        _done(f"Photo added to {slot.label}. Approve the slide when it looks right.")


# ---------- the editor for one slide ----------

def _draft_box(deal, row, state, user, email):
    targets = [i for i in row.items if om_slides.can_draft(i)]
    if not targets:
        return
    with st.container(key="om_slide_draft"):
        style.html('<span class="ai-label">AI · 1 request</span>')
        writable = [i for i in targets if i.status in ("empty", "ai-draft")]
        if st.button("Draft with AI", key="om_slide_draft_btn", icon=":material/auto_awesome:", disabled=not writable,
                     help="Writes this slide's text from the deal's data. It never replaces your own text or anything approved."):
            with st.spinner("Drafting this slide..."):
                try:
                    result = om_drafting.draft_all_text(deal["id"], queries.om_facts(deal["id"], email), state, user,
                                                        only={i.slot.id for i in targets})
                except Exception as exc:
                    _tab().flash("error", _tab().ai_error(exc))
                else:
                    lines = [f"Drafted: {', '.join(result['saved'])}. Check it, then approve." if result["saved"] else "Nothing new was drafted."]
                    _tab().flash("info", " ".join(lines + result["dropped"] + result["questions"]))
            st.rerun()
        if not writable:
            st.caption("This slide's text is yours or approved, so the AI leaves it alone.")
        with st.expander("Facts the AI will use"):
            facts = queries.om_facts(deal["id"], email)
            st.text(om_drafting.facts_text(facts))
            research = om_drafting.accepted_research(deal["id"])
            st.caption(f"Plus {len(research)} accepted research finding{'s' if len(research) != 1 else ''}."
                       if research else "No accepted research yet, so the location is not drafted.")


def _preview(state, row, pages, fresh):
    page = om_export.page_of(state, row.slide.id)
    if page < len(pages):
        st.image(str(pages[page]), width=PREVIEW_WIDTH, caption="This slide as it looks now (draft)" + ("" if fresh else " · updating with your latest change"))


def _editor(deal, row, state, user, email, pages, fresh):
    library = queries.om_assets(deal["id"])
    om_assets.ensure_sample_files(library)
    with st.container(key="om_slide_editor"):
        style.html(f'<div class="slide-head">{style.pill(om_slides.COLOUR_WORDS[row.colour], PILL[row.colour])}'
                   f'<div class="slide-need">{escape(om_slides.needs_line(row.number, row.slide, state))}</div></div>')
        _preview(state, row, pages, fresh)
        if not row.items:
            st.caption("This page is fixed wording or built by the app. Nothing to fill.")
        for item in row.items:
            with st.container(key=f"om_item_{_key(item.slot.id)}"):
                _item_head(item)
                if item.slot.type == "photo":
                    _photo_item(deal["id"], row.slide, item, user, library)
                elif om_slides.is_text(item):
                    _text_item(deal["id"], item, user)
                else:
                    _number_item(item)
                style.html(f'<div class="om-source">{escape(_source_line(item))}</div>')
        _draft_box(deal, row, state, user, email)
        waiting = om_slides.waiting_items(state, row.slide)
        label = f"Approve this slide ({len(waiting)} item{'s' if len(waiting) != 1 else ''})" if waiting else "Approve this slide"
        if st.button(label, key="om_slide_approve", type="primary", icon=":material/done_all:", disabled=not waiting,
                     width="stretch"):
            om_slots.approve(deal["id"], waiting, user)
            _tab().flash("success", f"Slide {row.number} - {row.slide.title}: {len(waiting)} item{'s' if len(waiting) != 1 else ''} approved.")
            st.rerun()
        if not waiting:
            st.caption("Nothing on this slide is waiting for approval." if row.colour != "red" else
                       "Fill what is missing first; filled items can then be approved.")


# ---------- "Upload many photos at once (AI places them)": folded away ----------

def _many_photos(deal, state, user):
    deal_id = deal["id"]
    with st.expander("Upload many photos at once (AI places them)", expanded=bool(st.session_state.get("om_bulk_plan"))):
        st.caption(f"The AI looks at the photos (1 request per {om_assets.BATCH} photos) and the app proposes which slide each "
                   "goes on. Nothing is placed until you check the list and click Place them.")
        files = st.file_uploader("Photos (PNG, JPEG or WebP)", type=PHOTO_TYPES, accept_multiple_files=True,
                                 key=f"om_bulk_files_{st.session_state.get('om_bulk_round', 0)}")
        if st.button("Upload and propose places", key="om_bulk_go", icon=":material/auto_awesome:", disabled=not files):
            saved, problems = om_assets.add_photos(deal_id, [(f.name, f.getvalue()) for f in files], user)
            st.session_state.om_bulk_round = st.session_state.get("om_bulk_round", 0) + 1
            try:
                proposals = om_assets.sort_photos(deal_id)[0]
            except Exception as exc:
                _tab().flash("warning", f"{len(saved)} photo(s) saved, not placed. {_tab().ai_error(exc)}")
            else:
                st.session_state.om_bulk_plan = om_assets.plan_placement(deal_id, proposals)
                if problems:
                    _tab().flash("warning", " ".join(problems))
            st.rerun()
        plan = st.session_state.get("om_bulk_plan")
        if not plan:
            return
        names = {a["id"]: a.get("caption") or f"Photo {a['id']}" for a in queries.om_assets(deal_id)}
        style.html('<span class="ai-label">Proposed places: check before placing</span>')
        for step in plan:
            after = state.slots[step["slot_id"]].slot.label if step["slot_id"] in state.slots else "Not placed (no free slot)"
            st.markdown(f"- **{escape(names.get(step['asset_id'], str(step['asset_id'])))}** "
                        f"({om_assets.KIND_NAMES.get(step['kind'], 'not sure')}): Not placed → {escape(after)}")
        with st.container(horizontal=True):
            if st.button("Place them", key="om_bulk_apply", type="primary"):
                placed = om_assets.apply_plan(deal_id, plan, user)
                st.session_state.pop("om_bulk_plan")
                _tab().flash("success", f"{placed} photo(s) placed. Approve each slide when it looks right.")
                st.rerun()
            if st.button("Cancel", key="om_bulk_cancel"):
                st.session_state.pop("om_bulk_plan")
                _tab().flash("info", "Nothing placed. The photos are kept in this deal's photos.")
                st.rerun()


# ---------- the view ----------

def render(state, deal, user, email):
    rows = om_slides.rows(state)
    ids = [r.slide.id for r in rows]
    if st.session_state.get("om_slide") not in ids:
        st.session_state.om_slide = ids[0]
    index = ids.index(st.session_state.om_slide)
    pdf, fresh, _ = om_export.live_preview(deal["id"], state, queries.om_facts(deal["id"], email))
    pages = om_export.page_images(pdf, zoom=1.0) if pdf and Path(pdf).exists() else []
    with st.container(key="om_slides_layout"):
        left, right = st.columns([1, 2.4], gap="medium")
        with left:
            _list(rows, index)
        with right:
            _stepper(rows, index)
            _editor(deal, rows[index], state, user, email, pages, fresh)
    _many_photos(deal, state, user)
