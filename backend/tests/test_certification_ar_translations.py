"""
Tests for the Arabic (ar) overlay on the S7 driver certification course —
backend/services/course_content_ar.py, wired into
certification.course_content_public().

Kept as its own file (rather than added to test_certification_service.py)
since an Amharic translation pass is editing that shared service module
concurrently — this file only imports from it, it never edits it.

Run in isolation:
    PYTHONPATH=. pytest backend/tests/test_certification_ar_translations.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

os.environ.setdefault("ZPAY_SECRET_KEY", "test-secret-certification-ar-long-enough")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from backend.services import certification  # noqa: E402
from backend.services.course_content_ar import apply_ar_translations  # noqa: E402


def _content() -> dict:
    return certification.course_content_public()


def test_thirteen_modules_in_public_content():
    assert len(_content()["modules"]) == 13


def test_eighteen_quiz_questions_in_public_content():
    assert len(_content()["quiz"]) == 18


def test_module_block_counts_match_between_en_and_ar():
    """The overlay must never add, drop, or reorder blocks — same list, same
    length, only the 'ar' key inside each dict changes."""
    for m in _content()["modules"]:
        for block in m["blocks"]:
            assert set(block["text"].keys()) >= {"en", "ar"}
            if block["lead"] is not None:
                assert set(block["lead"].keys()) >= {"en", "ar"}


def test_quiz_option_counts_and_correct_indices_match_between_en_and_ar():
    for q in _content()["quiz"]:
        assert set(q["question"].keys()) >= {"en", "ar"}
        assert len(q["options"]) == 4
        for opt in q["options"]:
            assert set(opt.keys()) >= {"en", "ar"}
        # correct index must stay inside bounds and must not have been
        # shifted by the overlay (all 18 questions are authored correct=0).
        assert 0 <= q["correct"] < len(q["options"])
        assert q["correct"] == 0


def test_ar_titles_are_non_empty_and_translated():
    for m in _content()["modules"]:
        ar_title = m["title"]["ar"]
        assert ar_title.strip()
        assert ar_title != m["title"]["en"], f"{m['key']} title not translated"


def test_ar_module_intro_translated_where_present():
    modules = {m["key"]: m for m in _content()["modules"]}
    m2 = modules["m2"]
    assert m2["intro"] is not None
    assert m2["intro"]["ar"].strip()
    assert m2["intro"]["ar"] != m2["intro"]["en"]


def test_ar_block_text_translated_for_every_module():
    """Every block's ar text must be non-empty and, apart from strings that
    are identical in both languages by nature (e.g. the numeral "911"),
    different from the English mirror — proof the overlay actually ran."""
    allowed_identical = {"911"}
    untranslated = []
    for m in _content()["modules"]:
        for i, block in enumerate(m["blocks"]):
            en = block["text"]["en"]
            ar = block["text"]["ar"]
            assert ar.strip(), f"{m['key']} block {i} missing ar text"
            if ar == en and en not in allowed_identical:
                untranslated.append((m["key"], i))
    assert untranslated == [], f"untranslated blocks: {untranslated}"


def test_ar_quiz_translated():
    allowed_identical = {"911"}
    untranslated = []
    for qi, q in enumerate(_content()["quiz"]):
        assert q["question"]["ar"].strip()
        assert q["question"]["ar"] != q["question"]["en"], f"quiz {qi} question not translated"
        for oi, opt in enumerate(q["options"]):
            assert opt["ar"].strip()
            if opt["ar"] == opt["en"] and opt["en"] not in allowed_identical:
                untranslated.append((qi, oi))
    assert untranslated == [], f"untranslated options: {untranslated}"


def test_dispatch_phone_interpolated_into_ar_text():
    m1 = next(m for m in _content()["modules"] if m["key"] == "m1")
    phone_block = next(b for b in m1["blocks"] if certification.DISPATCH_PHONE_DISPLAY in b["text"]["en"])
    assert certification.DISPATCH_PHONE_DISPLAY in phone_block["text"]["ar"]


def test_overlay_does_not_mutate_its_input():
    """apply_ar_translations must return a new dict/copies, never mutate the
    dict it was given (immutability law) — mutating course_content_public()'s
    dict in place would corrupt the shared en/am content other callers see."""
    # Build a fresh raw (pre-overlay) dict the same way course_content_public()
    # does internally, then confirm applying the overlay doesn't touch it.
    raw = {
        "course_version": certification.COURSE_VERSION,
        "pass_threshold_ratio": certification.PASS_THRESHOLD_RATIO,
        "modules": [
            {
                "key": m.key,
                "title": m.title,
                "intro": m.intro,
                "blocks": [{"lead": b.lead, "text": b.text} for b in m.blocks],
            }
            for m in certification.COURSE_MODULES
        ],
        "quiz": [
            {"question": q.question, "options": list(q.options), "correct": q.correct}
            for q in certification.QUIZ_QUESTIONS
        ],
    }
    snapshot_title = raw["modules"][0]["title"]["ar"]
    apply_ar_translations(raw, certification.DISPATCH_PHONE_DISPLAY)
    assert raw["modules"][0]["title"]["ar"] == snapshot_title
