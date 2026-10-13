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
  --control-h: 40px; --tab-h: 48px; --card-pad: var(--s3); --topbar-h: 64px;
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
.block-container { max-width: 1320px; padding: calc(var(--topbar-h) + var(--s2)) var(--s4) 96px; }
[data-testid="stHeader"] { display: none; }  /* Streamlit's own empty strip; our top bar replaces it */
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

/* ---- Top bar: fixed across the full width of every signed-in page ---- */
.st-key-topbar { position: fixed; top: 0; left: 0; right: 0; z-index: 900; width: 100% !important;
  height: var(--topbar-h); box-sizing: border-box; padding: 0 var(--s4); flex-wrap: nowrap !important;
  background: var(--green-dark); border-bottom: 3px solid var(--gold); box-shadow: 0 2px 8px rgba(19, 39, 30, 0.25); }
.st-key-topbar [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.st-key-topbar_user { gap: var(--s3) !important; flex-wrap: nowrap !important; }
.brand { display: flex; align-items: center; gap: 10px; font-family: 'Fraunces', Georgia, serif;
         font-size: 1.3rem; font-weight: 600; color: #ffffff; white-space: nowrap; }
.brand svg { width: 22px; height: 22px; flex: none; }
.who { display: flex; align-items: center; gap: 12px; color: #ffffff; font-weight: 500; white-space: nowrap; }
.role-badge { background: var(--gold); color: var(--green-dark); border-radius: var(--pill); padding: 3px 12px;
              font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; }
.st-key-sign_out button { background: transparent; color: #ffffff; border-color: rgba(255, 255, 255, 0.5); }
.st-key-sign_out button:hover { background: rgba(255, 255, 255, 0.14); color: #ffffff; border-color: var(--gold); }

/* ---- Stat cards: each one is a filter. The label is a real button stretched over the whole card. ---- */
[class*="st-key-statcard_"] { position: relative; background: var(--surface); border: 1px solid var(--line) !important;
  border-top: 3px solid var(--green-mid) !important; border-radius: var(--radius) !important;
  padding: var(--s2) var(--card-pad) !important; gap: 0 !important; box-shadow: var(--shadow); cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s, background 0.15s; }
[class*="st-key-statcard_"]:hover { border-color: var(--green-mid) !important; box-shadow: var(--shadow-hover); transform: translateY(-1px); }
[class*="st-key-statcard_"]:focus-within { box-shadow: var(--focus); }
[class*="st-key-statcard_on_"] { background: var(--green-tint); border: 2px solid var(--green) !important;
                                 border-top: 4px solid var(--green) !important; }
[class*="st-key-statcard_"] * { position: static !important; }
[class*="st-key-statcard_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
[class*="st-key-statbtn_"] button { min-height: 0; padding: 0; border: none; background: none; box-shadow: none;
                                    justify-content: flex-start; }
[class*="st-key-statbtn_"] button:hover { background: none; }
[class*="st-key-statbtn_"] button p { font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
                                      letter-spacing: 0.06em; color: var(--ink-soft); text-align: left; }
[class*="st-key-statbtn_"] button::after { content: ""; position: absolute; inset: 0; z-index: 1; cursor: pointer; }
.stat-value { font-size: 2rem; font-weight: 600; line-height: 1.25; margin: 4px 0; }
.stat-value.text { font-size: 1.15rem; line-height: 2.2; }
.stat-note { font-size: 0.82rem; color: var(--ink-soft); }

/* ---- Filter line above the deal list ---- */
.showing { font-size: 1rem; font-weight: 600; color: var(--green); }
.st-key-filter_bar { margin-top: var(--s2); align-items: baseline !important; }
.st-key-show_all_deals button { min-height: 0; padding: 0; border: none; background: none; box-shadow: none; }
.st-key-show_all_deals button:hover { background: none; }
.st-key-show_all_deals button p { color: var(--green-mid); font-weight: 600; text-decoration: underline; }
.st-key-time_saved_panel { background: var(--surface); border: 1px solid var(--line) !important;
  border-left: 4px solid var(--gold) !important; border-radius: var(--radius) !important;
  padding: var(--s2) var(--card-pad) !important; margin-top: var(--s2); }

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

/* ---- Tabs: 48px high, 16px text, green underline on the active one.
        The last tab (Ask AI) is a gold oval pill so the AI feature stands out. ---- */
.stTabs [role="tablist"] { gap: var(--s1); align-items: flex-end; border-bottom: 1px solid var(--line);
                            padding: var(--s1) var(--s1) 0 0; }  /* room for the pill's shadow and ring */
.stTabs [role="tab"] { height: var(--tab-h); padding: 0 var(--s3); display: flex; align-items: center;
  color: var(--ink-soft); cursor: pointer; border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  transition: background 0.15s, color 0.15s, box-shadow 0.15s, transform 0.15s; }
.stTabs [role="tab"] p { font-size: 16px; font-weight: 600; }
.stTabs [role="tab"]:hover { background: var(--green-tint); color: var(--green); }
.stTabs [role="tab"]:focus-visible { outline: none; box-shadow: var(--focus); }
.stTabs [role="tab"][aria-selected="true"] { color: var(--green); box-shadow: inset 0 -3px 0 var(--green); }
.stTabs .react-aria-SelectionIndicator, .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }
.stTabs [role="tab"]:last-of-type { height: 44px; margin: 0 0 6px var(--s3); padding: 0 var(--s3);
  border-radius: var(--pill); background: var(--gold); color: var(--green-dark);
  box-shadow: 0 2px 8px rgba(201, 162, 39, 0.45); }
.stTabs [role="tab"]:last-of-type p { font-weight: 700; }
.stTabs [role="tab"]:last-of-type:hover { background: #d8b23a; color: var(--green-dark);
  box-shadow: 0 4px 14px rgba(201, 162, 39, 0.6); transform: translateY(-1px); }
.stTabs [role="tab"]:last-of-type[aria-selected="true"] { background: var(--gold); color: var(--green-dark);
  box-shadow: inset 0 0 0 2px var(--green-dark), 0 4px 12px rgba(201, 162, 39, 0.6); }
.stTabs [role="tab"]:last-of-type:focus-visible { box-shadow: var(--focus), 0 2px 8px rgba(201, 162, 39, 0.45); }
.stTabs [role="tabpanel"] { padding-top: var(--s3); }

/* ---- Banners ---- */
.banner { border-radius: var(--radius); padding: var(--s2) var(--card-pad); margin: 0 0 var(--s3); border: 1px solid; border-left-width: 6px; }
.banner.flagged { background: var(--red-tint); border-color: var(--red); color: var(--red-ink); }
.banner.clear   { background: #dcebe3; border-color: var(--green-mid); color: var(--green); }
.banner.waiting { background: var(--amber-tint); border-color: #e0a82e; color: var(--amber-ink); }
.banner .title { font-weight: 600; margin-bottom: 4px; }
.banner ul { margin: 4px 0 6px 18px; padding: 0; }

/* ---- Floating AI assistant button: a real Streamlit button pinned to the bottom-right corner ---- */
.st-key-fab { position: fixed; right: 24px; bottom: 24px; z-index: 1000; width: auto !important; }
.st-key-fab button { width: 56px; height: 56px; min-height: 56px; padding: 0; border-radius: 50%;
  background: var(--green); border: 2px solid var(--gold); box-shadow: 0 6px 18px rgba(19, 39, 30, 0.35); }
.st-key-fab button:hover { background: var(--green-dark); border-color: var(--gold); transform: scale(1.06); }
.st-key-fab button:focus-visible { box-shadow: var(--focus), 0 6px 18px rgba(19, 39, 30, 0.35); }
.st-key-fab button p { font-size: 0; }  /* the label stays for screen readers; the hover label shows it */
.st-key-fab button [data-testid="stIconMaterial"] { color: var(--gold); font-size: 28px; margin: 0; }
.st-key-fab::before { content: "Ask the AI Teammate"; position: absolute; right: 68px; top: 50%;
  transform: translateY(-50%); background: var(--green-dark); color: #faf8fb; padding: var(--s1) 12px;
  border-radius: var(--radius-sm); font-size: 0.85rem; font-weight: 500; white-space: nowrap;
  opacity: 0; pointer-events: none; transition: opacity 0.15s; }
.st-key-fab:hover::before, .st-key-fab:focus-within::before { opacity: 1; }
</style>
"""

# A four-point sparkle in the gold accent, used wherever the AI is the subject.
SPARKLE = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#c9a227" '
           'd="M12 1.5l2.6 7.9 7.9 2.6-7.9 2.6-2.6 7.9-2.6-7.9-7.9-2.6 7.9-2.6z"/></svg>')

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


def banner(kind, title, lines=(), footer=""):
    items = "".join(f"<li>{escape(line)}</li>" for line in lines)
    body = f"<ul>{items}</ul>" if items else ""
    foot = f"<div>{escape(footer)}</div>" if footer else ""
    return f'<div class="banner {kind}"><div class="title">{escape(title)}</div>{body}{foot}</div>'
