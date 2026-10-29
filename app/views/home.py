"""Home: the first page after sign-in. A greeting, a scrolling strip of the broker's projects with their
progress, and (from Stage 2) the notification feed. Everything shown comes from the database; nothing is assumed.
"""

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

from app import images, nav, queries, style
from app.views import feed_view
from services import feed, progress

COLOUR_NAMES = {"red": "Just started", "orange": "Under way", "yellow": "Nearly done", "green": "Complete"}

# The ‹ › buttons scroll the strip by one card. Listening on the document once means the buttons keep
# working after Streamlit redraws the page.
STRIP_SCRIPT = """
<script>
if (!window.cbreStripArrows) {
  window.cbreStripArrows = true;
  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-strip-scroll]");
    const strip = document.querySelector(".st-key-project_strip");
    if (!button || !strip) return;
    const card = strip.querySelector("[class*='st-key-proj_card_']");
    const step = card ? card.getBoundingClientRect().width + 16 : 300;
    strip.scrollBy({left: step * Number(button.dataset.stripScroll), behavior: "smooth"});
  });
  // Grey out an arrow when there is nothing more to scroll that way (or the cards all fit).
  setInterval(function () {
    const strip = document.querySelector(".st-key-project_strip");
    if (!strip) return;
    const end = strip.scrollWidth - strip.clientWidth - 2;
    document.querySelectorAll("[data-strip-scroll]").forEach(function (arrow) {
      arrow.disabled = Number(arrow.dataset.stripScroll) < 0 ? strip.scrollLeft <= 2 : strip.scrollLeft >= end;
    });
  }, 400);
}
</script>
"""


def local_now():
    """The time where the person is (their browser's timezone), or the server's time if that is unknown."""
    try:
        return datetime.now(ZoneInfo(st.context.timezone))
    except Exception:
        return datetime.now()


def greeting(user, now):
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    first = (user.get("full_name") or "").split(" ")[0]
    return f"Good {part}, {first}" if first else f"Good {part}"


def needs_you_count(now):
    """How many things need the person today: open flags and meetings in the next 24 hours (the feed's
    "Needs you now" group)."""
    return feed.needs_you(feed.build(queries.feed_rows(), now))


def unread_count():
    """For the bell in the top bar: feed items the person has not read."""
    return feed.unread(feed.build(queries.feed_rows(), local_now()))


def summary_line(count):
    if count == 0:
        return "Nothing needs you right now."
    return f"{count} thing{'s' if count != 1 else ''} need{'s' if count == 1 else ''} you today."


def facts_for(project):
    return progress.Facts(documents=project["documents"], units=project["units"], open_flags=project["open_flags"],
                          drafts=project["drafts"], findings_new=project["findings_new"],
                          findings_reviewed=project["findings_reviewed"], approved=project["status"] == "Approved")


def progress_html(result):
    return (f'<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" '
            f'aria-valuenow="{result.percent}" aria-label="{result.count} of {result.total} steps done">'
            f'<div class="progress-track"><span class="progress-fill {result.colour}" style="width:{result.percent}%"></span></div>'
            f'<div class="progress-text"><b>{result.percent}%</b><span>{result.count} of {result.total} steps</span></div>'
            f'<div class="progress-next">{escape(result.next_step)}</div></div>')


def _project_card(project):
    result = progress.calculate(facts_for(project))
    picture, is_photo = images.picture(project)
    label = "" if is_photo else '<span class="pic-label">Illustration</span>'
    with st.container(key=f"proj_card_{result.colour}_{project['id']}"):
        style.html(f'<div class="proj-pic"><img src="{picture}" alt="">{label}</div>')
        # The name is the button. CSS in app/style.py stretches its click area over the whole card.
        st.button(project["name"], key=f"open_project_{project['id']}", type="tertiary",
                  on_click=nav.open_deal, args=(project["id"],))
        meta = " · ".join(part for part in (project["property_type"], project["submarket"]) if part)
        style.html(f'<div class="proj-meta">{escape(meta)}</div>{style.pill(project["status"])}{progress_html(result)}')


def legend_html():
    red_below, orange_below = progress.thresholds()
    ranges = {"red": f"under {red_below}%", "orange": f"{red_below}-{orange_below - 1}%",
              "yellow": f"{orange_below}-99%", "green": "100%"}
    items = "".join(f'<span class="legend-item"><span class="dot {colour}"></span>{COLOUR_NAMES[colour]} '
                    f'<span class="legend-range">{ranges[colour]}</span></span>' for colour in progress.COLOURS)
    return f'<div class="progress-legend">{items}</div>'


def _project_strip():
    projects = queries.projects()
    with st.container(key="strip_head", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.markdown('<div class="home-section">Your projects</div>', unsafe_allow_html=True, width="content")
        st.html('<div class="strip-arrows">'
                '<button type="button" class="strip-arrow" data-strip-scroll="-1" aria-label="Scroll projects left">‹</button>'
                '<button type="button" class="strip-arrow" data-strip-scroll="1" aria-label="Scroll projects right">›</button>'
                '</div>' + STRIP_SCRIPT, width="content", unsafe_allow_javascript=True)
    if not projects:
        st.info("No deals yet. Use + New deal on All deals to start one.")
        return
    with st.container(key="project_strip", horizontal=True):
        for project in projects:
            _project_card(project)
    style.html(legend_html())


def render():
    user = st.session_state.get("user") or {}
    now = local_now()
    style.html(f'<h2 class="home-greeting">{escape(greeting(user, now))}</h2>'
               f'<div class="home-summary">{escape(summary_line(needs_you_count(now)))}</div>')
    _project_strip()
    feed_view.render(local_now)
