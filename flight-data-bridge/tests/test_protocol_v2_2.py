from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import pytest
from flight_bridge.models import Offer,Direction,Segment,Connection,ProviderQueryResult
from flight_bridge.hard_filters import evaluate_offer
from flight_bridge.fingerprints import itinerary_fingerprint,commercial_offer_id
from flight_bridge.bridge import search_jobs,dedupe,provider_cycle,run
from flight_bridge.providers.ignav import IgnavAdapter
from flight_bridge.providers.skyscanner import SkyscannerAdapter
from flight_bridge.providers.base import ProviderAdapter

CFG=json.loads((Path(__file__).parents[1]/"config/protocol_v2_2.json").read_text())
NOW=datetime(2026,8,22,23,0,tzinfo=timezone.utc)

def seg(org,dst,dep="2026-10-26T20:00:00",arr="2026-10-27T06:00:00",mc="TP",oc="TP",num="123",mcn="TAP Air Portugal",ocn="TAP Air Portugal"):
    return Segment("s",org,dst,dep,arr,dep+"Z",arr+"Z",mc,oc,mcn,ocn,num,None,600)

def direct(org,dst,dep,arr,dur=600,mc="TP",oc="TP"):
    return Direction(org,dst,dep,arr,arr[:10],dur,0,dep+"Z",arr+"Z",[seg(org,dst,dep,arr,mc,oc)],[])

def connected(org,dst,dep,arr,conn_min=120,dur=800,country="ES",airport="MAD",self_transfer=False,airport_change=False,mc="IB",oc="IB"):
    s1=seg(org,airport,dep,"2026-10-27T01:00:00",mc,oc,"101",mcn="Iberia",ocn="Iberia")
    s2=seg(airport,dst,"2026-10-27T03:00:00",arr,mc,oc,"102",mcn="Iberia",ocn="Iberia")
    c=Connection(airport,country,conn_min,"SELF_TRANSFER" if self_transfer else "MANAGED",airport_change,self_transfer)
    return Direction(org,dst,dep,arr,arr[:10],dur,1,dep+"Z",arr+"Z",[s1,s2],[c])

def make_offer(price=4300,ob=None,ib=None,validation="VALIDATED",validated_at=None,currency="BRL",total=True,cabin="economy",booking_url="https://book",expires=None,agent="TAP",source_id="p1",booking_options=1,transfer="MANAGED"):
    ob=ob or direct("GRU","LIS","2026-10-26T20:00:00","2026-10-27T06:00:00")
    ib=ib or direct("LIS","GRU","2026-11-03T10:00:00","2026-11-03T20:00:00")
    o=Offer(None,None,source_id,"itin","TEST","s",None,price,currency,price if currency=="BRL" else None,None,None,total,None,cabin,None,None,None,"TEST",agent,booking_url,expires,NOW.isoformat(),validated_at or NOW.isoformat(),validation,ob,ib,transfer,booking_options)
    return o

def ev(**kw): return evaluate_offer(make_offer(**kw),CFG,NOW)

def codes(o): return set(o.derived["REJECTION_REASON_CODES"]+o.derived["NON_VALIDATABLE_REASON_CODES"])

@pytest.mark.parametrize("date,ok",[("2026-10-27",True),("2026-10-28",True),("2026-10-29",False)])
def test_arrival_dates(date,ok):
    ob=direct("GRU","LIS","2026-10-26T20:00:00",date+"T06:00:00")
    o=ev(ob=ob)
    assert o.derived["HARD_FILTER_PASS"] is ok
    if not ok: assert "REJECT_WRONG_ARRIVAL_DATE" in codes(o)

def test_return_date_exact():
    assert ev().derived["HARD_FILTER_PASS"]
    ib=direct("LIS","GRU","2026-11-04T10:00:00","2026-11-04T20:00:00")
    assert "REJECT_WRONG_RETURN_DATE" in codes(ev(ib=ib))

@pytest.mark.parametrize("mins,hard,quality",[(210,False,"B"),(211,False,"C"),(300,False,"C"),(301,True,None)])
def test_connection_boundaries(mins,hard,quality):
    ob=connected("GRU","LIS","2026-10-26T20:00:00","2026-10-27T09:00:00",mins,800)
    ib=connected("LIS","GRU","2026-11-03T10:00:00","2026-11-03T23:00:00",mins,800)
    o=ev(ob=ob,ib=ib)
    assert o.derived["HARD_REJECTED"] is hard
    if not hard: assert o.derived["QUALITY_CLASS"]==quality

@pytest.mark.parametrize("dur,hard,quality",[(720,False,"A"),(721,False,"B"),(900,False,"B"),(901,False,"C"),(1080,False,"C"),(1081,True,None)])
def test_duration_boundaries(dur,hard,quality):
    ob=direct("GRU","LIS","2026-10-26T20:00:00","2026-10-27T06:00:00",dur)
    ib=direct("LIS","GRU","2026-11-03T10:00:00","2026-11-03T20:00:00",dur)
    o=ev(ob=ob,ib=ib)
    assert o.derived["HARD_REJECTED"] is hard
    if not hard: assert o.derived["QUALITY_CLASS"]==quality

