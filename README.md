# CBRE AI Teammate

A prototype "AI Teammate" for commercial real estate brokers, built for CBRE as a TCU Business Information Systems capstone (INSC 40813). Project name: Agentic Broker Experience.

The AI Teammate does the document-heavy prep work a broker does before pricing a property: it reads the rent roll, checks the numbers, flags problems, and drafts a pricing narrative. **The AI drafts, flags and cites. A person always approves.** Nothing is ever sent to a client automatically.

> **Sample data only.** Every deal, tenant and number in this repo is made up. Do not upload real client files.

## What it does

| Area | What you can do |
|---|---|
| **Login** | Sign in as the demo broker (Avery Sample). Demo login only, no real Google or Microsoft sign-in yet. |
| **All deals** | Stat cards that filter the list, deals needing attention first, and **+ New deal** (upload a rent roll / T-12, or describe the deal to the AI). |
| **Review tab** | Decision card per flag: **fix it** (with a before/after preview) or **confirm it** (with a reason). Edit any extracted value, see the original, undo. Deal snapshot, key takeaways, sources, draft narrative, market research, activity timeline, and **approval**. |
| **Data tab** | Download the rent roll and T-12 as CSV or Excel, and the draft narrative as text. |
| **Recommendations tab** | Rule-based suggestions from the deal's data, plus AI suggestions from market research, each with its evidence. |
| **Ask AI** | A chat that answers only from that deal's data, every answer labelled. A floating AI button lets you ask about any deal or all deals. Voice input via recording or audio upload. |
| **Connections** | The data sources the research uses: web search, FRED, BLS, Census, imported market reports, and demo-only licensed sources. |

## Quick start (local)

Requires Python 3.11 or newer (developed on 3.14).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Add your keys (see below), then load the sample data and start the app
.venv/bin/python seed.py --reset
.venv/bin/streamlit run streamlit_app.py
```

Open http://localhost:8501 and click **Continue with Google** (demo sign-in).

`seed.py --reset` deletes the local database and rebuilds it from the sample files. Without `--reset` it does nothing.

### Keys (`.env`)

Create a `.env` file in the project folder. It is git-ignored and must never be committed.

```
GEMINI_API_KEY=...      # required for any AI feature
TAVILY_API_KEY=...      # optional: web research (free tier: 1,000 searches a month)
FRED_API_KEY=...        # optional: official unemployment data
BLS_API_KEY=...         # optional: official employment data
CENSUS_API_KEY=...      # optional: population and income
```

Without a key, that feature shows "Not set up" and explains where to get one. Everything else still works.

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub and create an app with `streamlit_app.py` as the main file.
2. In the app's **Settings → Secrets**, add:
   ```toml
   CBRE_DB_PATH = "sample_data/demo.db"
   GEMINI_API_KEY = "your-key-here"
   ```
3. Reboot the app.

The deployed app uses the committed sample database `sample_data/demo.db`. To rebuild it after changing the sample data:

```bash
CBRE_DB_PATH=sample_data/demo.db .venv/bin/python seed.py --reset
```

## Things to know

**How the AI is kept honest**
- **Humans decide.** The AI never saves a deal, applies a correction, accepts research or approves anything on its own. Every one of those needs a person to click a button.
- **Flags are never hidden or deleted.** A flag is open until a person fixes the value or confirms it is right, and resolved flags stay visible with who decided and why.
- **Every change is audited:** who, when, why, the value before, and whether it was Manual or AI-assisted. Each save can be undone until the deal is approved.
- **Numbers are checked in code.** AI answers, drafts, recommendations and proposed corrections are compared with the deal's data; anything with a figure that cannot be found is labelled "Not verified" or dropped. These checks can't judge wording, only numbers.
- **Every claim shows its source**, its reliability tier (1 government, 2 brokerage or research firm, 3 news) and its date where one exists.
- **No scraping, ever.** Only official APIs, cited web search, free public data and files you import. LinkedIn, CoStar, LoopNet / Crexi, Zillow and Redfin are demo-only: their findings are fake, marked SIMULATED, and can never be accepted or used.

**AI usage and limits**
- Gemini is only called when you click a button. Opening pages never calls it.
- The free Gemini tier allows about **20 requests a day**. Each of these uses one: a chat message, Generate draft, Generate recommendations, Understand my correction, a transcription, drafting a new deal, reading an uploaded rent roll, and summarising research.
- Run research also uses up to 4 Tavily searches and a few official-data calls, and reuses results for 24 hours.

**Known limits of the prototype**
- **Demo login:** anyone with the link signs in as the demo broker. There is one user type, Broker.
- **T-12 files are saved but not read yet**; only rent rolls are extracted.
- **No occupancy, cap rate, valuation or "time saved" figures are shown**, because none can be calculated from the data or has been measured.
- **Not tested live:** the outside APIs (Tavily, FRED, BLS, Census, Gemini web search) and Gemini's handling of real corrections have only been tested with simulated replies. Their request formats are the first thing to check with real keys.
- **Gemini web search** may not be available on a free Gemini key; if not, that source shows "Source unavailable" and the others still run.
- **Official data is set up for Fort Worth only** (`config/market_data.json`). Other locations get "No official series are set up".
- **The deployed copy resets.** Streamlit Cloud's disk is temporary, so edits, approvals and new deals return to the sample data when the app restarts.
- **Desktop only.** There is no mobile layout.
- **Accuracy against the 95% KPI has not been measured yet.**

## Project layout

```
streamlit_app.py        Entry point: settings, login, top bar, page routing
db.py                   SQLite schema and safe migrations
seed.py                 Loads the sample data (needs --reset)
app/views/              Screens (dashboard, deal, review, recommendations, connections, ...)
app/style.py            Design system (8px grid, colours, fonts)
services/               Logic with no UI:
  extraction.py           rent roll -> Gemini -> checked JSON -> SQLite
  validation.py           plain-Python rules that raise flags
  corrections.py          audited edits, confirm, undo, approve, reopen
  correction_ai.py        "Tell me what is wrong" -> checked proposals
  drafting.py             draft pricing narrative + number check
  qa.py                   deal-only chat with answer labels
  recommendations.py      rule-based and AI recommendations
  research.py, connections/   market research sources (adapters)
  gemini.py               shared Gemini access, retries, quota handling
config/                 Trusted source tiers, official data series per market
sample_data/            Fictional rent roll and T-12, and demo.db for deployment
tests/                  Unit and screen tests (all external services simulated)
tools/screenshots.py    Drives the real app in a browser and checks the layout
```

## Tests

```bash
.venv/bin/python -m pytest                                # all offline tests, no API calls
RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest -s -o log_cli=true   # also one real Gemini extraction
.venv/bin/pip install -r requirements-dev.txt             # then, for the browser checks:
.venv/bin/python tools/screenshots.py                     # (add "webkit" for Safari's engine)
```

Every external service is simulated in the offline tests, and tests never use the real `.env`. The screenshot tool runs its own copy of the app on a throwaway database and saves images to `screenshots/` (git-ignored).

## Design

Fraunces for headings and Public Sans for body text. Background `#faf8fb`, primary dark green `#1d3c2f`, top bar `#13271e`, secondary green `#30654f`, gold accent `#c9a227` (used to mark AI features), amber for warnings, red for flags.

## More detail

[CLAUDE.md](CLAUDE.md) is the full project brief: rules, data model, screens and roadmap.
