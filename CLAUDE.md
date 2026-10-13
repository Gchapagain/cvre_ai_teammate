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
4. **Draft (Service C)**: Gemini writes a pricing narrative from the validated numbers. Indicative value = NOI / cap rate, labeled as a draft working number, not a pricing decision.
5. **Review**: the human reviews, edits, flags or approves in the app.
6. **Q&A (Service D)**: a chat limited to one deal. It answers only from that deal's data in SQLite. An answer is labeled "From this deal" only when it names a real source and every number in it is found in the deal data; otherwise "Not verified".
7. **Research (Service E)**: proactive market research. When a deal arrives: plan questions, search the web with a search API (Tavily, Brave or Serper), score source reliability, write a cited brief. Advisory only.

Source reliability tiers: Tier 1 government/primary, Tier 2 brokerage research, Tier 3 trade press. Unrecognized sources are skipped.

Services live in `/services`: extraction, validation, drafting, qa, research, plus deals (the only writes the screens make), new_deal (uploads and AI drafts) and transcribe (audio to text). `gemini.py` is the shared Gemini access (client, retries, quota handling, timing log) used by every service. `pipeline.process_deal` runs extraction then validation and returns a short summary (units saved, flags raised, which rules).

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
- drafts
- users (email to role)
- documents (deal_id, filename, source, received_at, status, used_for). Status is one of Received (arrived, not read yet), Read, Reference only, Needs password.
- research_jobs
- research_sources (url, published date, retrieved date, reliability tier)
- research_briefs

## Rules that must always hold
- Human in the loop. Nothing leaves the system without approval.
- Sample or synthetic data only. No real client data in the repo.
- Secrets only in .env, never committed, never printed in logs.
- The AI never creates or saves a deal on its own. It drafts; a person presses Create deal.
- Voice: a person can record or upload audio (mp3, m4a, wav) in either chat and in the New deal box. It is sent to Gemini only when Transcribe is pressed. The audio is never saved; only the transcript the person has checked is used or stored (as a deal note, source "Recording"). The UI says: "Audio is sent to Gemini for transcription and is not saved."
- The free Gemini tier allows 20 requests a day. Each of these uses one: reading a rent roll, a chat message, drafting a deal from a description, transcribing a recording.
- Web search queries use generic terms only (property type + submarket). Never send client names or deal figures out.
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
