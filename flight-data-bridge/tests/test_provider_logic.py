import json
from pathlib import Path
from flight_bridge.providers.skyscanner import _merge
from flight_bridge.models import Offer,Direction,Segment
from flight_bridge.fingerprints import exact_itinerary_match


def test_skyscanner_replaced_action_discards_old():
    base={"results":{"itineraries":{"a":1}}}; incoming={"results":{"itineraries":{"b":2}}}; out=_merge(base,incoming,"RESULT_ACTION_REPLACED"); assert "a" not in out["results"]["itineraries"] and "b" in out["results"]["itineraries"]

def test_skyscanner_non_replaced_merges():
    base={"results":{"itineraries":{"a":1}}}; incoming={"results":{"itineraries":{"b":2}}}; out=_merge(base,incoming,"RESULT_ACTION_NOT_MODIFIED"); assert set(out["results"]["itineraries"])=={"a","b"}

def test_exact_match_requires_same_segments():
    def o(minute):
        s=Segment("1","GRU","LIS",f"2026-10-26T20:{minute:02d}:00","2026-10-27T06:00:00",None,None,"TP","TP",flight_number="123")
        d=Direction("GRU","LIS",s.departure_local,s.arrival_local,"2026-10-27",600,0,None,None,[s],[])
        r=Segment("2","LIS","GRU","2026-11-03T10:00:00","2026-11-03T20:00:00",None,None,"TP","TP",flight_number="124")
        di=Direction("LIS","GRU",r.departure_local,r.arrival_local,"2026-11-03",600,0,None,None,[r],[])
        return Offer(None,None,"x","i","T","s",None,4300,"BRL",4300,None,None,True,None,"economy",outbound=d,inbound=di)
    assert exact_itinerary_match(o(0),o(0)); assert not exact_itinerary_match(o(0),o(5))

def test_workflow_safety_contract():
    root=Path(__file__).parents[2]
    text=(root/'.github/workflows/flight-data-bridge.yml').read_text()
    assert 'cancel-in-progress: false' in text
    assert 'schedule:' not in text
    assert 'IGNAV_API_KEY' not in text
    assert 'SKYSCANNER_API_KEY' not in text
    assert 'DUFFEL_ACCESS_TOKEN' not in text
    assert 'permissions:' in text and 'contents: read' in text
