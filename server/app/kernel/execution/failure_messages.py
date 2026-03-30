from __future__ import annotations

import re
from typing import Dict

_TYPE_MISMATCH_RE = re.compile(
    r"Input validation failed:\s*Parameter '([^']+)' must be ([^,]+), got (.+)$",
    re.IGNORECASE,
)
_MISSING_PARAM_RE = re.compile(
    r"Input validation failed:\s*Missing required parameter:\s*([A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_DEPENDENCY_FAILED_RE = re.compile(
    r"Dependency '([^']+)' failed",
    re.IGNORECASE,
)
_SERVICE_REJECTED_RE = re.compile(
    r"rejected the request(?:\s*\([^)]*\))?(?::\s*(.+))?$",
    re.IGNORECASE,
)

_PARAM_LABELS = {
    "days": "the number of days",
    "lat": "the location",
    "lon": "the location",
    "units": "the units setting",
    "query": "the request",
    "message": "the message",
    "contact": "the contact details",
    "app_name": "the app name",
    "url": "the link",
}

_PARAM_LABELS_LOCALIZED = {
    "hi": {
        "days": "दिनों की संख्या",
        "lat": "जगह की जानकारी",
        "lon": "जगह की जानकारी",
        "units": "यूनिट सेटिंग",
        "query": "अनुरोध",
        "message": "संदेश",
        "contact": "संपर्क जानकारी",
        "app_name": "ऐप का नाम",
        "url": "लिंक",
    },
    "ne": {
        "days": "दिनको संख्या",
        "lat": "ठाउँको जानकारी",
        "lon": "ठाउँको जानकारी",
        "units": "एकाइ सेटिङ",
        "query": "अनुरोध",
        "message": "सन्देश",
        "contact": "सम्पर्क विवरण",
        "app_name": "एपको नाम",
        "url": "लिङ्क",
    },
}

_TOOL_ACTIONS = {
    "weather_forecast": "get the forecast",
    "weather_current": "get the weather",
    "web_search": "search the web",
    "web_research": "research that topic",
    "summarize": "summarize that content",
    "mic_mute": "mute the microphone",
    "mic_unmute": "unmute the microphone",
}

_TOOL_SERVICES = {
    "weather_forecast": "weather service",
    "weather_current": "weather service",
    "web_search": "web service",
    "web_research": "research service",
}


def build_failure_detail(
    task_id: str,
    tool_name: str,
    raw_error: str | None,
    locale: str = "en",
) -> Dict[str, str]:
    normalized = normalize_failure(tool_name, raw_error, locale=locale)
    return {
        "taskId": task_id,
        "tool": tool_name,
        "rawError": normalized["raw_error"],
        "userMessage": normalized["user_message"],
    }


def normalize_failure(
    tool_name: str,
    raw_error: str | None,
    locale: str = "en",
) -> Dict[str, str]:
    raw = str(raw_error or "").strip() or "Unknown error"
    message = _friendly_message(tool_name, raw, locale=locale)
    return {
        "raw_error": raw,
        "user_message": message,
    }


def _friendly_message(tool_name: str, raw_error: str, locale: str = "en") -> str:
    raw_lower = raw_error.lower()

    type_match = _TYPE_MISMATCH_RE.search(raw_error)
    if type_match:
        param_name = type_match.group(1)
        return _type_mismatch_message(tool_name, param_name, locale=locale)

    missing_match = _MISSING_PARAM_RE.search(raw_error)
    if missing_match:
        param_name = missing_match.group(1)
        return _missing_param_message(tool_name, param_name, locale=locale)

    if _DEPENDENCY_FAILED_RE.search(raw_error):
        return _message_for_locale(
            locale,
            en="I couldn't finish that request because an earlier step failed.",
            hi="मैं वह काम पूरा नहीं कर सका क्योंकि पहले वाला हिस्सा सफल नहीं हुआ।",
            ne="म त्यो काम पूरा गर्न सकिनँ किनकि पहिलेको चरण सफल भएन।",
        )

    if raw_lower.startswith("cannot resolve bindings:"):
        return _message_for_locale(
            locale,
            en="I couldn't finish that request because some needed information was not ready yet.",
            hi="मैं वह काम पूरा नहीं कर सका क्योंकि ज़रूरी जानकारी अभी तैयार नहीं थी।",
            ne="म त्यो काम पूरा गर्न सकिनँ किनकि चाहिएको जानकारी तयार थिएन।",
        )

    if "not found in registry" in raw_lower or "not implemented" in raw_lower:
        return _message_for_locale(
            locale,
            en="I couldn't run that action because it is not available right now.",
            hi="मैं वह काम नहीं कर सका क्योंकि वह अभी उपलब्ध नहीं है।",
            ne="म त्यो काम गर्न सकिनँ किनकि त्यो अहिले उपलब्ध छैन।",
        )

    if "timed out" in raw_lower:
        return _message_for_locale(
            locale,
            en="I couldn't finish that in time.",
            hi="मैं वह काम समय पर पूरा नहीं कर सका।",
            ne="म त्यो काम समयमै पूरा गर्न सकिनँ।",
        )

    if "rejected the request" in raw_lower or "http error 400" in raw_lower or "bad request" in raw_lower:
        return _service_rejection_message(tool_name, raw_error, locale=locale)

    if "user denied approval" in raw_lower or "approval wasn't granted" in raw_lower:
        return _message_for_locale(
            locale,
            en="I didn't continue because approval was not granted.",
            hi="मैं आगे नहीं बढ़ा क्योंकि अनुमति नहीं मिली।",
            ne="अनुमति नआएकाले म अगाडि बढिनँ।",
        )

    if "approval requested but no approval handler is configured" in raw_lower:
        return _message_for_locale(
            locale,
            en="I couldn't continue because approval could not be requested properly.",
            hi="मैं आगे नहीं बढ़ सका क्योंकि अनुमति सही तरह से नहीं मांगी जा सकी।",
            ne="अनुमति सही तरिकाले माग्न नसकिएकाले म अगाडि बढ्न सकिनँ।",
        )

    if raw_lower.startswith("input validation failed:"):
        return _message_for_locale(
            locale,
            en="I couldn't finish that request because part of it was sent in the wrong format.",
            hi="मैं वह काम पूरा नहीं कर सका क्योंकि उसका एक हिस्सा गलत फ़ॉर्मेट में भेजा गया था।",
            ne="म त्यो काम पूरा गर्न सकिनँ किनकि त्यसको एउटा भाग गलत ढाँचामा पठाइएको थियो।",
        )

    if raw_lower.startswith("latitude and longitude must"):
        return _type_mismatch_message(tool_name, "lat", locale=locale)

    if raw_lower.startswith("units must be"):
        return _type_mismatch_message(tool_name, "units", locale=locale)

    return _message_for_locale(
        locale,
        en="I couldn't finish that request because one step failed unexpectedly.",
        hi="मैं वह काम पूरा नहीं कर सका क्योंकि बीच का एक हिस्सा अचानक विफल हो गया।",
        ne="म त्यो काम पूरा गर्न सकिनँ किनकि बीचको एउटा चरण अचानक असफल भयो।",
    )


