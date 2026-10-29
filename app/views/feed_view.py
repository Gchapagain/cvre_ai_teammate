"""The Home notification feed: cards built live from the database (services/feed.py), refreshed every 60
seconds from the database only. Nothing here calls an outside service by itself; Prep brief calls Gemini
once, only when clicked.
"""

import json
import logging
from datetime import datetime, time, timedelta
from html import escape

import streamlit as st

from app import icons, nav, queries, style
from services import briefs, drafting, feed, gemini, notifications

log = logging.getLogger(__name__)

ICONS = {feed.FLAG: icons.FLAG, feed.WAITING_KIND: icons.HOURGLASS, feed.MEETING: icons.CALENDAR, feed.EMAIL: icons.MAIL}
REFRESH_SECONDS = 60


def css_key(item):
    return item.key.replace(":", "_").replace(" ", "_")


def _rerun():
    st.rerun()  # the whole page, so the greeting count and the bell match the feed


def _brief_html(meeting):
    brief = feed_brief(meeting)
    if not brief:
        return ""
    lines = "".join(f"<li>{escape(line.lstrip('- ').strip())}</li>" for line in brief["text"].splitlines() if line.strip())
    check = ('<div class="brief-check ok">Every number was found in the deal\'s data.</div>' if not brief["unverified"]
             else f'<div class="brief-check">{style.pill("Not verified", "not-verified")} These numbers could not be found '
                  f'in the deal\'s data: {escape(drafting.show_numbers(brief["unverified"]))}</div>')
    return (f'<div class="brief"><div class="brief-head"><span class="ai-label">{icons.SPARKLE} AI-drafted</span>'
            f'<span class="brief-when">Prep brief from this deal\'s saved data</span></div><ul>{lines}</ul>{check}</div>')


def feed_brief(meeting):
    """The saved prep brief ({text, unverified}) for a meeting, or None."""
    try:
        return json.loads(meeting["brief"]) if meeting.get("brief") else None
    except ValueError:
        return None


def _prep_brief(item, now):
    meeting = item.extra["meeting"]
    try:
        with st.spinner("Writing the prep brief..."):
            briefs.generate_brief(meeting["id"], now=now.replace(tzinfo=None))
        message = None
    except gemini.GeminiQuotaError as exc:
        message = f"The AI's daily quota is used up, so no brief was written. {exc}"
    except gemini.GeminiBusyError:
        message = "The AI is busy or rate-limited at the moment. Try again in a minute."
    except gemini.RateLimited as exc:
        message = str(exc)
    except (gemini.GeminiError, ValueError) as exc:
        message = f"The AI couldn't write a brief just now. {exc}"
    except Exception:
        log.exception("Prep brief failed")
        message = "Something went wrong while writing the brief. Nothing was saved."
    st.session_state[f"brief_message_{meeting['id']}"] = message


def _do(action, item, now):
    """What a card's button does. Every action also marks the item as read."""
    notifications.mark_read([item.key], now.replace(tzinfo=None))
    if action == "review_flag":
        nav.open_deal_at(item.deal_id, "Review", item.extra["flag_id"])
    elif action == "open_review":
        nav.open_deal_at(item.deal_id, "Review")
    elif action == "open_deal":
        nav.open_deal(item.deal_id)
    elif action == "prep_brief":
        _prep_brief(item, now)
    elif action == "add_email":
        names = item.extra["email"]["attachment_names"]
        notifications.add_email_to_deal(item.extra["email"]["id"], item.deal_id)
        st.session_state.home_flash = (f"Added {', '.join(names)} to {feed.short_name(item.deal_name)} as "
                                       f"{'a document' if len(names) == 1 else 'documents'} (source Email, status Received).")
    elif action == "dismiss_email":
        notifications.dismiss_email(item.extra["email"]["id"])
    _rerun()


def _add_email_picker(item, now):
    """An email not linked to a deal: the person picks the deal first."""
    with st.popover("Add to deal", key=f"pick_{css_key(item)}"):
        choices = dict(queries.deal_choices())
        deal_id = st.selectbox("Add the attachments to", list(choices), format_func=choices.get, index=None,
                               placeholder="Choose a deal", key=f"pick_deal_{css_key(item)}")
        if st.button("Add", key=f"pick_add_{css_key(item)}", type="primary", disabled=deal_id is None):
            notifications.mark_read([item.key], now.replace(tzinfo=None))
            notifications.add_email_to_deal(item.extra["email"]["id"], deal_id)
            st.session_state.home_flash = (f"Added {', '.join(item.extra['email']['attachment_names'])} to "
                                           f"{feed.short_name(choices[deal_id])} (source Email, status Received).")
            _rerun()


def _overflow(item, now):
    with st.popover("⋯", key=f"more_{css_key(item)}", help="More"):
        if not item.read and st.button("Mark as read", key=f"read_{css_key(item)}", type="tertiary"):
            notifications.mark_read([item.key], now.replace(tzinfo=None))
            _rerun()
        if item.can_hide:
            if st.button("Snooze 1 day", key=f"snooze_{css_key(item)}", type="tertiary"):
                notifications.snooze(item.key, now.replace(tzinfo=None))
                _rerun()
            if st.button("Dismiss", key=f"dismiss_{css_key(item)}", type="tertiary"):
                notifications.dismiss(item.key, now.replace(tzinfo=None))
                _rerun()
        else:
            st.caption("Flags cannot be snoozed or dismissed. Resolve the flag on the deal and it leaves the feed.")


