"""Connections page: every data source, its status, what it provides, and an on/off switch."""

from html import escape

import streamlit as st

from app import style
from services import connections
from services.connections.base import TIER_LABELS
from services import metrics

STATUS_PILLS = {connections.CONNECTED: "approved", connections.NOT_SET_UP: "needs-review",
                connections.DEMO: "simulated", connections.NEEDS_LICENSE: "other"}
HOW_SOURCES_ARE_USED = [
    "Only official data, free public data, web search with cited sources, and files you import.",
    "No website is ever scraped, and no unofficial scraping service is used.",
    "Sources are only called when someone clicks a button, and results are kept for 24 hours.",
    "Keys live only in the .env file. They are never shown here, printed, or saved anywhere else.",
    "Simulated (demo) sources are labelled SIMULATED. They can never be accepted, cited by the AI, or counted as research.",
]


# Where Home's meetings and emails will come from. None is connected yet (roadmap Step 8): until then the
# feed shows sample meetings and emails, each labelled Sample.
INBOX_SOURCES = [
    ("Google Calendar", "Calendar", "Meetings for the Home feed and the Today agenda."),
    ("Outlook Calendar", "Calendar", "Meetings for the Home feed and the Today agenda, via Microsoft Graph."),
    ("Gmail", "Email", "Emails about deals for the Home feed. Attachments can be added to a deal as documents."),
    ("Outlook Mail", "Email", "Emails about deals for the Home feed, via Microsoft Graph."),
]


def _inbox_card(name, kind, provides):
    key = name.lower().replace(" ", "_")
    with st.container(border=True, key=f"conn_card_inbox_{key}"):
        head = st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center")
        head.markdown(f"**{name}**", width="content")
        head.markdown(style.pill("Not connected", "other"), unsafe_allow_html=True, width="content")
        style.html(f'<div class="conn-kind">{escape(kind)}</div><div class="conn-provides">{escape(provides)}</div>')
        st.caption("Not connected yet (roadmap Step 8, pointed at a safe demo inbox). Until then Home shows "
                   "made-up sample items, each labelled Sample.")


def _switch(adapter_id, key):
    connections.set_enabled(adapter_id, st.session_state[key])


def _card(adapter, state):
    status = adapter.status(state["enabled"])
    with st.container(border=True, key=f"conn_card_{adapter.id}"):
        head = st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center")
        head.markdown(f"**{adapter.icon} {adapter.name}**", width="content")
        head.markdown(style.pill(status, STATUS_PILLS[status]), unsafe_allow_html=True, width="content")
        topics = "".join(f'<span class="chip">{escape(t)}</span>' for t in adapter.topics)
        used = metrics.time_ago(state["last_used_at"]) if state["last_used_at"] else "never"
        style.html(f'<div class="conn-kind">{escape(adapter.kind)}</div>'
                   f'<div class="conn-provides">{escape(adapter.provides)}</div>'
                   f'<div class="conn-topics">{topics}</div><div class="conn-used">Last used: {escape(used)}</div>')
        if status == connections.NOT_SET_UP:
            st.caption(adapter.key_help)
        if adapter.simulated:
            st.caption(connections.LICENSE_NOTE)
            if st.button("Connect", key=f"connect_{adapter.id}", icon=":material/link:"):
                st.session_state[f"explain_{adapter.id}"] = True
            if st.session_state.get(f"explain_{adapter.id}"):
                st.info(f"{adapter.name} cannot be connected from this prototype. Its data is licensed or partner-only, "
                        "and it is never scraped. In production, CBRE's own licence would connect here. Switching it on "
                        "only shows made-up sample findings, labelled SIMULATED.")
        if not adapter.runs_on_research:
            st.caption("Use it from a deal: Review tab > Market research > Import a market report.")
            return
        key = f"switch_{adapter.id}"
        st.toggle("On" if state["enabled"] else "Off", value=state["enabled"], key=key,
                  on_change=_switch, args=(adapter.id, key))


def render():
    st.header("Connections")
    st.caption("The data sources the AI Teammate can use for market research.")
    with st.container(border=True, key="card_how_sources"):
        style.html('<div class="card-title">How sources are used</div><ul class="takeaways">'
                   + "".join(f"<li>{escape(line)}</li>" for line in HOW_SOURCES_ARE_USED) + "</ul>"
                   '<div class="conn-tiers">' + " ".join(
                       f'<span class="tier-item"><span class="pill tier{tier}">Tier {tier}</span> {escape(label)}</span>'
                       for tier, label in TIER_LABELS.items())
                   + "</div>")
    st.caption("Switch a source off to stop Run research from using it.")
    adapters, state = connections.all_adapters(), connections.states()
    groups = [("Live sources", [a for a in adapters if not a.simulated]),
              ("Licensed sources (demo only)", [a for a in adapters if a.simulated])]
    for title, group in groups:
        style.section_title(title)
        columns = st.columns(2, gap="medium")
        for index, adapter in enumerate(group):
            with columns[index % 2]:
                _card(adapter, state[adapter.id])
    style.section_title("Calendar and email (for Home)")
    columns = st.columns(2, gap="medium")
    for index, source in enumerate(INBOX_SOURCES):
        with columns[index % 2]:
            _inbox_card(*source)
