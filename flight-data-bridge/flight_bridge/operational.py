from __future__ import annotations

import copy
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

FREE_REQUESTS_INITIAL = 1000
FREE_TIER_WARNING_THRESHOLD = 150
FREE_TIER_HARD_STOP_BUFFER = 50
BASE_SEARCH_REQUESTS_PER_CYCLE = 12
REVALIDATION_REQUEST_RESERVE = 2

_SECRET_FIELD_RE = re.compile(
    r"(?i)(authorization|x[-_]?api[-_]?key|api[-_]?key|access[-_]?token|refresh[-_]?token|session[-_]?token|cookie)"
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_SENSITIVE_URL_KEYS = {
    "token", "access_token", "refresh_token", "session", "session_token",
    "auth", "authorization", "api_key", "apikey", "key", "state",
    "code", "sig", "signature", "jwt",
}
_QUALITY_RANK = {"C": 1, "B": 2, "A": 3}


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def quota_gate(
    successful_used: int,
    *,
    free_initial: int = FREE_REQUESTS_INITIAL,
    warning_threshold: int = FREE_TIER_WARNING_THRESHOLD,
    hard_stop_buffer: int = FREE_TIER_HARD_STOP_BUFFER,
    base_search_requests: int = BASE_SEARCH_REQUESTS_PER_CYCLE,
    revalidation_reserve: int = REVALIDATION_REQUEST_RESERVE,
    extra_requests: int = 0,
    paid_usage_authorized: bool = False,
) -> dict:
    successful_used = max(0, int(successful_used))
    remaining = max(0, int(free_initial) - successful_used)
    required_before_start = int(base_search_requests) + int(revalidation_reserve) + int(extra_requests) + int(hard_stop_buffer)
    warning = remaining <= int(warning_threshold)
    allowed = bool(paid_usage_authorized or remaining >= required_before_start)
    return {
        "IGNAV_FREE_REQUESTS_INITIAL": int(free_initial),
        "IGNAV_SUCCESSFUL_REQUESTS_ESTIMATED": successful_used,
        "IGNAV_FREE_REQUESTS_ESTIMATED_REMAINING": remaining,
        "FREE_TIER_WARNING_THRESHOLD": int(warning_threshold),
        "FREE_TIER_HARD_STOP_BUFFER": int(hard_stop_buffer),
        "NEXT_CYCLE_BASE_REQUESTS": int(base_search_requests),
        "REVALIDATION_REQUEST_RESERVE": int(revalidation_reserve),
        "EXTRA_REQUEST_RESERVE": int(extra_requests),
        "MINIMUM_REMAINING_REQUIRED_BEFORE_START": required_before_start,
        "FREE_TIER_WARNING": warning,
        "IGNAV_PAID_USAGE_AUTHORIZED": bool(paid_usage_authorized),
        "QUOTA_GATE_ALLOWED": allowed,
        "QUOTA_GATE_STATUS": "PAID_AUTHORIZED" if paid_usage_authorized else ("WARNING" if allowed and warning else ("OK" if allowed else "QUOTA_GATE_BLOCKED")),
    }


def booking_url_is_sensitive(url: str | None) -> bool:
    if not url:
        return False
    try:
        parts = urlsplit(url)
    except Exception:
        return True
    if parts.username or parts.password:
        return True
    for chunk in parts.query.split("&") if parts.query else []:
        key = chunk.split("=", 1)[0].lower()
        if key in _SENSITIVE_URL_KEYS or any(mark in key for mark in ("token", "secret", "session", "auth", "signature")):
            return True
    return bool(_JWT_RE.search(url))


def _sanitize_node(value):
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if _SECRET_FIELD_RE.search(str(key)):
                continue
            out[key] = _sanitize_node(child)
        return out
    if isinstance(value, list):
        return [_sanitize_node(x) for x in value]
    return value


def sanitize_document(doc: dict, *, actual_secret: str | None = None) -> dict:
    clean = _sanitize_node(copy.deepcopy(doc))
    for bucket in ("VALID_OFFERS", "REJECTED_OFFERS", "NON_VALIDATABLE_OFFERS", "ALERT_CANDIDATES"):
        for offer in clean.get(bucket, []) or []:
            url = offer.get("booking_url")
            if booking_url_is_sensitive(url):
                try:
                    p = urlsplit(url)
                    host = p.hostname
                    path = p.path or "/"
                except Exception:
                    host = None
                    path = None
                offer["booking_url"] = None
                derived = offer.setdefault("derived", {})
                derived["BOOKING_URL_REDACTED"] = True
                derived["BOOKING_URL_HOST"] = host
                derived["BOOKING_URL_PATH"] = path
    serialized = __import__("json").dumps(clean, ensure_ascii=False, sort_keys=True)
    if actual_secret and actual_secret in serialized:
        raise RuntimeError("SECRET_SCAN_FAILED")
    if _SECRET_FIELD_RE.search(serialized) or _JWT_RE.search(serialized):
        raise RuntimeError("SECRET_SCAN_FAILED")
    return clean


def alert_dedupe_decision(previous: dict | None, current: dict) -> dict:
    if not previous:
        return {"SHOULD_ALERT": True, "REASON": "NEW_ITINERARY"}

    previous_id = previous.get("offer_id") or previous.get("itinerary_fingerprint")
    current_id = current.get("offer_id") or current.get("itinerary_fingerprint")
    if previous_id and current_id and previous_id != current_id:
        prev_conn = (previous.get("derived") or {}).get("MAX_CONNECTIONS")
        cur_conn = (current.get("derived") or {}).get("MAX_CONNECTIONS")
        same_route = (
            ((previous.get("outbound") or {}).get("origin") == (current.get("outbound") or {}).get("origin"))
            and ((previous.get("inbound") or {}).get("destination") == (current.get("inbound") or {}).get("destination"))
        )
        if same_route and cur_conn == 0 and prev_conn not in (None, 0):
            return {"SHOULD_ALERT": True, "REASON": "DIRECT_EQUIVALENT_APPEARED"}
        return {"SHOULD_ALERT": True, "REASON": "NEW_ITINERARY"}

    prev_price = _decimal(previous.get("price_brl"))
    cur_price = _decimal(current.get("price_brl"))
    if prev_price is not None and cur_price is not None and prev_price - cur_price >= Decimal("100"):
        return {"SHOULD_ALERT": True, "REASON": "PRICE_DROP_100_BRL"}

    prev_q = (previous.get("derived") or {}).get("QUALITY_CLASS")
    cur_q = (current.get("derived") or {}).get("QUALITY_CLASS")
    if _QUALITY_RANK.get(cur_q, 0) > _QUALITY_RANK.get(prev_q, 0):
        return {"SHOULD_ALERT": True, "REASON": "QUALITY_IMPROVED"}

    def bag_rank(v):
        if v in (None, "UNKNOWN", "NÃO CONFIRMADA", "NAO CONFIRMADA"):
            return 0
        if v is False or v == 0:
            return 1
        return 2

    if bag_rank(current.get("checked_bag")) > bag_rank(previous.get("checked_bag")):
        return {"SHOULD_ALERT": True, "REASON": "BAGGAGE_IMPROVED"}

    prev_condition = (previous.get("derived") or {}).get("CONDITION_SIGNATURE")
    cur_condition = (current.get("derived") or {}).get("CONDITION_SIGNATURE")
    if prev_condition and cur_condition and prev_condition != cur_condition:
        return {"SHOULD_ALERT": True, "REASON": "CONDITION_IMPROVED"}

    return {"SHOULD_ALERT": False, "REASON": "DUPLICATE_NO_MATERIAL_IMPROVEMENT"}
