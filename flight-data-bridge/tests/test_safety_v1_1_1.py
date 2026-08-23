from datetime import datetime, timezone
import json
from pathlib import Path

from flight_bridge.bridge import scheduled_slot, provider_cycle, search_jobs, canonical_query_id
from flight_bridge.hard_filters import evaluate_offer
from flight_bridge.models import Offer, Direction, Segment, ProviderQueryResult
from flight_bridge.operational import quota_gate, sanitize_document, alert_dedupe_decision, booking_url_is_sensitive
from flight_bridge.contract_observer import observe_search_response
from flight_bridge.providers.base import ProviderAdapter
from flight_bridge.providers.ignav import IgnavAdapter

CFG = json.loads((Path(__file__).parents[1] / "config/protocol_v2_2.json").read_text())
ROOT = Path(__file__).parents[1]


def _segment(dep_local, arr_local, dep_utc, arr_utc):
    return Segment(
        "s1", "GRU", "LIS", dep_local, arr_local, dep_utc, arr_utc,
        "TP", "TP", "TAP Air Portugal", "TAP Air Portugal", "123", None, 600,
    )


def _offer(arrival_local, arrival_utc, price=4300):
    ob_seg = _segment("2026-10-27T10:00:00", arrival_local, "2026-10-27T13:00:00Z", arrival_utc)
    ib_seg = Segment(
        "s2", "LIS", "GRU", "2026-11-03T10:00:00", "2026-11-03T20:00:00",
        "2026-11-03T10:00:00Z", "2026-11-03T20:00:00Z",
        "TP", "TP", "TAP Air Portugal", "TAP Air Portugal", "456", None, 600,
    )
    ob = Direction("GRU", "LIS", ob_seg.departure_local, arrival_local, arrival_local[:10], 600, 0, ob_seg.departure_utc, arrival_utc, [ob_seg], [])
    ib = Direction("LIS", "GRU", ib_seg.departure_local, ib_seg.arrival_local, "2026-11-03", 600, 0, ib_seg.departure_utc, ib_seg.arrival_utc, [ib_seg], [])
    return Offer(
        None, None, "x", "x", "TEST", "s", None,
        price, "BRL", price, None, None, True, None, "economy",
        None, None, None, "TEST", "TAP", "https://book.example/path", None,
        "2026-08-22T20:00:00+00:00", "2026-08-22T20:00:00+00:00", "VALIDATED",
        ob, ib, "MANAGED", 1,
    )


def test_four_cycle_logical_slots_brt():
    cases = [
        ("2026-08-22T09:05:00+00:00", "2026-08-22T09:00:00+00:00"),
        ("2026-08-22T14:12:00+00:00", "2026-08-22T14:00:00+00:00"),
        ("2026-08-22T19:30:00+00:00", "2026-08-22T19:00:00+00:00"),
        ("2026-08-23T00:07:00+00:00", "2026-08-23T00:00:00+00:00"),
        ("2026-08-22T08:30:00+00:00", "2026-08-22T00:00:00+00:00"),
    ]
    for started, expected in cases:
        assert scheduled_slot(datetime.fromisoformat(started), CFG).isoformat() == expected


class GridFake(ProviderAdapter):
    name = "IGNAV"
    role = "PRIMARY_DISCOVERY_TEMPORARY"
    def __init__(self, mode="ok"):
        self.mode = mode
    def configured(self):
        return True
    def search(self, job, search_id):
        qid = canonical_query_id(job, CFG)
        if self.mode == "duplicate" and job == {"origin":"VCP","outbound_date":"2026-10-28","return_destination":"VCP","query_type":"ROUND_TRIP"}:
            qid = "GRU-2026-10-26-LIS-2026-11-03-GRU"
        if self.mode == "unexpected" and job == {"origin":"VCP","outbound_date":"2026-10-28","return_destination":"VCP","query_type":"ROUND_TRIP"}:
            qid = "XXX-2099-01-01-LIS-2099-01-02-YYY"
        now = "2026-08-22T20:00:00+00:00"
        return ProviderQueryResult(self.name, qid, "COMPLETE", now, now, [], [], 0)
    def revalidate(self, offer, job):
        return offer, {}


def test_query_grid_exact_12_cells_required():
    c = provider_cycle(GridFake("ok"), list(search_jobs(CFG)), "s", CFG)
    assert c.search_status == "COMPLETE"
    assert c.complete == 12
    assert not c.error_codes


def test_duplicate_query_makes_cycle_incomplete():
    c = provider_cycle(GridFake("duplicate"), list(search_jobs(CFG)), "s", CFG)
    assert c.complete == 12
    assert c.search_status == "INCOMPLETE"
    assert "SEARCH_DUPLICATE_QUERY" in c.error_codes
    assert "SEARCH_MISSING_QUERY" in c.error_codes


