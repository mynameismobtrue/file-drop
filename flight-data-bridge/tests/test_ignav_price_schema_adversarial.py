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
    status_code=200
    def __init__(self,data):
        self._data=data
        self.text=json.dumps(data)
    def json(self):
        return self._data


class Session:
    def __init__(self,data):
        self.data=data
    def request(self,*args,**kwargs):
        return Resp(self.data)


def payload(price):
    def seg(org,dst,dep,arr,du,au,num):
        return {
            "marketing_carrier_code":"TP","flight_number":num,"operating_carrier_name":"TAP Air Portugal",
            "departure_airport":org,"departure_time_local":dep,"departure_time_utc":du,
            "arrival_airport":dst,"arrival_time_local":arr,"arrival_time_utc":au,
            "duration_minutes":600,"aircraft":"A330",
        }
    return {
        "legs":[
            {"origin":"GRU","destination":"LIS","departure_date":"2026-10-27"},
            {"origin":"LIS","destination":"VCP","departure_date":"2026-11-03"},
        ],
        "itineraries":[{
            "price":price,
            "legs":[
                {"carrier":"TAP Air Portugal","duration_minutes":600,"segments":[seg("GRU","LIS","2026-10-27T20:00:00","2026-10-28T06:00:00","2026-10-27T23:00:00Z","2026-10-28T05:00:00Z","1")]},
                {"carrier":"TAP Air Portugal","duration_minutes":600,"segments":[seg("LIS","VCP","2026-11-03T10:00:00","2026-11-03T20:00:00","2026-11-03T10:00:00Z","2026-11-03T23:00:00Z","2")]},
            ],
            "cabin_class":"economy","bags":{"carry_on":1,"checked":None},"requires_self_transfer":False,"ignav_id":"ig-1",
        }],
    }


def test_search_price_amount_string_never_becomes_eligible():
    data=payload({"amount":"4300","currency":"BRL","status":"verified"})
    a=IgnavAdapter("k",CFG,session=Session(data),airport_db=AIRPORTS,sleep_fn=lambda _:None)
    result=a.search(JOB,"s")
    assert result.status=="FAILED"
    assert result.error_codes==["SCHEMA_INVALID"]


def test_search_missing_price_status_never_defaults_verified():
    data=payload({"amount":4300,"currency":"BRL"})
    a=IgnavAdapter("k",CFG,session=Session(data),airport_db=AIRPORTS,sleep_fn=lambda _:None)
    result=a.search(JOB,"s")
    if result.status=="FAILED":
        assert result.error_codes==["SCHEMA_INVALID"]
    else:
        assert result.status=="COMPLETE"
        offer=evaluate_offer(result.offers[0],CFG)
        assert offer.total_price_confirmed is False
        assert offer.derived["NON_VALIDATABLE"] is True
        assert "NON_VALIDATABLE_PRICE_UNCONFIRMED" in offer.derived["NON_VALIDATABLE_REASON_CODES"]
