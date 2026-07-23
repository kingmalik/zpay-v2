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

def test_six_modules():
    assert len(certification.COURSE_MODULES) == 6


def test_ten_quiz_questions():
    assert len(certification.QUIZ_QUESTIONS) == 10


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
    assert len(content["modules"]) == 6
    assert len(content["quiz"]) == 10
    for q in content["quiz"]:
        assert "correct" in q
        assert isinstance(q["correct"], int)
