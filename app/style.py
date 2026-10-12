"""The small amount of custom CSS on top of .streamlit/config.toml, plus HTML helpers."""

from html import escape

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Public+Sans:wght@400;500;600&display=swap');

html, body, .stApp, .stMarkdown, button, input, label { font-family: 'Public Sans', sans-serif; }
h1, h2, h3, h4, .stat-value { font-family: 'Fraunces', Georgia, serif !important; color: #1d3c2f; }
.block-container { max-width: 1100px; padding-top: 3.5rem; }

/* Tap targets at least 44px high for phones. */
.stButton button, .stRadio label { min-height: 44px; }

.topbar { background: #13271e; color: #faf8fb; padding: 14px 18px; border-radius: 10px;
          border-bottom: 3px solid #c9a227; margin-bottom: 8px; }
.topbar .brand { font-family: 'Fraunces', Georgia, serif; font-size: 1.25rem; font-weight: 600; }
.topbar .who { font-size: 0.85rem; opacity: 0.85; }

/* Four across on a desktop, two across on a phone. */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 8px 0 20px; }
.stat-card { background: #ffffff; border: 1px solid #e3dde6; border-top: 3px solid #30654f;
             border-radius: 10px; padding: 14px 16px; }
.stat-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: #4d5b54; }
.stat-value { font-size: 1.7rem; font-weight: 600; line-height: 1.3; }
.stat-value.text { font-size: 1.1rem; }
.stat-note { font-size: 0.78rem; color: #4d5b54; }

.pill { display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }
.pill.needs-review { background: #fdf0d0; color: #7a5200; border: 1px solid #e0a82e; }
.pill.extracting   { background: #e6ecf0; color: #33475b; border: 1px solid #9fb0bf; }
.pill.approved     { background: #dcebe3; color: #1d3c2f; border: 1px solid #30654f; }
.pill.other        { background: #eeeeee; color: #333333; border: 1px solid #bbbbbb; }
.pill.flag         { background: #fbe1df; color: #8f1d14; border: 1px solid #c8382c; }

.deal-name { font-family: 'Fraunces', Georgia, serif; font-size: 1.15rem; font-weight: 600; color: #1d3c2f; }
.deal-meta { font-size: 0.88rem; color: #4d5b54; margin: 2px 0 8px; }

.banner { border-radius: 10px; padding: 14px 16px; margin: 8px 0 16px; }
.banner.flagged { background: #fbe1df; border: 1px solid #c8382c; border-left: 6px solid #c8382c; color: #5e130d; }
.banner.clear   { background: #dcebe3; border: 1px solid #30654f; border-left: 6px solid #30654f; color: #1d3c2f; }
.banner.waiting { background: #fdf0d0; border: 1px solid #e0a82e; border-left: 6px solid #e0a82e; color: #5c3f00; }
.banner .title { font-weight: 600; margin-bottom: 4px; }
.banner ul { margin: 4px 0 6px 18px; padding: 0; }
</style>
"""

PILL_CLASSES = {"Needs Review": "needs-review", "Extracting": "extracting", "Approved": "approved"}


def apply():
    st.markdown(CSS, unsafe_allow_html=True)


def html(markup):
    st.markdown(markup, unsafe_allow_html=True)


def pill(text, kind=None):
    kind = kind or PILL_CLASSES.get(text, "other")
    return f'<span class="pill {kind}">{escape(str(text))}</span>'


def stat_card(label, value, note="", is_text=False):
    value_class = "stat-value text" if is_text else "stat-value"
    note_html = f'<div class="stat-note">{escape(note)}</div>' if note else ""
    return (f'<div class="stat-card"><div class="stat-label">{escape(label)}</div>'
            f'<div class="{value_class}">{escape(str(value))}</div>{note_html}</div>')


def banner(kind, title, lines=(), footer=""):
    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    body = f"<ul>{items}</ul>" if items else ""
    foot = f"<div>{escape(footer)}</div>" if footer else ""
    return f'<div class="banner {kind}"><div class="title">{escape(title)}</div>{body}{foot}</div>'
