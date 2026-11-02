"""The deal's Documents tab: every file with its type, source, date, size and status; what was read from it;
where its data is used; upload, "Read it now" and unlocking a password-protected PDF.

Viewing only reads. Writes happen on a click through services/documents.py. "Read it now" uses one Gemini
request. A password is used once, in memory, and never saved or shown again.
"""

import mimetypes
from html import escape
from pathlib import Path

import streamlit as st

from app import nav, om_status, queries, style
from services import documents, gemini

STATUS_PILLS = {"Read": "approved", "Received": "needs-review", "Reference only": "other", "Needs password": "flag"}


def _user():
    return (st.session_state.get("user") or {}).get("full_name", "Broker")


def _flash(kind, text):
    st.session_state.docs_flash = (kind, text)


def _upload(deal):
    round_ = st.session_state.get("docs_round", 0)
    with st.container(key="docs_upload"):
        style.section_title("Add documents")
        files = st.file_uploader("Drag files here, or tap to choose (xlsx, csv, pdf, docx or photos)",
                                 type=[e.lstrip(".") for e in documents.EXTENSIONS], accept_multiple_files=True,
                                 max_upload_size=documents.MAX_BYTES // 1024 // 1024, key=f"docs_files_{deal['id']}_{round_}")
        st.caption(f"Up to {documents.MAX_BYTES // 1024 // 1024} MB each. Sample data only: never upload real client files. "
                   "Files are kept on this server only. New files start as Received; photos go to the OM photo sorter.")
        if st.button("Add to this deal", key="docs_add", type="primary", icon=":material/upload_file:", disabled=not files):
            results = documents.add_documents(deal["id"], [(f.name, f.getvalue()) for f in files])
            st.session_state.docs_round = round_ + 1
            ok = [r for r in results if r["status"]]
            lines = [f"{r['filename']}: {r['message']}" for r in results]
            _flash("success" if len(ok) == len(results) else "warning", " · ".join(lines))
            st.rerun()


def _read_now(doc):
    with st.spinner(f"Reading {doc['filename']} with the AI..."):
        try:
            summary = documents.read_now(doc["id"])
        except documents.DocumentError as error:
            _flash("warning", str(error))
        except gemini.GeminiQuotaError as error:
            _flash("warning", f"The AI's daily quota is used up, so it can't read this right now. {error} "
                              "The file stays Received; try again later.")
        except gemini.RateLimited as error:
            _flash("warning", f"{error} The file stays Received.")
        except gemini.GeminiError as error:
            _flash("warning", f"The AI couldn't read it just now. {error} The file stays Received.")
        else:
            flags = summary["flags_raised"]
            _flash("success", f"Read {doc['filename']}: {summary['units_saved']} units, {flags} flag{'s' if flags != 1 else ''}. "
                              "See the Review tab.")
    st.rerun()


def _unlock(doc):
    with st.container(key=f"doc_lock_{doc['id']}"):
        st.markdown("**This file is password-protected.** Type its password to unlock it. The password is used once "
                    "and is never saved. Or ask the sender for an unlocked copy.")
        password = st.text_input("Password", type="password", key=f"doc_password_{doc['id']}")
        if st.button("Unlock", key=f"doc_unlock_{doc['id']}", type="primary", icon=":material/lock_open:"):
            try:
                kind = documents.unlock(doc["id"], password)
            except documents.DocumentError as error:
                st.session_state.pop(f"doc_password_{doc['id']}", None)
                _flash("error", str(error))
            else:
                st.session_state.pop(f"doc_password_{doc['id']}", None)
                _flash("success", f"Unlocked {doc['filename']} ({kind}). An unlocked copy was saved; the password was not.")
            st.rerun()


def _uses(doc, om_state):
    """(OM items that come from this document, short text)."""
    if doc.get("used_for") == "OM photos":
        stem = Path(doc["filename"]).stem
        slots = [s for s in om_state.slots.values() if s.slot.type == "photo"
                 and any((a.get("caption") or "") == stem[:80] for a in s.photos)]
        return len(slots)
    return sum(1 for s in om_state.slots.values() if doc["filename"] in (s.source or {}).get("detail", ""))


def _card(doc, deal, units, flags, t12, om_state, focus):
    used = _uses(doc, om_state)
    with st.container(key=f"doc_card_{doc['id']}"):
        meta = " · ".join(x for x in (doc.get("doc_type") or "Type not known", doc.get("source") or "Upload",
                                      f"added {str(doc['received_at'])[:10]}", documents.size_text(doc)) if x)
        style.html(f'<div class="doc-head"><span class="doc-name">{escape(doc["filename"])}</span>'
                   f'{style.pill(doc["status"], STATUS_PILLS.get(doc["status"]))}</div>'
                   f'<div class="doc-meta">{escape(meta)}</div>'
                   f'<div class="doc-read">{escape(documents.what_we_read(doc, units, flags, t12, used))}</div>'
                   + (f'<div class="doc-used">Used in OM: {used} item{"s" if used != 1 else ""}</div>' if used else ""))
        if doc["status"] == "Needs password":
            _unlock(doc)
        with st.container(horizontal=True, key=f"doc_actions_{doc['id']}"):
            path = Path(doc.get("file_path") or "")
            has_file = bool(doc.get("file_path")) and path.is_file()
            if has_file:
                st.download_button("Download original", path.read_bytes(), file_name=doc["filename"],
                                   mime=mimetypes.guess_type(doc["filename"])[0] or "application/octet-stream",
                                   key=f"doc_dl_{doc['id']}", icon=":material/download:")
            if doc["status"] == "Received" and doc.get("doc_type") == "Rent roll" and has_file:
                if st.button("Read it now", key=f"doc_read_{doc['id']}", type="primary", icon=":material/auto_awesome:",
                             help="Reads the rent roll with the AI (1 request), then checks it."):
                    _read_now(doc)
            if doc["status"] == "Read":
                st.button("See the data", key=f"doc_data_{doc['id']}", icon=":material/table:",
                          on_click=nav.open_deal_at, args=(deal["id"], "Data"))
            if used:
                st.button("Open the OM", key=f"doc_om_{doc['id']}", icon=":material/slideshow:",
                          on_click=nav.open_deal_at, args=(deal["id"], "OM"))
            with st.popover("Change type", icon=":material/edit:", key=f"doc_type_{doc['id']}"):
                current = doc.get("doc_type") if doc.get("doc_type") in documents.TYPES else "Other"
                kind = st.selectbox("Type", documents.TYPES, index=documents.TYPES.index(current), key=f"doc_kind_{doc['id']}")
                if st.button("Save type", key=f"doc_kind_save_{doc['id']}", type="primary"):
                    documents.set_type(doc["id"], kind)
                    st.rerun()
                if doc["status"] == "Received" and st.button("Keep as reference only", key=f"doc_ref_{doc['id']}"):
                    documents.mark_reference(doc["id"])
                    st.rerun()
    if focus == doc["id"]:
        st.html(f"""<script>setTimeout(function () {{
          const card = document.querySelector(".st-key-doc_card_{int(doc['id'])}");
          if (card) {{ card.scrollIntoView({{behavior: "smooth", block: "center"}}); card.classList.add("flag-focus");
            setTimeout(function () {{ card.classList.remove("flag-focus"); }}, 2500); }} }}, 400);</script>""",
                unsafe_allow_javascript=True)


def render(deal):
    docs = queries.deal_documents(deal["id"])
    message = st.session_state.pop("docs_flash", None)
    if message:
        getattr(st, message[0])(message[1])
    if docs:
        style.html(f'<div class="docs-summary">{escape(documents.summary_line(docs))}</div>')
    focus = st.session_state.pop("focus_document", None)
    if not docs:
        style.html('<div class="docs-empty"><b>No documents yet.</b> Add the rent roll, T-12, BOV, OM, appraisal or photos '
                   'below. The rent roll can then be read with one tap.</div>')
    else:
        units, flags = queries.deal_units(deal["id"]), queries.deal_flags(deal["id"])
        t12, om_state = queries.deal_t12_with_documents(deal["id"]), om_status.state(deal["id"])
        for doc in docs:
            _card(doc, deal, units, flags, t12, om_state, focus)
    _upload(deal)
