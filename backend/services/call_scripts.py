"""
Multi-language call and SMS scripts for driver notifications.

Supported languages:
    en — English (default)
    ar — Arabic
    am — Amharic

Hardening (2026-04-22):
  - Voice scripts include the trip_ref so drivers can find the trip in the
    FA app. The clause is rendered only when trip_ref is provided (callers
    that don't pass it still produce a clean sentence).
  - Driver name is sanitized (apostrophes preserved, control chars stripped)
    so M'hand and other names don't break TwiML or invite injection.
  - Module-load TODO scan: if AR/AM still have placeholder translations,
    a one-shot warning is emitted so the issue is visible in Railway logs.
"""

import logging
import re
from string import Template

logger = logging.getLogger("zpay.call_scripts")


# ── Voice call scripts (read aloud via TTS — target ~8 seconds) ──────────────
# Driver name and pickup time are passed as $driver_name and $pickup_time.
# If $trip_ref is provided, a short reference clause is appended; if not,
# the clause is dropped without leaving a placeholder.
# Keep each script short. One clear ask per call.

CALL_SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "accept": (
            "Hey ${driver_name}, this is Maz dispatch. "
            "Your ${pickup_time} trip is waiting on you to accept it. "
            "Please open the app and tap accept."
        ),
        "start": (
            "Hey ${driver_name}, Maz dispatch here. "
            "Your ${pickup_time} pickup is coming up — please start your trip in the app now."
        ),
        "escalate": (
            "This is Maz dispatch with an urgent update. "
            "A driver hasn't responded and needs immediate attention."
        ),
    },
    "ar": {
        # NOTE: AR copy mirrors the English structure. Update with a
        # professional translation when available.
        "accept": (
            "مرحباً ${driver_name}، هذا إرسال MAZ. "
            "رحلتك في ${pickup_time} تنتظر قبولك. "
            "يرجى فتح التطبيق والضغط على قبول."
        ),
        "start": (
            "مرحباً ${driver_name}، إرسال MAZ هنا. "
            "موعد الاستلام ${pickup_time} يقترب — يرجى بدء رحلتك في التطبيق الآن."
        ),
        "escalate": (
            "هذه رسالة عاجلة من MAZ Services. "
            "لم يستجب أحد السائقين ويحتاج إلى اهتمام فوري."
        ),
    },
    "am": {
        # NOTE: AM copy mirrors the English structure. Update with a
        # professional translation when available.
        "accept": (
            "ሰላም ${driver_name}፣ ይህ MAZ ዲስፓቸር ነው። "
            "የ${pickup_time} ጉዞዎ ለመቀበል እየጠበቀ ነው። "
            "እባክዎ መተግበሪያውን ከፍተው ይቀበሉ።"
        ),
        "start": (
            "ሰላም ${driver_name}፣ MAZ ዲስፓቸር ነው። "
            "የ${pickup_time} ጉዞዎ ሊጀምር ቀርቧል — አሁን ይጀምሩ።"
        ),
        "escalate": (
            "ይህ ከMAZ Services አስቸኳይ መልዕክት ነው። "
            "አንድ ሾፌር ምላሽ አልሰጠም እና ወዲያውኑ ትኩረት ያስፈልጋል።"
        ),
    },
}

# Optional trip reference clause — appended only when caller passes trip_ref.
TRIP_REF_CLAUSES: dict[str, str] = {
    "en": " Your trip reference is ${trip_ref}.",
    "ar": " رقم الرحلة المرجعي هو ${trip_ref}.",
    "am": " የጉዞ ማመሳከሪያ ${trip_ref} ነው።",
}

# ── SMS scripts (~1 line, conversational) ────────────────────────────────────
# $driver_name, $pickup_time, optional $trip_ref are substituted at send time.
# Keep the sign-off — drivers need to know who texted them.

SMS_SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "accept": (
            "Hi ${driver_name} — your ${pickup_time} trip hasn't been accepted yet. "
            "Please accept in the app. — Maz dispatch"
        ),
        "start": (
            "Hi ${driver_name} — your ${pickup_time} trip is ready to start. "
            "Please tap start in the app. — Maz dispatch"
        ),
    },
    "ar": {
        "accept": (
            "مرحباً ${driver_name} — رحلتك في ${pickup_time} لم تُقبل بعد. "
            "يرجى القبول في التطبيق. — إرسال MAZ"
        ),
        "start": (
            "مرحباً ${driver_name} — رحلتك في ${pickup_time} جاهزة للبدء. "
            "يرجى الضغط على بدء في التطبيق. — إرسال MAZ"
        ),
    },
    "am": {
        "accept": (
            "ሰላም ${driver_name} — የ${pickup_time} ጉዞዎ ገና አልተቀበለም። "
            "እባክዎ በመተግበሪያው ይቀበሉ። — MAZ ዲስፓቸር"
        ),
        "start": (
            "ሰላም ${driver_name} — የ${pickup_time} ጉዞዎ ለመጀመር ዝግጁ ነው። "
            "እባክዎ ጀምር ይጫኑ። — MAZ ዲስፓቸር"
        ),
    },
}


