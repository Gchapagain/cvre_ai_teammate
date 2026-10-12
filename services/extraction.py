"""Extraction service: read a rent roll spreadsheet, have Gemini turn it into
strict JSON, validate that JSON, and save the rows to rent_roll_units.

Extraction only copies what the file says. Judging the numbers (for example the
rent/SF flag) is the validation service's job.
"""

import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openpyxl import load_workbook
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEY_PLACEHOLDER = "PASTE_KEY_HERE"

# Current stable Flash model per https://ai.google.dev/gemini-api/docs/models
# (checked 2026-10-12). Override with GEMINI_MODEL in .env if it changes.
DEFAULT_MODEL = "gemini-3.8-flash"

PROMPT = """You are extracting a commercial real estate rent roll into JSON.

Rules:
- Return one object per leased unit row in the table.
- Skip title rows, header rows, blank rows and total/subtotal rows.
- Copy every value exactly as it appears. Do not calculate, round, correct or guess.
- Dates must be YYYY-MM-DD. Numbers must be plain numbers with no currency symbols or commas.
- unit_number is text, exactly as written.

Rent roll (one spreadsheet row per line, cells separated by " | "):

{sheet_text}
"""


class ExtractionError(Exception):
    """Raised when the rent roll cannot be extracted or fails validation."""


class RentRollUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_number: str = Field(min_length=1)
    tenant_name: str = Field(min_length=1)
    square_feet: float = Field(gt=0)
    lease_start: date
    lease_end: date
    monthly_rent: float = Field(ge=0)
    annual_rent: float = Field(ge=0)
    rent_per_sf: float = Field(ge=0)
    lease_type: str


class RentRollExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: list[RentRollUnit] = Field(min_length=1)


def get_client():
    """Build a Gemini client using the key in .env."""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == KEY_PLACEHOLDER:
        raise ExtractionError("GEMINI_API_KEY is not set. Put your real key in the .env file.")
    return genai.Client(api_key=api_key)


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def read_sheet_rows(xlsx_path):
    """Return the first sheet as a list of rows, each a list of cell strings."""
    wb = load_workbook(xlsx_path, data_only=True, read_only=True)
    try:
        ws = wb.worksheets[0]
        rows = [[_cell_text(v) for v in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    return [r for r in rows if any(r)]


def validate_extraction(raw_json, source_rows):
    """Check the model's JSON against the schema and the source file. Returns the units."""
    try:
        extraction = RentRollExtraction.model_validate_json(raw_json)
    except ValidationError as exc:
        raise ExtractionError(f"Gemini output did not match the required JSON schema:\n{exc}") from exc

    source_cells = {cell.strip() for row in source_rows for cell in row}
    seen = set()
    for unit in extraction.units:
        if unit.unit_number in seen:
            raise ExtractionError(f"Unit {unit.unit_number} was returned more than once.")
        seen.add(unit.unit_number)
        if unit.unit_number not in source_cells:
            raise ExtractionError(f"Unit {unit.unit_number} is not in the source file.")
        if unit.lease_end <= unit.lease_start:
            raise ExtractionError(f"Unit {unit.unit_number}: lease end is not after lease start.")
    return extraction.units


def call_gemini(client, sheet_text, model=None):
    """Send the rent roll text to Gemini and return its raw JSON string."""
    response = client.models.generate_content(
        model=model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL,
        contents=PROMPT.format(sheet_text=sheet_text),
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=RentRollExtraction.model_json_schema(),
        ),
    )
    if not response.text:
        raise ExtractionError("Gemini returned an empty response.")
    return response.text


def save_units(conn, deal_id, document_id, units):
    """Replace this deal's rent roll rows with the newly extracted ones."""
    conn.execute("DELETE FROM rent_roll_units WHERE deal_id = ?", (deal_id,))
    conn.executemany(
        """INSERT INTO rent_roll_units
           (deal_id, document_id, unit_number, tenant_name, square_feet, lease_start,
            lease_end, monthly_rent, annual_rent, rent_per_sf, lease_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (deal_id, document_id, u.unit_number, u.tenant_name, u.square_feet,
             u.lease_start.isoformat(), u.lease_end.isoformat(), u.monthly_rent,
             u.annual_rent, u.rent_per_sf, u.lease_type)
            for u in units
        ],
    )


def extract_rent_roll(xlsx_path, deal_id, client=None, db_path=None, model=None):
    """Extract a rent roll file into rent_roll_units. Returns the number of units saved."""
    xlsx_path = Path(xlsx_path)
    source_rows = read_sheet_rows(xlsx_path)
    if not source_rows:
        raise ExtractionError(f"{xlsx_path.name} has no data.")
    sheet_text = "\n".join(" | ".join(row) for row in source_rows)

    raw_json = call_gemini(client or get_client(), sheet_text, model)
    units = validate_extraction(raw_json, source_rows)

    db.init_db(db_path)
    conn = db.get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO documents (deal_id, filename, doc_type, file_path, status) VALUES (?, ?, ?, ?, ?)",
                (deal_id, xlsx_path.name, "Rent roll", str(xlsx_path), "Extracted"),
            )
            save_units(conn, deal_id, cursor.lastrowid, units)
    finally:
        conn.close()
    return len(units)
