"""The design system: one set of tokens and component styles on top of .streamlit/config.toml.

Everything sits on an 8px grid. Components elsewhere use these classes and never set
their own spacing, radius or colours.
"""

from html import escape

import streamlit as st

from app import icons
from app.icons import SPARKLE  # noqa: F401  (kept here so screens can use style.SPARKLE)

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
  --orange: #dd7a1f; --yellow: #e9c43a;  /* progress colours only: red, orange, yellow, green */
  --shadow: 0 1px 2px rgba(19, 39, 30, 0.06); --shadow-hover: 0 4px 14px rgba(19, 39, 30, 0.12);
  --focus: 0 0 0 3px rgba(201, 162, 39, 0.55);
}

/* ---- Page ---- */
/* Blocks that only carry a stylesheet take no space (otherwise each adds an empty gap). */
[data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] style) { display: none; }
h1, h2, h3, h4, .stat-value { font-family: 'Fraunces', Georgia, serif !important; color: var(--green); }
.block-container { max-width: 1320px; padding: calc(var(--topbar-h) + var(--s4)) var(--s4) 96px; }
.block-container h2 { padding-top: 0; }  /* the page title starts exactly 32px under the top bar */
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
/* Primary buttons: the one main action on a page or in a dialog. */
.stButton button[kind="primary"], .stFormSubmitButton button[kind="primary"],
.stButton button[data-testid="stBaseButton-primary"], .stFormSubmitButton button[data-testid="stBaseButton-primary"] {
  background: var(--green); border-color: var(--green); color: #ffffff; font-weight: 600; padding: 0 20px; }
.stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind="primary"]:hover,
.stButton button[data-testid="stBaseButton-primary"]:hover, .stFormSubmitButton button[data-testid="stBaseButton-primary"]:hover {
  background: var(--green-dark); border-color: var(--green-dark); color: #ffffff; box-shadow: var(--shadow-hover); }
.stButton button[kind="primary"]:disabled, .stButton button[data-testid="stBaseButton-primary"]:disabled {
  background: #dfe3e0; border-color: #cfd6d2; color: #6f7a74; box-shadow: none; }  /* a locked action must not look ready */
.st-key-page_head { flex-wrap: nowrap !important; margin-bottom: var(--s1); }
.st-key-new_deal button { min-height: 44px; }

/* ---- Top bar: fixed across the full width of every signed-in page ---- */
.st-key-topbar { position: fixed; top: 0; left: 0; right: 0; z-index: 900; width: 100% !important;
  height: var(--topbar-h); box-sizing: border-box; padding: 0 var(--s4); flex-wrap: nowrap !important;
  background: var(--green-dark); border-bottom: 3px solid var(--gold); box-shadow: 0 2px 8px rgba(19, 39, 30, 0.25); }
.st-key-topbar [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.st-key-topbar_user { gap: var(--s3) !important; flex-wrap: nowrap !important; }
.st-key-topbar .pill.simulated { margin: 0; }
.st-key-topbar_nav { gap: var(--s4) !important; flex-wrap: nowrap !important; }
/* The brand and the All deals link are real buttons, so both can take the person home. */
.st-key-nav_home button, .st-key-nav_all_deals button, .st-key-nav_home_link button { min-height: var(--control-h); border: none; background: none;
  box-shadow: none; white-space: nowrap; border-radius: var(--radius-sm); }
.st-key-nav_home button { padding: 0; gap: 10px; }
.st-key-nav_home button::before { content: ""; width: 22px; height: 22px; flex: none;
  background: """ + icons.SPARKLE_URL + """ center / contain no-repeat; }
.st-key-nav_home button p { font-family: 'Fraunces', Georgia, serif; font-size: 1.3rem; font-weight: 600; color: #ffffff; }
.st-key-nav_home button:hover { background: none; }
.st-key-nav_all_deals button, .st-key-nav_home_link button { padding: 0 12px; }
.st-key-nav_all_deals button p, .st-key-nav_home_link button p { color: #dfe7e2; font-weight: 500; }
.st-key-nav_all_deals button:hover, .st-key-nav_home_link button:hover { background: rgba(255, 255, 255, 0.12); }
.st-key-nav_all_deals button:hover p, .st-key-nav_home_link button:hover p { color: #ffffff; }
.st-key-nav_home button:focus-visible, .st-key-nav_all_deals button:focus-visible,
.st-key-nav_home_link button:focus-visible { box-shadow: var(--focus); }

/* ---- Breadcrumb on a deal page: All deals > Deal name ---- */
.st-key-breadcrumb { gap: var(--s1) !important; margin-bottom: var(--s1); }
.st-key-breadcrumb [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.st-key-back_to_deals button { min-height: 0; padding: 0; border: none; background: none; box-shadow: none; }
.st-key-back_to_deals button:hover { background: none; }
.st-key-back_to_deals button p { color: var(--green-mid); font-weight: 600; }
.st-key-back_to_deals button:hover p { text-decoration: underline; }
.crumb { display: flex; align-items: center; gap: var(--s1); color: var(--ink-soft); font-size: 0.95rem; }
.crumb .sep { color: #8b958f; }
.crumb .here { color: var(--ink); font-weight: 500; }
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
[class*="st-key-statcard_on_"]:hover { border-color: var(--green) !important; }  /* stay selected-looking under the mouse */
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
.showing { font-size: 1rem; font-weight: 600; color: var(--green); line-height: 28px; }
.st-key-filter_bar { margin-top: var(--s2); align-items: center !important; }
.st-key-filter_bar { gap: 12px !important; }
.st-key-clear_filter button { min-height: 28px; padding: 0 10px 0 6px; border-radius: var(--pill); gap: 2px; }
.st-key-clear_filter button p { font-size: 0.85rem; font-weight: 600; }
.st-key-clear_filter button [data-testid="stIconMaterial"] { font-size: 16px; }
.st-key-time_saved_panel { background: var(--surface); border: 1px solid var(--line) !important;
  border-left: 4px solid var(--gold) !important; border-radius: var(--radius) !important;
  padding: var(--s2) var(--card-pad) !important; margin-top: var(--s2); }

/* ---- Pills ---- */
.pill { display: inline-block; padding: 3px 12px; border-radius: var(--pill); font-size: 0.8rem; font-weight: 600;
        border: 1px solid transparent; margin-right: 6px; }
.pill.needs-review, .pill.not-verified { background: var(--amber-tint); color: var(--amber-ink); border-color: #e0a82e; }
.pill.extracting, .pill.new { background: #e6ecf0; color: #2c3e50; border-color: #9fb0bf; }
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

/* ---- Deal header card ---- */
.st-key-deal_header { background: var(--surface); border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important; padding: var(--s3) var(--card-pad) !important; box-shadow: var(--shadow);
  margin-bottom: var(--s1); }
.st-key-deal_header [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.deal-top { display: flex; justify-content: space-between; align-items: flex-start; gap: var(--s3); }
.deal-title { font-family: 'Fraunces', Georgia, serif; font-size: 1.7rem; font-weight: 600; color: var(--green);
  line-height: 1.25; display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.deal-top .deal-meta { margin: var(--s1) 0 0; }
.deal-id { display: flex; align-items: center; gap: var(--s2); min-width: 0; }
.deal-thumb { width: 96px; height: 64px; object-fit: cover; border-radius: var(--radius-sm); border: 1px solid var(--line); flex: none; }
.st-key-change_photo button { min-height: 32px; font-size: 0.85rem; }
.chip { font-family: 'Public Sans', sans-serif; font-size: 0.78rem; font-weight: 500; color: var(--ink-soft);
  background: #f1eef3; border: 1px solid var(--line); border-radius: var(--pill); padding: 2px 10px; white-space: nowrap; }

/* ---- Review tab cards ---- */
[class*="st-key-card_"] { background: var(--surface); border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important; padding: var(--s3) var(--card-pad) !important; box-shadow: var(--shadow);
  gap: 12px !important; }
[class*="st-key-card_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.card-title { font-family: 'Fraunces', Georgia, serif; font-size: 1.2rem; font-weight: 600; color: var(--green);
  display: flex; justify-content: space-between; align-items: baseline; gap: var(--s2); }
.card-note { font-family: 'Public Sans', sans-serif; font-size: 0.82rem; font-weight: 500; color: var(--ink-soft); }
.kv { display: flex; justify-content: space-between; align-items: baseline; gap: var(--s2); padding: 10px 0;
  border-bottom: 1px solid #eee9f0; }
.kv:last-child { border-bottom: none; }
.kv .k { color: var(--ink-soft); font-size: 0.9rem; }
.kv-note { color: #7b8680; font-size: 0.75rem; }
.kv .v { font-weight: 600; color: var(--ink); text-align: right; white-space: nowrap; }
.kv .v.muted { font-weight: 500; color: var(--amber-ink); background: var(--amber-tint); border-radius: var(--pill);
  padding: 1px 10px; font-size: 0.82rem; }
.takeaways { margin: 0; padding-left: 18px; }
.takeaways li { margin-bottom: var(--s1); line-height: 1.45; font-size: 0.93rem; }
.st-key-narrative_actions { gap: var(--s1) !important; }
.ai-label { display: inline-flex; align-items: center; gap: var(--s1); background: var(--gold-tint); color: var(--gold-ink);
  border: 1px solid var(--gold); border-radius: var(--pill); padding: 3px 12px; font-size: 0.82rem; font-weight: 600; }
.ai-label svg { width: 14px; height: 14px; }
.st-key-card_narrative textarea { font-size: 0.97rem; line-height: 1.55; }
.st-key-card_narrative textarea:disabled { color: var(--ink); -webkit-text-fill-color: var(--ink); background: #faf8fb; }
.st-key-go_documents button { min-height: 0; padding: 0; border: none; background: none; box-shadow: none; }
.st-key-go_documents button:hover { background: none; }
.st-key-go_documents button p { color: var(--green-mid); font-weight: 600; }
.st-key-go_documents button:hover p { text-decoration: underline; }

/* ---- Research findings ---- */
[class*="st-key-finding_"] { border: 1px solid var(--line) !important; border-radius: var(--radius-sm) !important;
  padding: var(--s2) !important; gap: var(--s1) !important; background: #fdfcfe; }
[class*="st-key-finding_accepted_"] { border-left: 4px solid var(--green-mid) !important; }
[class*="st-key-finding_dismissed_"] { opacity: 0.6; }
[class*="st-key-finding_"] button { min-height: 32px; }
.finding-topic { display: flex; align-items: center; gap: var(--s1); font-weight: 600; color: var(--green); }
.finding-topic span:first-child { margin-right: 4px; }
.finding-summary { margin: 4px 0 var(--s1); font-size: 0.93rem; }
.source { display: grid; grid-template-columns: 64px minmax(0, 1.4fr) 110px minmax(0, 1.2fr); align-items: center;
  gap: var(--s1); padding: 6px 0; border-top: 1px solid #eee9f0; font-size: 0.86rem; }
.source a { color: var(--green-mid); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source .when { color: var(--ink-soft); }
.source .figure { font-weight: 600; text-align: right; }
.source .none { font-weight: 400; color: var(--ink-soft); }
.pill.tier1 { background: #dcebe3; color: var(--green); border-color: var(--green-mid); }
.pill.tier2 { background: var(--gold-tint); color: var(--gold-ink); border-color: var(--gold); }
.pill.tier3 { background: #ececec; color: #333333; border-color: #b5b5b5; }
.source .pill { margin: 0; text-align: center; padding: 2px 6px; font-size: 0.72rem; }

.finding-head { display: flex; align-items: center; gap: var(--s1); flex-wrap: wrap; }
.chip.simulated { background: #ede7f6; color: #4527a0; border-color: #9575cd; font-weight: 700; letter-spacing: 0.05em; }
.pill.simulated { background: #ede7f6; color: #4527a0; border-color: #9575cd; }
[class*="st-key-finding_simulated_"] { background: #faf8fd; border-style: dashed !important; }
.src-name { font-weight: 600; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unchecked { font-size: 0.75rem; color: var(--amber-ink); margin: -2px 0 4px 72px; }
.run-results { margin: 0; padding-left: 18px; font-size: 0.86rem; color: var(--ink-soft); }
.finding-topic { margin-top: var(--s1); }

/* ---- Connections page ---- */
[class*="st-key-conn_card_"] { background: var(--surface); border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important; padding: var(--s3) var(--card-pad) !important; box-shadow: var(--shadow);
  gap: var(--s1) !important; margin-bottom: var(--s2); }
[class*="st-key-conn_card_demo_"] { background: #fcfbfe; }
[class*="st-key-conn_card_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
[class*="st-key-conn_card_"] [data-testid="stMarkdownContainer"] p strong { font-family: 'Fraunces', Georgia, serif;
  font-size: 1.08rem; color: var(--green); }
.conn-kind { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft); }
.conn-provides { margin: 4px 0 var(--s1); }
.conn-topics { display: flex; flex-wrap: wrap; gap: 6px; }
.conn-used { font-size: 0.82rem; color: var(--ink-soft); margin-top: var(--s1); }
.tier-item { white-space: nowrap; }
.conn-tiers { margin-top: var(--s1); font-size: 0.86rem; color: var(--ink-soft); display: flex; gap: var(--s2); flex-wrap: wrap; }
.st-key-card_how_sources { margin-bottom: var(--s2); }
.st-key-nav_connections button { min-height: var(--control-h); border: none; background: none; box-shadow: none; padding: 0 12px;
  border-radius: var(--radius-sm); }
.st-key-nav_connections button p { color: #dfe7e2; font-weight: 500; }
.st-key-nav_connections button:hover { background: rgba(255, 255, 255, 0.12); }
.st-key-nav_connections button:hover p { color: #ffffff; }

/* ---- Recommendations ---- */
.banner.ai { background: var(--gold-tint); border-color: var(--gold); color: var(--gold-ink); }
[class*="st-key-rec_rule_"], [class*="st-key-rec_ai_"] { background: var(--surface); border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important; padding: var(--s3) var(--card-pad) !important; box-shadow: var(--shadow);
  gap: var(--s1) !important; margin-bottom: var(--s1); }
[class*="st-key-rec_ai_"] { border-left: 4px solid var(--gold) !important; }
[class*="st-key-rec_rule_"] { border-left: 4px solid var(--green-mid) !important; }
[class*="st-key-rec_"][class*="_dismissed_"] { opacity: 0.6; }
[class*="st-key-rec_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
[class*="st-key-rec_"] button { min-height: 32px; }
.rec-head { display: flex; align-items: center; gap: var(--s1); flex-wrap: wrap; }
.rec-title { font-family: 'Fraunces', Georgia, serif; font-size: 1.1rem; font-weight: 600; color: var(--green); margin-right: 4px; }
.rec-kind { font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft); margin-top: 4px; }
.rec-why, .rec-next { font-size: 0.93rem; margin-top: var(--s1); }
.rec-evidence { display: flex; flex-wrap: wrap; gap: 6px; margin-top: var(--s1); }
.evidence { font-size: 0.78rem; border: 1px solid var(--line); border-radius: var(--pill); padding: 2px 10px; background: #f6f4f7; color: var(--ink); }
.evidence.tier1 { background: #e8f2ec; border-color: #9cc4ae; }
.evidence.tier2 { background: var(--gold-tint); border-color: #e2cd7f; }
.evidence.tier3 { background: #f0f0f0; border-color: #c9c9c9; }
.st-key-rec_left_out { background: #fcfbfe; border: 1px dashed #b9a6dc !important; border-radius: var(--radius) !important;
  padding: var(--s2) var(--card-pad) !important; margin-top: var(--s2); }
.left-out { margin: var(--s1) 0 0; padding-left: 18px; font-size: 0.88rem; }
.left-out li { margin-bottom: 6px; }

/* ---- Flag decision cards, edit preview, timeline ---- */
[class*="st-key-flagcard_"] { background: var(--surface); border: 1px solid var(--line) !important; border-radius: var(--radius) !important;
  padding: var(--s2) var(--card-pad) !important; box-shadow: var(--shadow); gap: var(--s1) !important; margin-bottom: var(--s1); }
[class*="st-key-flagcard_open_"] { border-left: 6px solid var(--red) !important; background: #fffafa; }
[class*="st-key-flagcard_confirmed_"], [class*="st-key-flagcard_corrected_"] { border-left: 6px solid var(--green-mid) !important; }
[class*="st-key-flagcard_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.flag-head { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); flex-wrap: wrap; }
.flag-title { font-family: 'Fraunces', Georgia, serif; font-size: 1.1rem; font-weight: 600; color: var(--green); }
.flag-message { margin-top: 4px; }
.flag-numbers { font-size: 0.9rem; color: var(--ink-soft); }
.flag-numbers .num { font-weight: 700; color: var(--red-ink); }
.flag-detail { font-size: 0.82rem; color: var(--ink-soft); }
[class*="st-key-flag_choices_"] button { min-height: 44px; font-weight: 600; }
[class*="st-key-fix_btn_"] button { border-color: var(--red); color: var(--red-ink); }
[class*="st-key-fix_btn_"] button:hover { background: var(--red-tint); color: var(--red-ink); border-color: var(--red); }
[class*="st-key-confirm_btn_"] button { border-color: var(--green-mid); color: var(--green); }
table.preview { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin: 4px 0; }
table.preview th { text-align: left; color: var(--ink-soft); font-weight: 600; border-bottom: 1px solid var(--line); padding: 6px 8px; }
table.preview td { padding: 6px 8px; border-bottom: 1px solid #eee9f0; }
table.preview tr.derived td { background: var(--gold-tint); }
.original { font-size: 0.86rem; background: var(--gold-tint); border: 1px solid #e2cd7f; border-radius: var(--radius-sm); padding: 8px 12px; }
.event { padding: var(--s1) 0 4px; border-top: 1px solid #eee9f0; }
.event-title { font-weight: 600; color: var(--green); }
.event-meta { font-size: 0.78rem; color: var(--ink-soft); }
.event-detail, .event-why { font-size: 0.86rem; margin-top: 2px; }
.event-why { color: var(--ink-soft); }
[class*="st-key-undo_"] button { min-height: 28px; padding: 0 10px; font-size: 0.85rem; }

.understood { background: var(--gold-tint); border: 1px solid #e2cd7f; border-radius: var(--radius-sm); padding: 10px 14px; margin: 4px 0; }
[class*="st-key-proposal_"], [class*="st-key-question_"] { background: var(--surface); border: 1px solid var(--line) !important;
  border-left: 4px solid var(--gold) !important; border-radius: var(--radius-sm) !important; padding: var(--s2) !important; }
[class*="st-key-proposal_"] [data-testid="stMarkdownContainer"], [class*="st-key-question_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.proposal-title { font-weight: 600; color: var(--green); margin-bottom: 4px; }

.checklist { list-style: none; margin: 0; padding: 0; }
.checklist li { padding: 6px 0 6px 28px; position: relative; border-bottom: 1px solid #eee9f0; font-size: 0.93rem; }
.checklist li:last-child { border-bottom: none; }
.checklist li::before { position: absolute; left: 0; top: 5px; width: 20px; height: 20px; border-radius: 50%; text-align: center;
  font-size: 0.78rem; line-height: 20px; font-weight: 700; }
.checklist li.done::before { content: "✓"; background: #dcebe3; color: var(--green); }
.checklist li.todo::before { content: "!"; background: var(--amber-tint); color: var(--amber-ink); }
.st-key-card_approval { background: var(--surface); border: 1px solid var(--line) !important; border-top: 4px solid var(--gold) !important;
  border-radius: var(--radius) !important; padding: var(--s3) var(--card-pad) !important; box-shadow: var(--shadow); gap: 12px !important; }
.st-key-card_approval [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.approve-counts { display: flex; gap: var(--s1); flex-wrap: wrap; margin-bottom: var(--s1); }

/* ---- Notes ---- */
[class*="st-key-note_"] { background: var(--surface); border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important; padding: var(--s2) var(--card-pad) !important; }
[class*="st-key-note_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.note-text { white-space: pre-wrap; color: var(--ink); }
.note-meta { margin-top: var(--s1); font-size: 0.8rem; color: var(--ink-soft); }

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

/* ---- Home ---- */
.home-greeting { font-size: 2rem; margin: 0; padding: 0 !important; }
.home-summary { color: var(--ink-soft); font-size: 1.05rem; margin: 4px 0 var(--s3); }
.home-section { font-family: 'Fraunces', Georgia, serif; font-size: 1.3rem; font-weight: 600; color: var(--green); }
.st-key-strip_head { margin-bottom: var(--s1); }
.st-key-strip_head [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.strip-arrows { display: flex; gap: var(--s1); }
.strip-arrow { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--line); background: var(--surface);
  color: var(--green); font-size: 1.4rem; line-height: 1; cursor: pointer; box-shadow: var(--shadow);
  transition: background 0.15s, border-color 0.15s; font-family: 'Public Sans', sans-serif; }
.strip-arrow:hover { background: var(--green-tint); border-color: var(--green-mid); }
.strip-arrow:focus-visible { outline: none; box-shadow: var(--focus); }
.strip-arrow:disabled { opacity: 0.35; cursor: default; background: var(--surface); border-color: var(--line); }
/* The strip: one row that scrolls sideways (trackpad, wheel+shift, arrows) and snaps to each card. */
.st-key-project_strip { flex-wrap: nowrap !important; overflow-x: auto; gap: var(--s2) !important;
  align-items: stretch !important; scroll-snap-type: x mandatory; scroll-padding: 0 4px; padding: 4px 4px var(--s2);
  scrollbar-width: thin; }
/* Streamlit wraps each card in a box of its own: that box is what gets the fixed width and the snap point. */
.st-key-project_strip > div { flex: 0 0 288px !important; width: 288px !important; min-width: 0; scroll-snap-align: start; }
[class*="st-key-proj_card_"] { position: relative; width: 100% !important; height: 100%; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  overflow: hidden; gap: var(--s1) !important; padding: 0 0 var(--s2); box-shadow: var(--shadow);
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s; }
[class*="st-key-proj_card_"]:hover { border-color: var(--green-mid); box-shadow: var(--shadow-hover); transform: translateY(-2px); }
[class*="st-key-proj_card_"]:focus-within { box-shadow: var(--focus); border-color: var(--gold); }
[class*="st-key-proj_card_"] * { position: static !important; }
[class*="st-key-proj_card_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
[class*="st-key-proj_card_"] > [data-testid="stElementContainer"]:not(:first-child) { padding: 0 var(--s2); }
.proj-pic { height: 150px; overflow: hidden; background: var(--green-tint); }
.proj-pic img { width: 100%; height: 150px; object-fit: cover; display: block; }
[class*="st-key-proj_card_"] .proj-pic { position: relative !important; }
[class*="st-key-proj_card_"] .pic-label { position: absolute !important; left: 8px; bottom: 8px; font-size: 0.7rem;
  font-weight: 600; color: var(--green-dark); background: rgba(255, 255, 255, 0.85); border-radius: var(--pill); padding: 1px 8px; }
[class*="st-key-open_project_"] button { min-height: 0; padding: 0; border: none; background: none; box-shadow: none;
  justify-content: flex-start; }
[class*="st-key-open_project_"] button:hover { background: none; }
[class*="st-key-open_project_"] button p { font-family: 'Fraunces', Georgia, serif; font-size: 1.08rem; font-weight: 600;
  color: var(--green); text-align: left; line-height: 1.3; }
[class*="st-key-proj_card_"]:hover [class*="st-key-open_project_"] button p { text-decoration: underline; }
[class*="st-key-open_project_"] button::after { content: ""; position: absolute; inset: 0; z-index: 1; cursor: pointer; }
[class*="st-key-open_project_"] button:focus-visible { box-shadow: none; }
.proj-meta { font-size: 0.85rem; color: var(--ink-soft); margin-bottom: var(--s1); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.progress { margin-top: 12px; }
.progress-track { height: 8px; border-radius: var(--pill); background: #ece8ee; overflow: hidden; }
.progress-fill { display: block; height: 100%; border-radius: var(--pill); }
.progress-fill.red, .dot.red { background: var(--red); }
.progress-fill.orange, .dot.orange { background: var(--orange); }
.progress-fill.yellow, .dot.yellow { background: var(--yellow); }
.progress-fill.green, .dot.green { background: var(--green-mid); }
.progress-text { display: flex; justify-content: space-between; font-size: 0.82rem; color: var(--ink-soft); margin-top: 6px; }
.progress-text b { color: var(--ink); }
.progress-next { font-size: 0.85rem; font-weight: 600; color: var(--green); margin-top: 4px; }
.progress-legend { display: flex; flex-wrap: wrap; gap: var(--s2); font-size: 0.8rem; color: var(--ink-soft); margin: 4px 0 var(--s3); }
.legend-item { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.legend-range { color: #7b8680; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }

/* ---- Home feed ---- */
.st-key-feed_head { margin: var(--s2) 0 var(--s1); }
.st-key-feed_head [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.st-key-feed_tools { gap: var(--s1) !important; }
.st-key-mark_all_read button { min-height: 32px; }
.st-key-mark_all_read button p { color: var(--green-mid); font-weight: 600; font-size: 0.88rem; }
.st-key-add_meeting button { min-height: 32px; font-size: 0.88rem; }
.st-key-feed_filter { margin-bottom: var(--s1); }
.feed-group { font-size: 0.78rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft);
  margin: var(--s3) 0 var(--s1); display: flex; align-items: center; gap: var(--s1); }
.feed-group span { background: #ece8ee; color: var(--ink); border-radius: var(--pill); padding: 0 8px; font-size: 0.72rem; letter-spacing: 0; }
[class*="st-key-feeditem_"] { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--line);
  border-radius: var(--radius); padding: var(--s2) var(--s3) !important; gap: var(--s1) !important; box-shadow: var(--shadow);
  margin-bottom: var(--s1); transition: box-shadow 0.15s, border-color 0.15s; }
[class*="st-key-feeditem_"]:hover { box-shadow: var(--shadow-hover); }
[class*="st-key-feeditem_"]:focus-within { box-shadow: var(--focus); }
[class*="st-key-feeditem_flag_"] { border-left-color: var(--red); background: #fffafa; }
[class*="st-key-feeditem_waiting_"] { border-left-color: var(--amber); }
[class*="st-key-feeditem_meeting_"] { border-left-color: var(--green-mid); }
[class*="st-key-feeditem_email_"] { border-left-color: #8c99a6; }
[class*="st-key-feeditem_ai_"] { border-left-color: var(--gold); background: #fffdf6; }
[class*="st-key-feeditem_"][class*="_read_"] { box-shadow: none; }
[class*="st-key-feeditem_"][class*="_read_"] .feed-message { color: var(--ink-soft); font-weight: 400; }
[class*="st-key-feeditem_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.feed-head { display: flex; align-items: center; gap: var(--s1); flex-wrap: wrap; font-size: 0.82rem; color: var(--ink-soft); }
.feed-icon { width: 28px; height: 28px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex: none; }
.feed-icon svg { width: 16px; height: 16px; }
.feed-icon.flag { background: var(--red-tint); color: var(--red); }
.feed-icon.waiting { background: var(--amber-tint); color: var(--amber-ink); }
.feed-icon.meeting { background: var(--green-tint); color: var(--green); }
.feed-icon.email { background: #e9edf1; color: #44505c; }
.feed-type { font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.72rem; color: var(--ink); }
.feed-deal { font-weight: 600; color: var(--green-mid); }
.feed-deal::before { content: "·"; margin-right: var(--s1); color: #9aa39e; }
.feed-when { margin-left: auto; white-space: nowrap; }
.unread-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--green-mid); flex: none; }
.chip.sample { background: #eef0f2; color: #3b4651; border-color: #b8c1ca; font-weight: 700; font-size: 0.7rem;
  letter-spacing: 0.05em; text-transform: uppercase; padding: 1px 8px; }
.ai-label.small { padding: 1px 8px; font-size: 0.72rem; gap: 4px; }
.ai-label.small svg { width: 11px; height: 11px; }
.feed-message { font-size: 0.98rem; font-weight: 600; color: var(--ink); line-height: 1.4; margin-top: 2px; }
[class*="st-key-feedactions_"] { gap: var(--s1) !important; flex-wrap: wrap !important; margin-top: 4px; }
[class*="st-key-feedactions_"] button { min-height: 34px; font-size: 0.88rem; }
[class*="st-key-feedbtn_prep_brief_"] button { background: var(--gold-tint); border-color: var(--gold); color: var(--gold-ink); }
[class*="st-key-feedbtn_prep_brief_"] button:hover { background: #f6e7ad; border-color: var(--gold); color: var(--gold-ink); }
[class*="st-key-feedbtn_prep_brief_"] button [data-testid="stIconMaterial"] { color: var(--gold); }
[class*="st-key-more_"] button { min-height: 34px; min-width: 40px; padding: 0 10px; border-color: transparent; background: none; }
[class*="st-key-more_"] button:hover { background: #f1eef3; border-color: var(--line); }
[class*="st-key-more_"] button [data-testid="stIconMaterial"] { display: none; }  /* no dropdown arrow on the ... menu */
.brief { background: var(--gold-tint); border: 1px solid #e2cd7f; border-radius: var(--radius-sm); padding: 10px 14px; margin-top: var(--s1); }
.brief-head { display: flex; align-items: center; gap: var(--s1); flex-wrap: wrap; }
.brief-when { font-size: 0.78rem; color: var(--gold-ink); }
.brief ul { margin: 6px 0 4px; padding-left: 18px; font-size: 0.9rem; }
.brief li { margin-bottom: 2px; }
.brief-check { font-size: 0.8rem; color: var(--amber-ink); }
.brief-check.ok { color: var(--green); }
.caught-up { background: var(--surface); border: 1px dashed #b9c9bf; border-radius: var(--radius); padding: var(--s4) var(--s3);
  text-align: center; margin: var(--s2) 0; }
.caught-up-mark { width: 48px; height: 48px; margin: 0 auto var(--s1); border-radius: 50%; background: #dcebe3; color: var(--green);
  font-size: 1.5rem; line-height: 48px; font-weight: 700; }
.caught-up-title { font-family: 'Fraunces', Georgia, serif; font-size: 1.25rem; font-weight: 600; color: var(--green); }
.caught-up-text { color: var(--ink-soft); font-size: 0.92rem; margin-top: 4px; }
/* Bell in the top bar: the unread count sits next to the icon. */
.st-key-nav_bell button { min-height: var(--control-h); border: none; background: none; box-shadow: none; padding: 0 10px; gap: 4px;
  border-radius: var(--radius-sm); }
.st-key-nav_bell button [data-testid="stIconMaterial"] { color: #ffffff; font-size: 22px; }
.st-key-nav_bell button p { background: var(--gold); color: var(--green-dark); border-radius: var(--pill); padding: 0 7px;
  font-size: 0.75rem; font-weight: 700; line-height: 18px; }
.st-key-nav_bell button:hover { background: rgba(255, 255, 255, 0.12); }
.st-key-nav_bell button:focus-visible { box-shadow: var(--focus); }
/* Right rail: Today's agenda and Waiting on you. It stays in view while the feed scrolls (desktop). */
/* Streamlit wraps the rail in a box only as tall as the rail, so that wrapper is what sticks (inside the
   column, which is as tall as the feed). */
[data-testid="stLayoutWrapper"]:has(> .st-key-home_rail) { position: sticky; top: calc(var(--topbar-h) + var(--s2)); }
.st-key-home_rail { gap: var(--s2) !important; margin-top: var(--s2); }
.st-key-rail_today, .st-key-rail_waiting { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: var(--s2) var(--s3) !important; box-shadow: var(--shadow); gap: 4px !important; }
.st-key-rail_today { border-top: 3px solid var(--green-mid); }
.st-key-rail_waiting { border-top: 3px solid var(--amber); }
.st-key-rail_today [data-testid="stMarkdownContainer"], .st-key-rail_waiting [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.rail-title { font-family: 'Fraunces', Georgia, serif; font-size: 1.15rem; font-weight: 600; color: var(--green);
  display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }
.rail-title span { font-family: 'Public Sans', sans-serif; font-size: 0.8rem; font-weight: 500; color: var(--ink-soft); }
.rail-empty { color: var(--ink-soft); font-size: 0.9rem; padding: 4px 0; }
.agenda { list-style: none; margin: 0; padding: 0; }
.agenda-item { display: flex; gap: 12px; padding: 10px 0; border-top: 1px solid #eee9f0; }
.agenda-item:first-child { border-top: none; }
.agenda-time { flex: 0 0 64px; font-weight: 700; color: var(--green); font-size: 0.88rem; white-space: nowrap; }
.agenda-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.agenda-title { font-weight: 600; color: var(--ink); }
.agenda-meta { font-size: 0.82rem; color: var(--ink-soft); }
.agenda-status { font-size: 0.78rem; color: var(--green-mid); font-weight: 600; display: flex; align-items: center; gap: 6px; }
.agenda-item.done .agenda-time, .agenda-item.done .agenda-title { color: #8b958f; }
.agenda-item.done .agenda-status { color: #8b958f; font-weight: 500; }
.agenda-item.now .agenda-status { color: var(--gold-ink); }
[class*="st-key-rail_"] .stButton button { justify-content: space-between; min-height: 36px; padding: 0 4px;
  border: none; border-top: 1px solid #eee9f0; border-radius: 0; background: none; }
[class*="st-key-rail_"] .stButton button > div, [class*="st-key-rail_"] .stButton button span,
[class*="st-key-rail_"] .stButton button [data-testid="stMarkdownContainer"] { width: 100%; }
[class*="st-key-rail_"] .stButton button p { width: 100%; display: flex; justify-content: space-between; align-items: center;
  color: var(--ink); font-size: 0.92rem; text-align: left; }
[class*="st-key-rail_"] .stButton button p strong { background: var(--amber-tint); color: var(--amber-ink); border-radius: var(--pill);
  padding: 1px 9px; font-size: 0.8rem; line-height: 1.4; min-width: 26px; text-align: center; }
[class*="st-key-rail_open_flags"] .stButton button p strong { background: var(--red-tint); color: var(--red-ink); }
[class*="st-key-rail_"] .stButton button:hover { background: var(--green-tint); }

/* A flag card opened from Home is outlined for a moment. */
[class*="st-key-flagcard_open_"].flag-focus { box-shadow: 0 0 0 3px var(--gold), var(--shadow-hover); transition: box-shadow 0.3s; }

/* ---- Phones and narrow windows ---- */
@media (max-width: 760px) {
  :root { --topbar-h: 104px; --card-pad: 16px; }
  .block-container { padding: calc(var(--topbar-h) + 16px) 16px 96px !important; }
  /* Top bar: two rows. Brand and Sign out on top; All deals, Connections and the role badge below. */
  .st-key-topbar { height: auto; min-height: var(--topbar-h); padding: 8px 16px; flex-wrap: wrap !important;
    row-gap: 4px !important; align-content: center; }
  .st-key-topbar_nav { width: 100% !important; gap: 4px !important; flex-wrap: nowrap !important; }
  .st-key-nav_home { margin-right: auto; }
  /* Only the sparkle shows on a phone, so Home, All deals and Connections fit; the name stays for screen readers. */
  .st-key-nav_home button p { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .st-key-nav_home button { gap: 0; width: 40px; justify-content: center; }
  .st-key-nav_home button::before { width: 22px; height: 22px; }
  .st-key-nav_all_deals button, .st-key-nav_connections button { padding: 0 8px; }
  .st-key-nav_all_deals button p, .st-key-nav_connections button p { font-size: 0.9rem; }
  .st-key-topbar_user { width: 100% !important; justify-content: space-between; gap: 8px !important; }
  .who { gap: 8px; font-size: 0.9rem; }
  .who .user-name { display: none; }  /* room for the bell and Sign out; the badge stays */
  .st-key-topbar .pill.simulated { font-size: 0.7rem; padding: 2px 8px; }
  .st-key-sign_out button { min-height: 40px; padding: 0 12px; }
  /* Breadcrumb on one line; a long deal name is cut with an ellipsis. */
  .st-key-breadcrumb { flex-wrap: nowrap !important; }
  .st-key-breadcrumb [data-testid="stElementContainer"]:last-child { min-width: 0; }
  .crumb { min-width: 0; }
  .crumb .here { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* Headings and page title row */
  h2 { font-size: 1.6rem !important; }
  .st-key-page_head h2 { font-size: 1.6rem !important; }
  .deal-title { font-size: 1.3rem; }
  .deal-top { flex-direction: column; gap: 8px; }
  .deal-thumb { width: 72px; height: 48px; }
  /* Stat cards: two per row instead of one. */
  .st-key-stat_row [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 12px !important; }
  .st-key-stat_row [data-testid="stColumn"] { flex: 1 1 calc(50% - 6px) !important; min-width: calc(50% - 6px) !important;
    width: calc(50% - 6px) !important; }
  .stat-value { font-size: 1.5rem; }
  .stat-value.text { font-size: 1rem; line-height: 1.4; }
  [class*="st-key-statcard_"] { padding: 12px 14px !important; }
  /* Tabs: scroll sideways instead of overflowing the page. */
  .stTabs [role="tablist"] { overflow-x: auto; flex-wrap: nowrap; scrollbar-width: none; padding-right: 8px; }
  .stTabs [role="tab"] { padding: 0 14px; flex: none; }
  .stTabs [role="tab"]:last-of-type { margin-left: 8px; }
  /* Cards and rows */
  .source { grid-template-columns: 56px minmax(0, 1fr); row-gap: 2px; }
  .source .when { grid-column: 2; }
  .source .figure { grid-column: 2; text-align: left; }
  .unchecked { margin-left: 0; }
  .kv .v { white-space: normal; }
  table.preview { display: block; overflow-x: auto; }
  /* Comfortable tap targets for link-style buttons */
  .st-key-back_to_deals button, .st-key-go_documents button, .st-key-clear_filter button { min-height: 40px; }
  .st-key-fab { right: 16px; bottom: 16px; }
  .home-greeting { font-size: 1.6rem; }
  .st-key-project_strip > div { flex-basis: 78vw !important; width: 78vw !important; }
  .strip-arrows { display: none; }  /* swipe instead */
  .st-key-nav_home_link button { padding: 0 8px; }
  [class*="st-key-feeditem_"] { padding: 12px 14px !important; }
  .feed-when { margin-left: 0; width: 100%; order: 10; }
  [data-testid="stLayoutWrapper"]:has(> .st-key-home_rail) { position: static; }
  .st-key-nav_bell button { padding: 0 6px; }
  .st-key-nav_home_link button p { font-size: 0.9rem; }
  .st-key-fab::before { display: none; }  /* no hover on a phone */
}
</style>
"""

PILL_CLASSES = {"Needs Review": "needs-review", "Extracting": "extracting", "Approved": "approved", "New": "new"}


def apply():
    st.markdown(CSS, unsafe_allow_html=True)


def html_escape(text):
    from html import escape
    return escape(str(text))


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