def test_two_connections_rejected():
    ob=connected("GRU","LIS","2026-10-26T20:00:00","2026-10-27T09:00:00")
    ob.connection_count=2
    assert "REJECT_TOO_MANY_CONNECTIONS" in codes(ev(ob=ob))

def test_taag_marketing():
    ob=direct("GRU","LIS","2026-10-26T20:00:00","2026-10-27T06:00:00",mc="DT",oc="TP")
    assert "REJECT_TAAG_MARKETING" in codes(ev(ob=ob))

def test_taag_operating():
    ob=direct("GRU","LIS","2026-10-26T20:00:00","2026-10-27T06:00:00",mc="TP",oc="DT")
    assert "REJECT_TAAG_OPERATING" in codes(ev(ob=ob))

def test_taag_one_segment():
    ob=connected("GRU","LIS","2026-10-26T20:00:00","2026-10-27T09:00:00")
    ob.segments[1].operating_carrier="DT"; ob.segments[1].operating_carrier_name="TAAG Angola Airlines"
    assert "REJECT_TAAG_OPERATING" in codes(ev(ob=ob))

def test_africa_connection():
    ob=connected("GRU","LIS","2026-10-26T20:00:00","2026-10-27T09:00:00",country="AO",airport="LAD")
    assert "REJECT_FORBIDDEN_CONNECTION" in codes(ev(ob=ob))

def test_connection_country_unknown_nonvalidatable():
    ob=connected("GRU","LIS","2026-10-26T20:00:00","2026-10-27T09:00:00",country=None)
    o=ev(ob=ob); assert o.derived["NON_VALIDATABLE"] and "NON_VALIDATABLE_CONNECTION_COUNTRY_UNKNOWN" in codes(o)

def test_self_transfer():
    ob=connected("GRU","LIS","2026-10-26T20:00:00","2026-10-27T09:00:00",self_transfer=True)
    assert "REJECT_SELF_TRANSFER" in codes(ev(ob=ob,transfer="SELF_TRANSFER"))

def test_protected_self_transfer(): assert "REJECT_PROTECTED_SELF_TRANSFER" in codes(ev(transfer="PROTECTED_SELF_TRANSFER"))
def test_airport_change():
    ob=connected("GRU","LIS","2026-10-26T20:00:00","2026-10-27T09:00:00",airport_change=True)
    assert "REJECT_AIRPORT_CHANGE" in codes(ev(ob=ob))

def test_operating_carrier_unknown_nonvalidatable():
    ob=direct("GRU","LIS","2026-10-26T20:00:00","2026-10-27T06:00:00"); ob.segments[0].operating_carrier=None
    o=ev(ob=ob); assert o.derived["NON_VALIDATABLE"] and "NON_VALIDATABLE_OPERATING_CARRIER_UNKNOWN" in codes(o)

def test_price_unknown_nonvalidatable():
    o=make_offer(price=None,total=False); o.price_brl=None; evaluate_offer(o,CFG,NOW); assert o.derived["NON_VALIDATABLE"]

def test_currency_invalid_nonvalidatable(): assert ev(currency="EUR").derived["NON_VALIDATABLE"]

@pytest.mark.parametrize("price,pass_price",[(4499.99,True),(4500.00,False),(4500.01,False)])
def test_price_boundary(price,pass_price): assert ev(price=price).derived["ALERT_PRICE_PASS"] is pass_price

def test_price_above_threshold_stays_valid_offer():
    o=ev(price=4700); assert o.derived["HARD_FILTER_PASS"] and not o.derived["VERIFIED_ALERT_CANDIDATE"]

def test_expired_offer():
    o=ev(expires=(NOW-timedelta(seconds=1)).isoformat()); assert "REJECT_OFFER_EXPIRED" in codes(o)

def test_disappeared_no_alert(): assert not ev(validation="DISAPPEARED").derived["VERIFIED_ALERT_CANDIDATE"]
def test_price_changed_can_alert_if_still_below(): assert ev(validation="PRICE_CHANGED",price=4400).derived["VERIFIED_ALERT_CANDIDATE"]
def test_validation_exact_10_minutes_valid(): assert ev(validated_at=(NOW-timedelta(minutes=10)).isoformat()).derived["VERIFIED_ALERT_CANDIDATE"]
def test_validation_over_10_minutes_stale(): assert not ev(validated_at=(NOW-timedelta(minutes=10,seconds=1)).isoformat()).derived["VERIFIED_ALERT_CANDIDATE"]
def test_offer_expiry_shorter_than_validation_ttl():
    o=ev(expires=(NOW+timedelta(minutes=4)).isoformat()); assert datetime.fromisoformat(o.derived["ALERT_VALID_UNTIL"])==NOW+timedelta(minutes=4)

def test_baggage_unknown_does_not_reject(): assert ev().derived["HARD_FILTER_PASS"]
def test_multiple_booking_required(): assert "REJECT_MULTIPLE_BOOKING_REQUIRED" in codes(ev(booking_options=2))
def test_open_jaw_universe_12():
    jobs=list(search_jobs(CFG)); assert len(jobs)==12; assert any(j["origin"]=="GRU" and j["return_destination"]=="VCP" for j in jobs)
