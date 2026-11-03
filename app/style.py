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
/* The user name opens Settings. */
.st-key-nav_settings button { min-height: var(--control-h); border: none; background: none; box-shadow: none; padding: 0 8px; }
.st-key-nav_settings button p, .st-key-nav_settings button span { color: #ffffff; font-weight: 500; white-space: nowrap; }
.st-key-nav_settings button:hover { background: rgba(255, 255, 255, 0.12); }
.st-key-nav_settings button:focus-visible { box-shadow: var(--focus); }

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

/* ---- OM: badge and tab ---- */
.om-badge { display: inline-flex; align-items: center; gap: 5px; padding: 2px 10px 2px 3px; border-radius: var(--pill);
  font-size: 0.78rem; font-weight: 700; border: 1px solid var(--line); background: var(--surface); color: var(--ink);
  margin-right: 6px; vertical-align: middle; white-space: nowrap; }
.om-badge-label { border-radius: var(--pill); padding: 1px 7px; font-size: 0.68rem; letter-spacing: 0.05em; color: #ffffff; }
.om-badge.red .om-badge-label { background: var(--red); }
.om-badge.orange .om-badge-label { background: var(--orange); }
.om-badge.yellow .om-badge-label { background: var(--yellow); color: var(--green-dark); }
.om-badge.green .om-badge-label { background: var(--green-mid); }
.proj-pills { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.deal-pills { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.om-head { display: flex; align-items: center; gap: var(--s2); margin-bottom: 12px; }
.om-percent { font-family: 'Fraunces', Georgia, serif; font-size: 2.6rem; font-weight: 600; line-height: 1; }
.om-percent.red { color: var(--red); } .om-percent.orange { color: var(--orange); }
.om-percent.yellow { color: #a8861a; } .om-percent.green { color: var(--green-mid); }
.om-head-title { font-family: 'Fraunces', Georgia, serif; font-size: 1.25rem; font-weight: 600; color: var(--green); }
.om-head-note { color: var(--ink-soft); font-size: 0.9rem; }
.om-bar { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; }
.om-seg-track { height: 14px; border-radius: 4px; background: #ece8ee; overflow: hidden; display: flex; }
.om-fill { display: block; height: 100%; }
.om-fill.approved.red { background: var(--red); } .om-fill.approved.orange { background: var(--orange); }
.om-fill.approved.yellow { background: var(--yellow); } .om-fill.approved.green { background: var(--green-mid); }
.om-fill.waiting { background: #c9dccf; }
.om-seg-label { font-size: 0.75rem; color: var(--ink-soft); margin-top: 4px; display: flex; justify-content: space-between; gap: 4px; }
.om-seg-label b { color: var(--ink); }
.om-legend { display: flex; gap: var(--s2); font-size: 0.78rem; color: var(--ink-soft); margin: 8px 0 var(--s2); flex-wrap: wrap; }
.om-legend i { display: inline-block; width: 12px; height: 8px; border-radius: 2px; margin-right: 5px; vertical-align: middle; }
.om-legend i.solid { background: var(--green-mid); } .om-legend i.light { background: #c9dccf; } .om-legend i.none { background: #ece8ee; }
.om-item { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--line); border-radius: var(--radius-sm);
  padding: 12px 14px; margin-bottom: var(--s1); }
.om-item.required { border-left-color: var(--red); }
.om-item-head { display: flex; align-items: center; gap: var(--s1); flex-wrap: wrap; }
.om-item-what { font-weight: 700; color: var(--ink); margin-right: 4px; }
.om-item-why { font-size: 0.88rem; color: var(--ink); margin-top: 4px; }
.om-item-meta { font-size: 0.78rem; color: var(--ink-soft); margin-top: 4px; }
.om-need { font-size: 0.82rem; color: var(--amber-ink); margin-top: 4px; }
.om-priority { font-size: 0.72rem; font-weight: 600; color: var(--ink-soft); }
.om-priority.high { color: var(--red-ink); }
.om-value { font-size: 0.95rem; margin-top: 4px; word-break: break-word; }
.om-source { font-size: 0.78rem; color: var(--ink-soft); margin-top: 2px; }
.om-empty { color: var(--ink-soft); font-size: 0.9rem; }
.om-approved { padding: 6px 0; border-top: 1px solid #eee9f0; font-size: 0.9rem; }
/* The guided interview and the AI boxes on the OM tab */
.st-key-om_interview { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--green-mid);
  border-radius: var(--radius); padding: var(--s3); margin-bottom: var(--s3); }
.om-q-count { font-size: 0.78rem; color: var(--ink-soft); font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase; }
.om-q-label { font-family: 'Fraunces', Georgia, serif; font-size: 1.2rem; font-weight: 600; color: var(--green); margin-top: 4px; }
.om-q-text { font-size: 0.98rem; margin: 6px 0 4px; }
.st-key-om_draft_box, .st-key-om_ai_answer_box, .st-key-om_sort_box { background: var(--gold-tint); border: 1px solid var(--gold);
  border-radius: var(--radius-sm); padding: var(--s2); margin-bottom: var(--s2); }
[class*="st-key-om_wait_"], [class*="st-key-om_assumption_"], [class*="st-key-om_reply_card_"], [class*="st-key-om_doc_card_"] {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 12px var(--s2); }
/* OM compact bar: % approved, counts, Missing and the two exports on one row */
.st-key-om_bar { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 12px var(--s2) !important; margin-bottom: var(--s1); gap: var(--s2) !important; flex-wrap: wrap !important; }
.st-key-om_bar [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.st-key-om_bar_actions { gap: var(--s1) !important; flex-wrap: wrap !important; }
.om-mini { display: flex; align-items: center; gap: 12px; min-width: 0; }
.om-mini .om-percent { font-size: 2rem; }
.om-mini-text { min-width: 0; }
.om-mini .om-head-title { font-size: 1.05rem; }
.om-mini .om-head-note { font-size: 0.85rem; }
.om-mini-track { height: 6px; border-radius: var(--pill); background: #ece8ee; overflow: hidden; display: flex; margin-top: 6px; max-width: 360px; }
.st-key-om_export_result { gap: var(--s1) !important; flex-wrap: wrap !important; margin-bottom: var(--s1); }
/* OM slide editor: the list (desktop and tablet), the stepper, the editor */
.st-key-om_slide_list { gap: 2px !important; position: sticky; top: calc(var(--topbar-h) + var(--s2)); }
[class*="st-key-om_slide_btn_"] button { justify-content: flex-start; min-height: 36px; padding: 4px 10px; border-radius: var(--radius-sm); }
[class*="st-key-om_slide_btn_"] button > div, [class*="st-key-om_slide_btn_"] button [data-testid="stMarkdownContainer"] {
  justify-content: flex-start; text-align: left; width: 100%; }
[class*="st-key-om_slide_btn_"] button p { text-align: left; font-size: 0.9rem; }
.st-key-om_stepper { background: var(--green-tint); border-radius: var(--radius-sm); padding: 6px 8px !important;
  margin-bottom: var(--s1); flex-wrap: nowrap !important; }
.om-step { display: flex; flex-direction: column; align-items: center; text-align: center; line-height: 1.25; }
.om-step b { font-family: 'Fraunces', Georgia, serif; color: var(--green); font-size: 1.05rem; }
.om-step span { font-size: 0.8rem; color: var(--ink-soft); }
.st-key-om_slide_editor { gap: 12px !important; }
/* Previews have a readable fixed width on big screens, and shrink to fit a phone. */
.st-key-om_slide_editor [data-testid="stImage"], .st-key-om_slide_editor [data-testid="stImageContainer"],
.st-key-om_slide_editor [data-testid="stImage"] img { max-width: 100% !important; height: auto !important; }
/* Previous | title | Next on one line at every width. */
.st-key-om_stepper { display: grid !important; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; }
.st-key-om_stepper > * { width: auto !important; min-width: 0; }
.st-key-om_stepper [data-testid="stElementContainer"]:has(.om-step) { justify-self: center; }
.om-step span { white-space: nowrap; }
.slide-head { display: flex; align-items: center; gap: var(--s1); flex-wrap: wrap; }
.slide-need { font-weight: 600; color: var(--ink); font-size: 1rem; }
[class*="st-key-om_item_"] { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm);
  padding: 12px 14px !important; gap: 8px !important; }
[class*="st-key-om_item_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
[class*="st-key-om_photo_ways_"] { gap: var(--s1) !important; flex-wrap: wrap !important; }
[class*="st-key-om_photo_take_"] button, [class*="st-key-om_photo_upload_"] button { min-height: 56px; min-width: 180px;
  font-size: 1rem; font-weight: 700; }
[class*="st-key-om_photo_take_"] button [data-testid="stIconMaterial"],
[class*="st-key-om_photo_upload_"] button [data-testid="stIconMaterial"] { font-size: 24px; }
[class*="st-key-om_slot_photo_"] img, [class*="st-key-om_item_"] img { border-radius: var(--radius-sm); }
.res-chip { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 0.8rem; color: var(--ink-soft); }
[class*="st-key-om_slot_photo_"] [data-testid="stImage"] img { max-width: 480px; }
.grid-title { font-weight: 700; color: var(--ink); margin-top: 4px; }
[class*="st-key-om_photo_grid_"] [data-testid="stHorizontalBlock"] { gap: 10px !important; }
[class*="st-key-om_grid_"] { gap: 4px !important; }
[class*="st-key-om_grid_"] img { border-radius: var(--radius-sm); border: 1px solid var(--line); }
.grid-badge { font-size: 0.75rem; color: var(--ink-soft); background: #f1eef3; border-radius: var(--pill); padding: 1px 8px;
  display: inline-block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.grid-badge.used { background: var(--green-tint); color: var(--green); font-weight: 600; }
.st-key-om_slide_draft { background: var(--gold-tint); border: 1px solid var(--gold); border-radius: var(--radius-sm); padding: var(--s2); }
/* Rename: the small pencil next to a deal's name (above a card's click layer), and the Undo bar */
[class*="st-key-rename_btn_"] button { min-height: 32px; width: 32px; min-width: 32px; padding: 0; border-radius: 50%;
  justify-content: center; border: 1px solid transparent; background: none; }
/* Zero-size text, not position: absolute, because cards force every element inside them to be static. */
[class*="st-key-rename_btn_"] button p { font-size: 0 !important; width: 0; height: 0; overflow: hidden; margin: 0; }
[class*="st-key-rename_btn_"] button [data-testid="stIconMaterial"] { color: var(--green-mid); font-size: 18px; margin: 0; }
[class*="st-key-rename_btn_"] button:hover { background: var(--green-tint); border-color: var(--line); }
[class*="st-key-deal_card_"] [class*="st-key-rename_btn_"] button,
[class*="st-key-proj_card_"] [class*="st-key-rename_btn_"] button { position: relative !important; z-index: 2; }
[class*="st-key-proj_name_"], [class*="st-key-deal_name_"] { gap: 4px !important; flex-wrap: nowrap !important;
  align-items: flex-start !important; }
[class*="st-key-proj_name_"] { padding: 0 var(--s2); }
/* The name takes the room and wraps; the pencil keeps its place at the end. */
[class*="st-key-proj_name_"] > [data-testid="stElementContainer"]:first-child,
[class*="st-key-deal_name_"] > [data-testid="stElementContainer"]:first-child { flex: 0 1 auto !important; min-width: 0; }
[class*="st-key-proj_name_"] > [data-testid="stElementContainer"]:last-child,
[class*="st-key-deal_name_"] > [data-testid="stElementContainer"]:last-child { flex: none !important; }
[class*="st-key-open_project_"] button div, [class*="st-key-open_deal_"] button div { white-space: normal; overflow: visible;
  text-overflow: clip; }
[class*="st-key-open_project_"] button p, [class*="st-key-open_deal_"] button p { white-space: normal; }
[class*="st-key-open_project_"] button *, [class*="st-key-open_deal_"] button * { text-align: left !important; justify-content: flex-start !important; }
[class*="st-key-proj_card_"] [data-testid="stForm"] { padding: 0 var(--s2); }
[class*="st-key-rename_buttons_"] { gap: var(--s1) !important; }
[class*="st-key-deal_card_"] [data-testid="stForm"], [class*="st-key-proj_card_"] [data-testid="stForm"] { position: relative !important; z-index: 2; }
.st-key-deal_top { gap: var(--s3) !important; flex-wrap: nowrap !important; }
.st-key-deal_id { gap: var(--s2) !important; flex-wrap: nowrap !important; min-width: 0; }
.st-key-deal_name_col { gap: 4px !important; min-width: 0; }
.st-key-deal_name_row { gap: 6px !important; flex-wrap: nowrap !important; }
.st-key-rename_undo_bar { background: var(--green-tint); border: 1px solid #c9dccf; border-radius: var(--radius-sm);
  padding: 6px 12px !important; gap: var(--s1) !important; margin-bottom: var(--s1); flex-wrap: wrap !important; }
.st-key-rename_undo_bar [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.undo-text { font-weight: 600; color: var(--green); }
.st-key-rename_reapprove { gap: var(--s1) !important; align-items: center; }
/* "+": the first tile in the Home strip, the top bar button and the centre of the phone bottom bar */
.st-key-project_strip > div:has(.st-key-proj_add_tile) { flex: 0 0 200px !important; width: 200px !important; }
.st-key-proj_add_tile { position: relative; width: 100% !important; height: 100%; min-height: 240px; border: 2px dashed #b9c9bf;
  border-radius: var(--radius); background: var(--green-tint); align-items: center; justify-content: center !important; text-align: center;
  gap: 6px !important; padding: var(--s2); transition: border-color 0.15s, background 0.15s; }
.st-key-proj_add_tile:hover { border-color: var(--green-mid); background: #e3efe7; }
.st-key-proj_add_tile:focus-within { box-shadow: var(--focus); }
.st-key-proj_add_tile * { position: static !important; }
.st-key-proj_add_tile { display: grid !important; align-content: center; justify-items: center; }
.st-key-proj_add_tile > * { flex: none !important; width: auto !important; }
.st-key-proj_add_tile [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
.add-tile-plus { width: 56px; height: 56px; border-radius: 50%; background: var(--green); color: #ffffff; font-size: 2rem;
  line-height: 1; font-weight: 400; margin: 0 auto; display: flex; align-items: center; justify-content: center; padding-bottom: 3px;
  box-sizing: border-box; box-shadow: 0 0 0 4px #ffffff, 0 0 0 6px var(--gold); }
.st-key-add_property_tile button { min-height: 0; border: none; background: none; box-shadow: none; padding: 0; }
.st-key-add_property_tile button:hover { background: none; }
.st-key-add_property_tile button p { font-family: 'Fraunces', Georgia, serif; font-size: 1.08rem; font-weight: 600; color: var(--green); }
.st-key-add_property_tile button::after { content: ""; position: absolute; inset: 0; z-index: 1; cursor: pointer; }
.add-tile-note { font-size: 0.82rem; color: var(--ink-soft); max-width: 200px; margin: 0 auto; }
.st-key-nav_add button { min-height: 36px; background: var(--gold); border-color: var(--gold); color: var(--green-dark);
  border-radius: var(--pill); padding: 0 14px; font-weight: 700; white-space: nowrap; }
.st-key-nav_add button p { color: var(--green-dark); font-weight: 700; }
.st-key-nav_add button [data-testid="stIconMaterial"] { color: var(--green-dark); }
.st-key-nav_add button:hover { background: #d8b23a; border-color: #d8b23a; color: var(--green-dark); }
.om-live { font-size: 0.88rem; padding: 8px 12px; border-radius: var(--radius-sm); margin-bottom: var(--s1); }
.om-live.working { background: var(--gold-tint); border: 1px solid var(--gold); color: var(--gold-ink); }
.om-live.done { background: #eef5f0; border: 1px solid #c9dccf; color: var(--green); }
.om-live .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--gold); margin-right: 8px;
  animation: om-pulse 1.2s ease-in-out infinite; }
@keyframes om-pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .om-live .dot { animation: none; } }
[class*="st-key-om_wait_"] { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--amber);
  border-radius: var(--radius-sm); padding: 12px 14px !important; gap: 6px !important; margin-bottom: var(--s1); }
[class*="st-key-om_wait_"] [data-testid="stMarkdownContainer"] { margin-bottom: 0; }
[class*="st-key-om_approve_"] button { min-height: 32px; }

/* A flag card opened from Home is outlined for a moment. */
[class*="st-key-flagcard_open_"].flag-focus { box-shadow: 0 0 0 3px var(--gold), var(--shadow-hover); transition: box-shadow 0.3s; }

/* ---- Documents tab ---- */
.docs-summary { font-weight: 600; color: var(--green); margin-bottom: var(--s2); }
.docs-empty { background: var(--surface); border: 1px dashed var(--line); border-radius: var(--radius); padding: var(--s3);
  color: var(--ink-soft); margin-bottom: var(--s2); }
[class*="st-key-doc_card_"] { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: var(--s2) var(--s3); margin-bottom: var(--s1); }
[class*="st-key-doc_card_"].flag-focus { box-shadow: 0 0 0 3px var(--gold), var(--shadow-hover); transition: box-shadow 0.3s; }
.doc-head { display: flex; align-items: center; gap: var(--s1); flex-wrap: wrap; }
.doc-name { font-weight: 700; color: var(--ink); word-break: break-word; }
.doc-meta { font-size: 0.85rem; color: var(--ink-soft); margin-top: 2px; }
.doc-read { margin-top: 6px; }
.doc-used { font-size: 0.85rem; color: var(--green-mid); font-weight: 600; margin-top: 2px; }
[class*="st-key-doc_lock_"] { background: var(--red-tint); border: 1px solid #f0b7b1; border-radius: var(--radius-sm);
  padding: 12px var(--s2); margin: var(--s1) 0; }
.st-key-docs_upload { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: var(--s2) var(--s3);
  margin-top: var(--s2); }

/* ---- Phone-only and desktop-only pieces ---- */
.st-key-nav_menu, .st-key-bottom_nav { display: none !important; }
.menu-who { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }

/* ================= Tablets and phones (up to __TABLET__px) ================= */
@media (max-width: __TABLET__px) {
  :root { --card-pad: 20px; }
  .block-container { padding: calc(var(--topbar-h) + var(--s3)) var(--s3) 96px !important; }
  /* Top bar: the sparkle stands for the app name; the user name shows as a person icon. */
  .st-key-nav_home button p, .st-key-nav_settings button p { position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip: rect(0 0 0 0); }
  .st-key-nav_home button { gap: 0; width: 44px; justify-content: center; }
  .st-key-nav_settings button { width: 44px; min-width: 44px; padding: 0; justify-content: center; }
  .st-key-topbar_user, .st-key-topbar_nav { gap: 4px !important; }
  .st-key-topbar { padding-left: 12px; padding-right: 12px; }
  .st-key-nav_home_link button, .st-key-nav_all_deals button, .st-key-nav_connections button { padding: 0 10px; }
  .st-key-sign_out button { padding: 0 12px; }
  .st-key-topbar .pill.simulated { font-size: 0.68rem; padding: 2px 8px; }
  /* Tabs, the OM view switch and filter chips scroll sideways instead of wrapping or overflowing. */
  .stTabs [role="tablist"] { overflow-x: auto; flex-wrap: nowrap; scrollbar-width: none; padding-right: 8px; }
  .stTabs [role="tablist"]::-webkit-scrollbar { display: none; }
  .stTabs [role="tab"] { padding: 0 14px; flex: none; }
  .stTabs [role="tab"]:last-of-type { margin-left: 8px; }
  .st-key-om_view [data-testid="stButtonGroup"] > div, .st-key-feed_filter [data-testid="stButtonGroup"] > div {
    flex-wrap: nowrap !important; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
  .st-key-om_view button, .st-key-feed_filter button { flex: none; }
  .om-bar { grid-template-columns: repeat(3, minmax(0, 1fr)); row-gap: 10px; }
  /* "+" in the top bar: just the icon (the label is read out by screen readers). */
  .st-key-nav_add button { width: 40px; min-width: 40px; padding: 0; justify-content: center; }
  .st-key-nav_add button p { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  [data-testid="stLayoutWrapper"]:has(> .st-key-home_rail) { position: static; }
  /* Home: the rail ("Today", "Waiting on you") moves under the feed, full width. */
  .st-key-home_columns [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; row-gap: var(--s3) !important; }
  .st-key-home_columns [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { flex: 1 1 100% !important;
    width: 100% !important; min-width: 100% !important; }
  .kv .v { white-space: normal; }
  table.preview { display: block; overflow-x: auto; }
  .st-key-fab::before { display: none; }  /* no hover label on touch screens */
  /* Hover-only extras are hidden on touch screens: heading anchor links, and the tab arrows (swipe instead). */
  [data-testid="stHeaderActionElements"], [data-testid="stTabsScrollLeft"], [data-testid="stTabsScrollRight"] { display: none !important; }
}

/* ================= Phones (up to __PHONE__px) ================= */
@media (max-width: __PHONE__px) {
  :root { --topbar-h: 56px; --card-pad: 16px; --control-h: 44px; --bottomnav-h: 64px; }
  .block-container { padding: calc(var(--topbar-h) + 16px) 16px calc(var(--bottomnav-h) + 104px) !important; }
  /* Top bar: one row with the sparkle, the bell and the menu. Navigation moves to the bottom bar. */
  .st-key-topbar { padding: 0 8px 0 4px; flex-wrap: nowrap !important; }
  .st-key-nav_home_link, .st-key-nav_all_deals, .st-key-nav_connections, .st-key-nav_settings, .st-key-sign_out,
  .st-key-topbar_user .who { display: none !important; }
  .st-key-nav_menu { display: block !important; }
  .st-key-nav_menu button { min-height: 44px; min-width: 44px; padding: 0 10px; border: none; background: none; color: #ffffff; }
  .st-key-nav_menu button p { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .st-key-nav_menu button [data-testid="stIconMaterial"] { color: #ffffff; font-size: 26px; }
  .st-key-nav_menu button:hover { background: rgba(255, 255, 255, 0.12); }
  .st-key-nav_bell button { min-height: 44px; padding: 0 8px; }
  .st-key-nav_add { display: none !important; }  /* the "+" is the centre of the bottom bar on phones */
  .st-key-topbar .pill.simulated { font-size: 0.65rem; padding: 2px 6px; }
  /* Bottom navigation: always in view, one tap, icon and label. */
  .st-key-bottom_nav { display: flex !important; position: fixed; left: 0; right: 0; bottom: 0; z-index: 1001;
    height: calc(var(--bottomnav-h) + env(safe-area-inset-bottom)); padding: 0 8px env(safe-area-inset-bottom);
    background: var(--green-dark); border-top: 3px solid var(--gold); gap: 0 !important; flex-wrap: nowrap !important;
    align-items: stretch; box-shadow: 0 -2px 8px rgba(19, 39, 30, 0.25); }
  .st-key-bottom_nav > div { flex: 1 1 0 !important; width: auto !important; }
  .st-key-bottom_nav button { width: 100%; height: var(--bottomnav-h); min-height: 0; flex-direction: column; gap: 2px;
    border: none !important; background: none !important; box-shadow: none !important; border-radius: 0; padding: 6px 0 4px; }
  .st-key-bottom_nav button p { font-size: 0.78rem; color: #dfe7e2; font-weight: 500; white-space: nowrap;
    overflow: visible; text-overflow: clip; }
  .st-key-bottom_nav button > div, .st-key-bottom_nav button [data-testid="stMarkdownContainer"] { overflow: visible; max-width: none; }
  .st-key-bottom_nav button [data-testid="stIconMaterial"] { color: #dfe7e2; font-size: 24px; margin: 0; }
  .st-key-bottom_nav button[kind="primary"] p, .st-key-bottom_nav button[data-testid="stBaseButton-primary"] p,
  .st-key-bottom_nav button[kind="primary"] [data-testid="stIconMaterial"],
  .st-key-bottom_nav button[data-testid="stBaseButton-primary"] [data-testid="stIconMaterial"] { color: var(--gold); font-weight: 700; }
  .st-key-bottom_nav { padding: 0 2px env(safe-area-inset-bottom); }
  .st-key-bottom_nav button p { font-size: 0.68rem; letter-spacing: -0.01em; }
  .st-key-bottom_nav button > div > span { flex-direction: column !important; gap: 2px; align-items: center !important; }
  /* Card names stay left-aligned (phones centre other buttons). */
  [class*="st-key-open_project_"] button, [class*="st-key-open_deal_"] button { justify-content: flex-start !important; }
  [class*="st-key-open_project_"] button p, [class*="st-key-open_deal_"] button p { text-align: left; }
  /* The centre "+": a raised gold circle. */
  .st-key-bnav_add button [data-testid="stIconMaterial"] { width: 40px; height: 40px; border-radius: 50%; background: var(--gold);
    color: var(--green-dark) !important; font-size: 28px; display: inline-flex; align-items: center; justify-content: center;
    margin-top: -14px; box-shadow: 0 0 0 3px var(--green-dark); }
  .st-key-bnav_add button p { color: var(--gold) !important; font-weight: 700; }
  /* "This deal's photos": two thumbnails per row on a phone. */
  [class*="st-key-om_photo_grid_"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
  [class*="st-key-om_photo_grid_"] [data-testid="stColumn"] { flex: 1 1 calc(50% - 5px) !important; min-width: calc(50% - 5px) !important;
    width: calc(50% - 5px) !important; }
  [class*="st-key-om_photo_grid_"] [data-testid="stColumn"]:empty,
  [class*="st-key-om_photo_grid_"] [data-testid="stColumn"]:not(:has([class*="st-key-om_grid_"])) { display: none !important; }
  /* OM slide editor on a phone: Previous / Next instead of the list. */
  [data-testid="stColumn"]:has(.st-key-om_slide_list) { display: none !important; }
  .st-key-om_stepper [data-testid="stElementContainer"]:has(.stButton) { width: auto !important; flex: none !important; }
  .st-key-om_stepper .stButton, .st-key-om_stepper .stButton button { width: auto !important; min-width: 44px; }
  .st-key-om_stepper .stButton button p { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .st-key-om_stepper .om-step b { font-size: 1rem; }
  [class*="st-key-om_photo_take_"] button, [class*="st-key-om_photo_upload_"] button { min-width: 0; }
  .st-key-om_bar_actions { width: 100% !important; }
  /* The pencil: a 44px tap target that stays next to the name. */
  [class*="st-key-rename_btn_"] button { min-height: 44px; width: 44px !important; min-width: 44px; }
  .block-container [data-testid="stElementContainer"][class*="st-key-rename_btn_"], .block-container [class*="st-key-rename_btn_"] .stButton {
    width: auto !important; flex: none !important; }
  .st-key-deal_top, .st-key-deal_id { flex-direction: column !important; align-items: flex-start !important; gap: 8px !important; }
  .st-key-deal_id > [data-testid="stElementContainer"], .st-key-deal_id > [data-testid="stLayoutWrapper"] { width: 100% !important; }
  .st-key-proj_add_tile { min-height: 200px; }
  .st-key-project_strip > div:has(.st-key-proj_add_tile) { flex-basis: 150px !important; width: 150px !important; }
  /* The AI button sits above the bottom bar, never over it. */
  .st-key-fab { right: 16px; bottom: calc(var(--bottomnav-h) + 16px + env(safe-area-inset-bottom)); }
  /* Readable text and comfortable taps. */
  .om-item-why, .om-value, .feed-message, .rec-why, .rec-next, .finding-summary, .takeaways li, .banner, .kv .k, .kv .v,
  .om-q-text, .deal-meta, .om-head-note, .stMarkdown p, .stMarkdown li, .doc-read { font-size: 1rem; }
  [class*="st-key-doc_card_"], .st-key-docs_upload { padding: 14px 16px; }
  .stButton button, .stDownloadButton button, .stFormSubmitButton button, [data-testid="stPopover"] > div > button,
  [data-testid="stExpander"] summary, [data-testid="stButtonGroup"] button, [data-testid="stFileUploader"] button,
  [data-testid="stChatInputSubmitButton"], [data-testid="stAudioInputActionButton"] { min-height: 44px; }
  [data-testid="stChatInputSubmitButton"], [data-testid="stAudioInputActionButton"] { min-width: 44px; }
  [data-baseweb="select"] > div { min-height: 44px; }
  .stTextInput button { min-width: 44px; min-height: 44px; }  /* e.g. show / hide a password */
  [class*="st-key-more_"] button, [class*="st-key-rail_"] .stButton button { min-height: 44px; min-width: 44px; }
  [data-baseweb="tag"] { min-height: 36px; }
  [data-baseweb="tag"] button, button[aria-label="Clear all"] { min-width: 44px; min-height: 44px; }
  [data-baseweb="tag"] [role="presentation"] { min-width: 44px; min-height: 44px; display: inline-flex; align-items: center;
    justify-content: center; margin: -4px -8px -4px 0; }
  /* Buttons fill the width so they are easy to hit one-handed; rows of buttons stack. */
  .block-container .stButton, .block-container .stDownloadButton, .block-container .stFormSubmitButton,
  .block-container [data-testid="stPopover"], section[role="dialog"] .stButton, section[role="dialog"] .stDownloadButton,
  section[role="dialog"] .stFormSubmitButton { width: 100% !important; }
  .block-container .stButton button, .block-container .stDownloadButton button, .block-container .stFormSubmitButton button,
  .block-container [data-testid="stPopover"] > div > button, section[role="dialog"] .stButton button,
  section[role="dialog"] .stDownloadButton button, section[role="dialog"] .stFormSubmitButton button { width: 100%; justify-content: center; }
  .block-container [data-testid="stElementContainer"]:has(> .stButton, > .stDownloadButton, > .stFormSubmitButton,
    > [data-testid="stPopover"]),
  section[role="dialog"] [data-testid="stElementContainer"]:has(> .stButton, > .stDownloadButton, > .stFormSubmitButton) {
    width: 100% !important; flex: 1 1 100% !important; }
  .block-container [data-testid="stElementContainer"]:has([data-testid="stPopover"]),
  .block-container [data-testid="stLayoutWrapper"]:has(> [data-testid="stPopover"]),
  .block-container [data-testid="stPopover"], .block-container [data-testid="stPopover"] > div,
  .block-container [data-testid="stPopover"] button { width: 100% !important; flex: 1 1 100% !important; }
  .block-container .stButton [data-testid="stTooltipIcon"], .block-container .stButton [data-testid="stTooltipHoverTarget"],
  section[role="dialog"] .stButton [data-testid="stTooltipIcon"], section[role="dialog"] .stButton [data-testid="stTooltipHoverTarget"] {
    width: 100%; }
  /* ...except the small controls that belong on one line. */
  .st-key-back_to_deals, .st-key-back_to_deals button, .st-key-clear_filter, .st-key-clear_filter button,
  [class*="st-key-more_"], [class*="st-key-more_"] [data-testid="stPopover"], [class*="st-key-more_"] button,
  .block-container [data-testid="stElementContainer"]:is(.st-key-back_to_deals, .st-key-clear_filter, [class*="st-key-more_"]) {
    width: auto !important; flex: none !important; }
  .block-container [data-testid="stElementContainer"]:is(.st-key-back_to_deals, .st-key-clear_filter, [class*="st-key-more_"]),
  .st-key-fab { width: auto !important; }
  .st-key-fab button { width: 56px !important; min-width: 56px; }
  .block-container .st-key-topbar [data-testid="stLayoutWrapper"], .block-container .st-key-topbar [data-testid="stPopover"],
  .block-container .st-key-topbar [data-testid="stPopover"] > div, .block-container .st-key-topbar [data-testid="stPopover"] button,
  .block-container [data-testid="stLayoutWrapper"][class*="st-key-more_"], .block-container [class*="st-key-more_"] [data-testid="stPopover"],
  .block-container [class*="st-key-more_"] [data-testid="stPopover"] > div,
  .block-container [class*="st-key-more_"] [data-testid="stPopover"] button { width: auto !important; flex: none !important; }
  /* Breadcrumb on one line; a long deal name is cut with an ellipsis. */
  .st-key-breadcrumb { flex-wrap: nowrap !important; }
  .st-key-breadcrumb [data-testid="stElementContainer"]:last-child { min-width: 0; }
  .crumb { min-width: 0; }
  .crumb .here { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* Headings, deal header (photo above the title) */
  h2 { font-size: 1.6rem !important; }
  .st-key-page_head h2 { font-size: 1.6rem !important; }
  .deal-title { font-size: 1.3rem; }
  .deal-top, .deal-id { flex-direction: column; align-items: flex-start; gap: 8px; }
  .deal-thumb { width: 100%; max-width: 240px; height: auto; aspect-ratio: 16 / 9; }
  .deal-pills { flex-wrap: wrap; }
  /* Stat cards: two by two. */
  .st-key-stat_row [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 12px !important; }
  .st-key-stat_row [data-testid="stColumn"] { flex: 1 1 calc(50% - 6px) !important; min-width: calc(50% - 6px) !important;
    width: calc(50% - 6px) !important; }
  .stat-value { font-size: 1.5rem; }
  .stat-value.text { font-size: 1rem; line-height: 1.4; }
  [class*="st-key-statcard_"] { padding: 12px 14px !important; }
  .pill { white-space: normal; }
  /* Cards and rows */
  .source { grid-template-columns: 56px minmax(0, 1fr); row-gap: 2px; }
  .source .when { grid-column: 2; }
  .source .figure { grid-column: 2; text-align: left; }
  .unchecked { margin-left: 0; }
  .om-bar { grid-template-columns: 1fr; }
  .home-greeting { font-size: 1.6rem; }
  .st-key-project_strip > div { flex-basis: 82vw !important; width: 82vw !important; scroll-snap-align: start; }
  .strip-arrows { display: none; }  /* swipe instead */
  [class*="st-key-feeditem_"] { padding: 12px 14px !important; }
  .feed-when { margin-left: 0; width: 100%; order: 10; }
  /* Dialogs (New deal, approval, the AI Teammate chat): full screen, the close button easy to reach,
     and the chat box kept at the bottom above the keyboard. */
  section[role="dialog"] { position: fixed !important; inset: 0 !important; width: 100vw !important; max-width: 100vw !important;
    height: 100dvh !important; max-height: 100dvh !important; margin: 0 !important; transform: none !important;
    border-radius: 0 !important; overflow-y: auto; padding-bottom: env(safe-area-inset-bottom);
    background: var(--surface) !important; z-index: 1002; }
  body:has(section[role="dialog"]) .st-key-topbar, body:has(section[role="dialog"]) .st-key-bottom_nav,
  body:has(section[role="dialog"]) .st-key-fab { display: none !important; }
  section[role="dialog"] button[aria-label="Close"] { width: 44px; height: 44px; }
  section[role="dialog"] button[aria-label="Close"] svg { width: 22px; height: 22px; }
  section[role="dialog"] [data-testid="stChatInput"] { position: sticky; bottom: 0; z-index: 2; background: var(--surface);
    padding: 8px 0 calc(8px + env(safe-area-inset-bottom)); }
  /* Tables scroll inside their card, never the page. */
  [data-testid="stDataFrame"], [data-testid="stTable"] { max-width: 100%; overflow-x: auto; }
}
</style>
"""

# Breakpoints, the one place they are set: phones up to PHONE_MAX px, tablets up to TABLET_MAX px, desktops above.
PHONE_MAX = 640
TABLET_MAX = 1024
CSS = CSS.replace("__PHONE__", str(PHONE_MAX)).replace("__TABLET__", str(TABLET_MAX))

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
