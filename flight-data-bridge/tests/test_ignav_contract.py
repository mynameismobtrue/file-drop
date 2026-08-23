import json
import pytest, requests
from flight_bridge.providers.ignav import IgnavAdapter
from flight_bridge.hard_filters import evaluate_offer

CFG={"destination":"LIS","return_departure_date":"2026-11-03","max_connections_per_direction":1,"adults":1,
"request_timeout_sec":1,"health_timeout_sec":1,"max_retries":2,"retry_backoff_base_sec":0,
"origins":["GRU","VCP"],"outbound_departure_dates":["2026-10-26","2026-10-27","2026-10-28"],
"allowed_lis_arrival_dates":["2026-10-27","2026-10-28"],"return_destinations":["GRU","VCP"],
"max_total_duration_per_direction_min":1080,"max_connection_duration_min":300,"forbid_africa_connections":True,
"reject_airport_change":True,"reject_multiple_booking_required":True,"alert_price_brl_strict_lt":4500.0,
"alert_validation_ttl_min":10,"forbidden_carriers":[{"iata":"DT","name_contains":"TAAG"},{"iata":None,"name_contains":"TAAG ANGOLA"}]}
JOB={"origin":"GRU","outbound_date":"2026-10-27","return_destination":"VCP"}
AIRPORTS={"LIS":{"country":"PT"},"GRU":{"country":"BR"},"VCP":{"country":"BR"},"MAD":{"country":"ES"}}

class Resp:
    def __init__(self,status=200,data=None,text=""): self.status_code=status; self._data=data; self.text=text or json.dumps(data or {})
    def json(self):
        if isinstance(self._data,Exception): raise self._data
        return self._data
class Session:
    def __init__(self,*items): self.items=list(items); self.calls=[]
    def request(self,method,url,**kw):
        self.calls.append((method,url,kw))
        if not self.items: raise AssertionError("no fake response")
        x=self.items.pop(0)
        if isinstance(x,Exception): raise x
        return x

def seg(org,dst,dep_local,arr_local,dep_utc,arr_utc,code="TP",num="1",op_name="TAP Air Portugal"):
    return {"marketing_carrier_code":code,"flight_number":num,"operating_carrier_name":op_name,
        "departure_airport":org,"departure_time_local":dep_local,"departure_timezone":"America/Sao_Paulo" if org in {"GRU","VCP"} else "Europe/Lisbon",
        "departure_time_utc":dep_utc,"arrival_airport":dst,"arrival_time_local":arr_local,
        "arrival_timezone":"Europe/Lisbon" if dst=="LIS" else "America/Sao_Paulo","arrival_time_utc":arr_utc,
        "duration_minutes":600,"aircraft":"A330"}

def itinerary(price=4300,ignav_id="ig-1",vcp=True):
    out={"carrier":"TAP Air Portugal","duration_minutes":600,"segments":[seg("GRU","LIS","2026-10-27T20:00:00","2026-10-28T06:00:00","2026-10-27T23:00:00Z","2026-10-28T05:00:00Z","TP","1")]}
    dest="VCP" if vcp else "GRU"
    inn={"carrier":"TAP Air Portugal","duration_minutes":600,"segments":[seg("LIS",dest,"2026-11-03T10:00:00","2026-11-03T20:00:00","2026-11-03T10:00:00Z","2026-11-03T23:00:00Z","TP","2")]}
    return {"price":{"amount":price,"currency":"BRL","status":"verified"},"legs":[out,inn],"cabin_class":"economy","bags":{"carry_on":1,"checked":None},"requires_self_transfer":False,"ignav_id":ignav_id}

def search_response(items=None):
    return {"legs":[{"origin":"GRU","destination":"LIS","departure_date":"2026-10-27"},{"origin":"LIS","destination":"VCP","departure_date":"2026-11-03"}],"itineraries":items if items is not None else [itinerary()]}

def booking_response(price=4300,partial=False,changed=False,split=False):
    it=itinerary(price,"ignored"); it.pop("ignav_id",None)
    if changed: it["legs"][0]["segments"][0]["departure_time_utc"]="2026-10-27T23:05:00Z"
    if split:
        opts=[{"leg_indexes":[0],"links":[{"provider_name":"A","provider_type":"airline","url":"https://a"}]},{"leg_indexes":[1],"links":[{"provider_name":"B","provider_type":"airline","url":"https://b"}]}]
    elif partial: opts=[{"leg_indexes":[0],"links":[{"provider_name":"A","provider_type":"airline","url":"https://a"}]}]
    else: opts=[{"leg_indexes":[0,1],"links":[{"provider_name":"TAP","provider_type":"airline","price":{"amount":price,"currency":"BRL","status":"verified"},"url":"https://book"}]}]
    return {"itinerary":it,"booking_options":opts}

