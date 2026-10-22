"""Open the real app in a headless browser, click through it, and save screenshots.

Run:  .venv/bin/python tools/screenshots.py            (uses the installed Google Chrome)
      .venv/bin/python tools/screenshots.py webkit     (Safari's engine, if Playwright has it installed)

It starts its own copy of the app on port 8765 with its own freshly seeded database and
uploads folder (inside screenshots/), so a running app and your real data are left alone.
It never sends anything to Gemini: no chat message, no rent roll, no recording. It fails
loudly if the app shows an error box or the Streamlit log contains a traceback.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "screenshots"
PORT = 8765
URL = f"http://localhost:{PORT}"
problems = []
FAKE_MICROPHONE = False  # set in main() for Chrome only


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}")
    if not ok:
        problems.append(name)


def start_app(log_path):
    """Seed a throwaway database, then start the app pointed at it."""
    work = OUT / "tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    env = dict(os.environ, CBRE_DB_PATH=str(work / "screenshots.db"), CBRE_UPLOAD_DIR=str(work / "uploads"))
    subprocess.run([sys.executable, "seed.py", "--reset"], cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    log = open(log_path, "w")
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "streamlit_app.py", "--server.headless", "true",
         "--server.port", str(PORT)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        try:
            if urllib.request.urlopen(f"{URL}/_stcore/health", timeout=1).read() == b"ok":
                return process
        except OSError:
            time.sleep(0.5)
    process.terminate()
    raise RuntimeError("The app did not start. See " + str(log_path))


def no_error_box(page, where):
    errors = page.locator('[data-testid="stException"]')
    text = errors.first.inner_text()[:200] if errors.count() else ""
    check(f"no error box {where}", errors.count() == 0, text)


def css(page, selector, prop):
    return page.evaluate(
        "([s, p]) => { const e = document.querySelector(s); return e ? getComputedStyle(e)[p] : null; }",
        [selector, prop])


def box(page, selector):
    return page.locator(selector).first.bounding_box()


def tall_shot(page, name, height=2300):
    """A screenshot of the whole page. The app scrolls inside itself, so the window is made tall first."""
    size = page.viewport_size
    page.set_viewport_size({"width": size["width"], "height": height})
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / f"{name}.png"))
    page.set_viewport_size(size)
    page.wait_for_timeout(400)


def add_sample_drafts():
    """Insert a made-up draft into the script's own database (never the real one)."""
    import sqlite3
    conn = sqlite3.connect(OUT / "tmp" / "screenshots.db")
    conn.execute("INSERT INTO drafts (deal_id, text) VALUES (1, ?)", (
        "Fallowmere Industrial Park has 12 units totalling 154,600 SF, with average rent of $8.84 per SF. "
        "On these figures the property is worth about $19,000,000 at a 6.5% cap rate.\n\n"
        "Flagged units (110) need confirmation before these figures are used.",))
    conn.commit()
    conn.close()


def add_simulated_research(nothing_found=False):
    """Run the real connections code on the script's own database, with every source simulated
    (tests/connection_fakes.py) and made-up keys. Nothing is sent anywhere."""
    sys.path.insert(0, str(ROOT))
    from unittest import mock
    from services import connections
    from services.connections import base
    from tests import connection_fakes, research_fakes
    db_path = OUT / "tmp" / "screenshots.db"
    with mock.patch.object(base, "load_dotenv"), mock.patch.dict(os.environ, connection_fakes.TEST_KEYS):
        if nothing_found:
            adapters = [connections.TavilyAdapter(search_fn=research_fakes.fake_search({}), client=research_fakes.fake_gemini())]
        else:
            connections.set_enabled("demo_costar", True, db_path)
            adapters = connection_fakes.adapters()
        deal = {"id": 1, "property_type": "Industrial", "submarket": "Alliance, Fort Worth, TX"}
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM research_findings")
        conn.commit()
        conn.close()
        connections.run_research(deal, db_path, adapters=adapters, force=True)


def add_simulated_recommendations():
    """Run the real recommendations code with a simulated Gemini reply on the script's own database."""
    import json
    import sqlite3
    from types import SimpleNamespace
    from services import connections, recommendations
    db_path = OUT / "tmp" / "screenshots.db"
    conn = sqlite3.connect(db_path)
    ids = {(c, t): i for i, c, t in conn.execute("SELECT id, connection_id, topic FROM research_findings WHERE simulated = 0")}
    conn.close()
    reply = {"recommendations": [
        {"title": "Check the labour supply for tenants who are hiring", "why": "Local unemployment was 4.4% (FRED, 2026-08-01).",
         "next_step": "Ask leasing teams whether tenants expect hiring trouble.", "finding_ids": [ids[("fred", "Employment and demand")]]},
        {"title": "Show both vacancy figures when pricing", "why": "Two reports put Q2 2026 vacancy at 6.2% and 7.5%.",
         "next_step": "Quote both reports side by side rather than one number.", "finding_ids": [ids[("web_search_tavily", "Vacancy")]]},
        {"title": "Raise rents", "why": "Rents will rise 9% next year.", "next_step": "Raise rents.", "finding_ids": [ids[("fred", "Employment and demand")]]}]}
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: SimpleNamespace(text=json.dumps(reply))))
    names = {a.id: a.name for a in connections.all_adapters()}
    kept, removed = recommendations.generate_ai(1, names, client=client, db_path=db_path)
    return kept, removed


