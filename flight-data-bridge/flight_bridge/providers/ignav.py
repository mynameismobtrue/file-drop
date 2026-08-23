from __future__ import annotations
import hashlib,json,time
from datetime import datetime,timezone
from typing import Any
import requests
try:
    import airportsdata
except Exception:
    airportsdata=None
from .base import ProviderAdapter
from ..models import Offer,Direction,Segment,Connection,ProviderQueryResult
from ..fingerprints import itinerary_fingerprint, exact_itinerary_match

BASE="https://ignav.com/api"
class IgnavError(RuntimeError): pass

def now_iso(): return datetime.now(timezone.utc).isoformat()

class IgnavAdapter(ProviderAdapter):
    name="IGNAV"; role="PRIMARY_DISCOVERY_TEMPORARY"
    def __init__(self,api_key:str,cfg:dict,session:requests.Session|None=None):
        self.api_key=api_key; self.cfg=cfg; self.http=session or requests.Session()
        self._airports=airportsdata.load("IATA") if airportsdata else {}
    def configured(self): return bool(self.api_key)
    @property
    def headers(self): return {"X-Api-Key":self.api_key,"Content-Type":"application/json"}
    def _request(self,method,url,**kwargs):
        last=None
        for attempt in range(1,self.cfg.get("max_retries",3)+1):
            try:
                r=self.http.request(method,url,headers=self.headers,timeout=self.cfg.get("request_timeout_sec",30),**kwargs)
                if r.status_code==401: raise IgnavError("AUTH_REQUIRED")
                if r.status_code==402: raise IgnavError("BILLING_REQUIRED")
                if r.status_code==429: raise IgnavError("RATE_LIMITED")
                if r.status_code>=500:
                    last=IgnavError(f"PROVIDER_HTTP_ERROR_{r.status_code}"); time.sleep(min(2**attempt,8)); continue
                r.raise_for_status(); return r
            except IgnavError: raise
            except Exception as e:
                last=e
                if attempt<self.cfg.get("max_retries",3): time.sleep(min(2**attempt,8))
        raise IgnavError(f"PROVIDER_TIMEOUT_OR_HTTP:{type(last).__name__}")
    def _country(self,iata):
        row=self._airports.get((iata or "").upper()) if self._airports else None
        return (row or {}).get("country")
    def build_query(self,job):
        return {
            "legs":[
                {"origin":job["origin"],"destination":self.cfg["destination"],"departure_date":job["outbound_date"],"max_stops":1},
                {"origin":self.cfg["destination"],"destination":job["return_destination"],"departure_date":self.cfg["return_departure_date"],"max_stops":1}
            ],
            "adults":self.cfg.get("adults",1),"cabin_class":"economy","market":"BR",
            "allow_self_transfer":False,"airlines_exclude":["DT"]
        }
    def _direction(self,leg:dict)->Direction:
        segs=[]
        for i,s in enumerate(leg.get("segments") or []):
            segs.append(Segment(
                segment_id=str(s.get("segment_id") or i),origin=s.get("departure_airport") or "",destination=s.get("arrival_airport") or "",
                departure_local=s.get("departure_time_local") or "",arrival_local=s.get("arrival_time_local") or "",
                departure_utc=s.get("departure_time_utc"),arrival_utc=s.get("arrival_time_utc"),
                marketing_carrier=s.get("marketing_carrier_code"),operating_carrier=s.get("operating_carrier_code"),
                marketing_carrier_name=s.get("marketing_carrier_name") or leg.get("carrier"),operating_carrier_name=s.get("operating_carrier_name"),
                flight_number=s.get("flight_number"),aircraft=s.get("aircraft"),duration_min=s.get("duration_minutes")
            ))
        conns=[]
        for a,b in zip(segs,segs[1:]):
            minutes=None
            if a.arrival_utc and b.departure_utc:
                try:
                    da=datetime.fromisoformat(a.arrival_utc.replace("Z","+00:00")); db=datetime.fromisoformat(b.departure_utc.replace("Z","+00:00")); minutes=int((db-da).total_seconds()/60)
                except Exception: minutes=None
            conns.append(Connection(
                connection_airport=b.origin,connection_country=self._country(b.origin),connection_duration_min=minutes,
                transfer_type="MANAGED" if leg.get("requires_self_transfer") is False else "SELF_TRANSFER",
                airport_change=(a.destination!=b.origin),self_transfer=leg.get("requires_self_transfer")
            ))
        dep=segs[0].departure_local if segs else ""; arr=segs[-1].arrival_local if segs else ""
        return Direction(origin=segs[0].origin if segs else "",destination=segs[-1].destination if segs else "",departure_local=dep,arrival_local=arr,
                         arrival_date_local=arr[:10] if arr else "",total_duration_min=leg.get("duration_minutes"),connection_count=max(len(segs)-1,0) if segs else None,
                         departure_utc=segs[0].departure_utc if segs else None,arrival_utc=segs[-1].arrival_utc if segs else None,segments=segs,connections=conns)
    def _normalize_itinerary(self,it:dict,search_id:str)->Offer:
        legs=it.get("legs") or []
        ob=self._direction(legs[0]) if len(legs)>0 else None; ib=self._direction(legs[1]) if len(legs)>1 else None
        price=it.get("price") or {}; amount=price.get("amount"); currency=price.get("currency")
        try: amount=float(amount) if amount is not None else None
        except Exception: amount=None
        verified=(price.get("status") or "").lower()=="verified"
        bags=it.get("bags") or {}
        o=Offer(None,None,it.get("ignav_id"),it.get("ignav_id"),self.name,search_id,None,amount,currency,amount if currency=="BRL" else None,None,None,
                bool(verified and amount is not None and currency=="BRL"),None,it.get("cabin_class"),None,bags.get("carry_on"),bags.get("checked"),
                self.name,None,None,None,now_iso(),None,"NOT_REQUIRED",ob,ib,"SELF_TRANSFER" if it.get("requires_self_transfer") else "MANAGED",0)
        o.itinerary_fingerprint=itinerary_fingerprint(o); o.offer_id=o.itinerary_fingerprint
        o.runtime["IGNAV_ID"]=it.get("ignav_id")
        return o
    def search(self,job,search_id):
        started=now_iso(); query_id=f"{job['origin']}-{job['outbound_date']}-LIS-{self.cfg['return_departure_date']}-{job['return_destination']}"
        if not self.configured():
            return ProviderQueryResult(self.name,query_id,"FAILED",started,now_iso(),[],["AUTH_REQUIRED"])
        payload=self.build_query(job)
        try:
            data=self._request("POST",f"{BASE}/fares/search",json=payload).json()
            itineraries=data.get("itineraries") or []
            offers=[self._normalize_itinerary(it,search_id) for it in itineraries]
            h=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
            return ProviderQueryResult(self.name,query_id,"COMPLETE",started,now_iso(),offers,[],len(itineraries),h,{"query":payload})
        except IgnavError as e:
            code=str(e).split(":",1)[0]
            return ProviderQueryResult(self.name,query_id,"TIMED_OUT" if "TIMEOUT" in code else "FAILED",started,now_iso(),[],[code],0,None,{"query":payload})
    def revalidate(self,offer,job):
        meta={"revalidation_provider":self.name,"same_provider_revalidation":True,"independent_source_corroboration":False}
        if not self.configured() or not offer.runtime.get("IGNAV_ID"):
            offer.validation_status="ERROR"; return offer,{**meta,"error_code":"AUTH_REQUIRED_OR_ID_MISSING"}
        try:
            data=self._request("POST",f"{BASE}/fares/booking-links",json={"ignav_id":offer.runtime["IGNAV_ID"]}).json()
            current=data.get("itinerary") or {}
            fresh=self._normalize_itinerary(current,offer.search_id or "")
            if not exact_itinerary_match(offer,fresh):
                offer.validation_status="DISAPPEARED"; offer.last_validated_at=now_iso(); return offer,{**meta,"status":"DISAPPEARED"}
            options=data.get("booking_options") or []
            full=[]
            for opt in options:
                idx=opt.get("leg_indexes")
                if idx is None:
                    named=opt.get("legs") or []
                    covers=len(named)>=2
                else:
                    covers=set(idx)=={0,1}
                if covers:
                    for link in opt.get("links") or []:
                        if link.get("url"): full.append((opt,link))
            if not full:
                fresh.booking_option_count=len(options); fresh.validation_status="NON_VALIDATABLE"; fresh.last_validated_at=now_iso(); return fresh,{**meta,"status":"NON_VALIDATABLE","error_code":"MULTIPLE_BOOKING_REQUIRED"}
            # Keep separate commercial offers; for alert revalidation choose exact itinerary and first complete option, not cheapest across unrelated legs.
            opt,link=full[0]
            fresh.booking_option_count=1; fresh.booking_url=link.get("url"); fresh.booking_agent=link.get("provider_name"); fresh.booking_source=link.get("provider_type") or self.name
            p=link.get("price") or current.get("price") or {}; amount=p.get("amount"); cur=p.get("currency")
            try: amount=float(amount) if amount is not None else fresh.price
            except Exception: amount=fresh.price
            if cur: fresh.currency=cur
            if fresh.currency=="BRL" and amount is not None: fresh.price=amount; fresh.price_brl=amount; fresh.total_price_confirmed=(p.get("status") or "verified").lower()=="verified"
            fresh.validation_status="PRICE_CHANGED" if fresh.price_brl!=offer.price_brl else "VALIDATED"; fresh.last_validated_at=now_iso()
            return fresh,{**meta,"status":fresh.validation_status,"old_price_brl":offer.price_brl,"new_price_brl":fresh.price_brl}
        except IgnavError as e:
            offer.validation_status="ERROR"; offer.last_validated_at=now_iso(); return offer,{**meta,"status":"ERROR","error_code":str(e)}
