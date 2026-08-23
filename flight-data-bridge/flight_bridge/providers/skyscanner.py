from __future__ import annotations
import hashlib,json,time
from datetime import datetime,timezone
from typing import Any
from zoneinfo import ZoneInfo
import requests
try:
    import airportsdata
except Exception:
    airportsdata=None
from .base import ProviderAdapter
from ..models import Offer,Direction,Segment,Connection,ProviderQueryResult
from ..fingerprints import itinerary_fingerprint, exact_itinerary_match

BASE="https://partners.api.skyscanner.net/apiservices/v3"
class SkyscannerError(RuntimeError): pass

def now_iso(): return datetime.now(timezone.utc).isoformat()

def _local(dt:dict|None):
    if not dt: return None
    try: return f"{dt['year']:04d}-{dt['month']:02d}-{dt['day']:02d}T{dt.get('hour',0):02d}:{dt.get('minute',0):02d}:{dt.get('second',0):02d}"
    except Exception: return None

def _price(p):
    if not p or p.get("amount") in (None,""): return None
    try: amount=float(p["amount"])
    except Exception: return None
    div={"PRICE_UNIT_WHOLE":1,"PRICE_UNIT_CENTI":100,"PRICE_UNIT_MILLI":1000,"PRICE_UNIT_MICRO":1000000}.get(p.get("unit"))
    return amount/div if div else None

def _merge(base,incoming,action):
    if action=="RESULT_ACTION_REPLACED" or not base: return incoming or {}
    if not incoming: return base
    out=json.loads(json.dumps(base))
    for section in ("itineraries","legs","segments","places","carriers","agents","alliances","fareAttributeFilters"):
        src=((incoming.get("results") or {}).get(section) or {})
        if src: out.setdefault("results",{}).setdefault(section,{}).update(src)
    for k in ("stats","sortingOptions"):
        if k in incoming: out[k]=incoming[k]
    return out