def adapter(*responses,key="k",cfg=None): return IgnavAdapter(key,cfg or CFG,session=Session(*responses),airport_db=AIRPORTS,sleep_fn=lambda _:None)
def initial_offer(a):
    data=search_response(); return a._normalize_itinerary(data["itineraries"][0],"s",JOB)

def test_openapi_request_shape_open_jaw_and_dt_exclusion():
    q=adapter().build_query(JOB)
    assert set(q)=={"legs","adults","cabin_class","market","allow_self_transfer","airlines_exclude"}
    assert q["legs"]==[{"origin":"GRU","destination":"LIS","departure_date":"2026-10-27","max_stops":1},{"origin":"LIS","destination":"VCP","departure_date":"2026-11-03","max_stops":1}]
    assert q["market"]=="BR" and q["allow_self_transfer"] is False and q["airlines_exclude"]==["DT"]

def test_openapi_response_fixture_and_operating_missing():
    r=adapter(Resp(data=search_response())).search(JOB,"s"); assert r.status=="COMPLETE" and len(r.offers)==1
    s=r.offers[0].outbound.segments[0]; assert s.marketing_carrier=="TP" and s.operating_carrier is None and s.operating_carrier_name=="TAP Air Portugal"
    o=evaluate_offer(r.offers[0],CFG); assert o.derived["NON_VALIDATABLE"] and "NON_VALIDATABLE_OPERATING_CARRIER_UNKNOWN" in o.derived["NON_VALIDATABLE_REASON_CODES"]
    assert o.itinerary_fingerprint is not None

def test_unverified_operating_extension_not_promoted():
    d=search_response(); d["itineraries"][0]["legs"][0]["segments"][0]["operating_carrier_code"]="TP"
    o=adapter(Resp(data=d)).search(JOB,"s").offers[0]
    assert o.outbound.segments[0].operating_carrier is None and any("operating_carrier_code" in x for x in o.derived["UNVERIFIED_FIELDS"])

def test_unknown_field_ignored_safely():
    d=search_response(); d["future_top"]={"x":1}; d["itineraries"][0]["future_field"]=123; d["itineraries"][0]["legs"][0]["segments"][0]["future_segment"]="ok"
    assert adapter(Resp(data=d)).search(JOB,"s").status=="COMPLETE"

def test_unexpected_field_type_schema_invalid():
    d=search_response(); d["itineraries"][0]["legs"][0]["segments"][0]["duration_minutes"]="600"
    r=adapter(Resp(data=d)).search(JOB,"s"); assert r.status=="FAILED" and r.error_codes==["SCHEMA_INVALID"]

def test_malformed_response_schema_invalid():
    r=adapter(Resp(data={"legs":"bad","itineraries":[]})).search(JOB,"s"); assert r.status=="FAILED" and r.error_codes==["SCHEMA_INVALID"]

def test_health_200():
    h=adapter(Resp(200,[{"code":"GRU","name":"Guarulhos","city":"Sao Paulo","country":"BR"}])).health_check()
    assert h["STATUS"]=="UP" and h["HTTP_STATUS"]==200 and h["ERROR_CODE"] is None

def test_health_401():
    h=adapter(Resp(401,{"error":{"type":"auth_error","code":"invalid_api_key","message":"bad"}})).health_check()
    assert h["STATUS"]=="AUTH_REQUIRED" and h["ERROR_CODE"]=="invalid_api_key"

def test_health_402():
    assert adapter(Resp(402,{"error":{"type":"billing_error","code":"billing_required","message":"billing"}})).health_check()["STATUS"]=="BILLING_REQUIRED"

def test_health_429_monthly_cap_is_billing():
    h=adapter(Resp(429,{"error":{"type":"billing_error","code":"monthly_spend_limit_reached","message":"cap"}})).health_check()
    assert h["STATUS"]=="BILLING_REQUIRED" and h["ERROR_CODE"]=="monthly_spend_limit_reached"

