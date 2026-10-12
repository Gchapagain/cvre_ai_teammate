"""The design system: one set of tokens and component styles on top of .streamlit/config.toml.

Everything sits on an 8px grid. Components elsewhere use these classes and never set
their own spacing, radius or colours.
"""

from html import escape

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Public+Sans:wght@400;500;600&display=swap');

:root {
  /* Spacing: 8px grid */
  --s1: 8px; --s2: 16px; --s3: 24px; --s4: 32px; --s5: 48px;
  /* Shape and control sizes */
  --radius: 12px; --radius-sm: 8px; --pill: 999px;
  --control-h: 40px; --tab-h: 48px; --card-pad: var(--s3);
  /* Colour */
  --bg: #faf8fb; --surface: #ffffff; --line: #ddd6e1;
  --green: #1d3c2f; --green-dark: #13271e; --green-mid: #30654f; --green-tint: #e8f0ec;
  --gold: #c9a227; --gold-tint: #fbf3d6; --gold-ink: #5c4a08;
  --ink: #16241d; --ink-soft: #4a5750;
  --amber: #b97a00; --amber-tint: #fdf0d0; --amber-ink: #6b4700;
  --red: #c8382c; --red-tint: #fbe1df; --red-ink: #7a1a12;
  --shadow: 0 1px 2px rgba(19, 39, 30, 0.06); --shadow-hover: 0 4px 14px rgba(19, 39, 30, 0.12);
  --focus: 0 0 0 3px rgba(201, 162, 39, 0.55);
}

/* ---- Page ---- */
h1, h2, h3, h4, .stat-value { font-family: 'Fraunces', Georgia, serif !important; color: var(--green); }
.block-container { max-width: 1320px; padding: var(--s4) var(--s4) 96px; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--ink-soft); }
.section-title { font-size: 0.8rem; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
                 color: var(--ink-soft); margin: var(--s3) 0 var(--s1); }

/* ---- Buttons: one height, one radius, clear hover and keyboard focus ---- */
.stButton button, .stDownloadButton button {
  min-height: var(--control-h); padding: 0 var(--s2); border-radius: var(--radius-sm);
  border: 1px solid var(--line); background: var(--surface); color: var(--ink); font-weight: 500;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s; }
.stButton button:hover, .stDownloadButton button:hover {
  border-color: var(--green-mid); background: var(--green-tint); color: var(--green); }