class SkyscannerAdapter(ProviderAdapter):
    name="SKYSCANNER"; role="PRIMARY_DISCOVERY"
    def __init__(self,api_key:str,cfg:dict,session:requests.Session|None=None):
        self.api_key=api_key; self.cfg=cfg; self.http=session or requests.Session()
        self._airports=airportsdata.load("IATA") if airportsdata else {}
    def configured(self): return bool(self.api_key)
    @property
    def headers(self): return {"x-api-key":self.api_key,"Content-Type":"application/json"}
    def _request(self,method,url,**kwargs):
        last=None
        for attempt in range(1,self.cfg.get("max_retries",3)+1):
            try:
                r=self.http.request(method,url,headers=self.headers,timeout=self.cfg.get("request_timeout_sec",30),**kwargs)
                if r.status_code==401: raise SkyscannerError("AUTH_REQUIRED")
                if r.status_code==402: raise SkyscannerError("BILLING_REQUIRED")
                if r.status_code==403: raise SkyscannerError("AUTH_REQUIRED")
                if r.status_code==429: raise SkyscannerError("RATE_LIMITED")
                if r.status_code>=500:
                    last=SkyscannerError(f"PROVIDER_HTTP_ERROR_{r.status_code}"); time.sleep(min(2**attempt,8)); continue
                r.raise_for_status(); return r
            except SkyscannerError: raise
            except Exception as e:
                last=e
                if attempt<self.cfg.get("max_retries",3): time.sleep(min(2**attempt,8))
        raise SkyscannerError(f"PROVIDER_TIMEOUT_OR_HTTP:{type(last).__name__}")
    def build_query(self,job):
        def d(s):
            y,m,day=map(int,s.split("-")); return {"year":y,"month":m,"day":day}
        return {"query":{
            "market":self.cfg["market"],"locale":self.cfg["locale"],"currency":self.cfg["currency"],
            "queryLegs":[
                {"originPlaceId":{"iata":job["origin"]},"destinationPlaceId":{"iata":self.cfg["destination"]},"date":d(job["outbound_date"])},
                {"originPlaceId":{"iata":self.cfg["destination"]},"destinationPlaceId":{"iata":job["return_destination"]},"date":d(self.cfg["return_departure_date"])}
            ],
            "adults":self.cfg.get("adults",1),"childrenAges":[],"cabinClass":self.cfg["skyscanner_cabin_class"],
            "excludedCarriersIds":["DT"],"nearbyAirports":False,"includeSustainabilityData":False
        }}
    def _search_complete(self,query):
        create=self._request("POST",f"{BASE}/flights/live/search/create",json=query).json()
        token=create.get("sessionToken")
        if not token: raise SkyscannerError("CREATE_NO_SESSION_TOKEN")
        status=create.get("status"); merged=create.get("content") or {}; started=time.monotonic()
        while status!="RESULT_STATUS_COMPLETE":
            if status=="RESULT_STATUS_FAILED": raise SkyscannerError("POLL_FAILED")
            if time.monotonic()-started>self.cfg.get("poll_timeout_sec",75): raise SkyscannerError("POLL_TIMEOUT")
            time.sleep(self.cfg.get("poll_interval_sec",3))
            p=self._request("POST",f"{BASE}/flights/live/search/poll/{token}").json()
            status=p.get("status"); merged=_merge(merged,p.get("content") or {},p.get("action"))
        return {"sessionToken":token,"status":status,"content":merged}
    def _airport_country(self,iata):
        row=self._airports.get((iata or "").upper()) if self._airports else None
        return (row or {}).get("country")
    def _utc(self,local,iata):
        if not local: return None
        row=self._airports.get((iata or "").upper()) if self._airports else None
        tz=(row or {}).get("tz")
        if not tz: return None
        try: return datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        except Exception: return None
    def _normalize(self,payload,search_id,job):
        token=payload.get("sessionToken"); results=((payload.get("content") or {}).get("results") or {})
        itineraries=results.get("itineraries") or {}; legs=results.get("legs") or {}; segments=results.get("segments") or {}; places=results.get("places") or {}; carriers=results.get("carriers") or {}; agents=results.get("agents") or {}
        def iata(pid): return (places.get(pid) or {}).get("iata") if pid else None
        def carrier(cid):
            row=carriers.get(cid) or {}; return row.get("iata") or row.get("displayCode"),row.get("name")
        def direction(leg_id,transfer):
            leg=legs.get(leg_id) or {}; ss=[]
            for sid in leg.get("segmentIds") or []:
                s=segments.get(sid) or {}; org=iata(s.get("originPlaceId")) or ""; dst=iata(s.get("destinationPlaceId")) or ""; dep=_local(s.get("departureDateTime")) or ""; arr=_local(s.get("arrivalDateTime")) or ""; mc,mcn=carrier(s.get("marketingCarrierId")); oc,ocn=carrier(s.get("operatingCarrierId"))
                ss.append(Segment(str(sid),org,dst,dep,arr,self._utc(dep,org),self._utc(arr,dst),mc,oc,mcn,ocn,str(s.get("marketingFlightNumber")) if s.get("marketingFlightNumber") is not None else None,None,s.get("durationInMinutes")))
            conns=[]; self_transfer=transfer in {"TRANSFER_TYPE_SELF_TRANSFER","TRANSFER_TYPE_PROTECTED_SELF_TRANSFER"}
            for a,b in zip(ss,ss[1:]):
                mins=None
                if a.arrival_utc and b.departure_utc:
                    try: mins=int((datetime.fromisoformat(b.departure_utc.replace("Z","+00:00"))-datetime.fromisoformat(a.arrival_utc.replace("Z","+00:00"))).total_seconds()/60)
                    except Exception: mins=None
                conns.append(Connection(b.origin,self._airport_country(b.origin),mins,transfer,(a.destination!=b.origin),self_transfer))
            dep=_local(leg.get("departureDateTime")) or (ss[0].departure_local if ss else ""); arr=_local(leg.get("arrivalDateTime")) or (ss[-1].arrival_local if ss else "")
            return Direction(iata(leg.get("originPlaceId")) or (ss[0].origin if ss else ""),iata(leg.get("destinationPlaceId")) or (ss[-1].destination if ss else ""),dep,arr,arr[:10] if arr else "",leg.get("durationInMinutes"),leg.get("stopCount"),self._utc(dep,iata(leg.get("originPlaceId"))),self._utc(arr,iata(leg.get("destinationPlaceId"))),ss,conns)
        out=[]
        for iid,it in itineraries.items():
            leg_ids=it.get("legIds") or []
            for po in it.get("pricingOptions") or []:
                items=po.get("items") or []; transfer=(items[0].get("transferType") if items else None); ob=direction(leg_ids[0],transfer) if len(leg_ids)>0 else None; ib=direction(leg_ids[1],transfer) if len(leg_ids)>1 else None
                amount=_price(po.get("price")); item=items[0] if len(items)==1 else {}; aid=item.get("agentId"); agent=(agents.get(aid) or {}).get("name") if aid else None
                o=Offer(None,None,str(po.get("id")) if po.get("id") is not None else None,str(iid),self.name,search_id,None,amount,"BRL",amount,None,None,bool(amount is not None and len(items)==1),None,"economy",None,None,None,self.name,agent,item.get("deepLink"),None,now_iso(),None,"NOT_REQUIRED",ob,ib,transfer,len(items))
                o.itinerary_fingerprint=itinerary_fingerprint(o); o.offer_id=o.itinerary_fingerprint; o.runtime.update({"SESSION_TOKEN":token,"JOB":job})
                out.append(o)
        return out
    def search(self,job,search_id):
        started=now_iso(); qid=f"{job['origin']}-{job['outbound_date']}-LIS-{self.cfg['return_departure_date']}-{job['return_destination']}"; query=self.build_query(job)
        if not self.configured(): return ProviderQueryResult(self.name,qid,"FAILED",started,now_iso(),[],["AUTH_REQUIRED"])
        try:
            payload=self._search_complete(query); offers=self._normalize(payload,search_id,job); h=hashlib.sha256(json.dumps(payload.get("content") or {},sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
            return ProviderQueryResult(self.name,qid,"COMPLETE",started,now_iso(),offers,[],len(offers),h,{"query":query})
        except SkyscannerError as e:
            code=str(e).split(":",1)[0]; return ProviderQueryResult(self.name,qid,"TIMED_OUT" if "TIMEOUT" in code else "FAILED",started,now_iso(),[],[code],0,None,{"query":query})
    def _refresh(self,session_token,itinerary_id):
        c=self._request("POST",f"{BASE}/flights/live/itineraryrefresh/create/{session_token}",json={"itineraryId":itinerary_id}).json(); token=c.get("refreshSessionToken")
        if not token: raise SkyscannerError("REFRESH_NO_TOKEN")
        status=c.get("status"); content=c.get("content") or {}; started=time.monotonic()
        while status!="RESULT_STATUS_COMPLETE":
            if status=="RESULT_STATUS_FAILED": raise SkyscannerError("REFRESH_FAILED")
            if time.monotonic()-started>self.cfg.get("poll_timeout_sec",75): raise SkyscannerError("REFRESH_TIMEOUT")
            time.sleep(self.cfg.get("poll_interval_sec",3)); p=self._request("GET",f"{BASE}/flights/live/itineraryrefresh/poll/{token}").json(); status=p.get("status"); content=p.get("content") or content
        return content
    def revalidate(self,offer,job):
        meta={"revalidation_provider":self.name,"same_provider_revalidation":True,"independent_source_corroboration":False,"second_independent_acquisition":True}
        try:
            second=self.search(job,offer.search_id or "")
            if second.status!="COMPLETE": offer.validation_status="ERROR"; offer.last_validated_at=now_iso(); return offer,{**meta,"status":"ERROR","error_code":"SECOND_SEARCH_INCOMPLETE"}
            matches=[x for x in second.offers if exact_itinerary_match(offer,x) and x.booking_agent==offer.booking_agent]
            if not matches: offer.validation_status="DISAPPEARED"; offer.last_validated_at=now_iso(); return offer,{**meta,"status":"DISAPPEARED"}
            fresh=matches[0]; token=fresh.runtime.get("SESSION_TOKEN")
            content=self._refresh(token,fresh.itinerary_id) if token and fresh.itinerary_id else {}
            itins=((content.get("results") or {}).get("itineraries") or {}); it=itins.get(fresh.itinerary_id) or next(iter(itins.values()),{})
            pos=it.get("pricingOptions") or []; exact=[p for p in pos if str(p.get("id"))==str(fresh.source_offer_id)]
            if not exact: offer.validation_status="DISAPPEARED"; offer.last_validated_at=now_iso(); return offer,{**meta,"status":"DISAPPEARED","reason":"PRICING_OPTION_GONE"}
            po=exact[0]; amount=_price(po.get("price")); items=po.get("items") or []
            if len(items)!=1: fresh.booking_option_count=len(items); fresh.validation_status="NON_VALIDATABLE"; fresh.last_validated_at=now_iso(); return fresh,{**meta,"status":"NON_VALIDATABLE","error_code":"MULTIPLE_BOOKING_REQUIRED"}
            old=offer.price_brl; fresh.price=amount; fresh.price_brl=amount; fresh.total_price_confirmed=amount is not None; fresh.booking_url=items[0].get("deepLink") or fresh.booking_url; fresh.booking_option_count=1; fresh.validation_status="PRICE_CHANGED" if amount!=old else "VALIDATED"; fresh.last_validated_at=now_iso(); fresh.discovered_at=offer.discovered_at
            return fresh,{**meta,"status":fresh.validation_status,"old_price_brl":old,"new_price_brl":amount}
        except SkyscannerError as e:
            offer.validation_status="ERROR"; offer.last_validated_at=now_iso(); return offer,{**meta,"status":"ERROR","error_code":str(e)}
