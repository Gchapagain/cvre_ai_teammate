# CBRE AI Teammate

## What we're building
Prototype "AI Teammate" (project name: Agentic Broker Experience) for CBRE, a global commercial real estate firm. TCU Business Information Systems capstone (INSC 40813).

Priority 1 is **Research & Value**: the AI Teammate does the document-heavy prep work that brokers (Agents) and Analysts do by hand before pricing a property. The AI drafts, flags and cites. Humans always approve. It never sends anything to a client by itself.

### KPIs (from the charter)
- 95% accuracy on tested financial figures.
- Voice-to-deal under 90 seconds (stretch).
- No producer interaction longer than 5 minutes.

### Scope
Scope additions (email ingestion, proactive research, locked-file handling) must be flagged to the PM. Mobile is out of scope: the app is desktop only. Keep scope tight and say so when something feels like scope creep.

## How it works end to end
1. **Capture**: a deal starts from an uploaded document (OM, BOV, rent roll, T-12) or an email captured from a connected inbox (Gmail API / Microsoft Graph, pointed at a safe demo inbox). Built so far: the "+ New deal" button on the dashboard, with two ways in. Upload files (xlsx or csv): the deal is created, files are saved as Received, and the first rent roll is read; T-12 files are saved but not read, because T-12 extraction is not built yet. Describe it to the AI: the AI returns a draft, anything it was not told is left blank, and nothing is saved until the person presses Create deal.
2. **Extract (Service A)**: Gemini reads the documents and returns strict JSON (rent roll units, T-12 line items, key terms). We validate the JSON and save to SQLite.
3. **Validate (Service B)**: plain Python rules check the numbers, e.g. flag any unit whose rent/SF is above 2x the average of the building's other units. Flag it, never hide it.
4. **Draft (Service C)**: Gemini writes a short pricing narrative from the deal's saved numbers and any accepted research, only when a person clicks "Generate draft" (1 request). A code check compares every number in the draft with the deal data; if one does not match, Approve stays locked until a person edits it. The app adds the "flagged units need confirmation" sentence itself if the AI leaves it out. Drafts are saved as "Generated, not sent"; only a person can approve. Indicative value (NOI / cap rate) is not built: no cap rate is available.
5. **Review**: the human reviews, edits, flags or approves in the app.
6. **Q&A (Service D)**: a chat limited to one deal. It answers only from that deal's data in SQLite. An answer is labeled "From this deal" only when it names a real source and every number in it is found in the deal data; otherwise "Not verified".
7. **Research (Service E)**: market research for the deal's submarket, run only when a person clicks "Run research" on the Review tab (not automatic yet, to protect the free quotas). It searches four topics (vacancy, asking rent trend, new supply, employment and demand) with Tavily, keeps only sources on the trusted list, and asks Gemini once to summarise them. Each run uses 4 searches and at most 1 Gemini request. Code checks every figure against the text of the source it is attributed to. Findings are cards with Accept / Dismiss; nothing reaches the narrative until a person accepts. Sources that give different figures get a "Sources disagree" tag and both figures are shown, never merged. If nothing is found it says "No reliable public sources found". Advisory only.

Source reliability tiers: Tier 1 official/government, Tier 2 brokerage and research firms, Tier 3 news and trade press. Anything else is skipped and counted. The domain list lives in one file: `config/source_tiers.json`.

Services live in `/services`: extraction, validation, drafting, qa, research, plus deals (the only writes the screens make), new_deal (uploads and AI drafts) and transcribe (audio to text). `gemini.py` is the shared Gemini access (client, retries, quota handling, timing log) used by every service. `pipeline.process_deal` runs extraction then validation and returns a short summary (units saved, flags raised, which rules).

## Connections (data sources)
Every source of market data is an adapter in `services/connections/`, behind one interface (`base.Adapter`): `id`, `name`, `kind`, `topics`, `provides`, `key_name`, `key_help`, `status()` and `search(deal)`. `search` returns findings, which are saved in `research_findings` with a `connection_id` and a `simulated` flag. A finding is: topic, summary, and its sources (name, URL if any, date, tier, figure, metric).

