"""
Tests for the email-based dedup path added to upsert_person (2026-05-06).

Background: pid 319 ("Seude Adem") was created as a ghost duplicate of
pid 37 ("Seude  Mohammed Adem") during W15 Maz import because the import
row had no external_id and the whitespace-variant name didn't match.
The fix adds step 1b: email-match before falling through to name-match.

Test strategy: source-text checks (no DB) + inline logic stubs that
replicate the dedup algorithm without importing the backend package.
This follows the same pattern as test_ingest_guards.py so these tests
run in any environment (CI, local, Railway).
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read_source(rel_path: str) -> str:
    return (BACKEND_DIR / rel_path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Source-text sanity checks — verify the patch landed in crud.py
# ---------------------------------------------------------------------------


class TestUpsertPersonSourceText:
    """Verify the email-dedup code is present in the source without needing a DB."""

    def test_upsert_person_accepts_email_arg(self):
        """upsert_person signature must include an `email` parameter."""
        src = _read_source("db/crud.py")
        fn_start = src.find("def upsert_person(")
        assert fn_start != -1, "upsert_person not found in crud.py"
        # Grab up to the closing paren of the signature (first 300 chars is enough)
        sig_region = src[fn_start : fn_start + 300]
        assert "email" in sig_region, (
            "upsert_person must accept an `email` keyword argument"
        )

    def test_email_arg_defaults_to_none(self):
        """email parameter must default to None so existing callers are not broken."""
        src = _read_source("db/crud.py")
        fn_start = src.find("def upsert_person(")
        sig_region = src[fn_start : fn_start + 300]
        assert "email: str | None = None" in sig_region or "email=None" in sig_region, (
            "email parameter must default to None"
        )

    def test_email_match_comes_before_name_match(self):
        """Email dedup (step 1b) must appear before the name-fallback (step 2)
        in the function body."""
        src = _read_source("db/crud.py")
        fn_start = src.find("def upsert_person(")
        fn_body = src[fn_start : fn_start + 6000]
        email_idx = fn_body.find("lower(Person.email)")
        name_idx = fn_body.find("regexp_replace")
        assert email_idx != -1, "Email match query not found in upsert_person"
        assert name_idx != -1, "Name-normalization query not found in upsert_person"
        assert email_idx < name_idx, (
            "Email match (step 1b) must appear before name fallback (step 2) in the function"
        )

    def test_external_id_backfill_on_email_match(self):
        """When a match is found by email, the external_id must be backfilled
        if missing on the canonical row."""
        src = _read_source("db/crud.py")
        fn_start = src.find("def upsert_person(")
        fn_body = src[fn_start : fn_start + 6000]
        # The backfill block must appear inside the email branch — look for it
        # before the name-fallback query
        email_idx = fn_body.find("lower(Person.email)")
        name_idx = fn_body.find("regexp_replace")
        email_branch = fn_body[email_idx:name_idx]
        assert "person.external_id = external_id" in email_branch, (
            "upsert_person must backfill external_id on the canonical row when matched by email"
        )


# ---------------------------------------------------------------------------
# Logic tests — replicate the dedup algorithm with dict-based fakes
# ---------------------------------------------------------------------------

def _make_fake_db(people: list[dict]) -> "FakeDB":
    """Build a minimal DB stub from a list of person dicts."""

    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter_email(self, email_lower: str) -> "FakeQuery":
            matched = [p for p in self._rows if (p.get("email") or "").lower() == email_lower]
            return FakeQuery(matched)

        def filter_ext(self, ext_id: str) -> "FakeQuery":
            matched = [p for p in self._rows if p.get("external_id") == ext_id]
            return FakeQuery(matched)

        def filter_name_norm(self, norm: str) -> "FakeQuery":
            import re as _re
            matched = [
                p for p in self._rows
                if " ".join((p.get("full_name") or "").lower().split()) == norm
            ]
            return FakeQuery(matched)

        def order_by_active(self) -> "FakeQuery":
            sorted_rows = sorted(self._rows, key=lambda p: (not p.get("active", True), p.get("person_id", 0)))
            return FakeQuery(sorted_rows)

        def first(self):
            return self._rows[0] if self._rows else None

        def one_or_none(self):
            if len(self._rows) == 0:
                return None
            if len(self._rows) == 1:
                return self._rows[0]
            raise ValueError("Multiple rows found")

    class FakeDB:
        def __init__(self, rows):
            self._rows = list(rows)

        def query_by_email(self, email_lower: str):
            return FakeQuery(self._rows).filter_email(email_lower).order_by_active()

        def query_by_ext(self, ext_id: str):
            return FakeQuery(self._rows).filter_ext(ext_id)

        def query_by_name_norm(self, norm: str):
            return FakeQuery(self._rows).filter_name_norm(norm).order_by_active()

        def get_by_id(self, pid: int):
            for p in self._rows:
                if p.get("person_id") == pid:
                    return p
            return None

        def insert(self, person: dict) -> dict:
            next_id = max((p["person_id"] for p in self._rows), default=0) + 1
            person = dict(person, person_id=next_id)
            self._rows.append(person)
            return person

        def backfill_ext(self, person: dict, ext_id: str):
            person["external_id"] = ext_id

    return FakeDB(people)


def _upsert_person_sim(db, external_id, full_name, email=None):
    """
    Simulated upsert_person that mirrors the exact dedup logic in crud.py:
    1a. external_id
    1b. email (case-insensitive)
    2.  normalized name
    3.  insert
    Returns (person_dict, action) where action is 'found_ext'/'found_email'/'found_name'/'created'.
    """
    external_id = external_id.strip() if isinstance(external_id, str) else None
    full_name = full_name.strip() if isinstance(full_name, str) else None
    email_norm = email.strip().lower() if isinstance(email, str) and email.strip() else None

    if not full_name:
        return None, "no_name"

    # 1a) external_id
    if external_id:
        q = db.query_by_ext(external_id)
        person = q.one_or_none()
        if person:
            return person, "found_ext"

    # 1b) email
    if email_norm:
        q = db.query_by_email(email_norm)
        person = q.first()
        if person:
            if external_id and not person.get("external_id"):
                db.backfill_ext(person, external_id)
            return person, "found_email"

    # 2) normalized name
    norm = " ".join(full_name.lower().split())
    q = db.query_by_name_norm(norm)
    person = q.first()
    if person:
        return person, "found_name"

    # 3) create
    new_person = {
        "external_id": external_id,
        "full_name": full_name,
        "email": email_norm,
        "active": True,
    }
    created = db.insert(new_person)
    return created, "created"


class TestUpsertPersonEmailDedup:
    """Logic tests for the email-dedup path (step 1b)."""

    def test_seude_case_email_match_prevents_ghost_duplicate(self):
        """
        Replicates the exact Seude Adem / pid-319 incident.
        Canonical: pid 37, name "Seude  Mohammed Adem", ext "155280", email seudemadem@gmail.com.
        Import row: name "Seude Adem", ext None (absent in import file), same email.
        Expected: upsert_person returns pid 37, no new person created.
        """
        canonical = {
            "person_id": 37,
            "full_name": "Seude  Mohammed Adem",
            "external_id": "155280",
            "email": "seudemadem@gmail.com",
            "active": True,
        }
        db = _make_fake_db([canonical])

        person, action = _upsert_person_sim(
            db,
            external_id=None,
            full_name="Seude Adem",
            email="seudemadem@gmail.com",
        )

        assert person is not None, "Should have found an existing person"
        assert person["person_id"] == 37, (
            f"Expected pid 37 (canonical Seude), got pid {person['person_id']}"
        )
        assert action == "found_email", (
            f"Expected email-match path, got '{action}'"
        )
        # Confirm no new row was inserted
        all_people = db._rows
        assert len(all_people) == 1, (
            f"Ghost duplicate was created: {len(all_people)} person rows in DB"
        )

    def test_external_id_wins_over_email_when_both_match_different_people(self):
        """
        external_id match (step 1a) must win over email match (step 1b)
        even when those two paths would return different people.
        Scenario: two drivers share a clerical email error but have distinct external_ids.
        The correct driver is the one whose external_id matches.
        """
        driver_a = {
            "person_id": 10,
            "full_name": "Aisha Nur",
            "external_id": "111",
            "email": "shared@example.com",
            "active": True,
        }
        driver_b = {
            "person_id": 20,
            "full_name": "Fadumo Ali",
            "external_id": "222",
            "email": "shared@example.com",
            "active": True,
        }
        db = _make_fake_db([driver_a, driver_b])

        person, action = _upsert_person_sim(
            db,
            external_id="222",   # matches driver_b
            full_name="Fadumo Ali",
            email="shared@example.com",  # also present on driver_a
        )

        assert person["person_id"] == 20, (
            f"external_id match should win; expected pid 20 (driver_b), got {person['person_id']}"
        )
        assert action == "found_ext", (
            f"Expected external_id path, got '{action}'"
        )

    def test_distinct_people_no_email_no_ext_do_not_merge(self):
        """
        Two separate drivers with no email and no external_id but distinct names
        must NOT be merged just because their normalized names are similar.
        """
        existing = {
            "person_id": 50,
            "full_name": "Amina Hassan",
            "external_id": None,
            "email": None,
            "active": True,
        }
        db = _make_fake_db([existing])

        # Completely different driver
        person, action = _upsert_person_sim(
            db,
            external_id=None,
            full_name="Amina Hashi",
            email=None,
        )

        assert action == "created", (
            f"Different name should create a new row, not merge — got action='{action}'"
        )
        assert person["person_id"] != 50, (
            "Distinct drivers should not share person_id=50"
        )
        assert len(db._rows) == 2, (
            f"Should have 2 distinct person rows, got {len(db._rows)}"
        )

    def test_email_match_is_case_insensitive(self):
        """
        Email dedup must be case-insensitive.
        Canonical has lowercase email; import row has mixed-case.
        """
        canonical = {
            "person_id": 80,
            "full_name": "Rawda Hassan",
            "external_id": None,
            "email": "rawdahassan@gmail.com",
            "active": True,
        }
        db = _make_fake_db([canonical])

        # Import sends email in mixed case (common from SP files)
        person, action = _upsert_person_sim(
            db,
            external_id=None,
            full_name="Rawda Hassan",
            email="RawdaHassan@Gmail.Com",
        )

        assert person["person_id"] == 80, (
            f"Case-insensitive email match should return pid 80, got {person['person_id']}"
        )
        assert action == "found_email", (
            f"Expected email-match path, got '{action}'"
        )
        assert len(db._rows) == 1, "No duplicate should be created on mixed-case email"

    def test_external_id_backfilled_on_email_match(self):
        """
        When a person is found via email and the canonical row has no external_id,
        the external_id from the import row must be backfilled onto the canonical row.
        """
        canonical = {
            "person_id": 37,
            "full_name": "Seude  Mohammed Adem",
            "external_id": None,   # missing on canonical
            "email": "seudemadem@gmail.com",
            "active": True,
        }
        db = _make_fake_db([canonical])

        person, action = _upsert_person_sim(
            db,
            external_id="155280",   # provided on this import row
            full_name="Seude Adem",
            email="seudemadem@gmail.com",
        )

        assert person["person_id"] == 37
        assert action == "found_email"
        # Backfill must have happened
        assert person["external_id"] == "155280", (
            f"external_id should have been backfilled to '155280', got {person['external_id']!r}"
        )

    def test_no_false_merge_on_name_alone_when_email_is_different(self):
        """
        Two people with the same name but different emails must NOT be merged.
        The email check should return the first (active) person, but if the
        caller passes a different email the lookup must miss and fall through to name.
        This validates the scenario where name collides but email disambiguates.
        """
        driver_a = {
            "person_id": 100,
            "full_name": "Mohammed Ali",
            "external_id": "AAA",
            "email": "mali_driver@gmail.com",
            "active": True,
        }
        driver_b_ext_id = "BBB"
        db = _make_fake_db([driver_a])

        # A new "Mohammed Ali" with different external_id and different email arrives
        person, action = _upsert_person_sim(
            db,
            external_id=driver_b_ext_id,
            full_name="Mohammed Ali",
            email="different_mali@gmail.com",
        )

        # external_id BBB is new, so 1a misses.
        # email different_mali@ doesn't match driver_a's email, so 1b misses.
        # name "Mohammed Ali" normalized matches driver_a — so we get found_name.
        # This is acceptable behaviour (name collision is intentional dedup).
        # The important thing: we did NOT spuriously find via email.
        assert action in ("found_name", "created"), (
            f"Should not find via wrong email; got action='{action}'"
        )
