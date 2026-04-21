"""
Multi-language call and SMS scripts for driver notifications.

Supported languages:
    en — English (default)
    ar — Arabic
    am — Amharic
"""

# ── Voice call scripts (read aloud via TTS — target ~8 seconds) ──────────────
# Driver name and pickup time are passed as {driver_name} and {pickup_time}.
# Keep each script short. One clear ask per call.

CALL_SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "accept": (
            "Hey {driver_name}, this is Maz dispatch. "
            "Your {pickup_time} trip is waiting on you to accept it. "
            "Please open the app and tap accept."
        ),
        "start": (
            "Hey {driver_name}, Maz dispatch here. "
            "Your {pickup_time} pickup is coming up — please start your trip in the app now."
        ),
        "escalate": (
            "This is Maz dispatch with an urgent update. "
            "A driver hasn't responded and needs immediate attention."
        ),
    },
    "ar": {
        # TODO translate — updated English copy above needs professional Arabic translation.
        # Previous translation preserved as structural placeholder.
        "accept": (
            "مرحباً {driver_name}، هذا إرسال MAZ. "
            "رحلتك في {pickup_time} تنتظر قبولك. "
            "يرجى فتح التطبيق والضغط على قبول."
        ),
        "start": (
            "مرحباً {driver_name}، إرسال MAZ هنا. "
            "موعد الاستلام {pickup_time} يقترب — يرجى بدء رحلتك في التطبيق الآن."
        ),
        "escalate": (
            "هذه رسالة عاجلة من MAZ Services. "
            "لم يستجب أحد السائقين ويحتاج إلى اهتمام فوري."
        ),
    },
    "am": {
        # TODO translate — updated English copy above needs professional Amharic translation.
        # Previous translation preserved as structural placeholder.
        "accept": (
            "ሰላም {driver_name}፣ ይህ MAZ ዲስፓቸር ነው። "
            "የ{pickup_time} ጉዞዎ ለመቀበል እየጠበቀ ነው። "
            "እባክዎ መተግበሪያውን ከፍተው ይቀበሉ።"
        ),
        "start": (
            "ሰላም {driver_name}፣ MAZ ዲስፓቸር ነው። "
            "የ{pickup_time} ጉዞዎ ሊጀምር ቀርቧል — አሁን ይጀምሩ።"
        ),
        "escalate": (
            "ይህ ከMAZ Services አስቸኳይ መልዕክት ነው። "
            "አንድ ሾፌር ምላሽ አልሰጠም እና ወዲያውኑ ትኩረት ያስፈልጋል።"
        ),
    },
}

# ── SMS scripts (~1 line, conversational) ────────────────────────────────────
# {driver_name} and {pickup_time} are substituted at send time.
# Keep the sign-off — drivers need to know who texted them.

SMS_SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "accept": (
            "Hi {driver_name} — your {pickup_time} trip hasn't been accepted yet. "
            "Please accept in the app. — Maz dispatch"
        ),
        "start": (
            "Hi {driver_name} — your {pickup_time} trip is ready to start. "
            "Please tap start in the app. — Maz dispatch"
        ),
    },
    "ar": {
        # TODO translate — updated English copy above needs professional Arabic translation.
        "accept": (
            "مرحباً {driver_name} — رحلتك في {pickup_time} لم تُقبل بعد. "
            "يرجى القبول في التطبيق. — إرسال MAZ"
        ),
        "start": (
            "مرحباً {driver_name} — رحلتك في {pickup_time} جاهزة للبدء. "
            "يرجى الضغط على بدء في التطبيق. — إرسال MAZ"
        ),
    },
    "am": {
        # TODO translate — updated English copy above needs professional Amharic translation.
        "accept": (
            "ሰላም {driver_name} — የ{pickup_time} ጉዞዎ ገና አልተቀበለም። "
            "እባክዎ በመተግበሪያው ይቀበሉ። — MAZ ዲስፓቸር"
        ),
        "start": (
            "ሰላም {driver_name} — የ{pickup_time} ጉዞዎ ለመጀመር ዝግጁ ነው። "
            "እባክዎ ጀምር ይጫኑ። — MAZ ዲስፓቸር"
        ),
    },
}


def get_call_script(language: str | None, script_type: str, **kwargs: str) -> str:
    """Return the call script for the given language and type, with substitutions.

    Args:
        language: "en", "ar", "am", or None (defaults to "en")
        script_type: "accept", "start", or "escalate"
        **kwargs: substitution values (driver_name, pickup_time, etc.)

    Returns:
        The formatted script string, falling back to English if language is unsupported.
    """
    lang = (language or "en").lower()
    lang_scripts = CALL_SCRIPTS.get(lang, CALL_SCRIPTS["en"])
    template = lang_scripts.get(script_type, CALL_SCRIPTS["en"].get(script_type, ""))
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


def get_sms_script(language: str | None, script_type: str, **kwargs: str) -> str:
    """Return the SMS script for the given language and type, with substitutions.

    Args:
        language: "en", "ar", "am", or None (defaults to "en")
        script_type: "accept" or "start"
        **kwargs: substitution values (pickup_time, source, driver_name, etc.)

    Returns:
        The formatted SMS string.
    """
    lang = (language or "en").lower()
    lang_scripts = SMS_SCRIPTS.get(lang, SMS_SCRIPTS["en"])
    template = lang_scripts.get(script_type, SMS_SCRIPTS["en"].get(script_type, ""))
    try:
        return template.format(**kwargs)
    except KeyError:
        return template