- **Live sources:**
  - Web search with Gemini + Google Search grounding. The source pages' text is not returned, so its figures are marked as not checked.
  - Web search with Tavily. Figures are checked against each source's text.
  - FRED, BLS and Census, using official APIs with free keys.
  - "Import a market report": a CSV, Excel or PDF the person exported from their own platform. Its findings cite the file. Locked PDFs get "Needs password".
- **Demo sources** (LinkedIn, CoStar, LoopNet / Crexi, Zillow, Redfin): their data is licensed or partner-only. They return obviously fake samples with a SIMULATED chip. Simulated findings can never be accepted, never count as a disagreement, and are never sent to the AI.
- **Status:** Connected, Not set up (key missing; the card says how to get one), Demo, Needs licensed access.
- **On/off:** the `connections` table stores on/off and last used. Only Administrators can switch sources; others see status only.
- **Run research:** runs each switched-on source on its own. One failing shows "Source unavailable" and never stops the others. Results under 24 hours old are reused unless the person ticks Refresh.
- **Config files:** official series per market are in `config/market_data.json`; trusted domains per tier are in `config/source_tiers.json`.

**No scraping, ever.** Only official APIs, free public data, web search with citations, and files the person imports. No unofficial scraping APIs. Zillow's open API is retired, LinkedIn needs a partnership, Redfin prohibits automated collection, and CoStar / Crexi PRO / Reonomy are licensed: these stay demo-only until CBRE's own licence connects them.

**Adding a source:**
1. Write a subclass of `Adapter` in `services/connections/` with a unique `id`, `name`, `kind`, `topics` and `provides`.
2. Set `key_name` and a one-line `key_help` if it needs a key (read from .env, never shown).
3. Implement `search(deal)` returning `finding(...)` dicts. Use `base.get_json` for HTTP so errors never include the URL. Raise `SourceError` with a friendly message.
4. Add it to `all_adapters()` in `services/connections/__init__.py`.
5. Add a simulated reply in `tests/connection_fakes.py` and tests in `tests/test_connections.py`. Never call the real service in tests.

## Users and login
- Roles: Agent (broker/producer), Analyst, Administrator.
- Google or Microsoft OAuth proves identity only.
- Prototype: the user must pick a role on the login screen BEFORE the sign-in buttons unlock.
- Production alternative (not built now): an email-to-role table.

## Screens (Streamlit, desktop only, wide layout)
1. **Login**: two columns. Left: dark green brand panel. Right: a card with Step 1 pick a role (three role cards), Step 2 sign in (Google / Microsoft buttons, locked until a role is chosen). Demo login only for now.
2. **Deals dashboard**: stat cards (active deals, needs review, time saved, anomalies) and deal cards with status pills. The stat cards are filters: clicking one shows only the matching deals, with "Showing: ..." above the list and a small Clear button. Time saved opens a note explaining it is not measured yet. Deals needing attention (Needs Review or an anomaly) come first with a coloured left border. Clicking a card opens the deal.
3. **Deal workspace**, opened by clicking a deal, with four tabs:
   - **Review**: a deal header card, then two columns. Left: anomaly banner, extracted fields ("12 of 12 units read"), draft pricing narrative with Flag for producer / Edit / Approve / Download, market research, Notes. Right: deal snapshot, key takeaways, where this came from. Snapshot and takeaways are calculated in `services/metrics.py` from saved rows, never by the AI. No occupancy, cap rate or accuracy figures are shown, because none can be calculated or has been measured; anything unavailable says "Not available", "Needs T-12" or "Not measured yet".
   - **Documents**: all files for the deal with status (Received / Read / Reference only / Needs password), source, an add-document box, and an expected-documents checklist. Locked PDFs get "Needs password": the user enters the password (used once, not stored) or requests an unlocked copy. Scanned PDFs go to OCR.
   - **Recommendations**: banner "AI suggestions. A person decides." Two kinds of card. "From the deal's data": rules in `services/recommendations.py`, calculated in code, no AI (flagged unit, leases ending in 12 / 24 months, tenant concentration at 25%+ of SF, missing values, no T-12); each shows the rule and the exact numbers. "From market research": one Gemini request on "Generate recommendations", from the deal's facts and real (never simulated) findings; each must cite a finding ID that exists and every number must be in the deal data or a cited finding, otherwise it is dropped and counted. Priority comes from the rules (for AI cards: the strongest cited source's tier). Accept / Dismiss / Add to deal notes; accepted ones show on the Review tab and feed the draft narrative.
   - **Data**: this deal's rent roll, T-12 summary, indicative value, draft versions, per-deal export. Built so far: rent roll and T-12 as CSV and Excel, draft narrative as text. PDF later.
   - **Ask AI**: deal-only chat. Gemini is called only when a message is sent; quota and rate-limit problems show as a friendly chat message. The web search toggle is shown disabled until Step 7. Every answer is labeled "From this deal", "From the web (Tier 1-3)" or "Not verified".