# ── One-shot translation freshness check ─────────────────────────────────────
# If the module is shipped with the literal English copy in a non-English
# slot (regression detection), emit a single warning at module load.
def _check_translation_freshness() -> None:
    en_accept = CALL_SCRIPTS["en"]["accept"]
    en_start = CALL_SCRIPTS["en"]["start"]
    suspicious_langs: list[str] = []
    for lang in ("ar", "am"):
        scripts = CALL_SCRIPTS.get(lang, {})
        if scripts.get("accept", "") == en_accept or scripts.get("start", "") == en_start:
            suspicious_langs.append(lang)
    if suspicious_langs:
        logger.warning(
            "[call_scripts] Translations missing/regressed for: %s — "
            "drivers in those languages will hear English wording.",
            ",".join(suspicious_langs),
        )


_check_translation_freshness()


# ── Sanitization + safe rendering ────────────────────────────────────────────

# Strip control characters and TwiML/HTML angle brackets from interpolated
# values. Apostrophes are preserved (M'hand, O'Brien) — TwiML tolerates them.
_DISALLOWED = re.compile(r"[\x00-\x1f<>]")


def _sanitize_value(value: object) -> str:
    if value is None:
        return ""
    s = str(value)
    return _DISALLOWED.sub("", s).strip()


def _safe_render(template: str, **kwargs: object) -> str:
    """
    Render a template using string.Template safe_substitute, sanitizing
    interpolated values and stripping unfilled $placeholders cleanly.
    """
    cleaned = {k: _sanitize_value(v) for k, v in kwargs.items()}
    rendered = Template(template).safe_substitute(**cleaned)
    # Drop any leftover ${...} placeholders + collapse the surrounding
    # whitespace artifacts so we never read "$trip_ref" out loud.
    rendered = re.sub(r"\$\{[a-zA-Z_]\w*\}", "", rendered)
    rendered = re.sub(r"\$[a-zA-Z_]\w*", "", rendered)
    rendered = re.sub(r"\s{2,}", " ", rendered).strip()
    return rendered


def get_call_script(language: str | None, script_type: str, **kwargs: object) -> str:
    """Return the call script for the given language and type, with substitutions.

    Args:
        language: "en", "ar", "am", or None (defaults to "en")
        script_type: "accept", "start", or "escalate"
        **kwargs: substitution values. Recognized: driver_name, pickup_time,
                  trip_ref (optional — appended as a sentence if provided).

    Returns:
        The formatted script string, falling back to English if language is
        unsupported. Single-token names and names with apostrophes are safe;
        TwiML control characters are stripped.
    """
    lang = (language or "en").lower()
    if lang not in CALL_SCRIPTS:
        lang = "en"
    template = CALL_SCRIPTS[lang].get(script_type) or CALL_SCRIPTS["en"].get(script_type, "")

    # Append the trip-ref clause when caller actually provided a non-empty value.
    trip_ref = kwargs.get("trip_ref")
    if trip_ref:
        clause_template = TRIP_REF_CLAUSES.get(lang, TRIP_REF_CLAUSES["en"])
        template = template + clause_template

    return _safe_render(template, **kwargs)


def get_sms_script(language: str | None, script_type: str, **kwargs: object) -> str:
    """Return the SMS script for the given language and type, with substitutions.

    Args:
        language: "en", "ar", "am", or None (defaults to "en")
        script_type: "accept" or "start"
        **kwargs: substitution values (pickup_time, source, driver_name, trip_ref, etc.)

    Returns:
        The formatted SMS string. Unfilled placeholders are stripped.
    """
    lang = (language or "en").lower()
    if lang not in SMS_SCRIPTS:
        lang = "en"
    template = SMS_SCRIPTS[lang].get(script_type) or SMS_SCRIPTS["en"].get(script_type, "")
    return _safe_render(template, **kwargs)
