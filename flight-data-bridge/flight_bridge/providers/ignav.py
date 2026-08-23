from __future__ import annotations
import hashlib, json, time
from datetime import datetime, timezone
from typing import Any, Callable
import requests
from .base import ProviderAdapter
from ..models import ProviderQueryResult, Offer, Direction, Segment, Connection
from ..fingerprints import itinerary_fingerprint, exact_itinerary_match
from ..ignav_contract import (
    IgnavContractError, IGNAV_API_CONTRACT_VERSION, OPENAPI_SOURCE_SHA,
    validate_search_response, validate_booking_response, parse_error_payload,
)

BASE = "https://ignav.com/api"
def now_iso(): return datetime.now(timezone.utc).isoformat()

class IgnavError(RuntimeError):
    def __init__(self, code:str, message:str="", *, http_status:int|None=None,
                 provider_error_type:str|None=None, provider_error_code:str|None=None,
                 retryable:bool=False, mapping_confidence:str="DOCUMENTED"):
        super().__init__(message or code)
        self.code=code; self.http_status=http_status
        self.provider_error_type=provider_error_type; self.provider_error_code=provider_error_code
        self.retryable=retryable; self.mapping_confidence=mapping_confidence

class IgnavAdapter(ProviderAdapter):
    name="IGNAV"; role="PRIMARY_DISCOVERY_TEMPORARY"
    def __init__(self, api_key:str, cfg:dict, session:requests.Session|None=None,
                 airport_db:dict|None=None, sleep_fn:Callable[[float],None]=time.sleep):
        self.api_key=api_key; self.cfg=cfg; self.http=session or requests.Session(); self._sleep=sleep_fn
        if airport_db is not None:
            self.airports=airport_db
        else:
            import airportsdata
            self.airports=airportsdata.load("IATA")
    def configured(self): return bool(self.api_key)
    @property
    def headers(self): return {"X-Api-Key":self.api_key,"Content-Type":"application/json"}

    def _response_error(self, r)->IgnavError:
        payload={}
        try: payload=r.json()
        except Exception: pass
        parsed=parse_error_payload(payload); status=getattr(r,"status_code",None)
        et=parsed.get("type"); ec=parsed.get("code"); msg=parsed.get("message") or getattr(r,"text","")[:300]
        if status==400: code,retry,confidence="INVALID_REQUEST",False,"DOCUMENTED"
        elif status==401: code,retry,confidence="AUTH_REQUIRED",False,"DOCUMENTED"
        elif status==402:
            code,retry="BILLING_REQUIRED",False
            confidence="DOCUMENTED" if ec=="billing_required" or et=="billing_error" else "STATUS_DOCUMENTED_CODE_UNVERIFIED"
        elif status==404: code,retry,confidence="NOT_FOUND",False,"DOCUMENTED"
        elif status==405: code,retry,confidence="METHOD_NOT_ALLOWED",False,"DOCUMENTED"
        elif status==424: code,retry,confidence="UPSTREAM_DEPENDENCY",True,"DOCUMENTED"
        elif status==429:
            if ec=="monthly_spend_limit_reached": code,confidence="BILLING_REQUIRED","DOCUMENTED"
            else: code,confidence="RATE_LIMITED","PROVISIONAL_HTTP_429"
            retry=False
        elif status is not None and status>=500: code,retry,confidence="PROVIDER_HTTP_ERROR",False,"STANDARD_HTTP"
        elif status is not None and status>=400: code,retry,confidence="PROVIDER_CLIENT_ERROR",False,"STANDARD_HTTP"
        else: code,retry,confidence="PROVIDER_HTTP_ERROR",False,"STANDARD_HTTP"
        return IgnavError(code,msg,http_status=status,provider_error_type=et,provider_error_code=ec,
                          retryable=retry,mapping_confidence=confidence)

    def _request(self, method, path, **kw):
        retries=max(1,int(self.cfg.get("max_retries",3)))
        timeout=self.cfg.get("request_timeout_sec",30); backoff=float(self.cfg.get("retry_backoff_base_sec",1)); last=None
        for attempt in range(1,retries+1):
            try:
                r=self.http.request(method,BASE+path,headers=self.headers,timeout=timeout,**kw)
            except requests.Timeout as e:
                last=IgnavError("PROVIDER_TIMEOUT",str(e),retryable=True,mapping_confidence="DOCUMENTED_NETWORK_RETRY")
                if attempt<retries: self._sleep(backoff*(2**(attempt-1))); continue
                raise last
            except requests.ConnectionError as e:
                last=IgnavError("PROVIDER_NETWORK_ERROR",str(e),retryable=True,mapping_confidence="DOCUMENTED_NETWORK_RETRY")
                if attempt<retries: self._sleep(backoff*(2**(attempt-1))); continue
                raise last
            except requests.RequestException as e:
                raise IgnavError("PROVIDER_NETWORK_ERROR",str(e),mapping_confidence="REQUESTS_EXCEPTION") from e
            if 200 <= r.status_code < 300: return r
            err=self._response_error(r); last=err
            if err.retryable and attempt<retries: self._sleep(backoff*(2**(attempt-1))); continue
            raise err
        raise last or IgnavError("PROVIDER_HTTP_ERROR")

    def health_check(self)->dict[str,Any]:
        checked=now_iso(); started=time.perf_counter(); status_code=None
        def result(status,error_code=None,confidence="DOCUMENTED"):
            return {"PROVIDER":"IGNAV","STATUS":status,"LATENCY_MS":round((time.perf_counter()-started)*1000,2),
                    "CHECKED_AT":checked,"HTTP_STATUS":status_code,"ERROR_CODE":error_code,"ERROR_MAPPING_CONFIDENCE":confidence}
        if not self.configured(): return result("AUTH_REQUIRED","API_KEY_MISSING")
        try:
            r=self.http.request("GET",BASE+"/airports",headers=self.headers,params={"q":"GRU","limit":1},
                                timeout=self.cfg.get("health_timeout_sec",8)); status_code=r.status_code
            if 200 <= status_code < 300:
                try: data=r.json()
                except Exception: return result("DEGRADED","SCHEMA_INVALID")
                if not isinstance(data,list) or any(not isinstance(x,dict) for x in data): return result("DEGRADED","SCHEMA_INVALID")
                return result("UP")
            err=self._response_error(r)
            state={"AUTH_REQUIRED":"AUTH_REQUIRED","BILLING_REQUIRED":"BILLING_REQUIRED","RATE_LIMITED":"RATE_LIMITED","UPSTREAM_DEPENDENCY":"DEGRADED"}.get(err.code)
            if not state: state="DOWN" if status_code>=500 else "DEGRADED"
            return result(state,err.provider_error_code or err.code,err.mapping_confidence)
        except requests.Timeout: return result("DOWN","PROVIDER_TIMEOUT","DOCUMENTED_NETWORK_RETRY")
        except requests.ConnectionError: return result("DOWN","PROVIDER_NETWORK_ERROR","DOCUMENTED_NETWORK_RETRY")
        except requests.RequestException: return result("DOWN","PROVIDER_NETWORK_ERROR","REQUESTS_EXCEPTION")

    def build_query(self, job):
        return {"legs":[
            {"origin":job["origin"],"destination":self.cfg["destination"],"departure_date":job["outbound_date"],"max_stops":self.cfg["max_connections_per_direction"]},
            {"origin":self.cfg["destination"],"destination":job["return_destination"],"departure_date":self.cfg["return_departure_date"],"max_stops":self.cfg["max_connections_per_direction"]}],
            "adults":self.cfg.get("adults",1),"cabin_class":"economy","market":"BR","allow_self_transfer":False,"airlines_exclude":["DT"]}

    def _country(self,iata): return (self.airports.get((iata or "").upper()) or {}).get("country")
    def _conn_minutes(self,a:Segment,b:Segment):
        if not a.arrival_utc or not b.departure_utc: return None
        try:
            x=datetime.fromisoformat(a.arrival_utc.replace("Z","+00:00")); y=datetime.fromisoformat(b.departure_utc.replace("Z","+00:00"))
            m=int((y-x).total_seconds()/60); return m if m>=0 else None
        except Exception: return None

    def _direction(self, leg:dict, leg_index:int, self_transfer:bool|None):
        segs=[]; unverified=[]; display=leg.get("carrier") if isinstance(leg.get("carrier"),str) else None
        for i,s in enumerate(leg.get("segments") or []):
            if "operating_carrier_code" in s: unverified.append(f"legs[{leg_index}].segments[{i}].operating_carrier_code")
            segs.append(Segment(segment_id=f"{leg_index}-{i}",origin=s.get("departure_airport") or "",destination=s.get("arrival_airport") or "",
                departure_local=s.get("departure_time_local") or "",arrival_local=s.get("arrival_time_local") or "",
                departure_utc=s.get("departure_time_utc"),arrival_utc=s.get("arrival_time_utc"),marketing_carrier=s.get("marketing_carrier_code"),
                operating_carrier=None,marketing_carrier_name=display,operating_carrier_name=s.get("operating_carrier_name"),
                flight_number=str(s.get("flight_number")) if s.get("flight_number") is not None else None,
                aircraft=s.get("aircraft"),duration_min=s.get("duration_minutes")))
        if not segs: return None,unverified
        conns=[]
        for a,b in zip(segs,segs[1:]):
            conns.append(Connection(b.origin,self._country(b.origin),self._conn_minutes(a,b),
                "SELF_TRANSFER" if self_transfer is True else ("MANAGED" if self_transfer is False else None),a.destination!=b.origin,self_transfer))
        return Direction(segs[0].origin,segs[-1].destination,segs[0].departure_local,segs[-1].arrival_local,
            (segs[-1].arrival_local or "")[:10],leg.get("duration_minutes"),max(0,len(segs)-1),segs[0].departure_utc,segs[-1].arrival_utc,segs,conns),unverified

    def _normalize_itinerary(self,it:dict,search_id:str,job:dict|None,forced_ignav_id:str|None=None):
        self_transfer=it.get("requires_self_transfer") if isinstance(it.get("requires_self_transfer"),bool) else None
        raw_legs=it.get("legs")
        if raw_legs is None and "outbound" in it: raw_legs=[it.get("outbound"),it.get("inbound")]
        dirs=[]; unverified=[]
        for idx,leg in enumerate([x for x in (raw_legs or []) if x is not None]):
            d,u=self._direction(leg,idx,self_transfer); dirs.append(d); unverified.extend(u)
        p=it.get("price") or {}; amount=float(p["amount"]) if isinstance(p.get("amount"),(int,float)) and not isinstance(p.get("amount"),bool) else None
        currency=p.get("currency") if isinstance(p.get("currency"),str) else None; verified=p.get("status")=="verified"
        ignav_id=forced_ignav_id if forced_ignav_id is not None else it.get("ignav_id"); bags=it.get("bags") if isinstance(it.get("bags"),dict) else {}
        offer=Offer(offer_id=None,commercial_offer_id=None,source_offer_id=ignav_id,itinerary_id=ignav_id,source="IGNAV",search_id=search_id,
            itinerary_fingerprint=None,price=amount,currency=currency,price_brl=amount if currency=="BRL" else None,fx_source=None,fx_timestamp=None,
            total_price_confirmed=bool(verified),taxes_included=None,cabin_class=it.get("cabin_class") if isinstance(it.get("cabin_class"),str) else None,
            personal_item=None,carry_on=bags.get("carry_on"),checked_bag=bags.get("checked"),booking_source="IGNAV",booking_agent=None,booking_url=None,
            offer_expires_at=None,discovered_at=now_iso(),last_validated_at=None,validation_status="NOT_REQUIRED",
            outbound=dirs[0] if len(dirs)>0 else None,inbound=dirs[1] if len(dirs)>1 else None,
            transfer_type="SELF_TRANSFER" if self_transfer is True else ("MANAGED" if self_transfer is False else None),booking_option_count=0)
        offer.itinerary_fingerprint=itinerary_fingerprint(offer); offer.offer_id=offer.itinerary_fingerprint
        offer.runtime={"IGNAV_ID":ignav_id,"JOB":job,"CONTRACT_VERSION":IGNAV_API_CONTRACT_VERSION}
        if unverified: offer.derived["UNVERIFIED_FIELDS"]=sorted(set(unverified))
        if not ignav_id: offer.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append("IGNAV_ID_UNKNOWN")
        return offer

    def _query_id(self,job): return f"{job['origin']}-{job['outbound_date']}-LIS-{self.cfg['return_departure_date']}-{job['return_destination']}"
    def search(self,job,search_id):
        started=now_iso(); qid=self._query_id(job)
        if not self.configured(): return ProviderQueryResult(self.name,qid,"FAILED",started,now_iso(),[],["AUTH_REQUIRED"])
        try:
            data=self._request("POST","/fares/search",json=self.build_query(job)).json(); validate_search_response(data,2)
            its=data["itineraries"]; offers=[self._normalize_itinerary(x,search_id,job) for x in its]
            raw=json.dumps(data,sort_keys=True,separators=(",",":"),default=str)
            return ProviderQueryResult(self.name,qid,"COMPLETE",started,now_iso(),offers,[],len(its),hashlib.sha256(raw.encode()).hexdigest(),
                {"CONTRACT_VERSION":IGNAV_API_CONTRACT_VERSION,"OPENAPI_SOURCE_SHA":OPENAPI_SOURCE_SHA})
        except IgnavContractError as e: return ProviderQueryResult(self.name,qid,"FAILED",started,now_iso(),[],[e.code],0,None,{"contract_detail":e.detail})
        except IgnavError as e:
            return ProviderQueryResult(self.name,qid,"TIMED_OUT" if e.code=="PROVIDER_TIMEOUT" else "FAILED",started,now_iso(),[],[e.code],0,None,
                {"http_status":e.http_status,"provider_error_type":e.provider_error_type,"provider_error_code":e.provider_error_code,"mapping_confidence":e.mapping_confidence})
        except (ValueError,TypeError,json.JSONDecodeError) as e: return ProviderQueryResult(self.name,qid,"FAILED",started,now_iso(),[],["SCHEMA_INVALID"],0,None,{"contract_detail":str(e)[:200]})

    @staticmethod
    def _full_option(opt:dict, expected_legs:int)->bool:
        idx=opt.get("leg_indexes")
        if isinstance(idx,list): return set(idx)==set(range(expected_legs)) and len(set(idx))==expected_legs
        named=opt.get("legs")
        return bool(expected_legs==2 and isinstance(named,list) and set(named)=={"outbound","inbound"} and len(set(named))==2)
    @staticmethod
    def _coverage(opt:dict)->set:
        if isinstance(opt.get("leg_indexes"),list): return set(opt["leg_indexes"])
        if isinstance(opt.get("legs"),list): return {0 if x=="outbound" else 1 for x in opt["legs"] if x in {"outbound","inbound"}}
        return set()

    def revalidate(self, offer, job):
        meta={"revalidation_provider":"IGNAV","same_provider_revalidation":True,"independent_source_corroboration":False,
              "second_full_search":False,"booking_links_refresh":False,"price_based_selection":False}
        if not job:
            offer.validation_status="NON_VALIDATABLE"; offer.last_validated_at=now_iso(); offer.booking_url=None
            offer.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append("REVALIDATION_JOB_UNKNOWN"); return offer,meta
        try:
            data=self._request("POST","/fares/search",json=self.build_query(job)).json(); validate_search_response(data,2)
            second=[self._normalize_itinerary(x,(offer.search_id or "search")+"-revalidation",job) for x in data["itineraries"]]
            exact=[x for x in second if exact_itinerary_match(offer,x)]; meta.update({"second_full_search":True,"second_search_exact_matches":len(exact)})
            if not exact:
                offer.validation_status="DISAPPEARED"; offer.last_validated_at=now_iso(); offer.booking_url=None; return offer,meta
            fresh=exact[0]; meta["source_offer_id_changed"]=fresh.source_offer_id!=offer.source_offer_id; ignav_id=fresh.runtime.get("IGNAV_ID")
            if not ignav_id:
                fresh.validation_status="NON_VALIDATABLE"; fresh.last_validated_at=now_iso(); fresh.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append("IGNAV_ID_UNKNOWN"); return fresh,meta
            data=self._request("POST","/fares/booking-links",json={"ignav_id":ignav_id}).json(); validate_booking_response(data,2); meta["booking_links_refresh"]=True
            booked=self._normalize_itinerary(data["itinerary"],(offer.search_id or "search")+"-booking",job,forced_ignav_id=ignav_id)
            if not exact_itinerary_match(fresh,booked):
                fresh.validation_status="CHANGED"; fresh.last_validated_at=now_iso(); fresh.booking_url=None
                fresh.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append("BOOKING_ITINERARY_CHANGED"); return fresh,meta
            options=data.get("booking_options") or []; full=[o for o in options if self._full_option(o,2)]
            meta.update({"booking_option_count":len(options),"full_journey_option_count":len(full)})
            if not full:
                coverage=set().union(*(self._coverage(o) for o in options)) if options else set(); booked.validation_status="NON_VALIDATABLE"; booked.last_validated_at=now_iso(); booked.booking_url=None
                if coverage=={0,1} and len(options)>1:
                    booked.booking_option_count=2; booked.derived.setdefault("SOURCE_HARD_REJECTION_REASONS",[]).append("MULTIPLE_BOOKING_REQUIRED")
                else:
                    booked.booking_option_count=0; booked.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append("BOOKING_FULL_JOURNEY_UNAVAILABLE")
                return booked,meta
            selected=full[0]; link=next((x for x in (selected.get("links") or []) if isinstance(x,dict) and x.get("url")),None)
            if not link:
                booked.validation_status="NON_VALIDATABLE"; booked.last_validated_at=now_iso(); booked.booking_url=None
                booked.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append("BOOKING_URL_MISSING"); return booked,meta
            booked.booking_option_count=1; booked.derived["BOOKING_ALTERNATIVE_COUNT"]=len(full); booked.booking_url=link["url"]
            booked.booking_agent=link.get("provider_name"); booked.booking_source=link.get("provider_type") or "IGNAV"
            lp=link.get("price")
            if isinstance(lp,dict):
                booked.price=float(lp["amount"]); booked.currency=lp["currency"]; booked.price_brl=booked.price if booked.currency=="BRL" else None
                booked.total_price_confirmed=lp.get("status")=="verified"
            booked.last_validated_at=now_iso(); booked.validation_status="PRICE_CHANGED" if (booked.price_brl!=offer.price_brl or booked.currency!=offer.currency) else "VALIDATED"
            return booked,meta
        except IgnavContractError as e:
            offer.validation_status="ERROR"; offer.last_validated_at=now_iso(); offer.booking_url=None; offer.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append("SCHEMA_INVALID")
            meta.update({"error":"SCHEMA_INVALID","contract_detail":e.detail}); return offer,meta
        except IgnavError as e:
            offer.validation_status="ERROR"; offer.last_validated_at=now_iso(); offer.booking_url=None; offer.derived.setdefault("SOURCE_NON_VALIDATABLE_REASONS",[]).append(e.code)
            meta.update({"error":e.code,"http_status":e.http_status,"provider_error_code":e.provider_error_code}); return offer,meta