4. **Inbox & Chat**: captured emails with extraction chips and linked deal, plus a general chat.
5. **All Data**: master table across every deal, compare two deals, export everything.
6. **AI Teammate assistant**: a round floating button fixed to the bottom-right of every page after login. It opens a chat where the user picks one deal or "All deals". One deal uses the same logic as the Ask AI tab. "All deals" answers only from the database, is labeled "From these deals" and lists the deals used.

Desktop only. No mobile layout, bottom navigation or tables-as-cards.

## Data (SQLite)
Tables:
- deals
- deal_notes (deal_id, text, source Recording or Typed, created_at)
- rent_roll_units
- t12_line_items
- flags (deal_id, unit, rule, field, actual value, threshold, message)
- valuation_outputs
- drafts (deal_id, text, status Generated not sent / Flagged for producer / Approved, edited flag, created_at)
- research_findings (deal_id, topic, summary, sources as JSON, skipped count, status new / accepted / dismissed, fetched_at, connection_id, simulated)
- recommendations (deal_id, kind rule / ai, rule_key, title, priority, why, next_step, evidence JSON, status, created_at)
- connections (id, enabled, last_used_at)
- users (email to role)
- documents (deal_id, filename, source, received_at, status, used_for). Status is one of Received (arrived, not read yet), Read, Reference only, Needs password.
- research_jobs
- research_sources (url, published date, retrieved date, reliability tier)
- research_briefs

## Rules that must always hold
- Human in the loop. Nothing leaves the system without approval.
- Sample or synthetic data only. No real client data in the repo. The Fallowmere sample deal sits in a real submarket (Alliance, Fort Worth, TX) so research has something to find; the property, tenants and numbers are still made up.
- Secrets only in .env, never committed, never printed in logs. Keys used: GEMINI_API_KEY, TAVILY_API_KEY (web research; free tier is 1,000 searches a month).
- The AI never creates or saves a deal on its own. It drafts; a person presses Create deal.
- Voice: a person can record or upload audio (mp3, m4a, wav) in either chat and in the New deal box. It is sent to Gemini only when Transcribe is pressed. The audio is never saved; only the transcript the person has checked is used or stored (as a deal note, source "Recording"). The UI says: "Audio is sent to Gemini for transcription and is not saved."
- The free Gemini tier allows 20 requests a day. Each of these uses one: reading a rent roll, a chat message, drafting a deal from a description, transcribing a recording.
- Web search queries use generic terms only (property type + submarket). Never send client names or deal figures out.
- No scraping of any website, ever, and no unofficial scraping APIs. Simulated (demo) data is always labelled and never counts.
- External services and Gemini are only called when a person clicks a button.
- Every AI statement is traceable to a source (document or URL).
- Label every AI answer: From this deal / From these deals (all-deals questions) / From the web (Tier 1-3) / Not verified.
- Research is advisory and labeled "sourced", not "verified".
- Validation flags rent/SF above 2x the average of the building's other units. Flag, never hide. Flags never change the data or block saving.
- Extraction rejects a whole file (and saves nothing) only when the file is unreadable, a required column is missing, or Gemini's reply is not valid JSON. A bad value in one row is saved exactly as extracted and flagged by validation.
- Locked PDFs get status "Needs password". Never guess or bypass passwords.

