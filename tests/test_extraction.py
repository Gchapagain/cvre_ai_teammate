"""Compare every extracted rent roll value to the source spreadsheet.

Offline (default, no API calls):   .venv/bin/python -m pytest tests
Live (one real Gemini request):    RUN_LIVE_GEMINI=1 .venv/bin/python -m pytest tests -s -o log_cli=true

The live test only runs when RUN_LIVE_GEMINI=1 is set. When every value matches,
it saves Gemini's real response to tests/recordings/. TestRecordedGeminiResponse
then replays that file on every offline run, so real model output is checked
without spending quota. All other tests use a stand-in for Gemini.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from dotenv import load_dotenv
from google.genai import errors
from openpyxl import Workbook, load_workbook

import db
from services import extraction, validation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RENT_ROLL = PROJECT_ROOT / "sample_data" / "rent_roll.xlsx"
RECORDING = PROJECT_ROOT / "tests" / "recordings" / "rent_roll_gemini.json"
FIELDS = [
    "unit_number", "tenant_name", "square_feet", "lease_start", "lease_end",
    "monthly_rent", "annual_rent", "rent_per_sf", "lease_type",
]
NUMERIC_FIELDS = {"square_feet", "monthly_rent", "annual_rent", "rent_per_sf"}

load_dotenv(PROJECT_ROOT / ".env")
HAS_REAL_KEY = os.getenv("GEMINI_API_KEY", "").strip() not in ("", extraction.KEY_PLACEHOLDER)
LIVE_REQUESTED = os.getenv("RUN_LIVE_GEMINI") == "1"


def read_source_units():
    """Read the rent roll straight from the Excel file, without any AI."""
    ws = load_workbook(RENT_ROLL, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header_index = next(i for i, r in enumerate(rows) if r[0] == "Unit")
    units = []
    for row in rows[header_index + 1:]:
        if row[0] is None or row[0] == "Total":
            continue
        unit = dict(zip(FIELDS, row))
        unit["lease_start"] = unit["lease_start"].date().isoformat()
        unit["lease_end"] = unit["lease_end"].date().isoformat()
        units.append(unit)
    return units


def fake_client(units):
    """A stand-in Gemini client that replies with the given units as JSON."""
    reply = SimpleNamespace(text=json.dumps({"units": units}))
    return SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: reply))


def gemini_error(code, status, message="simulated", quota_id=None):
    """Build the error the Gemini SDK raises for an HTTP error code."""
    error = {"code": code, "message": message, "status": status}
    if quota_id:
        error["details"] = [{
            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
            "violations": [{"quotaId": quota_id, "quotaValue": "20"}],
        }]
    error_class = errors.ServerError if code >= 500 else errors.ClientError
    return error_class(code, {"error": error})


def per_minute_quota_error():
    return gemini_error(429, "RESOURCE_EXHAUSTED", quota_id="GenerateRequestsPerMinutePerProjectPerModel-FreeTier")


def daily_quota_error():
    return gemini_error(
        429, "RESOURCE_EXHAUSTED",
        message="You exceeded your current quota.\nPlease retry in 3h52m47.09578507s.",
        quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier",
    )


def forbidden_client():
    """A client that fails the test if anything tries to call Gemini."""
    def generate_content(**kwargs):
        raise AssertionError("Gemini was called, but this test must not use the API")
    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def flaky_client(outcomes):
    """A stand-in client that works through outcomes in order: raise errors, return units as JSON."""
    calls = []

    def generate_content(**kwargs):
        outcome = outcomes[len(calls)]
        calls.append(outcome)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=json.dumps({"units": outcome}))

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    return client, calls


class ExtractionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path)
        conn = db.get_connection(self.db_path)
        with conn:
            self.deal_id = conn.execute(
                "INSERT INTO deals (name, property_type) VALUES ('Sample Deal', 'Industrial')"
            ).lastrowid
        conn.close()
        self.source = read_source_units()

    def saved_units(self):
        conn = db.get_connection(self.db_path)
        rows = conn.execute(
            f"SELECT {', '.join(FIELDS)} FROM rent_roll_units WHERE deal_id = ?", (self.deal_id,)
        ).fetchall()
        conn.close()
        return {row["unit_number"]: dict(row) for row in rows}

    def saved_documents(self):
        conn = db.get_connection(self.db_path)
        rows = conn.execute("SELECT * FROM documents WHERE deal_id = ?", (self.deal_id,)).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def find_mismatches(self):
        """Return a list of every value in the database that differs from the source file."""
        saved = self.saved_units()
        mismatches = []
        if len(saved) != len(self.source):
            mismatches.append(f"unit count: source {len(self.source)}, extracted {len(saved)}")
        for expected in self.source:
            actual = saved.get(expected["unit_number"])
            if actual is None:
                mismatches.append(f"unit {expected['unit_number']}: missing")
                continue
            for field in FIELDS:
                if field in NUMERIC_FIELDS:
                    same = abs(actual[field] - expected[field]) < 0.005
                else:
                    same = actual[field] == expected[field]
                if not same:
                    mismatches.append(
                        f"unit {expected['unit_number']} {field}: source {expected[field]!r}, extracted {actual[field]!r}"
                    )
        return mismatches


class TestSampleData(ExtractionTestCase):
    def test_twelve_units_with_one_outlier_at_2_3x(self):
        self.assertEqual(len(self.source), 12)
        average = sum(u["annual_rent"] for u in self.source) / sum(u["square_feet"] for u in self.source)
        ratios = {u["unit_number"]: u["rent_per_sf"] / average for u in self.source}
        above_2x = [unit for unit, ratio in ratios.items() if ratio > 2]
        self.assertEqual(above_2x, ["110"])
        self.assertAlmostEqual(ratios["110"], 2.3, places=2)


class TestPipelineWithoutGemini(ExtractionTestCase):
    def test_every_value_saved_matches_source(self):
        count = extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, client=fake_client(self.source), db_path=self.db_path
        )
        self.assertEqual(count, 12)
        self.assertEqual(self.find_mismatches(), [])

    def test_document_is_recorded_as_read(self):
        extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, client=fake_client(self.source), db_path=self.db_path
        )
        documents = self.saved_documents()
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["filename"], "rent_roll.xlsx")
        self.assertEqual(documents[0]["status"], "Read")
        self.assertEqual(documents[0]["source"], "Upload")
        self.assertEqual(documents[0]["used_for"], "Rent roll")
        self.assertTrue(documents[0]["received_at"])

    def test_comparison_catches_a_wrong_value(self):
        wrong = [dict(u) for u in self.source]
        wrong[4]["monthly_rent"] += 100
        extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=fake_client(wrong), db_path=self.db_path)
        mismatches = self.find_mismatches()
        self.assertEqual(len(mismatches), 1)
        self.assertIn("unit 105 monthly_rent", mismatches[0])

    def test_rerun_replaces_rows_instead_of_duplicating(self):
        for _ in range(2):
            extraction.extract_rent_roll(
                RENT_ROLL, self.deal_id, client=fake_client(self.source), db_path=self.db_path
            )
        self.assertEqual(len(self.saved_units()), 12)

    def test_bad_output_is_rejected_and_nothing_is_saved(self):
        missing_field = [{k: v for k, v in u.items() if k != "annual_rent"} for u in self.source]
        extra_field = [dict(u, notes="made up") for u in self.source]
        wrong_type = [dict(u, square_feet=True) for u in self.source]
        no_unit_id = [dict(u, unit_number="") for u in self.source]
        invented_unit = self.source + [dict(self.source[0], unit_number="999")]
        duplicate_unit = self.source + [self.source[0]]
        cases = {
            "missing field": missing_field,
            "extra field": extra_field,
            "true/false where a number belongs": wrong_type,
            "blank unit ID": no_unit_id,
            "unit not in the file": invented_unit,
            "unit repeated more often than in the file": duplicate_unit,
            "no units": [],
        }
        for name, units in cases.items():
            with self.subTest(name):
                with self.assertRaises(extraction.ExtractionError):
                    extraction.extract_rent_roll(
                        RENT_ROLL, self.deal_id, client=fake_client(units), db_path=self.db_path
                    )
                self.assertEqual(self.saved_units(), {})

    def test_not_json_is_rejected(self):
        client = SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text="Sure! Here it is"))
        )
        with self.assertRaises(extraction.ExtractionError):
            extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=client, db_path=self.db_path)


class TestUnitProblemsAreSavedNotRejected(ExtractionTestCase):
    """A bad value in one row is saved exactly as extracted and left for validation to flag."""

    CASES = {
        "zero SF": ("square_feet", 0, validation.RULE_ZERO_OR_NEGATIVE),
        "negative SF": ("square_feet", -12000, validation.RULE_ZERO_OR_NEGATIVE),
        "negative rent": ("monthly_rent", -8500.0, validation.RULE_ZERO_OR_NEGATIVE),
        "zero annual rent": ("annual_rent", 0, validation.RULE_ZERO_OR_NEGATIVE),
        "text where a number belongs": ("rent_per_sf", "TBD", validation.RULE_NON_NUMERIC),
        "empty number": ("monthly_rent", None, validation.RULE_MISSING),
        "lease end before start": ("lease_end", "2020-01-01", validation.RULE_LEASE_DATES),
        "unreadable date": ("lease_end", "month to month", validation.RULE_INVALID_DATE),
    }

    def test_each_problem_is_saved_as_extracted_and_flagged(self):
        for name, (field, bad_value, rule) in self.CASES.items():
            with self.subTest(name):
                units = [dict(u) for u in self.source]
                units[4][field] = bad_value
                count = extraction.extract_rent_roll(
                    RENT_ROLL, self.deal_id, client=fake_client(units), db_path=self.db_path
                )
                self.assertEqual(count, 12)
                self.assertEqual(self.saved_units()["105"][field], bad_value)
                flags = validation.validate_deal(self.deal_id, self.db_path)
                self.assertIn(("105", rule, field), [(f.unit_number, f.rule, f.field) for f in flags])

    def test_lease_ending_on_its_start_date_is_saved(self):
        units = [dict(u) for u in self.source]
        units[4]["lease_end"] = units[4]["lease_start"]
        extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=fake_client(units), db_path=self.db_path)
        self.assertEqual(self.saved_units()["105"]["lease_end"], units[4]["lease_start"])

    def test_other_rows_are_untouched_by_one_bad_row(self):
        units = [dict(u) for u in self.source]
        units[4]["square_feet"] = 0
        extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=fake_client(units), db_path=self.db_path)
        mismatches = self.find_mismatches()
        self.assertEqual(len(mismatches), 1)
        self.assertIn("unit 105 square_feet", mismatches[0])


HEADERS = ["Unit", "Tenant", "SF", "Lease Start", "Lease End",
           "Monthly Base Rent", "Annual Base Rent", "Rent / SF (Annual)", "Lease Type"]
# A made-up rent roll with a problem in every row except the first.
MESSY_ROWS = [
    ["A1", "Clean Tenant Co.", 5000, "2024-01-01", "2028-12-31", 4000.0, 48000.0, 9.6, "NNN"],
    ["A2", "Zero Size LLC", 0, "2024-01-01", "2028-12-31", 3000.0, 36000.0, 0, "NNN"],
    ["A3", "Negative Rent Inc.", 4000, "2024-01-01", "2028-12-31", -2500.5, -30006.0, -7.5, "NNN"],
    ["A4", "Backwards Dates Ltd.", 6000, "2026-06-01", "2025-05-31", 5000.0, 60000.0, 10.0, "NNN"],
    ["A5", "Text Rent Partners", 3000, "2024-01-01", "2028-12-31", "TBD", "see lease", 8.0, "NNN"],
    ["A5", "Same Unit Again", 3000, "2024-01-01", "2028-12-31", 2000.0, 24000.0, 8.0, "NNN"],
]


def write_rent_roll(path, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["Made-up Property (SAMPLE - fictional)"])
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


class TestSavedValuesAreIdenticalToTheFile(ExtractionTestCase):
    def test_every_saved_value_equals_the_cell_in_the_file_even_when_it_is_wrong(self):
        path = Path(self.tmp.name) / "messy_rent_roll.xlsx"
        write_rent_roll(path, HEADERS, MESSY_ROWS)
        # Read the cells back from the saved file, so the comparison is against the file itself.
        file_rows = list(load_workbook(path).worksheets[0].iter_rows(min_row=3, values_only=True))
        units = [dict(zip(FIELDS, row)) for row in file_rows]

        count = extraction.extract_rent_roll(path, self.deal_id, client=fake_client(units), db_path=self.db_path)
        self.assertEqual(count, len(file_rows))

        conn = db.get_connection(self.db_path)
        saved = conn.execute(f"SELECT {', '.join(FIELDS)} FROM rent_roll_units ORDER BY id").fetchall()
        conn.close()
        checked = 0
        for file_row, saved_row in zip(file_rows, saved, strict=True):
            for field, file_value in zip(FIELDS, file_row):
                self.assertEqual(saved_row[field], file_value, f"unit {file_row[0]} {field}")
                checked += 1
        self.assertEqual(checked, len(MESSY_ROWS) * len(FIELDS))

        flags = validation.validate_deal(self.deal_id, self.db_path)
        self.assertEqual(
            {f.rule for f in flags},
            {validation.RULE_ZERO_OR_NEGATIVE, validation.RULE_LEASE_DATES,
             validation.RULE_NON_NUMERIC, validation.RULE_DUPLICATE},
        )


class TestFileLevelProblemsAreRejected(ExtractionTestCase):
    """These stop before Gemini is called, and nothing is saved."""

    def assert_rejected(self, path, expected_text):
        with self.assertRaises(extraction.ExtractionError) as caught:
            extraction.extract_rent_roll(path, self.deal_id, client=forbidden_client(), db_path=self.db_path)
        self.assertIn(expected_text, str(caught.exception))
        self.assertEqual(self.saved_units(), {})
        self.assertEqual(self.saved_documents(), [])

    def test_file_that_is_not_a_spreadsheet(self):
        path = Path(self.tmp.name) / "broken.xlsx"
        path.write_bytes(b"this is not an Excel file")
        self.assert_rejected(path, "could not be read")

    def test_file_that_does_not_exist(self):
        self.assert_rejected(Path(self.tmp.name) / "nowhere.xlsx", "could not be read")

    def test_empty_spreadsheet(self):
        path = Path(self.tmp.name) / "empty.xlsx"
        Workbook().save(path)
        self.assert_rejected(path, "has no data")

    def test_each_missing_required_column(self):
        required = {
            "Unit": "unit", "Tenant": "tenant", "SF": "square feet", "Lease Start": "lease start",
            "Lease End": "lease end", "Monthly Base Rent": "monthly rent",
            "Annual Base Rent": "annual rent", "Rent / SF (Annual)": "rent per SF",
        }
        for header, name in required.items():
            with self.subTest(header):
                keep = [i for i, h in enumerate(HEADERS) if h != header]
                path = Path(self.tmp.name) / "missing_column.xlsx"
                write_rent_roll(path, [HEADERS[i] for i in keep], [[row[i] for i in keep] for row in MESSY_ROWS])
                self.assert_rejected(path, f"missing required column(s): {name}.")

    def test_several_missing_columns_are_all_named(self):
        path = Path(self.tmp.name) / "two_columns.xlsx"
        write_rent_roll(path, HEADERS[:2], [row[:2] for row in MESSY_ROWS])
        self.assert_rejected(path, "square feet, lease start, lease end, monthly rent, annual rent, rent per SF")

    def test_lease_type_column_is_optional(self):
        path = Path(self.tmp.name) / "no_lease_type.xlsx"
        write_rent_roll(path, HEADERS[:-1], [row[:-1] for row in MESSY_ROWS[:1]])
        units = [dict(zip(FIELDS, MESSY_ROWS[0][:-1] + [None]))]
        count = extraction.extract_rent_roll(path, self.deal_id, client=fake_client(units), db_path=self.db_path)
        self.assertEqual(count, 1)

    def test_other_common_heading_names_are_accepted(self):
        headers = ["Suite", "Tenant Name", "Sq Ft", "Commencement", "Expiration",
                   "Monthly Rent", "Annual Rent", "Rent PSF", "Type"]
        path = Path(self.tmp.name) / "other_headings.xlsx"
        write_rent_roll(path, headers, MESSY_ROWS[:1])
        units = [dict(zip(FIELDS, MESSY_ROWS[0]))]
        count = extraction.extract_rent_roll(path, self.deal_id, client=fake_client(units), db_path=self.db_path)
        self.assertEqual(count, 1)


class TestGeminiRetry(ExtractionTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(extraction.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def test_temporary_errors_are_retried_then_succeed(self):
        outcomes = [gemini_error(503, "UNAVAILABLE"), per_minute_quota_error(), self.source]
        client, calls = flaky_client(outcomes)
        count = extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=client, db_path=self.db_path)
        self.assertEqual(count, 12)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.sleep.call_count, 2)
        self.assertEqual(self.find_mismatches(), [])

    def test_three_failures_stop_with_clear_error_and_save_nothing(self):
        for code, error in [(503, gemini_error(503, "UNAVAILABLE")), (429, per_minute_quota_error())]:
            with self.subTest(code):
                client, calls = flaky_client([error] * 5)
                with self.assertRaises(extraction.ExtractionError) as caught:
                    extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=client, db_path=self.db_path)
                self.assertEqual(len(calls), 3)
                message = str(caught.exception)
                self.assertIn("after 3 tries", message)
                self.assertIn(str(code), message)
                self.assertIn("Nothing was saved", message)
                self.assertEqual(self.saved_units(), {})
                self.assertEqual(self.saved_documents(), [])

    def test_permanent_error_is_not_retried(self):
        client, calls = flaky_client([gemini_error(400, "INVALID_ARGUMENT"), self.source])
        with self.assertRaises(extraction.ExtractionError) as caught:
            extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=client, db_path=self.db_path)
        self.assertEqual(len(calls), 1)
        self.sleep.assert_not_called()
        self.assertIn("400", str(caught.exception))
        self.assertEqual(self.saved_units(), {})
        self.assertEqual(self.saved_documents(), [])


    def test_daily_quota_stops_immediately_and_saves_nothing(self):
        client, calls = flaky_client([daily_quota_error(), self.source])
        with self.assertRaises(extraction.ExtractionError) as caught:
            extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=client, db_path=self.db_path)
        self.assertEqual(len(calls), 1)
        self.sleep.assert_not_called()
        message = str(caught.exception)
        self.assertIn("daily quota is used up", message)
        self.assertIn("Nothing was saved", message)
        self.assertIn("3h52m", message)
        self.assertEqual(self.saved_units(), {})
        self.assertEqual(self.saved_documents(), [])

    def test_each_attempt_and_the_total_are_logged(self):
        client, _ = flaky_client([gemini_error(503, "UNAVAILABLE"), self.source])
        with self.assertLogs("services.extraction", level="INFO") as logs:
            extraction.extract_rent_roll(RENT_ROLL, self.deal_id, client=client, db_path=self.db_path)
        lines = [record.getMessage() for record in logs.records]
        self.assertEqual(len(lines), 3)
        self.assertIn("attempt 1/3: failed with 503 UNAVAILABLE", lines[0])
        self.assertIn("attempt 2/3: ok", lines[1])
        self.assertIn("total:", lines[2])
        self.assertIn("2 attempt(s)", lines[2])


class TestRecordAndReplay(ExtractionTestCase):
    def setUp(self):
        super().setUp()
        self.recording = Path(self.tmp.name) / "recordings" / "rent_roll.json"

    def record(self, units):
        extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, client=fake_client(units), db_path=self.db_path,
            record_to=self.recording,
        )

    def replay(self):
        return extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, client=forbidden_client(), db_path=self.db_path,
            replay_from=self.recording,
        )

    def test_replay_gives_the_recorded_values_without_calling_gemini(self):
        self.record(self.source)
        self.assertEqual(self.replay(), 12)
        self.assertEqual(self.find_mismatches(), [])

    def test_recording_keeps_the_response_exactly_and_no_secrets(self):
        self.record(self.source)
        recording = json.loads(self.recording.read_text())
        self.assertEqual(set(recording), {"recorded_at", "model", "prompt_sha256", "response_text"})
        self.assertEqual(json.loads(recording["response_text"]), {"units": self.source})

    def test_replayed_response_is_still_validated(self):
        wrong = [dict(u) for u in self.source]
        wrong[4]["monthly_rent"] += 100
        self.record(wrong)
        self.replay()
        self.assertEqual(len(self.find_mismatches()), 1)

    def test_out_of_date_recording_is_refused_and_nothing_is_saved(self):
        self.record(self.source)
        conn = db.get_connection(self.db_path)
        with conn:
            conn.execute("DELETE FROM rent_roll_units")
            conn.execute("DELETE FROM documents")
        conn.close()
        with mock.patch.object(extraction, "PROMPT", extraction.PROMPT + "\nOne more rule."):
            with self.assertRaises(extraction.ExtractionError) as caught:
                self.replay()
        self.assertIn("out of date", str(caught.exception))
        self.assertEqual(self.saved_units(), {})
        self.assertEqual(self.saved_documents(), [])

    def test_missing_recording_gives_a_clear_error(self):
        with self.assertRaises(extraction.ExtractionError) as caught:
            self.replay()
        self.assertIn("No recorded Gemini response", str(caught.exception))

    def test_nothing_is_recorded_when_gemini_fails(self):
        with mock.patch.object(extraction.time, "sleep"):
            client, _ = flaky_client([daily_quota_error()])
            with self.assertRaises(extraction.ExtractionError):
                extraction.extract_rent_roll(
                    RENT_ROLL, self.deal_id, client=client, db_path=self.db_path, record_to=self.recording
                )
        self.assertFalse(self.recording.exists())


@unittest.skipUnless(RECORDING.exists(), "no real Gemini response recorded yet; run once with RUN_LIVE_GEMINI=1")
class TestRecordedGeminiResponse(ExtractionTestCase):
    def test_recorded_real_response_matches_source_exactly(self):
        count = extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, client=forbidden_client(), db_path=self.db_path, replay_from=RECORDING
        )
        self.assertEqual(count, 12)
        self.assertEqual(self.find_mismatches(), [])


@unittest.skipUnless(LIVE_REQUESTED, "live Gemini call not requested; set RUN_LIVE_GEMINI=1 to run it")
@unittest.skipUnless(HAS_REAL_KEY, "GEMINI_API_KEY in .env is still the placeholder")
class TestLiveExtraction(ExtractionTestCase):
    def test_gemini_extraction_matches_source_exactly(self):
        new_recording = Path(self.tmp.name) / "recording.json"
        count = extraction.extract_rent_roll(
            RENT_ROLL, self.deal_id, db_path=self.db_path, record_to=new_recording
        )
        self.assertEqual(count, 12)
        mismatches = self.find_mismatches()
        total = len(self.source) * len(FIELDS)
        summary = f"Gemini: {total - len(mismatches)} of {total} values match the source"
        print(f"\n  {summary}")
        self.assertEqual(mismatches, [], f"\n{summary}\n" + "\n".join(mismatches))
        # Only a response that matched every value becomes the recording used offline.
        RECORDING.parent.mkdir(exist_ok=True)
        shutil.copy(new_recording, RECORDING)


if __name__ == "__main__":
    unittest.main()