def _type_mismatch_message(tool_name: str, param_name: str, locale: str = "en") -> str:
    param_label = _param_label(param_name, locale=locale)
    action = _action_phrase(tool_name)
    if locale == "hi":
        return f"मैं वह काम पूरा नहीं कर सका क्योंकि {param_label} गलत फ़ॉर्मेट में भेजा गया था।"
    if locale == "ne":
        return f"म त्यो काम पूरा गर्न सकिनँ किनकि {param_label} गलत ढाँचामा पठाइएको थियो।"
    return f"I couldn't {action} because {param_label} was sent in the wrong format."


def _missing_param_message(tool_name: str, param_name: str, locale: str = "en") -> str:
    param_label = _param_label(param_name, locale=locale)
    action = _action_phrase(tool_name)
    if locale == "hi":
        return f"मैं वह काम पूरा नहीं कर सका क्योंकि {param_label} नहीं मिला।"
    if locale == "ne":
        return f"म त्यो काम पूरा गर्न सकिनँ किनकि {param_label} भेटिएन।"
    return f"I couldn't {action} because {param_label} was missing."


def _param_label(param_name: str, locale: str = "en") -> str:
    localized = _PARAM_LABELS_LOCALIZED.get(locale, {})
    label = localized.get(param_name) or _PARAM_LABELS.get(param_name)
    if label:
        return label
    return param_name.replace("_", " ")


def _action_phrase(tool_name: str) -> str:
    return _TOOL_ACTIONS.get(tool_name, "finish that request")


def _service_label(tool_name: str) -> str:
    return _TOOL_SERVICES.get(tool_name, "service")


def _service_rejection_reason(raw_error: str) -> str | None:
    match = _SERVICE_REJECTED_RE.search(raw_error)
    if match:
        reason = (match.group(1) or "").strip().rstrip(".")
        if reason:
            return reason
        return None

    if raw_error.lower().startswith("http error 400"):
        return None

    return None


def _service_rejection_message(tool_name: str, raw_error: str, locale: str = "en") -> str:
    action = _action_phrase(tool_name)
    service = _service_label(tool_name)
    reason = _service_rejection_reason(raw_error)

    if locale == "hi":
        if reason:
            return f"मैं {action} नहीं कर सका क्योंकि {service} ने अनुरोध अस्वीकार कर दिया: {reason}।"
        return f"मैं {action} नहीं कर सका क्योंकि {service} ने अनुरोध अस्वीकार कर दिया।"

    if locale == "ne":
        if reason:
            return f"म {action} गर्न सकिनँ किनकि {service} ले अनुरोध अस्वीकार गर्‍यो: {reason}।"
        return f"म {action} गर्न सकिनँ किनकि {service} ले अनुरोध अस्वीकार गर्‍यो।"

    if reason:
        return f"I couldn't {action} because the {service} rejected the request: {reason}."
    return f"I couldn't {action} because the {service} rejected the request."


def _message_for_locale(locale: str, *, en: str, hi: str, ne: str) -> str:
    if locale == "hi":
        return hi
    if locale == "ne":
        return ne
    return en
