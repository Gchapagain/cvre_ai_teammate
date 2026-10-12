"""Data tab: download this deal's saved data. Files are built from SQLite when the tab is shown."""

import streamlit as st

from app import exports, queries

EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _table_downloads(title, table, file_stem, sheet_name, key):
    st.markdown(f"**{title}**")
    csv_column, excel_column, _ = st.columns([1, 1, 3])
    csv_column.download_button(f"{title} (CSV)", exports.to_csv(table), f"{file_stem}.csv", "text/csv",
                               key=f"{key}_csv", width="stretch")
    excel_column.download_button(f"{title} (Excel)", exports.to_excel(table, sheet_name), f"{file_stem}.xlsx",
                                 EXCEL_TYPE, key=f"{key}_xlsx", width="stretch")
    st.caption(f"Downloads {file_stem}.csv or {file_stem}.xlsx · {len(table)} rows")


def draft_text(deal, draft):
    """The draft as plain text, with its review status on the first line so it cannot pass as final."""
    heading = f"{deal['name']}\nDraft narrative - status: {draft['status']}. AI draft, not a pricing decision.\n"
    return f"{heading}\n{draft['title'] or ''}\n\n{draft['body']}\n".encode("utf-8")


def render(deal):
    stem = exports.slug(deal["name"])
    units, t12, draft = queries.deal_units(deal["id"]), queries.deal_t12(deal["id"]), queries.latest_draft(deal["id"])

    st.subheader("Downloads")
    st.caption("Each file is built from what is saved for this deal, exactly as extracted. Sample data only.")

    if units:
        table = exports.rent_roll_table(units, queries.deal_flags(deal["id"]))
        _table_downloads("Rent roll", table, f"{stem}_rent_roll", "Rent roll", "download_rent_roll")
    else:
        st.info("Rent roll: nothing saved for this deal yet.")

    if t12:
        _table_downloads("T-12", exports.t12_table(t12), f"{stem}_t12", "T-12", "download_t12")
    else:
        st.info("T-12: nothing saved for this deal yet.")

    st.markdown("**Draft narrative**")
    if draft:
        st.download_button("Draft narrative (text)", draft_text(deal, draft), f"{stem}_draft_narrative.txt",
                           "text/plain", key="download_draft")
        st.caption(f"Downloads {stem}_draft_narrative.txt")
    else:
        st.info("Draft narrative: none yet. Drafting comes in a later step.")
    st.caption("PDF export comes in a later step.")