def _card(item, now):
    accent = "ai" if item.ai else item.kind
    state = "read" if item.read else "unread"
    with st.container(key=f"feeditem_{accent}_{state}_{css_key(item)}"):
        chips = (f'<span class="chip sample">Sample</span>' if item.sample else "") + (
            f'<span class="ai-label small">{icons.SPARKLE} AI</span>' if item.ai else "")
        deal = f'<span class="feed-deal">{escape(feed.short_name(item.deal_name))}</span>' if item.deal_name else ""
        dot = '<span class="unread-dot" title="Unread"></span>' if not item.read else ""
        style.html(f'<div class="feed-head"><span class="feed-icon {item.kind}">{ICONS[item.kind]}</span>'
                   f'<span class="feed-type">{item.label}</span>{deal}{chips}'
                   f'<span class="feed-when">{escape(feed.time_text(item, now))}</span>{dot}</div>'
                   f'<div class="feed-message">{escape(item.message)}</div>'
                   + (_brief_html(item.extra["meeting"]) if item.kind == feed.MEETING else ""))
        message = st.session_state.pop(f"brief_message_{item.extra['meeting']['id']}", None) if item.kind == feed.MEETING else None
        if message:
            st.warning(message)
        with st.container(key=f"feedactions_{css_key(item)}", horizontal=True, vertical_alignment="center"):
            for index, (label, action) in enumerate(item.actions):
                if action == "add_email" and item.deal_id is None:
                    _add_email_picker(item, now)
                    continue
                if action == "prep_brief":
                    has_brief = bool(feed_brief(item.extra["meeting"]))
                    label = "Update brief" if has_brief else "Prep brief"
                    clicked = st.button(label, key=f"feedbtn_{action}_{css_key(item)}", icon=":material/auto_awesome:",
                                        help="Uses 1 AI request. Written only from this deal's saved data.")
                else:
                    # "feedbtn_" keeps these keys clear of other screens' CSS (open_deal_* is the dashboard's card link).
                    clicked = st.button(label, key=f"feedbtn_{action}_{css_key(item)}",
                                        type="primary" if index == 0 else "secondary")
                if clicked:
                    _do(action, item, now)
            _overflow(item, now)


def _add_meeting_form(now):
    with st.popover("Add meeting", icon=":material/add:", key="add_meeting"):
        with st.form("add_meeting_form", clear_on_submit=True, border=False):
            title = st.text_input("Title", placeholder="Client call")
            client = st.text_input("Client name (optional)")
            choices = dict(queries.deal_choices())
            deal_id = st.selectbox("Deal (optional)", list(choices), format_func=choices.get, index=None,
                                   placeholder="No deal")
            day = st.date_input("Day", value=now.date())
            left, right = st.columns(2)
            start = left.time_input("Starts", value=time(15, 0), step=timedelta(minutes=15))
            end = right.time_input("Ends", value=time(15, 30), step=timedelta(minutes=15))
            location = st.text_input("Location or link (optional)")
            notes = st.text_area("Notes (optional)", height=80)
            if st.form_submit_button("Save meeting", type="primary"):
                try:
                    notifications.add_meeting(title, datetime.combine(day, start), datetime.combine(day, end), deal_id,
                                              client, location, notes)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.home_flash = f"Meeting saved: {title.strip()}."
                    _rerun()


def _empty(filtered):
    what = "in this filter" if filtered else "right now"
    style.html(f'<div class="caught-up"><div class="caught-up-mark">✓</div><div class="caught-up-title">'
               f"You're all caught up</div><div class=\"caught-up-text\">Nothing needs you {what}. New flags, meetings, "
               f"emails and anything waiting for you will appear here.</div></div>")


@st.fragment(run_every=REFRESH_SECONDS)
def render(now_fn):
    """The feed. Re-runs by itself every 60 seconds, reading only the database."""
    now = now_fn()
    items = feed.build(queries.feed_rows(), now)
    with st.container(key="feed_head", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown('<div class="home-section">What needs you</div>', unsafe_allow_html=True, width="content")
        with st.container(key="feed_tools", horizontal=True, width="content", vertical_alignment="center"):
            if st.button("Mark all as read", key="mark_all_read", type="tertiary", disabled=not feed.unread(items)):
                notifications.mark_read([item.key for item in items], now.replace(tzinfo=None))
                _rerun()
            _add_meeting_form(now)
    flash = st.session_state.pop("home_flash", None)
    if flash:
        st.success(flash)
    counts = feed.counts(items)
    choice = st.pills("Show", list(feed.FILTERS), default="All", key="feed_filter", label_visibility="collapsed",
                      format_func=lambda name: f"{name} {counts[name]}")
    kind = feed.FILTERS.get(choice or "All")
    groups = feed.grouped(items, kind)
    if not groups:
        _empty(kind is not None)
    for group, group_items in groups:
        style.html(f'<div class="feed-group">{escape(group)} <span>{len(group_items)}</span></div>')
        for item in group_items:
            _card(item, now)
    st.caption(f"Built from the database every time and refreshed every {REFRESH_SECONDS} seconds. "
               "Items marked Sample are made up for the demo: no inbox or calendar is connected yet.")
