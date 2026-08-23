from __future__ import annotations

from collections import Counter
from typing import Any

OPENAPI_FIELD_STATUS = {
    "ignav_id": "DOCUMENTED",
    "price.amount": "DOCUMENTED",
    "price.currency": "DOCUMENTED",
    "price.status": "DOCUMENTED",
    "cabin_class": "DOCUMENTED",
    "requires_self_transfer": "DOCUMENTED",
    "legs": "DOCUMENTED",
    "segments": "DOCUMENTED",
    "marketing_carrier_code": "DOCUMENTED",
    "marketing_carrier_name": "UNDOCUMENTED",
    "operating_carrier_code": "UNDOCUMENTED",
    "operating_carrier_name": "DOCUMENTED",
    "flight_number": "DOCUMENTED",
    "departure_airport": "DOCUMENTED",
    "arrival_airport": "DOCUMENTED",
    "departure_time_local": "DOCUMENTED",
    "arrival_time_local": "DOCUMENTED",
    "departure_time_utc": "DOCUMENTED",
    "arrival_time_utc": "DOCUMENTED",
    "duration_minutes": "DOCUMENTED",
    "aircraft": "DOCUMENTED",
    "bags": "DOCUMENTED_OPTIONAL",
}

SEGMENT_FIELDS = (
    "marketing_carrier_code", "marketing_carrier_name",
    "operating_carrier_code", "operating_carrier_name",
    "flight_number", "departure_airport", "arrival_airport",
    "departure_time_local", "arrival_time_local",
    "departure_time_utc", "arrival_time_utc", "duration_minutes", "aircraft",
)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _new_stat(field: str) -> dict:
    return {
        "FIELD": field,
        "OPENAPI_EXPECTED": OPENAPI_FIELD_STATUS[field],
        "SAMPLES": 0,
        "PRESENT_COUNT": 0,
        "NULL_COUNT": 0,
        "TYPES": {},
        "VALUES": [],
    }


def _record(stats: dict, field: str, container: dict, key: str, *, capture_values: bool = False):
    row = stats.setdefault(field, _new_stat(field))
    row["SAMPLES"] += 1
    if key not in container:
        return
    row["PRESENT_COUNT"] += 1
    value = container.get(key)
    if value is None:
        row["NULL_COUNT"] += 1
    t = _type_name(value)
    row["TYPES"][t] = row["TYPES"].get(t, 0) + 1
    if capture_values and value not in (None, ""):
        text = str(value)[:120]
        if text not in row["VALUES"] and len(row["VALUES"]) < 50:
            row["VALUES"].append(text)


def observe_search_response(data: dict) -> dict:
    stats: dict[str, dict] = {}
    itineraries = data.get("itineraries") if isinstance(data, dict) else None
    if not isinstance(itineraries, list):
        itineraries = []
    for it in itineraries:
        if not isinstance(it, dict):
            continue
        _record(stats, "ignav_id", it, "ignav_id")
        _record(stats, "cabin_class", it, "cabin_class")
        _record(stats, "requires_self_transfer", it, "requires_self_transfer")
        _record(stats, "legs", it, "legs")
        _record(stats, "bags", it, "bags")
        price = it.get("price") if isinstance(it.get("price"), dict) else {}
        _record(stats, "price.amount", price, "amount")
        _record(stats, "price.currency", price, "currency")
        _record(stats, "price.status", price, "status", capture_values=True)
        legs = it.get("legs") if isinstance(it.get("legs"), list) else []
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            segments = leg.get("segments") if isinstance(leg.get("segments"), list) else []
            # segments is a structural field, sampled at leg level.
            row = stats.setdefault("segments", _new_stat("segments"))
            row["SAMPLES"] += 1
            if "segments" in leg:
                row["PRESENT_COUNT"] += 1
                row["TYPES"][_type_name(leg.get("segments"))] = row["TYPES"].get(_type_name(leg.get("segments")), 0) + 1
                if leg.get("segments") is None:
                    row["NULL_COUNT"] += 1
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                for field in SEGMENT_FIELDS:
                    _record(
                        stats,
                        field,
                        seg,
                        field,
                        capture_values=field in {
                            "marketing_carrier_code", "marketing_carrier_name",
                            "operating_carrier_code", "operating_carrier_name",
                        },
                    )
    return finalize_observation(stats)


def observe_booking_response(data: dict) -> dict:
    it = data.get("itinerary") if isinstance(data, dict) and isinstance(data.get("itinerary"), dict) else None
    if it is None:
        return {"FIELDS": [], "BOOKING_OPTIONS_PRESENT": False, "BOOKING_OPTIONS_COUNT": 0}
    pseudo = {"itineraries": [it]}
    observed = observe_search_response(pseudo)
    options = data.get("booking_options") if isinstance(data.get("booking_options"), list) else []
    observed["BOOKING_OPTIONS_PRESENT"] = "booking_options" in data
    observed["BOOKING_OPTIONS_COUNT"] = len(options)
    observed["FULL_JOURNEY_OPTIONS"] = sum(
        1
        for option in options
        if isinstance(option, dict)
        and (
            set(option.get("leg_indexes") or []) == {0, 1}
            or set(option.get("legs") or []) == {"outbound", "inbound"}
        )
    )
    return observed


def finalize_observation(stats: dict[str, dict]) -> dict:
    rows = []
    for field in OPENAPI_FIELD_STATUS:
        row = stats.get(field, _new_stat(field))
        samples = row["SAMPLES"]
        row["NULL_RATE"] = (row["NULL_COUNT"] / samples) if samples else None
        row["REAL_PRESENT"] = row["PRESENT_COUNT"] > 0
        rows.append(row)
    return {"FIELDS": rows}


def merge_observations(observations: list[dict]) -> dict:
    merged: dict[str, dict] = {}
    booking_options_present = False
    booking_options_count = 0
    full_journey_options = 0
    for observation in observations:
        booking_options_present = booking_options_present or bool(observation.get("BOOKING_OPTIONS_PRESENT"))
        booking_options_count += int(observation.get("BOOKING_OPTIONS_COUNT") or 0)
        full_journey_options += int(observation.get("FULL_JOURNEY_OPTIONS") or 0)
        for incoming in observation.get("FIELDS", []):
            field = incoming["FIELD"]
            row = merged.setdefault(field, _new_stat(field))
            row["SAMPLES"] += int(incoming.get("SAMPLES") or 0)
            row["PRESENT_COUNT"] += int(incoming.get("PRESENT_COUNT") or 0)
            row["NULL_COUNT"] += int(incoming.get("NULL_COUNT") or 0)
            for key, value in (incoming.get("TYPES") or {}).items():
                row["TYPES"][key] = row["TYPES"].get(key, 0) + int(value)
            for value in incoming.get("VALUES") or []:
                if value not in row["VALUES"] and len(row["VALUES"]) < 50:
                    row["VALUES"].append(value)
    result = finalize_observation(merged)
    result["BOOKING_OPTIONS_PRESENT"] = booking_options_present
    result["BOOKING_OPTIONS_COUNT"] = booking_options_count
    result["FULL_JOURNEY_OPTIONS"] = full_journey_options
    return result
