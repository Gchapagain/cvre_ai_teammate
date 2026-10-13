"""Open the real app in a headless browser, click through it, and save screenshots.

Run:  .venv/bin/python tools/screenshots.py            (uses the installed Google Chrome)
      .venv/bin/python tools/screenshots.py webkit     (Safari's engine, if Playwright has it installed)

It starts its own copy of the app on port 8765, so a running app is left alone.
It never sends a chat message, so Gemini is never called. It fails loudly if the app
shows an error box or the Streamlit log contains a traceback.
"""

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


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}")
    if not ok:
        problems.append(name)


def start_app(log_path):
    log = open(log_path, "w")
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "streamlit_app.py", "--server.headless", "true",
         "--server.port", str(PORT)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
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
    check("sign-in buttons are disabled before a role is chosen", google.is_disabled()
          and page.get_by_role("button", name="Continue with Microsoft").is_disabled())
    check("sign-in buttons are full width", abs(google.bounding_box()["width"] - (card["width"] - 82)) < 6, google.bounding_box()["width"])
    check("helper text asks for a role", page.get_by_text("Choose a role to continue").count() == 1)
    check("three role cards", page.locator('[class*="st-key-rolecard_"]').count() == 3)
    shot("0_login")
    agent = page.locator(".st-key-rolecard_agent")
    agent.click(position={"x": 300, "y": 40})  # the card body, not the name
    page.locator(".st-key-rolecard_on_agent").wait_for()
    page.mouse.move(700, 850)
    page.wait_for_timeout(500)
    check("chosen card has a green border and a check mark",
          css(page, ".st-key-rolecard_on_agent", "borderTopColor") == "rgb(29, 60, 47)" and page.locator(".role .tick").count() == 1)
    check("sign-in buttons unlock", google.is_enabled())
    shot("0b_login_role_selected")
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

    print("AI dialog")
    page.locator(".st-key-fab button").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_text("Ask about", exact=True).wait_for()
    page.wait_for_timeout(1000)
    no_error_box(page, "with the AI dialog open on All deals")
    picker = dialog.locator('[data-testid="stSelectbox"]')
    check("dialog has the deal picker on All deals", "All deals" in picker.inner_text() or picker.locator("input").input_value() == "All deals",
          picker.inner_text())
    check("dialog has a chat box", dialog.locator("textarea").count() == 1)
    check("web search switch is disabled", dialog.locator("input[type=checkbox]").first.is_disabled())
    shot("3_ai_dialog")
    picker.locator("input").click()
    page.get_by_role("option").nth(3).wait_for()  # the list fills in a moment after it opens
    shot("3a_ai_dialog_picker_open")
    options = page.get_by_role("option").all_inner_texts()
    check("picker lists All deals plus each deal", len(options) == 4 and options[0] == "All deals", options)
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
    check("four tabs, each at least 44px tall", len(heights) == 4 and min(heights) >= 44, heights)
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
    tabs.last.click()
    page.get_by_text("Web search: coming in a later step.").first.wait_for()
    page.mouse.move(400, 800)
    page.wait_for_timeout(600)
    no_error_box(page, "on the Ask AI tab")
    shot("4b_deal_tabs_ask_ai_active")

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
    engine = sys.argv[1] if len(sys.argv) > 1 else "chrome"
    OUT.mkdir(exist_ok=True)
    log_path = OUT / "streamlit.log"
    app = start_app(log_path)
    try:
        with sync_playwright() as p:
            browser = p.webkit.launch() if engine == "webkit" else p.chromium.launch(channel="chrome")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
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
