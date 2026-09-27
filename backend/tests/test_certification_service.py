"""
Tests for backend/services/certification.py — S7 driver certification course.

Covers:
  - is_certified / needs_recert / record_certification against a real
    in-memory SQLite DB (StaticPool pattern used across the suite, see
    test_assignment_service.py).
  - quiz_passes / pass_threshold (8-of-10 pass rule).
  - course-content integrity: every quiz question has exactly one correct
    option, and all three languages (en/am/ar) have equal module and
    question counts / non-empty text.

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_certification_service.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-certification-service-long-enough")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.db.models import Base, DriverCertification, Person  # noqa: E402
from backend.services import certification  # noqa: E402


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _rec):
        dbapi_conn.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())

    Base.metadata.create_all(engine, tables=[Person.__table__, DriverCertification.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _person(db, person_id: int, name: str = "Test Driver") -> Person:
    p = Person(person_id=person_id, full_name=name, active=True, status="active")
    db.add(p)
    db.commit()
    return p


# ── quiz_passes / pass_threshold ─────────────────────────────────────────────

def test_pass_threshold_is_eight_of_ten():
    assert certification.pass_threshold(10) == 8


def test_quiz_passes_at_exactly_threshold():
    assert certification.quiz_passes(8, 10) is True


def test_quiz_passes_above_threshold():
    assert certification.quiz_passes(10, 10) is True


def test_quiz_fails_below_threshold():
    assert certification.quiz_passes(7, 10) is False


def test_quiz_fails_with_zero_total():
    assert certification.quiz_passes(0, 0) is False


# ── is_certified / needs_recert / record_certification ───────────────────────

def test_never_certified_driver_is_not_certified(db):
    _person(db, 1)
    assert certification.is_certified(db, 1) is False
    assert certification.needs_recert(db, 1) is False  # never certified != needs recert


def test_record_certification_makes_driver_certified(db):
    _person(db, 2)
    row = certification.record_certification(db, 2, quiz_score=9, quiz_total=10, signed_name="Test Driver")
    assert row.cert_id is not None
    assert certification.is_certified(db, 2) is True
    assert certification.needs_recert(db, 2) is False


def test_stale_course_version_needs_recert_not_certified(db):
    _person(db, 3)
    certification.record_certification(
        db, 3, quiz_score=8, quiz_total=10, signed_name="Old Cert",
        course_version="2025-01",
    )
    assert certification.is_certified(db, 3) is False
    assert certification.needs_recert(db, 3) is True


def test_latest_row_wins_when_multiple_certifications_exist(db):
    _person(db, 4)
    old_time = datetime.now(timezone.utc) - timedelta(days=10)
    stale = DriverCertification(
        person_id=4, course_version="2025-01", quiz_score=8, quiz_total=10,
        signed_name="First Pass", certified_at=old_time,
    )
    db.add(stale)
    db.commit()

    # Recertify on the current course version — this should now be "latest".
    certification.record_certification(db, 4, quiz_score=9, quiz_total=10, signed_name="Second Pass")

    assert certification.is_certified(db, 4) is True
    assert certification.needs_recert(db, 4) is False


def test_multiple_rows_per_person_allowed_history(db):
    _person(db, 5)
    certification.record_certification(db, 5, quiz_score=8, quiz_total=10, signed_name="Attempt 1")
    certification.record_certification(db, 5, quiz_score=10, quiz_total=10, signed_name="Attempt 2")
    rows = db.query(DriverCertification).filter_by(person_id=5).all()
    assert len(rows) == 2


# ── course-content integrity ──────────────────────────────────────────────────

def test_thirteen_modules():
    assert len(certification.COURSE_MODULES) == 13


def test_eighteen_quiz_questions():
    assert len(certification.QUIZ_QUESTIONS) == 18


def test_every_quiz_question_has_exactly_one_correct_option():
    for q in certification.QUIZ_QUESTIONS:
        assert 0 <= q.correct < len(q.options), f"correct index out of range: {q.question['en']!r}"
        # "exactly one correct option" — correct is a single index (not a
        # list), so structurally there's exactly one; also guard against a
        # negative/duplicate-content authoring mistake by checking the
        # correct option text isn't accidentally duplicated among the
        # distractors (would make two options "correct" in effect).
        for lang in certification.LANGS:
            correct_text = q.options[q.correct][lang]
            same_text_count = sum(1 for o in q.options if o[lang] == correct_text)
            assert same_text_count == 1, f"duplicate correct-option text in {lang}: {correct_text!r}"


def test_all_languages_have_equal_module_count():
    for m in certification.COURSE_MODULES:
        langs_present = set(m.title.keys())
        assert langs_present == set(certification.LANGS)


def test_all_languages_have_equal_question_count_and_option_count():
    for q in certification.QUIZ_QUESTIONS:
        assert set(q.question.keys()) == set(certification.LANGS)
        for opt in q.options:
            assert set(opt.keys()) == set(certification.LANGS)


def test_no_empty_translations_in_modules():
    for m in certification.COURSE_MODULES:
        for lang in certification.LANGS:
            assert m.title[lang].strip(), f"{m.key} missing {lang} title"
            if m.intro:
                assert m.intro[lang].strip(), f"{m.key} missing {lang} intro"
        for b in m.blocks:
            for lang in certification.LANGS:
                assert b.text[lang].strip(), f"{m.key} block missing {lang} text"
                if b.lead:
                    assert b.lead[lang].strip(), f"{m.key} block missing {lang} lead"


def test_no_empty_translations_in_quiz():
    for q in certification.QUIZ_QUESTIONS:
        for lang in certification.LANGS:
            assert q.question[lang].strip()
            for opt in q.options:
                assert opt[lang].strip()


def test_course_content_public_is_json_safe_and_matches_counts():
    content = certification.course_content_public()
    assert content["course_version"] == certification.COURSE_VERSION
    assert len(content["modules"]) == 13
    assert len(content["quiz"]) == 18
    for q in content["quiz"]:
        assert "correct" in q
        assert isinstance(q["correct"], int)


# ---------------------------------------------------------------------------
# Amharic translation pass (2026-09-26) — docs/training/glossary-am.md and
# docs/training/translation-notes-am.md. These pin the en/am structural
# parity the frontend language toggle depends on, and guard against a
# future content edit silently reintroducing an untranslated (English-
# mirrored) 'am' string.
# ---------------------------------------------------------------------------

# Strings where am == en is expected and correct (numerals/emergency
# numbers have no Amharic form — "911" stays "911").
_AM_MIRROR_ALLOWLIST = {"911"}


def test_module_and_block_counts_match_between_en_and_am():
    """Every module's block list is the same object for every language —
    this pins that a module never gains/loses a block in one language."""
    for m in certification.COURSE_MODULES:
        assert set(m.title.keys()) >= {"en", "am"}
        if m.intro:
            assert set(m.intro.keys()) >= {"en", "am"}
        for b in m.blocks:
            assert set(b.text.keys()) >= {"en", "am"}
            if b.lead:
                assert set(b.lead.keys()) >= {"en", "am"}
    # en and am modules are the same COURSE_MODULES tuple (one bilingual
    # record per module/block), so count parity is structural — pin the
    # counts explicitly anyway so a future refactor that splits per-language
    # content still gets caught.
    assert len(certification.COURSE_MODULES) == 13


def test_quiz_question_and_option_counts_match_between_en_and_am():
    assert len(certification.QUIZ_QUESTIONS) == 18
    for q in certification.QUIZ_QUESTIONS:
        assert set(q.question.keys()) >= {"en", "am"}
        assert len(q.options) == 4
        for opt in q.options:
            assert set(opt.keys()) >= {"en", "am"}
        # every question's en option list and am option list are the same
        # length by construction (one options tuple per question) — assert
        # it explicitly so a future edit that appends an en-only option
        # (or vice versa) fails loudly.
        en_count = sum(1 for o in q.options if o["en"].strip())
        am_count = sum(1 for o in q.options if o["am"].strip())
        assert en_count == am_count == len(q.options)


def test_quiz_correct_answer_indices_identical_across_languages():
    """The correct index is language-agnostic (one QuizQuestion record
    serves en/am/ar), so this is mostly a structural pin — but it directly
    encodes the requirement that translating options must never reorder
    them relative to `correct`."""
    for q in certification.QUIZ_QUESTIONS:
        assert isinstance(q.correct, int)
        assert 0 <= q.correct < len(q.options)
        # the am translation of the correct option must still be non-empty
        # and must not equal any other am option (would make the correct
        # answer ambiguous in Amharic even though the index is right)
        correct_am = q.options[q.correct]["am"]
        assert correct_am.strip()
        duplicates = [o["am"] for o in q.options if o["am"] == correct_am]
        assert len(duplicates) == 1


def test_amharic_translation_pass_is_complete_no_leftover_english_mirrors():
    """Guards the 2026-09-26 am translation pass: every module title/intro/
    block and every quiz question/option must have an 'am' value that
    differs from 'en', except the allowlisted numerals. A regression here
    means new English content was added without its Amharic counterpart
    (see _tri()/_block()/_opt() in certification.py)."""
    mirrored = []

    for m in certification.COURSE_MODULES:
        if m.title["en"] not in _AM_MIRROR_ALLOWLIST and m.title["am"] == m.title["en"]:
            mirrored.append((m.key, "title", m.title["en"]))
        if m.intro and m.intro["en"] not in _AM_MIRROR_ALLOWLIST and m.intro["am"] == m.intro["en"]:
            mirrored.append((m.key, "intro", m.intro["en"]))
        for i, b in enumerate(m.blocks):
            if b.text["en"] not in _AM_MIRROR_ALLOWLIST and b.text["am"] == b.text["en"]:
                mirrored.append((m.key, f"block[{i}].text", b.text["en"]))
            if b.lead and b.lead["en"] not in _AM_MIRROR_ALLOWLIST and b.lead["am"] == b.lead["en"]:
                mirrored.append((m.key, f"block[{i}].lead", b.lead["en"]))

    for qi, q in enumerate(certification.QUIZ_QUESTIONS):
        if q.question["en"] not in _AM_MIRROR_ALLOWLIST and q.question["am"] == q.question["en"]:
            mirrored.append((f"quiz[{qi}]", "question", q.question["en"]))
        for oi, o in enumerate(q.options):
            if o["en"] not in _AM_MIRROR_ALLOWLIST and o["am"] == o["en"]:
                mirrored.append((f"quiz[{qi}]", f"option[{oi}]", o["en"]))

    assert not mirrored, f"untranslated (English-mirrored) 'am' strings: {mirrored}"


def test_amharic_strings_use_geez_script():
    """Sanity check that 'am' values actually contain Ge'ez-block
    characters (not just Latin app/brand names) — catches an am= kwarg
    accidentally left as an English copy-paste that happens to differ from
    en (e.g. a stray character added)."""
    geez_range = range(0x1200, 0x137F + 1)

    def _has_geez(s: str) -> bool:
        return any(ord(ch) in geez_range for ch in s)

    checked = 0
    for m in certification.COURSE_MODULES:
        assert _has_geez(m.title["am"]), f"{m.key} title has no Ge'ez text: {m.title['am']!r}"
        checked += 1
        for b in m.blocks:
            assert _has_geez(b.text["am"]), f"{m.key} block text has no Ge'ez text: {b.text['am']!r}"
            checked += 1
    assert checked > 0