def test_unexpected_query_makes_cycle_incomplete():
    c = provider_cycle(GridFake("unexpected"), list(search_jobs(CFG)), "s", CFG)
    assert c.complete == 12
    assert c.search_status == "INCOMPLETE"
    assert "SEARCH_UNEXPECTED_QUERY" in c.error_codes
    assert "SEARCH_MISSING_QUERY" in c.error_codes


def test_lisbon_arrival_uses_utc_and_rejects_29_even_if_provider_local_says_28():
    o = _offer("2026-10-28T23:30:00", "2026-10-29T00:30:00Z")
    evaluate_offer(o, CFG, datetime(2026, 8, 22, 20, tzinfo=timezone.utc))
    assert o.derived["LIS_ARRIVAL_DATE_FROM_UTC"] == "2026-10-29"
    assert "REJECT_WRONG_ARRIVAL_DATE" in o.derived["REJECTION_REASON_CODES"]
    assert "NON_VALIDATABLE_LIS_ARRIVAL_TIMEZONE_MISMATCH" in o.derived["NON_VALIDATABLE_REASON_CODES"]


def test_lisbon_arrival_mismatch_fail_closed_even_when_utc_date_allowed():
    o = _offer("2026-10-29T00:30:00", "2026-10-28T23:30:00Z")
    evaluate_offer(o, CFG, datetime(2026, 8, 22, 20, tzinfo=timezone.utc))
    assert o.derived["LIS_ARRIVAL_DATE_FROM_UTC"] == "2026-10-28"
    assert o.derived["ELIGIBILITY_STATE"] == "NON_VALIDATABLE"
    assert "NON_VALIDATABLE_LIS_ARRIVAL_TIMEZONE_MISMATCH" in o.derived["NON_VALIDATABLE_REASON_CODES"]


def test_string_price_fails_closed():
    o = _offer("2026-10-27T20:00:00", "2026-10-27T20:00:00Z", price=4300)
    o.price = "4499.99"
    o.price_brl = "4499.99"
    evaluate_offer(o, CFG, datetime(2026, 8, 22, 20, tzinfo=timezone.utc))
    assert o.derived["ELIGIBILITY_STATE"] == "NON_VALIDATABLE"
    assert o.derived["ALERT_PRICE_PASS"] is False
    assert "NON_VALIDATABLE_PRICE_UNCONFIRMED" in o.derived["NON_VALIDATABLE_REASON_CODES"]


def test_quota_gate_reserves_full_cycle_revalidation_and_50_buffer():
    assert quota_gate(936)["QUOTA_GATE_ALLOWED"] is True
    blocked = quota_gate(937)
    assert blocked["QUOTA_GATE_ALLOWED"] is False
    assert blocked["QUOTA_GATE_STATUS"] == "QUOTA_GATE_BLOCKED"


def test_manual_validation_quota_includes_one_health_request():
    assert quota_gate(935, extra_requests=1)["QUOTA_GATE_ALLOWED"] is True
    assert quota_gate(936, extra_requests=1)["QUOTA_GATE_ALLOWED"] is False


def test_quota_warning_at_150_remaining():
    row = quota_gate(850)
    assert row["IGNAV_FREE_REQUESTS_ESTIMATED_REMAINING"] == 150
    assert row["FREE_TIER_WARNING"] is True


def test_paid_usage_not_authorized_by_default():
    assert quota_gate(999)["IGNAV_PAID_USAGE_AUTHORIZED"] is False
    assert quota_gate(999)["QUOTA_GATE_ALLOWED"] is False


def test_sensitive_booking_url_redacted_and_secret_not_serialized():
    doc = {
        "VALID_OFFERS": [{"booking_url": "https://seller.example/buy?session_token=abc123", "derived": {}}],
        "REJECTED_OFFERS": [], "NON_VALIDATABLE_OFFERS": [], "ALERT_CANDIDATES": [],
        "Authorization": "Bearer SECRET-VALUE",
    }
    clean = sanitize_document(doc, actual_secret="SECRET-VALUE")
    offer = clean["VALID_OFFERS"][0]
    assert offer["booking_url"] is None
    assert offer["derived"]["BOOKING_URL_REDACTED"] is True
    assert "Authorization" not in clean
    assert "SECRET-VALUE" not in json.dumps(clean)


def test_booking_url_without_sensitive_state_can_remain():
    assert booking_url_is_sensitive("https://seller.example/flights/offer/123") is False


def test_alert_dedupe_same_offer_same_conditions_silent():
    previous = {"offer_id":"x","price_brl":4300,"checked_bag":None,"derived":{"QUALITY_CLASS":"A","MAX_CONNECTIONS":0}}
    current = {"offer_id":"x","price_brl":4300,"checked_bag":None,"derived":{"QUALITY_CLASS":"A","MAX_CONNECTIONS":0}}
    assert alert_dedupe_decision(previous, current)["SHOULD_ALERT"] is False


