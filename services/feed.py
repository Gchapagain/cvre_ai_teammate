"""The Home notification feed, built live from the database every time it is shown, so it is never stale.

Nothing here writes or calls an outside service. app/queries.feed_rows() reads the rows; build() turns
them into feed items, applies what the person did (read, snoozed, dismissed, from notification_state),
and sorts them into groups. Times: meeting and email times are the broker's local wall-clock time;
everything else in the database is UTC and is converted to the person's timezone here.

Adding a feed source: write a function that takes the rows and returns Items (see _flag_items), add the
rows it needs to queries.feed_rows(), add it to SOURCES, and give it a filter in FILTERS if it is a new kind.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import db

NOW_GROUP, WAITING, TODAY, COMING_UP, EARLIER = "Needs you now", "Waiting", "Today", "Coming up", "Earlier"
GROUPS = (NOW_GROUP, WAITING, TODAY, COMING_UP, EARLIER)
FLAG, WAITING_KIND, MEETING, EMAIL = "flag", "waiting", "meeting", "email"
FILTERS = {"All": None, "Flags": FLAG, "Waiting": WAITING_KIND, "Meetings": MEETING, "Email": EMAIL}
LABELS = {FLAG: "Flag", WAITING_KIND: "Waiting", MEETING: "Meeting", EMAIL: "Email"}
SNOOZE = timedelta(days=1)
MEETINGS_AHEAD = timedelta(days=7)    # meetings further away than this are not shown yet
MEETINGS_BEHIND = timedelta(days=2)   # ended meetings stay under Earlier this long
EMAILS_BEHIND = timedelta(days=7)


@dataclass
class Item:
    key: str            # what notification_state is stored under, e.g. "flag:12"
    kind: str           # flag, waiting, meeting or email
    group: str
    message: str
    when: datetime      # local time the item is about (for sorting and "2h ago" / "in 2 hours")
    deal_id: int | None = None
    deal_name: str | None = None
    actions: tuple = ()           # (label, action id) pairs; the screen decides what each action does
    sample: bool = False          # made up for the demo: always shown with a Sample chip
    ai: bool = False              # about something the AI wrote: gold accent
    can_hide: bool = True         # flags cannot be snoozed or dismissed: flag, never hide
    read: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def label(self):
        return LABELS[self.kind]


# ---- Times ----

def parse(text):
    return datetime.fromisoformat(text) if text else None


def stamp(moment):
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def from_utc(text, now):
    """A UTC time from the database as naive local time, in now's timezone."""
    moment = parse(text)
    if moment is None:
        return None
    if now.tzinfo is None:
        return moment
    return moment.replace(tzinfo=timezone.utc).astimezone(now.tzinfo).replace(tzinfo=None)


def local(text, source, today):
    """A meeting or email time. Sample rows are moved from SAMPLE_ANCHOR_DAY to the same place relative to today."""
    moment = parse(text)
    if moment is not None and source == "Sample":
        moment += today - date.fromisoformat(db.SAMPLE_ANCHOR_DAY)
    return moment


def clock(moment):
    return moment.strftime("%I:%M %p").lstrip("0")


def day_word(moment, today):
    days = (moment.date() - today).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days == -1:
        return "Yesterday"
    return moment.strftime("%a %b %d").replace(" 0", " ")


def _span(minutes):
    if minutes < 60:
        return f"{minutes} min"
    hours = round(minutes / 60)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    days = round(hours / 24)
    return f"{days} day{'s' if days != 1 else ''}"