.stButton button:focus-visible, .stDownloadButton button:focus-visible { outline: none; box-shadow: var(--focus); }
.stButton button:disabled { background: #f1eef3; color: #6f7a74; border-color: var(--line); }

/* ---- Header bar ---- */
.st-key-topbar { background: var(--green-dark); border-bottom: 3px solid var(--gold); border-radius: var(--radius);
                 padding: var(--s2) var(--s3); margin-bottom: var(--s2); }
.st-key-topbar [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.brand { font-family: 'Fraunces', Georgia, serif; font-size: 1.3rem; font-weight: 600; color: #faf8fb; }
.who { display: flex; align-items: center; justify-content: flex-end; gap: var(--s1); color: #faf8fb; font-weight: 500; }
.who .demo { color: #c9d4ce; font-size: 0.8rem; font-weight: 400; }
.role-badge { background: var(--gold); color: var(--green-dark); border-radius: var(--pill); padding: 2px 10px;
              font-size: 0.72rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; }
.st-key-sign_out { display: flex; justify-content: flex-end; }
.st-key-sign_out button { background: transparent; color: #faf8fb; border-color: rgba(250, 248, 251, 0.45); }
.st-key-sign_out button:hover { background: rgba(250, 248, 251, 0.12); color: #ffffff; border-color: var(--gold); }

/* ---- Stat cards ---- */
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--s2); margin: var(--s2) 0 var(--s1); }
.stat-card { background: var(--surface); border: 1px solid var(--line); border-top: 3px solid var(--green-mid);
             border-radius: var(--radius); padding: var(--s2) var(--card-pad); box-shadow: var(--shadow); }
.stat-label { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-soft); }
.stat-value { font-size: 2rem; font-weight: 600; line-height: 1.25; margin: 4px 0; }
.stat-value.text { font-size: 1.15rem; line-height: 1.9; }
.stat-note { font-size: 0.82rem; color: var(--ink-soft); }

/* ---- Pills ---- */
.pill { display: inline-block; padding: 3px 12px; border-radius: var(--pill); font-size: 0.8rem; font-weight: 600;
        border: 1px solid transparent; margin-right: 6px; }
.pill.needs-review, .pill.not-verified { background: var(--amber-tint); color: var(--amber-ink); border-color: #e0a82e; }
.pill.extracting   { background: #e6ecf0; color: #2c3e50; border-color: #9fb0bf; }
.pill.approved, .pill.from-deal { background: #dcebe3; color: var(--green); border-color: var(--green-mid); }
.pill.flag         { background: var(--red-tint); color: var(--red-ink); border-color: var(--red); }
.pill.other, .pill.no-answer { background: #ececec; color: #333333; border-color: #b5b5b5; }

/* ---- Deal cards ----
   The deal name is a real Streamlit button styled as a heading. Its ::after layer is stretched over
   the whole card, so a click anywhere on the card opens the deal. This relies on the st-key-* classes
   Streamlit adds for widget and container keys. */
[class*="st-key-deal_card_"] { position: relative; background: var(--surface); border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important; padding: var(--card-pad) !important; gap: var(--s1) !important;
  box-shadow: var(--shadow); transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s; }
[class*="st-key-deal_card_flagged_"] { border-left: 4px solid var(--red) !important; }
[class*="st-key-deal_card_review_"]  { border-left: 4px solid var(--amber) !important; }
[class*="st-key-deal_card_"]:hover { border-color: var(--green-mid) !important; box-shadow: var(--shadow-hover); transform: translateY(-1px); }
[class*="st-key-deal_card_flagged_"]:hover { border-left-color: var(--red) !important; }
[class*="st-key-deal_card_review_"]:hover  { border-left-color: var(--amber) !important; }
[class*="st-key-deal_card_"]:focus-within { box-shadow: var(--focus); }
/* Nothing between the card and the button may be positioned, or the click layer would shrink to it. */
[class*="st-key-deal_card_"] * { position: static !important; }
[class*="st-key-deal_card_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
[class*="st-key-open_deal_"] button { min-height: 0; padding: 0; border: none; background: none; box-shadow: none;
                                      justify-content: flex-start; }
[class*="st-key-open_deal_"] button:hover { background: none; }
[class*="st-key-open_deal_"] button p { font-family: 'Fraunces', Georgia, serif; font-size: 1.2rem; font-weight: 600;
                                        color: var(--green); text-align: left; }
[class*="st-key-deal_card_"]:hover [class*="st-key-open_deal_"] button p { text-decoration: underline; }
[class*="st-key-open_deal_"] button::after { content: ""; position: absolute; inset: 0; z-index: 1; cursor: pointer; }
.deal-meta { font-size: 0.9rem; color: var(--ink-soft); margin-bottom: var(--s1); }
.deal-head { margin-bottom: var(--s2); }

/* ---- Tabs: 48px high, clear active state. The last tab (Ask AI) is the gold AI tab. ---- */
.stTabs [role="tablist"] { gap: var(--s1); border-bottom: 1px solid var(--line); }
.stTabs [data-testid="stTab"] { height: var(--tab-h); padding: 0 var(--s3); display: flex; align-items: center;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0; color: var(--ink-soft); cursor: pointer;
  transition: background 0.15s, color 0.15s; }
.stTabs [data-testid="stTab"] p { font-size: 1rem; font-weight: 600; }
.stTabs [data-testid="stTab"]:hover { background: var(--green-tint); color: var(--green); }
.stTabs [data-testid="stTab"]:focus-visible { outline: none; box-shadow: var(--focus); }
.stTabs [data-testid="stTab"][aria-selected="true"] { background: var(--surface); color: var(--green);
                                                      box-shadow: inset 0 -3px 0 var(--green); }
.stTabs .react-aria-SelectionIndicator { display: none; }
.stTabs [data-testid="stTab"]:last-of-type { background: var(--gold-tint); color: var(--gold-ink);
  border: 1px solid var(--gold); border-bottom: none; margin-left: var(--s2); }
.stTabs [data-testid="stTab"]:last-of-type:hover { background: #f5e6ad; color: var(--green-dark); }
.stTabs [data-testid="stTab"]:last-of-type[aria-selected="true"] { background: var(--gold); color: var(--green-dark);
                                                                    box-shadow: inset 0 -3px 0 var(--green-dark); }
.stTabs [role="tabpanel"] { padding-top: var(--s3); }

/* ---- Banners ---- */
.banner { border-radius: var(--radius); padding: var(--s2) var(--card-pad); margin: 0 0 var(--s3); border: 1px solid; border-left-width: 6px; }
.banner.flagged { background: var(--red-tint); border-color: var(--red); color: var(--red-ink); }
.banner.clear   { background: #dcebe3; border-color: var(--green-mid); color: var(--green); }
.banner.waiting { background: var(--amber-tint); border-color: #e0a82e; color: var(--amber-ink); }
.banner .title { font-weight: 600; margin-bottom: 4px; }
.banner ul { margin: 4px 0 6px 18px; padding: 0; }

/* ---- Floating AI assistant button: a real Streamlit button pinned to the bottom-right corner ---- */
.st-key-assistant_fab { position: fixed; right: var(--s4); bottom: var(--s4); z-index: 1000; width: auto !important; }
.st-key-assistant_fab button { width: 56px; height: 56px; min-height: 56px; padding: 0; border-radius: 50%;
  background: var(--green); border: 2px solid var(--gold); box-shadow: 0 6px 18px rgba(19, 39, 30, 0.35); }
.st-key-assistant_fab button:hover { background: var(--green-dark); border-color: var(--gold); transform: scale(1.06); }
.st-key-assistant_fab button:focus-visible { box-shadow: var(--focus), 0 6px 18px rgba(19, 39, 30, 0.35); }
.st-key-assistant_fab button p { font-size: 0; }  /* the label stays for screen readers; the hover label shows it */
.st-key-assistant_fab button [data-testid="stIconMaterial"] { color: var(--gold); font-size: 28px; margin: 0; }
.st-key-assistant_fab::before { content: "Ask the AI Teammate"; position: absolute; right: 68px; top: 50%;
  transform: translateY(-50%); background: var(--green-dark); color: #faf8fb; padding: var(--s1) 12px;
  border-radius: var(--radius-sm); font-size: 0.85rem; font-weight: 500; white-space: nowrap;
  opacity: 0; pointer-events: none; transition: opacity 0.15s; }
.st-key-assistant_fab:hover::before, .st-key-assistant_fab:focus-within::before { opacity: 1; }
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


def section_title(text):
    html(f'<div class="section-title">{escape(text)}</div>')


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