def test_alert_dedupe_realerts_on_100_brl_drop():
    previous = {"offer_id":"x","price_brl":4300,"derived":{"QUALITY_CLASS":"B"}}
    current = {"offer_id":"x","price_brl":4200,"derived":{"QUALITY_CLASS":"B"}}
    assert alert_dedupe_decision(previous, current) == {"SHOULD_ALERT": True, "REASON": "PRICE_DROP_100_BRL"}


def test_alert_dedupe_realerts_on_quality_improvement():
    previous = {"offer_id":"x","price_brl":4300,"derived":{"QUALITY_CLASS":"C"}}
    current = {"offer_id":"x","price_brl":4300,"derived":{"QUALITY_CLASS":"B"}}
    assert alert_dedupe_decision(previous, current)["REASON"] == "QUALITY_IMPROVED"


def test_alert_dedupe_does_not_treat_arbitrary_condition_signature_change_as_improvement():
    previous = {"offer_id":"x","price_brl":4300,"derived":{"QUALITY_CLASS":"B","CONDITION_SIGNATURE":"old"}}
    current = {"offer_id":"x","price_brl":4300,"derived":{"QUALITY_CLASS":"B","CONDITION_SIGNATURE":"new"}}
    assert alert_dedupe_decision(previous, current)["SHOULD_ALERT"] is False


def test_alert_dedupe_explicit_condition_improvement_can_realert():
    previous = {"offer_id":"x","price_brl":4300,"derived":{"QUALITY_CLASS":"B"}}
    current = {"offer_id":"x","price_brl":4300,"derived":{"QUALITY_CLASS":"B","CONDITION_IMPROVED":True}}
    assert alert_dedupe_decision(previous, current)["REASON"] == "CONDITION_IMPROVED"


def test_contract_observer_marks_operating_code_undocumented_even_if_present():
    payload = {
        "itineraries": [{
            "ignav_id":"i1", "price":{"amount":4300,"currency":"BRL","status":"verified"},
            "cabin_class":"economy", "requires_self_transfer":False, "bags":None,
            "legs":[{"segments":[{
                "marketing_carrier_code":"TP", "operating_carrier_code":"TP", "operating_carrier_name":"TAP Air Portugal",
                "flight_number":"123", "departure_airport":"GRU", "arrival_airport":"LIS",
                "departure_time_local":"2026-10-27T10:00:00", "arrival_time_local":"2026-10-27T20:00:00",
                "departure_time_utc":"2026-10-27T13:00:00Z", "arrival_time_utc":"2026-10-27T20:00:00Z",
                "duration_minutes":600, "aircraft":None,
            }]}],
        }]
    }
    obs = observe_search_response(payload)
    rows = {r["FIELD"]: r for r in obs["FIELDS"]}
    assert rows["operating_carrier_code"]["OPENAPI_EXPECTED"] == "UNDOCUMENTED"
    assert rows["operating_carrier_code"]["REAL_PRESENT"] is True
    assert rows["operating_carrier_name"]["OPENAPI_EXPECTED"] == "DOCUMENTED"
    assert rows["operating_carrier_name"]["REAL_PRESENT"] is True


def test_private_template_stays_preproduction_and_manual_only():
    live = (ROOT / "private-env-template/.github/workflows/live-provider-validation.yml").read_text()
    monitor = (ROOT / "private-env-template/.github/workflows/flight-monitor.yml").read_text()
    private_cfg = json.loads((ROOT / "private-env-template/config/live-validation.json").read_text())
    assert "workflow_dispatch:" in live
    assert "schedule:" not in live
    assert "workflow_dispatch:" in monitor
    assert "  schedule:" not in monitor
    assert private_cfg["state"] == "PRE_PRODUCTION"
    assert private_cfg["paid_usage_authorized"] is False
    assert private_cfg["alert_delivery_enabled"] is False
    assert private_cfg["approved_code_sha"].startswith("__SET_TO_FINAL_VALIDATED_PR_HEAD")


def test_public_workflow_is_ci_only_and_has_no_provider_secret_refs():
    text = (ROOT.parent / ".github/workflows/flight-data-bridge.yml").read_text()
    assert "\n  schedule:" not in text
    assert "secrets." not in text
    assert "IGNAV_API_KEY" not in text
    assert "SKYSCANNER_API_KEY" not in text


def test_protocol_version_is_frozen_while_bridge_is_1_1_2():
    assert CFG["data_bridge_version"] == "1.1.2"
    assert CFG["protocol_version"] == "LISBOA_V2.2"
    assert CFG["schedule_times_brt"] == ["06:00", "11:00", "16:00", "21:00"]
