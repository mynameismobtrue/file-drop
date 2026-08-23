import json

from flight_bridge.hard_filters import evaluate_offer
from flight_bridge.providers.ignav import IgnavAdapter


CFG={
    "destination":"LIS","return_departure_date":"2026-11-03","max_connections_per_direction":1,"adults":1,
    "request_timeout_sec":1,"health_timeout_sec":1,"max_retries":1,"retry_backoff_base_sec":0,
    "origins":["GRU","VCP"],"outbound_departure_dates":["2026-10-26","2026-10-27","2026-10-28"],
    "allowed_lis_arrival_dates":["2026-10-27","2026-10-28"],"return_destinations":["GRU","VCP"],
    "max_total_duration_per_direction_min":1080,"max_connection_duration_min":300,"forbid_africa_connections":True,
    "reject_airport_change":True,"reject_multiple_booking_required":True,"alert_price_brl_strict_lt":4500.0,
    "alert_validation_ttl_min":10,"quality_a_max_duration_min":720,"quality_b_max_duration_min":900,
    "preferred_connection_duration_min":210,
    "forbidden_carriers":[{"iata":"DT","name_contains":"TAAG"},{"iata":None,"name_contains":"TAAG ANGOLA"}],
}
JOB={"origin":"GRU","outbound_date":"2026-10-27","return_destination":"VCP"}
AIRPORTS={"LIS":{"country":"PT"},"GRU":{"country":"BR"},"VCP":{"country":"BR"}}


class Resp:
    def __init__(self,data,status=200):
        self.status_code=status
        self._data=data
        self.text=json.dumps(data)
    def json(self):
        return self._data


class Session:
    def __init__(self,*items):
        self.items=list(items)
        self.calls=[]
    def request(self,method,url,**kw):
        self.calls.append((method,url,kw))
        if not self.items:
            raise AssertionError("no fake response")
        return self.items.pop(0)


def segment(org,dst,dep_local,arr_local,dep_utc,arr_utc,marketing="TP",operating_name="TAP Air Portugal",number="1"):
    return {
        "marketing_carrier_code":marketing,
        "flight_number":number,
        "operating_carrier_name":operating_name,
        "departure_airport":org,
        "departure_time_local":dep_local,
        "departure_timezone":"America/Sao_Paulo" if org in {"GRU","VCP"} else "Europe/Lisbon",
        "departure_time_utc":dep_utc,
        "arrival_airport":dst,
        "arrival_time_local":arr_local,
        "arrival_timezone":"Europe/Lisbon" if dst=="LIS" else "America/Sao_Paulo",
        "arrival_time_utc":arr_utc,
        "duration_minutes":600,
        "aircraft":"A330",
    }


def itinerary(ignav_id="ig-1",price=4300,operating_name="TAP Air Portugal"):
    out={
        "carrier":"TAP Air Portugal","duration_minutes":600,
        "segments":[segment("GRU","LIS","2026-10-27T20:00:00","2026-10-28T06:00:00","2026-10-27T23:00:00Z","2026-10-28T05:00:00Z",operating_name=operating_name,number="1")],
    }
    inn={
        "carrier":"TAP Air Portugal","duration_minutes":600,
        "segments":[segment("LIS","VCP","2026-11-03T10:00:00","2026-11-03T20:00:00","2026-11-03T10:00:00Z","2026-11-03T23:00:00Z",operating_name=operating_name,number="2")],
    }
    return {
        "price":{"amount":price,"currency":"BRL","status":"verified"},
        "legs":[out,inn],
        "cabin_class":"economy",
        "bags":{"carry_on":1,"checked":None},
        "requires_self_transfer":False,
        "ignav_id":ignav_id,
    }


def search_response(items):
    return {
        "legs":[
            {"origin":"GRU","destination":"LIS","departure_date":"2026-10-27"},
            {"origin":"LIS","destination":"VCP","departure_date":"2026-11-03"},
        ],
        "itineraries":items,
    }