## Design
- Background: #faf8fb
- Primary dark green: #1d3c2f
- Top bar: #13271e
- Secondary green: #30654f
- Gold accent: #c9a227
- Amber for warnings, red for flags
- Fonts: Fraunces (headings), Public Sans (body)
- Streamlit theme goes in `.streamlit/config.toml`. The design system lives in `app/style.py`: 8px spacing grid, 24px card padding, 12px radius, 40px buttons, 48px tabs. Use its tokens and classes instead of one-off styles.
- A full-width dark green top bar sits across every signed-in page: sparkle, app name and an "All deals" link on the left (both go to the dashboard and clear any filter); user name, role badge and Sign out on the right.
- Deal pages show a breadcrumb: All deals > Deal name.
- The Ask AI tab (a gold oval pill) and the assistant button use the gold accent with a sparkle icon so AI features are recognisable.

## How to work with me
- I'm a student and the technical lead. Explain in simple words what you did and why, not just code.
- One step at a time. After each step, run the tests, show me the results, and wait.
- Ask before big decisions (new libraries, changing the schema, anything that adds scope).
- Keep functions small, add comments only where logic isn't obvious, and keep tests for every number we extract.
- Commit to git after each working step with a clear message.

## Running the app
- Load sample data (deletes and rebuilds the local database, so it needs the flag): `.venv/bin/python seed.py --reset`
- Start the app: `.venv/bin/streamlit run streamlit_app.py`
- Viewing only reads the database (read-only connection in `app/queries.py`). The only writes come from explicit actions through `services/deals.py`: creating a deal, saving an upload, saving a note. The app never runs seed.py and never deletes data.
- Uploaded files are stored in `uploads/` (git-ignored). Sample data only: no real client files.
- Login is a demo login for now (no real OAuth), and the UI says so.
- "Time saved" shows "Not measured yet" until the accuracy report. No assumed numbers anywhere.

## Testing
- Run one area: `.venv/bin/python -m pytest tests/test_connections.py`, `tests/test_recommendations.py`, `tests/test_research.py`, `tests/test_drafting.py`, `tests/test_metrics.py`. Every external service is simulated in tests (`tests/connection_fakes.py`, `tests/research_fakes.py`); tests use made-up keys and never the real `.env`.
- After any UI change, look at the real app, not only the tests: `.venv/bin/python tools/screenshots.py` (add `webkit` for Safari's engine). It starts its own copy of the app, clicks through it, checks the layout, fails on any error box or traceback, and saves screenshots to `screenshots/` (git-ignored). It never sends a chat message, so Gemini is not called. It needs `requirements-dev.txt`.
- Restart the app after code changes. `app/fresh.py` reloads all app code together if a file changes while the app is running, but a restart is the safe habit.
- Offline (default, no API calls): `.venv/bin/python -m pytest`
- Live (one real Gemini request per extraction): `RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest -s -o log_cli=true`
- Only run the live test when I explicitly ask. The free-tier key allows 20 requests per day.
- A live run that matches every value saves Gemini's response to `tests/recordings/`. Offline runs replay it.

## Roadmap
- Step 1 (done): structure, db.py, sample data, extraction service, test.
- Step 2: validation service + T-12 extraction + tests.
- Step 3: drafting service.
- Step 4: Streamlit shell: login with role gate, dashboard, deal workspace tabs. (Part A done: seed.py, theme, demo login, dashboard, Review tab.)
- Step 5: Documents tab and locked-file flow.
- Step 6 (done): Ask AI chat, deal-only.
- Step 7: web research with source tiers.
- Step 8: Gmail connection to a demo inbox.
- Step 9: an accuracy report against the 95% KPI.