def countdown(start, end, now):
    """'in 2 hours', 'starting now', 'happening now', 'ended'."""
    minutes = int((start - now).total_seconds() // 60)
    if minutes > 0:
        return f"in {_span(minutes)}"
    if end and now < end or not end and minutes > -30:
        return "happening now" if minutes < 0 else "starting now"
    return "ended"


def ago(moment, now):
    """'just now', '25 min ago', '3 hours ago', 'Yesterday', 'Mon Oct 26'."""
    if moment is None:
        return ""
    minutes = int((now - moment).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60 * 12 or moment.date() == now.date():
        return f"{_span(minutes)} ago"
    return day_word(moment, now.date())


def time_text(item, now):
    """What the card shows in its corner: how long ago. Meetings show nothing there: their message already
    has the time and the countdown ("Today 3:00 PM - Client call - in 2 hours")."""
    if item.kind == MEETING:
        return ""
    return ago(item.when, now.replace(tzinfo=None))


def short_name(deal_name):
    """'Fallowmere Industrial Park (SAMPLE - fictional)' -> 'Fallowmere Industrial Park'."""
    return (deal_name or "").split(" (")[0]


def _plural(count, word):
    return f"{count} {word}{'' if count == 1 else 's'}"


# ---- Sources ----

def flag_message(flag):
    """'Unit 110 rent/SF is 2.37x the average - Fallowmere Industrial Park', from the flag's own numbers."""
    deal = short_name(flag["deal_name"])
    if flag["rule"] == "rent_per_sf_above_2x_average":
        try:
            ratio = float(flag["actual_value"]) / (float(flag["threshold"]) / 2)
            return f"Unit {flag['unit_number']} rent/SF is {ratio:.2f}x the average - {deal}"
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return f"{flag['message']} - {deal}"


def _flag_items(rows, now, today):
    return [Item(f"flag:{f['id']}", FLAG, NOW_GROUP, flag_message(f), from_utc(f["created_at"], now),
                 f["deal_id"], f["deal_name"], (("Review flag", "review_flag"),), can_hide=False,
                 extra={"flag_id": f["id"]})
            for f in rows["flags"]]


def _waiting_items(rows, now, today):
    items = []
    for deal in rows["review_deals"]:
        items.append(Item(f"review:{deal['deal_id']}", WAITING_KIND, WAITING,
                          f"{short_name(deal['deal_name'])} is waiting for your review",
                          from_utc(deal["updated_at"], now), deal["deal_id"], deal["deal_name"],
                          (("Open review", "open_review"),)))
    for doc in rows["documents"]:
        what = ("needs a password before it can be read" if doc["status"] == "Needs password"
                else "has arrived and has not been read yet")
        items.append(Item(f"doc:{doc['id']}:{doc['status']}", WAITING_KIND, WAITING, f"{doc['filename']} {what}",
                          from_utc(doc["received_at"], now), doc["deal_id"], doc["deal_name"],
                          (("Open deal", "open_deal"),), extra={"source": doc["source"]}))
    for draft in rows["drafts"]:
        items.append(Item(f"draft:{draft['id']}", WAITING_KIND, WAITING,
                          f"An AI-drafted narrative for {short_name(draft['deal_name'])} is waiting for your approval",
                          from_utc(draft["created_at"], now), draft["deal_id"], draft["deal_name"],
                          (("Review draft", "open_review"),), ai=True))
    for research in rows["research"]:
        items.append(Item(f"research:{research['deal_id']}:{research['newest']}", WAITING_KIND, WAITING,
                          f"{_plural(research['waiting'], 'research finding')} for {short_name(research['deal_name'])} "
                          "waiting to be accepted or dismissed",
                          from_utc(research["fetched_at"], now), research["deal_id"], research["deal_name"],
                          (("Review research", "open_review"),)))
    return items


def meeting_message(meeting, start, end, now):
    parts = [f"{day_word(start, now.date())} {clock(start)}", meeting["title"]]
    if meeting["deal_name"]:
        parts.append(short_name(meeting["deal_name"]))
    parts.append(countdown(start, end, now))
    return " - ".join(parts)


def _meeting_items(rows, now, today):
    now = now.replace(tzinfo=None)  # meeting times are local wall-clock times
    items = []
    for meeting in rows["meetings"]:
        start = local(meeting["starts_at"], meeting["source"], today)
        end = local(meeting["ends_at"], meeting["source"], today)
        finished = (end or start + timedelta(minutes=30)) <= now
        if start > now + MEETINGS_AHEAD or finished and now - start > MEETINGS_BEHIND:
            continue
        group = EARLIER if finished else NOW_GROUP if start <= now + timedelta(hours=24) else COMING_UP
        actions = (("Open deal", "open_deal"), ("Prep brief", "prep_brief")) if meeting["deal_id"] else ()
        items.append(Item(f"meeting:{meeting['id']}", MEETING, group, meeting_message(meeting, start, end, now), start,
                          meeting["deal_id"], meeting["deal_name"], () if finished else actions,
                          sample=meeting["source"] == "Sample",
                          extra={"meeting": meeting, "start": start, "end": end}))
    return items


def email_message(email):
    files = email["attachment_names"]
    about = f" about {short_name(email['deal_name'])}" if email["deal_name"] else f": {email['subject']}"
    attached = f" - {_plural(len(files), 'attachment')} ({', '.join(files)})" if files else ""
    return f"New email from {email['sender']}{about}{attached}"


def _email_items(rows, now, today):
    now = now.replace(tzinfo=None)  # email times are local wall-clock times
    items = []
    for email in rows["emails"]:
        received = local(email["received_at"], email["source"], today)
        if now - received > EMAILS_BEHIND:
            continue
        received = min(received, now)  # a sample email dated later today has simply arrived
        actions = (("Add to deal", "add_email"),) if email["attachment_names"] else ()
        items.append(Item(f"email:{email['id']}", EMAIL, TODAY if received.date() == today else EARLIER,
                          email_message(email), received, email["deal_id"], email["deal_name"],
                          actions + (("Dismiss", "dismiss_email"),), sample=email["source"] == "Sample",
                          extra={"email": email}))
    return items


SOURCES = (_flag_items, _waiting_items, _meeting_items, _email_items)


# ---- Putting it together ----

def hidden(item, state, now):
    """True when a person dismissed or snoozed it. Flags are never hidden, whatever is stored."""
    if not item.can_hide or not state:
        return False
    snoozed = parse(state.get("snoozed_until"))
    return bool(state.get("dismissed_at")) or bool(snoozed and snoozed > now)


def build(rows, now):
    """Every visible item, in group order, then soonest meeting / most pressing first within a group.

    now: the person's current time, timezone-aware (their browser's timezone) or naive local time.
    """
    today = now.date()
    local_now = now.replace(tzinfo=None)
    items = []
    for source in SOURCES:
        items += source(rows, now, today)
    visible = []
    for item in items:
        state = rows["state"].get(item.key)
        if item.when is None:
            item.when = local_now
        if hidden(item, state, local_now):
            continue
        item.read = bool(state and state.get("read_at"))
        visible.append(item)

    def order(item):
        upcoming = item.kind == MEETING and item.group != EARLIER
        # Meetings soonest first; everything else newest first.
        return (GROUPS.index(item.group), item.kind != MEETING,
                item.when.timestamp() if upcoming else -item.when.timestamp())
    return sorted(visible, key=order)


def grouped(items, kind=None):
    """[(group, items)] for the groups that have something in them, keeping the order."""
    chosen = [item for item in items if kind is None or item.kind == kind]
    return [(group, [i for i in chosen if i.group == group]) for group in GROUPS if any(i.group == group for i in chosen)]


def counts(items):
    """How many items each filter chip shows."""
    return {name: sum(1 for i in items if kind is None or i.kind == kind) for name, kind in FILTERS.items()}


def needs_you(items):
    """The 'N things need you today' number: open flags and meetings in the next 24 hours."""
    return sum(1 for item in items if item.group == NOW_GROUP)


def unread(items):
    return sum(1 for item in items if not item.read)


# ---- Right rail ----

# "Waiting on you": one line per kind of thing, the filter chip it opens, and which item keys it counts.
WAITING_LINES = (
    ("Open flags", "Flags", "flag:"),
    ("Deals to review", "Waiting", "review:"),
    ("Documents not read yet", "Waiting", "doc:"),
    ("AI drafts to approve", "Waiting", "draft:"),
    ("Deals with research to review", "Waiting", "research:"),
    ("New emails", "Email", "email:"),
)


def todays_meetings(rows, now):
    """Today's meetings in time order, for the agenda: every one, even if its feed card was dismissed."""
    now = now.replace(tzinfo=None)
    agenda = []
    for meeting in rows["meetings"]:
        start = local(meeting["starts_at"], meeting["source"], now.date())
        end = local(meeting["ends_at"], meeting["source"], now.date())
        if start.date() == now.date():
            agenda.append({"id": meeting["id"], "start": start, "end": end, "title": meeting["title"],
                           "deal_name": meeting["deal_name"], "client_name": meeting["client_name"],
                           "sample": meeting["source"] == "Sample", "status": countdown(start, end, now)})
    return sorted(agenda, key=lambda m: (m["start"], m["id"]))


def waiting_summary(items):
    """[(label, count, filter chip)] for the kinds of thing that have at least one item in the feed."""
    lines = [(label, sum(1 for i in items if i.key.startswith(prefix)), chip) for label, chip, prefix in WAITING_LINES]
    return [line for line in lines if line[1]]