def booking_response(*, link_price_marker="normal"):
    it=itinerary("ignored")
    it.pop("ignav_id",None)
    link={"provider_name":"TAP","provider_type":"airline","url":"https://book.example/offer"}
    if link_price_marker=="normal":
        link["price"]={"amount":4300,"currency":"BRL","status":"verified"}
    elif link_price_marker=="missing_status":
        link["price"]={"amount":4300,"currency":"BRL"}
    elif link_price_marker=="string_amount":
        link["price"]={"amount":"4300","currency":"BRL","status":"verified"}
    return {
        "itinerary":it,
        "booking_options":[{"leg_indexes":[0,1],"links":[link]}],
    }


def adapter(*responses):
    return IgnavAdapter("k",CFG,session=Session(*[Resp(x) for x in responses]),airport_db=AIRPORTS,sleep_fn=lambda _:None)


def initial_offer(a):
    return a._normalize_itinerary(itinerary("initial"),"s",JOB)


def test_second_search_two_exact_matches_with_different_source_ids_is_nonvalidatable():
    second=search_response([itinerary("fresh-a"),itinerary("fresh-b")])
    a=adapter(second)
    fresh,meta=a.revalidate(initial_offer(a),JOB)
    assert fresh.validation_status=="NON_VALIDATABLE"
    assert fresh.booking_url is None
    assert "REVALIDATION_AMBIGUOUS_EXACT_MATCH" in fresh.derived["SOURCE_NON_VALIDATABLE_REASONS"]
    assert meta["second_search_exact_matches"]==2
    assert meta["second_search_source_offer_ids"]==["fresh-a","fresh-b"]
    assert len(a.http.calls)==1


def test_second_search_duplicate_rows_same_source_and_terms_can_collapse():
    second=search_response([itinerary("same"),itinerary("same")])
    a=adapter(second,booking_response())
    fresh,meta=a.revalidate(initial_offer(a),JOB)
    assert fresh.validation_status=="VALIDATED"
    assert fresh.booking_url=="https://book.example/offer"
    assert meta["second_search_exact_matches"]==2
    assert meta["second_search_duplicate_matches_collapsed"]==1


def test_booking_link_without_own_price_is_nonvalidatable():
    a=adapter(search_response([itinerary("fresh")]),booking_response(link_price_marker="missing"))
    fresh,_=a.revalidate(initial_offer(a),JOB)
    assert fresh.validation_status=="NON_VALIDATABLE"
    assert fresh.booking_url is None
    assert fresh.total_price_confirmed is False
    assert "BOOKING_PRICE_MISSING" in fresh.derived["SOURCE_NON_VALIDATABLE_REASONS"]


def test_booking_link_missing_verified_status_is_nonvalidatable():
    a=adapter(search_response([itinerary("fresh")]),booking_response(link_price_marker="missing_status"))
    fresh,_=a.revalidate(initial_offer(a),JOB)
    assert fresh.validation_status=="NON_VALIDATABLE"
    assert fresh.booking_url is None
    assert fresh.total_price_confirmed is False
    assert "BOOKING_PRICE_UNVERIFIED" in fresh.derived["SOURCE_NON_VALIDATABLE_REASONS"]


def test_booking_link_string_amount_fails_closed():
    a=adapter(search_response([itinerary("fresh")]),booking_response(link_price_marker="string_amount"))
    fresh,meta=a.revalidate(initial_offer(a),JOB)
    assert fresh.booking_url is None
    assert fresh.total_price_confirmed is False
    assert fresh.validation_status in {"NON_VALIDATABLE","ERROR"}
    reasons=set(fresh.derived.get("SOURCE_NON_VALIDATABLE_REASONS",[]))
    assert "BOOKING_PRICE_INVALID" in reasons or meta.get("error")=="SCHEMA_INVALID"


def test_operating_name_taag_is_hard_rejected_even_without_trusted_operating_code():
    a=adapter()
    offer=a._normalize_itinerary(itinerary("taag",operating_name="TAAG Angola Airlines"),"s",JOB)
    evaluated=evaluate_offer(offer,CFG)
    assert evaluated.derived["HARD_REJECTED"] is True
    assert "REJECT_TAAG_OPERATING" in evaluated.derived["REJECTION_REASON_CODES"]
