"""
Multi-language call and SMS scripts for driver notifications.

Supported languages:
    en — English (default)
    ar — Arabic
    am — Amharic
"""

CALL_SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "accept": (
            "Hello, this is a message from MAZ Services. You have a ride that needs to be accepted "
            "in your app. Please open your driver app and accept your ride now. Thank you."
        ),
        "start": (
            "Hello, this is MAZ Services. Your pickup time is coming up soon. "
            "Please start your ride in the driver app now. Thank you."
        ),
        "escalate": (
            "This is an urgent message from MAZ Services. "
            "A driver has not responded and needs immediate attention."
        ),
    },
    "ar": {
        "accept": (
            "مرحباً، هذه رسالة من MAZ Services. لديك رحلة تحتاج إلى قبولها في تطبيقك. "
            "يرجى فتح تطبيق السائق وقبول رحلتك الآن. شكراً."
        ),
        "start": (
            "مرحباً، هذه MAZ Services. موعد الاستلام يقترب. "
            "يرجى بدء رحلتك في تطبيق السائق الآن. شكراً."
        ),
        "escalate": (
            "هذه رسالة عاجلة من MAZ Services. "
            "لم يستجب أحد السائقين ويحتاج إلى اهتمام فوري."
        ),
    },
    "am": {
        "accept": (
            "ሰላም፣ ይህ ከMAZ Services የተላከ መልዕክት ነው። በመተግበሪያዎ ውስጥ መቀበል ያለብዎ ጉዞ አለዎት። "
            "እባክዎ የሾፌር መተግበሪያዎን ከፍቶ አሁን ጉዞዎን ይቀበሉ። አመሰግናለሁ።"
        ),
        "start": (
            "ሰላም፣ ይህ MAZ Services ነው። የማንሳት ጊዜዎ እየቀረበ ነው። "
            "እባክዎ አሁን በሾፌር መተግበሪያዎ ጉዞዎን ይጀምሩ። አመሰግናለሁ።"
        ),
        "escalate": (
            "ይህ ከMAZ Services አስቸኳይ መልዕክት ነው። "
            "አንድ ሾፌር ምላሽ አልሰጠም እና ወዲያውኑ ትኩረት ያስፈልጋል።"
        ),
    },
}

SMS_SCRIPTS: dict[str, dict[str, str]] = {
    "en": {
        "accept": (
            "MAZ Services: You have an unaccepted trip at {pickup_time}. "
            "Please accept it in your driver app now."
        ),
        "start": (
            "MAZ Services: Your {source} trip starts at {pickup_time} — time to head out!"
        ),
    },
    "ar": {
        "accept": (
            "MAZ Services: لديك رحلة غير مقبولة في {pickup_time}. "
            "يرجى قبولها في تطبيق السائق الآن."
        ),
        "start": (
            "MAZ Services: رحلتك تبدأ في {pickup_time} — حان وقت الانطلاق!"
        ),
    },
    "am": {
        "accept": (
            "MAZ Services: በ{pickup_time} ያልተቀበሉት ጉዞ አለዎት። "
            "እባክዎ አሁን በሾፌር መተግበሪያዎ ይቀበሉ።"
        ),
        "start": (
            "MAZ Services: ጉዞዎ በ{pickup_time} ይጀምራል — ለመነሳት ጊዜው ደርሷል!"
        ),
    },
}


def get_call_script(language: str | None, script_type: str) -> str:
    """Return the call script for the given language and type.

    Args:
        language: "en", "ar", "am", or None (defaults to "en")
        script_type: "accept", "start", or "escalate"

    Returns:
        The script string, falling back to English if language is unsupported.
    """
    lang = (language or "en").lower()
    lang_scripts = CALL_SCRIPTS.get(lang, CALL_SCRIPTS["en"])
    return lang_scripts.get(script_type, CALL_SCRIPTS["en"].get(script_type, ""))


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
