"""Import a market report: a CSV, Excel or PDF file the person exported from their own platform.

The findings cite the uploaded file. Figures are checked against the file's own text.
Locked PDFs are never opened: they get "Needs password".
"""

import io
import re

from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from services import gemini, qa
from services.connections.base import Adapter, SourceError, finding

MAX_TEXT = 60_000  # characters sent to the AI from one report
TOPICS = ("Vacancy", "Asking rent trend", "New supply", "Employment and demand", "Population and income")

PROMPT = """Below is the text of a market report a broker imported. List the market findings it states.

Rules:
- Use ONLY the report text. Never estimate, average or add outside knowledge.
- topic must be one of: {topics}.
- summary: one plain sentence saying what the report states.
- figure: the number with its unit, copied exactly from the report, or null.
- metric: a short name for what the figure measures (for example "vacancy rate"), or null.
- period: the date or quarter the figure refers to, copied exactly from the report, or null.

REPORT TEXT
{text}
"""


class ReportFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    summary: str
    figure: str | None
    metric: str | None
    period: str | None


class ReportReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ReportFinding]


def report_text(filename, data):
    """The text of an imported report. Raises SourceError for a locked or unreadable file."""
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix == "pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise SourceError("Needs password: this PDF is locked. Ask for an unlocked copy; the app never guesses passwords.")
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except PdfReadError:
            raise SourceError("This PDF could not be read.") from None
    if suffix in ("csv", "xlsx"):
        import tempfile
        from pathlib import Path
        from services import extraction
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"report.{suffix}"
            path.write_bytes(data)
            try:
                rows = extraction.read_sheet_rows(path)
            except extraction.ExtractionError:
                raise SourceError("This file could not be read.") from None
        return "\n".join(" | ".join(cell for cell in row if cell) for row in rows)
    raise SourceError("Import a CSV, Excel (.xlsx) or PDF file.")


class ImportAdapter(Adapter):
    id, name, kind, icon = "import", "Import a market report", "Import", ":material/upload_file:"
    topics = TOPICS
    provides = "Findings from a report you export from your own platform (CSV, Excel or PDF), citing that file."
    runs_on_research = False  # it runs when a file is imported, not on Run research

    def __init__(self, client=None, model=None):
        self.client, self.model = client, model

    def read(self, filename, data, publisher, tier):
        """Turn an imported report into findings. One Gemini request. Saves nothing."""
        if tier not in (1, 2, 3):
            raise SourceError("Choose the tier of the report's publisher.")
        text = report_text(filename, data)
        if not text:
            raise SourceError("No text could be read from this file (a scanned PDF needs OCR first).")
        config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                             response_json_schema=ReportReply.model_json_schema())
        raw = gemini.generate(self.client or gemini.get_client(),
                              PROMPT.format(topics=", ".join(TOPICS), text=text[:MAX_TEXT]), config, self.model)
        try:
            reply = ReportReply.model_validate_json(raw)
        except ValidationError:
            raise SourceError("The report could not be summarised.") from None
        source = f"{filename} (imported, {publisher.strip() or 'publisher not given'})"
        findings = []
        for item in reply.findings:
            if item.topic not in TOPICS or qa.unmatched_numbers(item.summary, text):
                continue  # a statement with a number the report does not contain is dropped
            figure = item.figure if item.figure and not qa.unmatched_numbers(item.figure, text) else None
            period = item.period if item.period and re.sub(r"\s+", " ", item.period).lower() in re.sub(r"\s+", " ", text).lower() else None
            findings.append(finding(item.topic, item.summary, source, tier, self.id, figure=figure,
                                    metric=(item.metric or "").lower() or None if figure else None, date=period))
        return findings