def test_gru_vcp_open_jaw_allowed():
    ib=direct("LIS","VCP","2026-11-03T10:00:00","2026-11-03T20:00:00"); assert ev(ib=ib).derived["HARD_FILTER_PASS"]
def test_fingerprint_same_physical_different_agent():
    a=make_offer(agent="A",source_id="a"); b=make_offer(agent="B",source_id="b"); evaluate_offer(a,CFG,NOW); evaluate_offer(b,CFG,NOW); assert a.offer_id==b.offer_id and a.commercial_offer_id!=b.commercial_offer_id
def test_dedupe_same_commercial_offer_only_once():
    a=make_offer(agent="A",source_id="a"); b=make_offer(agent="A",source_id="a"); evaluate_offer(a,CFG,NOW); evaluate_offer(b,CFG,NOW); assert len(dedupe([a,b]))==1
def test_runtime_secret_not_serialized():
    o=make_offer(); o.runtime["SESSION_TOKEN"]="SECRET"; assert "SECRET" not in json.dumps(o.to_dict())

def test_ignav_query_filter_locations_correct():
    a=IgnavAdapter("x",CFG); q=a.build_query({"origin":"GRU","outbound_date":"2026-10-26","return_destination":"VCP"}); assert q["market"]=="BR" and q["allow_self_transfer"] is False and q["airlines_exclude"]==["DT"] and q["legs"][0]["max_stops"]==1 and q["legs"][1]["max_stops"]==1 and "max_stops" not in {k:v for k,v in q.items() if k!="legs"}
def test_skyscanner_query_excludes_taag_and_open_jaw_single_search():
    a=SkyscannerAdapter("x",CFG); q=a.build_query({"origin":"GRU","outbound_date":"2026-10-26","return_destination":"VCP"})["query"]; assert len(q["queryLegs"])==2 and q["excludedCarriersIds"]==["DT"]

class Fake(ProviderAdapter):
    def __init__(self,name,status="COMPLETE",configured=True,offers=None,role="PRIMARY_DISCOVERY"): self.name=name; self.role=role; self._status=status; self._configured=configured; self._offers=offers or []
    def configured(self): return self._configured
    def search(self,job,search_id): return ProviderQueryResult(self.name,f"{job['origin']}-{job['outbound_date']}-{job['return_destination']}",self._status,NOW.isoformat(),NOW.isoformat(),list(self._offers),[] if self._status=="COMPLETE" else ["PROVIDER_TIMEOUT"],len(self._offers))
    def revalidate(self,offer,job): offer.validation_status="VALIDATED"; offer.last_validated_at=datetime.now(timezone.utc).isoformat(); return offer,{"revalidation_provider":self.name,"same_provider_revalidation":True,"independent_source_corroboration":False}

def test_provider_cycle_complete_requires_12_of_12():
    c=provider_cycle(Fake("X"),list(search_jobs(CFG)),"s",CFG); assert c.complete==12 and c.search_status=="COMPLETE"
def test_provider_cycle_partial_is_incomplete():
    # One incomplete query via custom fake.
    class Partial(Fake):
        n=0
        def search(self,job,search_id):
            self.n+=1; return super().search(job,search_id) if self.n<12 else ProviderQueryResult(self.name,"x","FAILED",NOW.isoformat(),NOW.isoformat(),[],["PROVIDER_TIMEOUT"])
    c=provider_cycle(Partial("X"),list(search_jobs(CFG)),"s",CFG); assert c.complete==11 and c.search_status=="INCOMPLETE"
def test_fallback_is_explicit(tmp_path):
    cfg=dict(CFG); cfg["provider_priority"]=["SKYSCANNER","IGNAV"]
    providers={"SKYSCANNER":Fake("SKYSCANNER",configured=False),"IGNAV":Fake("IGNAV")}
    code,doc=run(tmp_path,cfg,providers=providers); assert code==0 and doc["ACTIVE_DISCOVERY_PROVIDER"]=="IGNAV" and doc["PRIMARY_STATUS"]=="FAILED" and doc["SEARCH_METADATA"]["SEARCH_STATUS"]=="COMPLETE_WITH_SOURCE_ERRORS" and doc["SOURCE_HEALTH"]=="DEGRADED" and doc["COVERAGE_EQUIVALENCE_NOT_ASSERTED"] is True
def test_incomplete_does_not_overwrite_last_complete_snapshot(tmp_path):
    sentinel={"SEARCH_METADATA":{"SEARCH_ID":"old","SEARCH_COMPLETED_AT":"2026-08-22T00:00:00+00:00"}}; (tmp_path/"snapshot.json").write_text(json.dumps(sentinel))
    cfg=dict(CFG); cfg["provider_priority"]=["SKYSCANNER"]
    code,doc=run(tmp_path,cfg,providers={"SKYSCANNER":Fake("SKYSCANNER",status="FAILED")}); assert code!=0 and json.loads((tmp_path/"snapshot.json").read_text())==sentinel and (tmp_path/"status.json").exists()