def test_health_429_unknown_is_provisional():
    h=adapter(Resp(429,{"error":{"type":"upstream_error","code":"something_new","message":"x"}})).health_check()
    assert h["STATUS"]=="RATE_LIMITED" and h["ERROR_MAPPING_CONFIDENCE"]=="PROVISIONAL_HTTP_429"

def test_health_timeout(): assert adapter(requests.Timeout("slow")).health_check()["ERROR_CODE"]=="PROVIDER_TIMEOUT"

def test_424_retries_then_succeeds():
    a=adapter(Resp(424,{"error":{"type":"upstream_error","code":"upstream_unavailable","message":"retry"}}),Resp(data=search_response()))
    assert a.search(JOB,"s").status=="COMPLETE" and len(a.http.calls)==2

def test_timeout_search_maps_timeout():
    cfg=dict(CFG); cfg["max_retries"]=1; r=adapter(requests.Timeout("slow"),cfg=cfg).search(JOB,"s")
    assert r.status=="TIMED_OUT" and r.error_codes==["PROVIDER_TIMEOUT"]

def test_booking_full_journey():
    a=adapter(Resp(data=search_response()),Resp(data=booking_response())); fresh,meta=a.revalidate(initial_offer(a),JOB)
    assert fresh.validation_status=="VALIDATED" and fresh.booking_url=="https://book" and fresh.booking_option_count==1
    assert meta["second_full_search"] and meta["booking_links_refresh"] and meta["price_based_selection"] is False

def test_booking_partial_nonvalidatable():
    a=adapter(Resp(data=search_response()),Resp(data=booking_response(partial=True))); fresh,_=a.revalidate(initial_offer(a),JOB)
    assert fresh.validation_status=="NON_VALIDATABLE" and "BOOKING_FULL_JOURNEY_UNAVAILABLE" in fresh.derived["SOURCE_NON_VALIDATABLE_REASONS"]

def test_booking_split_requires_multiple_purchase():
    a=adapter(Resp(data=search_response()),Resp(data=booking_response(split=True))); fresh,_=a.revalidate(initial_offer(a),JOB); evaluate_offer(fresh,CFG)
    assert fresh.booking_option_count==2 and "REJECT_MULTIPLE_BOOKING_REQUIRED" in fresh.derived["REJECTION_REASON_CODES"]

def test_booking_changed_itinerary_not_switched():
    a=adapter(Resp(data=search_response()),Resp(data=booking_response(changed=True))); original=initial_offer(a); fp=original.itinerary_fingerprint; fresh,_=a.revalidate(original,JOB)
    assert fresh.validation_status=="CHANGED" and fresh.itinerary_fingerprint==fp and fresh.booking_url is None

def test_booking_price_change():
    a=adapter(Resp(data=search_response([itinerary(4300,"ig-2")])),Resp(data=booking_response(4200))); fresh,_=a.revalidate(initial_offer(a),JOB)
    assert fresh.validation_status=="PRICE_CHANGED" and fresh.price_brl==4200 and fresh.total_price_confirmed is True

def test_second_search_never_min_price():
    second=search_response([itinerary(4400,"first"),itinerary(4000,"cheaper")]); a=adapter(Resp(data=second),Resp(data=booking_response(4400))); fresh,meta=a.revalidate(initial_offer(a),JOB)
    assert fresh.price_brl==4400 and meta["price_based_selection"] is False

def test_booking_unverified_price_not_confirmed():
    b=booking_response(4200); b["booking_options"][0]["links"][0]["price"]["status"]="unverified"
    fresh,_=adapter(Resp(data=search_response()),Resp(data=b)).revalidate(initial_offer(adapter()),JOB); assert fresh.total_price_confirmed is False

def test_no_secret_serialization():
    a=adapter(); o=initial_offer(a); o.runtime["API_KEY"]="super-secret"; assert "super-secret" not in json.dumps(o.to_dict())

def test_persisted_openapi_fixtures_round_trip():
    from pathlib import Path
    root=Path(__file__).parent/'fixtures'/'ignav'; search=json.loads((root/'fare_search_openjaw.json').read_text()); booking=json.loads((root/'booking_links_full.json').read_text())
    a=adapter(Resp(data=search),Resp(data=search),Resp(data=booking)); r=a.search(JOB,'fixture-search'); assert r.status=='COMPLETE' and r.raw_offers_count==1
    fresh,meta=a.revalidate(r.offers[0],JOB); assert fresh.booking_url=='https://example.invalid/book' and meta['booking_links_refresh'] is True