def sign_in_again(page):
    page.get_by_text("Welcome back").wait_for()
    page.get_by_role("button", name="Continue with Google").click()
    page.get_by_text("Needs your attention").wait_for()
    page.wait_for_timeout(800)


def run(page, suffix):
    shot = lambda name: page.screenshot(path=str(OUT / f"{name}{suffix}.png"))
    width, height = page.viewport_size["width"], page.viewport_size["height"]

    page.goto(URL)
    page.get_by_text("Welcome back").wait_for()
    page.wait_for_timeout(1200)
    print("Login page")
    no_error_box(page, "on the login page")
    left, card = box(page, ".login-left"), box(page, ".st-key-login_card")
    check("left half is a dark green panel", css(page, ".login-left", "backgroundColor") == "rgb(19, 39, 30)"
          and left["x"] == 0 and abs(left["width"] - width / 2) < 2 and abs(left["height"] - height) < 2, left)
    check("card is on the right, at most 440px wide, with a shadow", card["x"] > width / 2 and card["width"] <= 441
          and css(page, ".st-key-login_card", "boxShadow") != "none", card)
    check("card is centred in the right half", abs((card["x"] + card["width"] / 2) - width * 0.75) < 24, card["x"])
    check("card fits on the screen", card["y"] >= 0 and card["y"] + card["height"] <= height, card)
    google = page.get_by_role("button", name="Continue with Google")
    check("both sign-in buttons work straight away", google.is_enabled()
          and page.get_by_role("button", name="Continue with Microsoft").is_enabled())
    check("sign-in buttons are full width", abs(google.bounding_box()["width"] - (card["width"] - 82)) < 6, google.bounding_box()["width"])
    card_text = page.locator(".st-key-login_card").inner_text()
    check("card says Welcome back, Broker sign-in and the demo note", all(part in card_text for part in
          ("Welcome back", "Sign in to review your deals.", "Demo login. No real sign-in happens yet."))
          and "broker sign-in" in card_text.lower())
    check("no role step", page.locator('[class*="st-key-rolecard_"]').count() == 0
          and not any(word in card_text for word in ("Step 1", "Step 2", "Choose a role", "Analyst", "Administrator")))
    shot("0_login")
    google.click()
    page.get_by_text("Needs your attention").wait_for()
    page.wait_for_timeout(1200)
    no_error_box(page, "on the dashboard")

    print("Top bar")
    bar = box(page, ".st-key-topbar")
    check("dark green background", css(page, ".st-key-topbar", "backgroundColor") == "rgb(19, 39, 30)",
          css(page, ".st-key-topbar", "backgroundColor"))
    check("spans the full width at the very top", bar["x"] == 0 and bar["y"] == 0 and abs(bar["width"] - width) < 2, bar)
    sign_out, badge, name = box(page, ".st-key-sign_out button"), box(page, ".role-badge"), box(page, ".user-name")
    check("the role badge says BROKER", page.locator(".role-badge").inner_text().strip() == "BROKER"
          and page.locator(".user-name").inner_text().strip() == "Avery Sample")
    page.screenshot(path=str(OUT / f"1b_top_bar{suffix}.png"), clip={"x": 0, "y": 0, "width": width, "height": 90})
    check("sign out is inside the bar", sign_out["y"] > 0 and sign_out["y"] + sign_out["height"] < bar["height"], sign_out)
    check("space between name and badge", badge["x"] - (name["x"] + name["width"]) >= 8)
    check("space between badge and sign out", sign_out["x"] - (badge["x"] + badge["width"]) >= 16)
    check("brand has a sparkle icon", "svg" in page.evaluate(
        "getComputedStyle(document.querySelector('.st-key-nav_home button'), '::before').backgroundImage"))
    check("brand font is Fraunces", "Fraunces" in css(page, ".st-key-nav_home button p", "fontFamily"))
    brand, all_deals = box(page, ".st-key-nav_home button"), box(page, ".st-key-nav_all_deals button")
    check("All deals link sits next to the brand, inside the bar", all_deals["x"] - (brand["x"] + brand["width"]) >= 16
          and all_deals["y"] > 0 and all_deals["y"] + all_deals["height"] < bar["height"], all_deals)
    title = page.get_by_role("heading", name="All deals").bounding_box()
    check("at least 32px between the top bar and the page title", title["y"] - bar["height"] >= 32, title["y"] - bar["height"])

    print("Floating AI button")
    fab = box(page, ".st-key-fab button")
    check("position is fixed", css(page, ".st-key-fab", "position") == "fixed")
    check("24px from the right and bottom", round(width - fab["x"] - fab["width"]) == 24
          and round(height - fab["y"] - fab["height"]) == 24, fab)
    check("round, 56px", fab["width"] == 56 and fab["height"] == 56 and css(page, ".st-key-fab button", "borderRadius") == "50%")
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(400)
    check("stays put when the page scrolls", box(page, ".st-key-fab button") == fab)
    page.mouse.wheel(0, -2000)
    page.locator(".st-key-fab button").hover()
    page.wait_for_timeout(400)
    label_opacity = page.evaluate("getComputedStyle(document.querySelector('.st-key-fab'), '::before').opacity")
    check("hover label appears", label_opacity == "1", label_opacity)
    shot("5_fab_hover")
    page.mouse.move(400, 400)

    print("Deal cards")
    for card in page.locator('[class*="st-key-deal_card_"]').all():
        card_box, pills = card.bounding_box(), card.locator(".pill").all()
        gap = min(card_box["y"] + card_box["height"] - (p.bounding_box()["y"] + p.bounding_box()["height"]) for p in pills)
        check("pills at least 16px above the card's bottom edge", gap >= 16, f"{gap:.0f}px")
    page.wait_for_timeout(300)
    shot("1_dashboard")

    print("Stat card filters")
    page.locator(".st-key-statcard_review").click(position={"x": 200, "y": 90})  # away from the label
    page.get_by_text("Showing: Needs Review (1)").wait_for()
    page.wait_for_timeout(400)  # let the colour transition finish before measuring it
    check("clicked card is marked selected", page.locator(".st-key-statcard_on_review").count() == 1)
    check("selected card has a green border", css(page, ".st-key-statcard_on_review", "borderLeftColor") == "rgb(29, 60, 47)")
    check("only matching deals are listed", page.locator('[class*="st-key-deal_card_"]').count() == 1)
    check("pointer cursor on cards", css(page, ".st-key-statcard_active", "cursor") == "pointer")
    page.mouse.move(400, 700)
    page.wait_for_timeout(400)
    shot("2_dashboard_filtered_needs_review")
    clear = page.get_by_role("button", name="Clear")
    check("small Clear button next to the Showing label", clear.count() == 1 and clear.bounding_box()["height"] <= 32
          and page.get_by_role("button", name="Show all deals").count() == 0)
    page.get_by_role("button", name="Active deals").click()
    page.get_by_text("Showing: Active deals (2)").wait_for()
    check("active deals filter lists 2", page.locator('[class*="st-key-deal_card_"]').count() == 2)
    page.get_by_role("button", name="Anomalies").click()
    page.get_by_text("Showing: Anomalies (1)").wait_for()
    page.get_by_role("button", name="Time saved").click()
    page.get_by_text("Time saved is not measured yet.").wait_for()
    check("time saved panel keeps every deal listed", page.locator('[class*="st-key-deal_card_"]').count() == 3)
    page.wait_for_timeout(400)
    shot("6_time_saved_panel")
    page.get_by_role("button", name="Review", exact=False).first.click()
    page.get_by_text("Showing: Needs Review (1)").wait_for()
    page.get_by_role("button", name="Clear").click()
    page.get_by_text("Needs your attention").wait_for()
    check("Clear resets the list", page.locator('[class*="st-key-deal_card_"]').count() == 3)
    page.get_by_role("button", name="Anomalies").click()
    page.get_by_text("Showing: Anomalies (1)").wait_for()
    page.locator(".st-key-nav_all_deals button").click()
    page.get_by_text("Needs your attention").wait_for()
    check("All deals in the top bar clears the filter", page.locator('[class*="st-key-deal_card_"]').count() == 3)
    no_error_box(page, "after using the filters")

    print("New deal")
    new_button = box(page, ".st-key-new_deal button")
    title = page.get_by_role("heading", name="All deals").bounding_box()
    check("+ New deal is dark green with white text", css(page, ".st-key-new_deal button", "backgroundColor") == "rgb(29, 60, 47)"
          and css(page, ".st-key-new_deal button p", "color") == "rgb(255, 255, 255)", css(page, ".st-key-new_deal button", "backgroundColor"))
    check("+ New deal is at the top right, level with the title", new_button["x"] > width * 0.75
          and abs((new_button["y"] + new_button["height"] / 2) - (title["y"] + title["height"] / 2)) < 12, new_button)
    check("+ New deal has a plus icon", "add" in page.locator(".st-key-new_deal button").inner_text())
    page.locator(".st-key-new_deal button").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_text("How do you want to start?").wait_for()
    page.wait_for_timeout(800)
    no_error_box(page, "with the New deal dialog open")
    check("upload form has name, type, location and a file box", dialog.get_by_label("Deal name").count() == 1
          and dialog.get_by_text("Property type").count() == 1 and dialog.get_by_label("Location").count() == 1
          and dialog.locator('[data-testid="stFileUploader"]').count() == 1)
    shot("7_new_deal_upload")
    dialog.get_by_text("Describe it to the AI", exact=True).click()
    dialog.get_by_text("What do you know about the deal?").wait_for()
    page.wait_for_timeout(800)
    no_error_box(page, "on the describe tab of New deal")
    check("describe form has a text box and a Draft with AI button", dialog.locator("textarea").count() >= 1
          and dialog.get_by_role("button", name="Draft with AI").count() == 1)
    dialog.locator("textarea").first.fill("Oakmere Depot is a 40,000 sf warehouse in Fort Worth with three tenants.")
    page.wait_for_timeout(300)
    check("describe box has the record control", dialog.get_by_text("Record or upload audio").count() == 1)
    shot("8_new_deal_describe")
    dialog.get_by_text("Record or upload audio").click()
    dialog.get_by_text("Audio is sent to Gemini for transcription and is not saved.").wait_for()
    page.wait_for_timeout(600)
    shot("8b_new_deal_describe_recorder_open")
    # A real upload through the browser, using only a T-12 so that nothing is sent to Gemini.
    dialog.get_by_text("Upload files", exact=True).click()
    dialog.get_by_label("Deal name").wait_for()
    dialog.get_by_label("Deal name").fill("Screenshot Test Depot (made up)")
    dialog.get_by_label("Location").fill("Testville")
    dialog.locator('input[type="file"]').set_input_files(str(ROOT / "sample_data" / "t12.xlsx"))
    dialog.get_by_text("t12.xlsx").first.wait_for()
    dialog.get_by_role("button", name="Create deal and read files").click()
    page.get_by_text("Created 'Screenshot Test Depot (made up)'.").wait_for()
    page.wait_for_timeout(1000)
    no_error_box(page, "after creating a deal from an upload")
    check("dialog closes after creating", page.get_by_role("dialog").count() == 0)
    check("the new deal is on the dashboard straight away",
          page.get_by_role("button", name="Screenshot Test Depot (made up)").count() == 1)
    check("result message says the T-12 was saved but not read", page.get_by_text("t12.xlsx: Saved, not read").count() == 1)
    shot("9_dashboard_after_new_deal")
    page.locator(".st-key-nav_all_deals button").click()
    page.wait_for_timeout(800)

    print("AI dialog")
    page.locator(".st-key-fab button").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_text("Ask about", exact=True).wait_for()
    page.wait_for_timeout(1000)
    no_error_box(page, "with the AI dialog open on All deals")
    check("assistant chat has the record control", dialog.get_by_text("Record or upload audio").count() == 1)
    picker = dialog.locator('[data-testid="stSelectbox"]')
    check("dialog has the deal picker on All deals", "All deals" in picker.inner_text() or picker.locator("input").input_value() == "All deals",
          picker.inner_text())
    check("dialog has a chat box", dialog.locator("textarea").count() == 1)
    check("web search switch is disabled", dialog.locator("input[type=checkbox]").first.is_disabled())
    shot("3_ai_dialog")
    picker.locator("input").click()
    page.get_by_role("option").nth(4).wait_for()  # the list fills in a moment after it opens
    shot("3a_ai_dialog_picker_open")
    options = page.get_by_role("option").all_inner_texts()
    check("picker lists All deals plus each deal", len(options) == 5 and options[0] == "All deals", options)
    page.get_by_role("option", name="Fallowmere", exact=False).click()
    dialog.get_by_text("this deal's saved data", exact=False).wait_for()
    page.wait_for_timeout(800)
    no_error_box(page, "with the AI dialog on a single deal")
    shot("3b_ai_dialog_one_deal")
    page.keyboard.press("Escape")
    page.wait_for_timeout(1200)
    check("dialog closes", page.get_by_role("dialog").count() == 0)

    print("Deal page and tabs")
    card = page.locator('[class*="st-key-deal_card_"]').first
    card_box = card.bounding_box()
    card.click(position={"x": card_box["width"] - 30, "y": card_box["height"] - 14})  # far corner, not the name
    page.get_by_text("Extracted fields").wait_for()
    page.wait_for_timeout(1000)
    no_error_box(page, "on the deal page")
    tabs = page.get_by_role("tab")
    heights = [round(tab.bounding_box()["height"]) for tab in tabs.all()]
    check("five tabs, each at least 44px tall", len(heights) == 5 and min(heights) >= 44, heights)
    check("tab text is 16px", css(page, '.stTabs [role="tab"] p', "fontSize") == "16px")
    ai = '.stTabs [role="tab"]:last-of-type'
    check("Ask AI is gold", css(page, ai, "backgroundColor") == "rgb(201, 162, 39)", css(page, ai, "backgroundColor"))
    check("Ask AI is an oval pill", float(css(page, ai, "borderTopLeftRadius").replace("px", "")) >= 22, css(page, ai, "borderTopLeftRadius"))
    check("Ask AI text is dark green", css(page, ai, "color") == "rgb(19, 39, 30)", css(page, ai, "color"))
    check("Ask AI has a shadow", css(page, ai, "boxShadow") != "none")
    check("Ask AI has a sparkle icon", "auto_awesome" in tabs.last.inner_text(), tabs.last.inner_text())
    check("active tab has a green underline", "inset" in css(page, '.stTabs [role="tab"][aria-selected="true"]', "boxShadow"))
    check("top bar and AI button are on the deal page too",
          css(page, ".st-key-topbar", "position") == "fixed" and css(page, ".st-key-fab", "position") == "fixed")
    crumb = box(page, ".st-key-breadcrumb")
    check("breadcrumb reads All deals > deal name", "Fallowmere" in page.locator(".crumb .here").inner_text()
          and page.locator(".st-key-back_to_deals button").inner_text().strip() == "All deals")
    check("at least 32px between the top bar and the breadcrumb", crumb["y"] - 67 >= 32, crumb["y"] - 67)
    shot("4_deal_tabs")

    print("Review tab")
    header = box(page, ".st-key-deal_header")
    check("header card has the name, source chip, facts line and status", page.locator(".deal-title").count() == 1
          and "from rent_roll.xlsx" in page.locator(".chip").first.inner_text()
          and "12 units · 154,600 SF · Extracted" in page.locator(".deal-top .deal-meta").inner_text()
          and page.locator(".deal-top .pill").count() == 1)
    check("Documents tab shows a count", "2" in tabs.nth(1).inner_text(), tabs.nth(1).inner_text())
    fields, snapshot = box(page, ".st-key-card_fields"), box(page, ".st-key-card_snapshot")
    check("two columns: wide left, narrow right", snapshot["x"] > fields["x"] + fields["width"]
          and fields["width"] > snapshot["width"] * 1.6, (fields["width"], snapshot["width"]))
    for key in ("fields", "narrative", "research", "snapshot", "takeaways", "sources"):
        check(f"card present: {key}", page.locator(f".st-key-card_{key}").count() == 1)
    check("12 of 12 units read", "12 of 12 units read" in page.locator(".st-key-card_fields").inner_text())
    snapshot_text = page.locator(".st-key-card_snapshot").inner_text()
    check("snapshot has no occupancy or cap rate row", "Occupancy\n" not in snapshot_text and "Cap rate\n" not in snapshot_text)
    check("no Deploy button", page.get_by_role("button", name="Deploy").count() == 0)
    tall_shot(page, f"12_review{suffix}")

    print("Resolve flags")
    card = page.locator('[class*="st-key-flagcard_open_"]').first
    check("a decision card for the open flag, with the rule and the exact numbers",
          "Unit 110" in card.inner_text() and "20.33" in card.inner_text() and "17.19" in card.inner_text()
          and card.get_by_role("button", name="This is wrong - fix it").count() == 1
          and card.get_by_role("button", name="This is correct - confirm it").count() == 1)
    card.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    shot("17_flag_card")
    card.get_by_role("button", name="This is correct - confirm it").click()
    card.get_by_text("Why is it correct?").wait_for()
    card.get_by_text("Confirmed with property manager", exact=True).click()
    card.locator("textarea").fill("Called the property manager; the lab space carries a fit-out premium.")
    card.locator("textarea").press("Tab")
    page.wait_for_timeout(1000)
    confirm_button = card.locator('[class*="st-key-confirm_"][class*="_go"] button')
    check("the confirm panel has reason chips, a note and a Confirm button that unlocks", confirm_button.is_enabled())
    card.scroll_into_view_if_needed()
    shot("18_confirm_panel")
    card.get_by_role("button", name="Cancel").click()
    page.wait_for_timeout(800)
    card = page.locator('[class*="st-key-flagcard_open_"]').first
    card.get_by_role("button", name="This is wrong - fix it").click()
    card.get_by_label("Monthly rent").wait_for()
    card.get_by_label("Monthly rent").fill("2400")
    card.get_by_label("Monthly rent").press("Tab")
    card.get_by_text("Before and after").wait_for()
    page.wait_for_timeout(600)
    preview = card.locator("table.preview").inner_text()
    check("the fix preview lists the change and every recomputed field", "Recomputed: annual rent = monthly rent x 12" in preview
          and "Recomputed: rent/SF = annual rent / SF" in preview)
    card.scroll_into_view_if_needed()
    tall_shot(page, f"19_fix_panel_preview{suffix}", height=2000)
    card.get_by_role("button", name="Cancel").click()
    page.wait_for_timeout(800)

    print("Edit a cell")
    table = page.locator(".st-key-card_fields [data-testid='stDataFrame']")
    table.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    tbox = table.bounding_box()
    # Click the Tenant cell of the first row (columns: Unit, Flag, Tenant ...); the grid is a canvas.
    tbox = table.bounding_box()  # measured again after scrolling
    page.mouse.move(tbox["x"] + 230, tbox["y"] + 54)
    page.wait_for_timeout(300)
    page.mouse.down()
    page.wait_for_timeout(120)
    page.mouse.up()
    page.wait_for_timeout(2500)
    page.get_by_text("Unit 101 · Tenant").wait_for()
    field = page.locator(".st-key-card_fields").get_by_label("Tenant")
    field.fill("Northfield Pallet Company")
    page.locator(".st-key-card_fields").get_by_label("Why are you changing it? (required)").fill("Tenant name per the signed lease.")
    page.locator(".st-key-card_fields").get_by_label("Why are you changing it? (required)").press("Tab")
    page.wait_for_timeout(600)
    page.locator(".st-key-card_fields").get_by_role("button", name="Save changes").click()
    page.get_by_text("Saved.").first.wait_for()
    page.wait_for_timeout(1000)
    check("a saved cell edit shows in the timeline with who, why and Manual", "Tenant name per the signed lease." in
          page.locator(".st-key-card_timeline").inner_text() and "Manual" in page.locator(".st-key-card_timeline").inner_text())
    check("the edited cell is counted under the table", "1 value changed by a person" in page.locator(".st-key-card_fields").inner_text())
    no_error_box(page, "after editing a cell")
    page.locator(".st-key-card_timeline").scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    shot("20_timeline")
    check("Generate draft button is offered and nothing has been drafted", page.get_by_role("button", name="Generate draft").count() == 1
          and page.locator(".ai-label").count() == 0)
    # Show what a draft looks like without calling Gemini: put two made-up drafts straight into the
    # throwaway database, exactly as the drafting service would save them.
    add_sample_drafts()
    page.reload()
    sign_in_again(page)
    page.locator('[class*="st-key-deal_card_"]').first.click()
    page.locator(".ai-label").wait_for()
    page.wait_for_timeout(1000)
    narrative = page.locator(".st-key-card_narrative")
    check("draft is labelled as AI-drafted and not sent", "AI-drafted - edit anything before it goes out" in narrative.inner_text()
          and "Generated, not sent" in narrative.inner_text())
    check("a draft with a figure that is not in the data shows a warning and locks Approve",
          "figures that are not in the deal data: 6.5, 19,000,000" in narrative.inner_text()
          and narrative.get_by_role("button", name="Approve").is_disabled())
    narrative.scroll_into_view_if_needed()
    tall_shot(page, f"13_review_draft_warning{suffix}")
    narrative.get_by_role("button", name="Edit").click()
    narrative.get_by_role("button", name="Save edits").wait_for()
    narrative.locator("textarea").fill("The rent roll shows 12 units totalling 154,600 SF, with average rent of $8.84 per SF. "
                                       "Unit 110 is flagged and needs confirmation before these figures are used.")
    narrative.get_by_role("button", name="Save edits").click()
    narrative.get_by_text("Checked: every number in this draft").wait_for()
    check("after a person edits it, the check passes and Approve unlocks",
          narrative.get_by_role("button", name="Approve").is_enabled() and "then edited by a person" in narrative.inner_text())
    tall_shot(page, f"13b_review_draft_edited{suffix}")
    narrative.get_by_role("button", name="Approve").click()
    narrative.get_by_text("Approved", exact=True).first.wait_for()
    check("a person can approve it", narrative.get_by_role("button", name="Approve").is_disabled())
    no_error_box(page, "after editing and approving a draft")

    print("Market research")
    research_card = page.locator(".st-key-card_research")
    check("research has not run and says what it is about", "Not run yet" in research_card.inner_text()
          and "not about this property" in research_card.inner_text()
          and research_card.get_by_role("button", name="Run research").count() == 1)
    # Findings are produced by the real research service, but fed simulated search results and a
    # simulated Gemini reply (tests/research_fakes.py). No search and no AI request is made.
    add_simulated_research()
    page.reload()
    sign_in_again(page)
    page.locator('[class*="st-key-deal_card_"]').first.click()
    page.locator(".finding-topic").first.wait_for()
    page.wait_for_timeout(1000)
    research_card = page.locator(".st-key-card_research")
    text = research_card.inner_text()
    check("five topics", research_card.locator(".finding-topic").count() == 5)
    check("tier labels, source names, dates and figures are shown", all(part in text for part in
          ("Tier 1", "Tier 2", "Tier 3", "bls.gov", "cbre.com", "2026-09-20", "4.1%", "no figure stated", "FRED, St. Louis Fed")))
    check("sources that disagree are tagged red and every figure is shown", "Sources disagree" in text
          and "6.2%" in text and "7.5%" in text and "7.0%" in text
          and css(page, ".finding-topic .pill.flag", "backgroundColor") == "rgb(251, 225, 223)")
    check("simulated findings carry a SIMULATED chip and cannot be accepted",
          research_card.locator(".chip.simulated").count() == 2
          and all(card.get_by_role("button", name="Accept").is_disabled()
                  for card in research_card.locator('[class*="st-key-finding_simulated_"]').all()))
    check("skipped sources are counted", "1 source skipped" in text)
    page.locator(".finding-topic").first.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    shot("14b_research_sources_disagree")
    research_card.get_by_role("button", name="Accept").last.click()
    research_card.locator('[class*="st-key-finding_accepted_"]').wait_for()
    # Dismiss a finding the recommendations below do not rely on (the last one, a Census figure).
    research_card.locator('[class*="st-key-finding_new_"]').last.get_by_role("button", name="Dismiss").click()
    research_card.locator('[class*="st-key-finding_dismissed_"]').wait_for()
    page.wait_for_timeout(600)
    check("a person can accept one and dismiss another", "Accepted" in research_card.inner_text()
          and "Dismissed" in research_card.inner_text())
    no_error_box(page, "with research findings showing")
    tall_shot(page, f"14_review_research{suffix}", height=4200)
    print("Recommendations tab")
    add_simulated_recommendations()
    page.reload()
    sign_in_again(page)
    page.locator('[class*="st-key-deal_card_"]').first.click()
    page.get_by_role("tab").nth(3).wait_for()
    page.get_by_role("tab").nth(3).click()
    page.get_by_text("AI suggestions. A person decides.").wait_for()
    page.wait_for_timeout(1200)
    no_error_box(page, "on the Recommendations tab")
    tabs = page.get_by_role("tab")
    labels = [t.inner_text() for t in tabs.all()]
    check("tabs are Review, Documents, Data, Recommendations, Ask AI",
          len(labels) == 5 and all(word in label for word, label in zip(("Review", "Documents", "Data", "Recommendations", "Ask AI"), labels))
          and css(page, '.stTabs [role="tab"]:last-of-type', "backgroundColor") == "rgb(201, 162, 39)")
    panel = page.get_by_role("tabpanel")
    rule_cards, ai_cards = panel.locator('[class*="st-key-rec_rule_"]'), panel.locator('[class*="st-key-rec_ai_"]')
    check("both kinds of card are shown and labelled", rule_cards.count() >= 3 and ai_cards.count() == 2
          and "from the deal's data" in rule_cards.first.inner_text().lower()
          and "from market research" in ai_cards.first.inner_text().lower())
    check("rule cards show the rule and exact numbers", "Rule: Validation rule rent_per_sf_above_2x_average" in panel.inner_text()
          and "44,700 SF, 28.9% of total SF" in panel.inner_text())
    check("evidence chips show source, tier, date and connection",
          "FRED, St. Louis Fed · Tier 1 · 2026-08-01 · FRED (St. Louis Fed)" in panel.inner_text())
    check("a Sources disagree tag on the evidence", ai_cards.locator(".pill.flag", has_text="Sources disagree").count() == 1)
    # "N suggestions removed" appears right after a click on Generate; that path is covered by tests/test_app.py,
    # because clicking it here would call the real Gemini.
    check("the unverifiable suggestion was not saved", "Rents will rise 9%" not in panel.inner_text())
    check("SIMULATED chips mark the findings that were not used", panel.locator(".chip.simulated").count() == 2
          and "Not used: simulated findings" in panel.inner_text())
    check("each card has Accept, Dismiss and Add to deal notes", all(
          card.get_by_role("button", name=name).count() == 1 for card in rule_cards.all() + ai_cards.all()
          for name in ("Accept", "Dismiss", "Add to deal notes")))
    shot("16_recommendations_top")
    tall_shot(page, f"16_recommendations{suffix}", height=3300)
    rule_cards.first.get_by_role("button", name="Accept").click()
    panel.locator('[class*="st-key-rec_rule_accepted_"]').wait_for()
    tabs.first.click()
    page.get_by_text("Accepted recommendations").wait_for()
    check("an accepted recommendation shows on the Review tab", page.locator(".st-key-card_accepted_recs").count() == 1)
    add_simulated_research(nothing_found=True)
    page.reload()
    sign_in_again(page)
    page.locator('[class*="st-key-deal_card_"]').first.click()
    page.locator(".finding-topic").first.wait_for()
    research_card = page.locator(".st-key-card_research")
    check("when nothing is found it says so and offers nothing to accept",
          research_card.inner_text().count("No reliable public sources found.") == 4
          and research_card.get_by_role("button", name="Accept").count() == 0)
    research_card.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    shot("14c_research_nothing_found")
    page.mouse.wheel(0, -6000)
    page.wait_for_timeout(300)
    tabs = page.get_by_role("tab")
    page.locator(".st-key-go_documents button").click()
    page.get_by_text("Documents: coming in a later step.").wait_for()
    check("link jumps to the Documents tab", tabs.nth(1).get_attribute("aria-selected") == "true")
    tabs.first.click()
    page.get_by_text("Deal snapshot").wait_for()
    tabs.last.click()
    page.get_by_text("Web search: coming in a later step.").first.wait_for()
    page.mouse.move(400, 800)
    page.wait_for_timeout(600)
    no_error_box(page, "on the Ask AI tab")
    shot("4b_deal_tabs_ask_ai_active")

    print("Record button in the deal chat")
    panel = page.get_by_role("tabpanel")
    recorder = panel.locator(".st-key-chat_1_voice")
    check("record control with a microphone icon is under the chat box",
          recorder.count() == 1 and "mic" in recorder.inner_text() and "Record or upload audio" in recorder.inner_text())
    recorder.locator("summary").click()
    panel.get_by_text("Audio is sent to Gemini for transcription and is not saved.").wait_for()
    page.wait_for_timeout(800)
    check("privacy notice is shown next to it", True)
    check("has a microphone recorder and an audio upload box", panel.locator('[data-testid="stAudioInput"]').count() == 1
          and panel.locator('[data-testid="stFileUploader"]').count() == 1)
    transcribe_button = panel.get_by_role("button", name="Transcribe")
    check("Transcribe is disabled until there is audio", transcribe_button.is_disabled())
    no_error_box(page, "with the recorder open")
    shot("10_chat_record_button")
    if FAKE_MICROPHONE:
        # Chrome's built-in fake microphone (a test tone). This shows the recorder works in Chrome.
        # It is not your real microphone and not Safari. Transcribe is never pressed, so nothing is sent.
        try:
            audio_box = panel.locator('[data-testid="stAudioInput"]')
            print("  info recorder buttons:", [b.get_attribute("aria-label") or b.inner_text() for b in audio_box.locator("button").all()])
            audio_box.get_by_role("button", name="Record").click()
            page.wait_for_timeout(3000)
            print("  info while recording:", [b.get_attribute("aria-label") or b.inner_text() for b in audio_box.locator("button").all()],
                  audio_box.inner_text().replace("\n", " ")[-20:])
            audio_box.get_by_role("button", name="Stop recording").click()
            page.wait_for_timeout(3000)
            check("fake microphone: a recording unlocks Transcribe", transcribe_button.is_enabled())
            shot("10b_chat_after_fake_recording")
        except Exception as exc:
            check("fake microphone: a recording unlocks Transcribe", False, str(exc)[:120])
    else:
        print("  skip microphone recording is not tried in this browser engine")

    print("Notes on the Review tab")
    tabs.first.click()
    panel = page.get_by_role("tabpanel")
    panel.get_by_role("heading", name="Notes").scroll_into_view_if_needed()
    panel.get_by_label("Add a note").fill("Seller prefers a quick close.\nCall back Friday.")
    panel.get_by_role("button", name="Save note").click()
    page.locator(".note-text").first.wait_for()
    page.wait_for_timeout(600)
    check("a typed note is shown as written, with its source", "Seller prefers a quick close." in page.locator(".note-text").first.inner_text()
          and "Typed" in page.locator(".note-meta").first.inner_text())
    no_error_box(page, "after saving a note")
    page.locator(".note-text").first.scroll_into_view_if_needed()
    shot("11_deal_notes")
    page.mouse.wheel(0, -5000)

    print("Connections page")
    page.locator(".st-key-nav_connections button").click()
    page.get_by_role("heading", name="Connections").wait_for()
    page.wait_for_timeout(1200)
    no_error_box(page, "on the Connections page")
    cards = page.locator('[class*="st-key-conn_card_"]')
    check("a card for each of the 11 sources", cards.count() == 11)
    check("the How sources are used note is there", "No website is ever scraped" in page.locator(".st-key-card_how_sources").inner_text())
    check("the Broker can use every switch",
          not any(t.is_disabled() for t in page.locator('[class*="st-key-switch_"] input').all()))
    texts = page.locator('[class*="st-key-conn_card_"]').all_inner_texts()
    check("no key appears anywhere on the page", not any("AIza" in t or "tvly-" in t for t in texts))
    page.locator(".st-key-connect_demo_zillow button").click()
    page.get_by_text("Zillow cannot be connected").wait_for()
    tall_shot(page, f"15_connections{suffix}", height=2600)

    print("Going home")
    page.locator(".st-key-nav_home button").click()
    page.get_by_text("Needs your attention").wait_for()
    check("the logo goes to the dashboard", page.get_by_role("heading", name="All deals").count() == 1)
    page.locator('[class*="st-key-deal_card_"]').first.click()
    page.get_by_text("Extracted fields").wait_for()
    page.locator(".st-key-back_to_deals button").click()
    page.get_by_text("Needs your attention").wait_for()
    check("the breadcrumb link goes to the dashboard", page.get_by_role("heading", name="All deals").count() == 1)


def main():
    global FAKE_MICROPHONE
    engine = sys.argv[1] if len(sys.argv) > 1 else "chrome"
    FAKE_MICROPHONE = engine == "chrome"
    OUT.mkdir(exist_ok=True)
    log_path = OUT / "streamlit.log"
    app = start_app(log_path)
    try:
        with sync_playwright() as p:
            if engine == "webkit":
                browser = p.webkit.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
            else:
                browser = p.chromium.launch(channel="chrome", args=[
                    "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
                context = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["microphone"])
                page = context.new_page()
            page.set_default_timeout(15000)
            run(page, "" if engine == "chrome" else f"_{engine}")
            browser.close()
    finally:
        app.terminate()
        app.wait(timeout=10)
    log = log_path.read_text()
    print("Streamlit log")
    check("no traceback in the Streamlit output", "Traceback" not in log and "Error" not in log,
          [line for line in log.splitlines() if "Error" in line][:3])
    print(f"\n{'ALL CHECKS PASSED' if not problems else 'PROBLEMS: ' + ', '.join(problems)}. Screenshots are in {OUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
