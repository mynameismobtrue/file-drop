from __future__ import annotations
import argparse,json,os,statistics,uuid
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone,timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import jsonschema
from .models import ProviderCycleResult
from .hard_filters import evaluate_offer
from .providers.skyscanner import SkyscannerAdapter
from .providers.ignav import IgnavAdapter

ROOT=Path(__file__).resolve().parents[1]; BRT=ZoneInfo("America/Sao_Paulo")
def now_iso(): return datetime.now(timezone.utc).isoformat()
def load_cfg(path=None): return json.loads((Path(path) if path else ROOT/"config/protocol_v2_2.json").read_text())
def atomic_json(path:Path,doc):
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+".tmp"); tmp.write_text(json.dumps(doc,ensure_ascii=False,indent=2)); os.replace(tmp,path)
def search_jobs(cfg):
    for origin in cfg["origins"]:
        for outbound in cfg["outbound_departure_dates"]:
            for ret in cfg["return_destinations"]:
                yield {"origin":origin,"outbound_date":outbound,"return_destination":ret,"query_type":"ROUND_TRIP" if origin==ret else "MULTI_CITY_OPEN_JAW"}
def scheduled_slot(started:datetime):
    local=started.astimezone(BRT); midnight=local.replace(hour=0,minute=0,second=0,microsecond=0); mins=int((local-midnight).total_seconds()/60); slot=(mins//90)*90; dt=midnight+timedelta(minutes=slot); return dt.astimezone(timezone.utc)
def ttl_status(completed_at,ttl_min):
    if not completed_at: return "UNAVAILABLE"
    dt=datetime.fromisoformat(completed_at.replace("Z","+00:00")); return "LIVE" if (datetime.now(timezone.utc)-dt).total_seconds()<=ttl_min*60 else "STALE"
def provider_cycle(adapter,jobs,search_id,cfg):
    results=[]
    with ThreadPoolExecutor(max_workers=min(4,len(jobs))) as ex:
        futs=[ex.submit(adapter.search,j,search_id) for j in jobs]
        for f in as_completed(futs): results.append(f.result())
    complete=sum(r.status=="COMPLETE" for r in results); failed=sum(r.status=="FAILED" for r in results); timed=sum(r.status=="TIMED_OUT" for r in results)
    expected=cfg["expected_queries_per_complete_provider"]
    if complete==expected: status="COMPLETE"; health="LIVE"
    elif complete>0: status="INCOMPLETE"; health="DEGRADED"
    elif timed==expected: status="TIMED_OUT"; health="UNAVAILABLE"
    else: status="FAILED"; health="UNAVAILABLE"
    codes=sorted({c for r in results for c in r.error_codes})
    if "AUTH_REQUIRED" in codes: health="AUTH_REQUIRED"
    elif "RATE_LIMITED" in codes: health="RATE_LIMITED"
    elif "BILLING_REQUIRED" in codes: health="BILLING_REQUIRED"
    return ProviderCycleResult(adapter.name,adapter.role,expected,len(results),complete,failed,timed,status,health,results,codes)
def cycle_dict(c):
    return {"provider":c.provider,"role":c.role,"PROVIDER_QUERIES_EXPECTED":c.expected,"PROVIDER_QUERIES_STARTED":c.started,"PROVIDER_QUERIES_COMPLETE":c.complete,"PROVIDER_QUERIES_FAILED":c.failed,"PROVIDER_QUERIES_TIMED_OUT":c.timed_out,"PROVIDER_SEARCH_STATUS":c.search_status,"SOURCE_HEALTH":c.source_health,"ERROR_CODES":c.error_codes,"queries":[{"query_id":q.query_id,"status":q.status,"started_at":q.started_at,"completed_at":q.completed_at,"raw_offers_count":q.raw_offers_count,"error_codes":q.error_codes,"response_sha256":q.response_sha256} for q in c.query_results]}
def dedupe(offers):
    out={}
    for o in offers:
        key=(o.source,o.source_offer_id,o.booking_agent,o.itinerary_fingerprint)
        out.setdefault(key,o)
    return list(out.values())
def _min(rows): return min(rows,key=lambda x:x["price_brl"]) if rows else None
def _summary(o):
    if not o:return None
    return {"price_brl":o.get("price_brl"),"offer_id":o.get("offer_id"),"commercial_offer_id":o.get("commercial_offer_id"),"origin":((o.get("outbound") or {}).get("origin")),"quality_class":((o.get("derived") or {}).get("QUALITY_CLASS")),"operating_carriers":sorted({s.get("operating_carrier") for d in [o.get("outbound"),o.get("inbound")] if d for s in d.get("segments",[]) if s.get("operating_carrier")})}
def history_metrics(history_dir:Path,current:list[dict],completed:str):
    observations=[]
    for p in history_dir.glob("**/*.json"):
        try: doc=json.loads(p.read_text())
        except Exception: continue
        if (doc.get("SEARCH_METADATA") or {}).get("SEARCH_STATUS") not in {"COMPLETE","COMPLETE_WITH_SOURCE_ERRORS"}: continue
        ts=(doc.get("SEARCH_METADATA") or {}).get("SEARCH_COMPLETED_AT")
        for o in doc.get("VALID_OFFERS",[]):
            if o.get("price_brl") is not None: observations.append((ts,o))
    observations.extend((completed,o) for o in current if o.get("price_brl") is not None)
    if not observations: return {"informational_only":True,"observation_count":0}
    now=datetime.fromisoformat(completed.replace("Z","+00:00")); today=now.astimezone(BRT).date()
    def parse(ts):
        try:return datetime.fromisoformat(ts.replace("Z","+00:00"))
        except:return None
    rows=[{"ts":ts,"dt":parse(ts),"o":o,"price_brl":float(o["price_brl"])} for ts,o in observations]
    cur=[r for r in rows if r["ts"]==completed]; day=[r for r in rows if r["dt"] and r["dt"].astimezone(BRT).date()==today]; h24=[r for r in rows if r["dt"] and r["dt"]>=now-timedelta(hours=24)]; d7=[r for r in rows if r["dt"] and r["dt"]>=now-timedelta(days=7)]
    def mr(rs):
        r=min(rs,key=lambda x:x["price_brl"]) if rs else None; return _summary(r["o"])|{"observed_at":r["ts"]} if r else None
    prices=[r["price_brl"] for r in rows]; current_min=min(cur,key=lambda x:x["price_brl"]) if cur else None; hist_min=min(rows,key=lambda x:x["price_brl"])
    prev_ts=sorted({r["ts"] for r in rows if r["ts"] and r["ts"]<completed},reverse=True); prev=[r for r in rows if prev_ts and r["ts"]==prev_ts[0]]; prev_min=min(prev,key=lambda x:x["price_brl"]) if prev else None
    direct=[r for r in rows if (r["o"].get("derived") or {}).get("MAX_CONNECTIONS")==0]; conn=[r for r in rows if (r["o"].get("derived") or {}).get("MAX_CONNECTIONS",0)>0]
    return {"informational_only":True,"observation_count":len(rows),"MIN_CYCLE":mr(cur),"MIN_DAY":mr(day),"MIN_24H":mr(h24),"MIN_7D":mr(d7),"MIN_SINCE_START":mr(rows),"AVERAGE":sum(prices)/len(prices),"MEDIAN":statistics.median(prices),"CHEAPEST_OPERATING_CARRIER":(_summary(hist_min["o"])["operating_carriers"] if hist_min else None),"CHEAPEST_ORIGIN":((hist_min["o"].get("outbound") or {}).get("origin") if hist_min else None),"MIN_DIRECT":mr(direct),"MIN_CONNECTION":mr(conn),"PREVIOUS_SEARCH_MIN":mr(prev),"DELTA_PREVIOUS":(current_min["price_brl"]-prev_min["price_brl"] if current_min and prev_min else None),"DELTA_HISTORICAL_MIN":(current_min["price_brl"]-hist_min["price_brl"] if current_min else None)}
def provider_map(cfg):
    return {
        "SKYSCANNER":SkyscannerAdapter(os.getenv("SKYSCANNER_API_KEY","").strip(),cfg),
        "IGNAV":IgnavAdapter(os.getenv("IGNAV_API_KEY","").strip(),cfg)
    }
def _last_complete(out_dir):
    p=out_dir/"snapshot.json"
    if not p.exists(): return None
    try:
        d=json.loads(p.read_text()); return {"search_id":d.get("SEARCH_METADATA",{}).get("SEARCH_ID"),"completed_at":d.get("SEARCH_METADATA",{}).get("SEARCH_COMPLETED_AT"),"path":"snapshot.json"}
    except Exception:return None
def build_base(cfg,search_id,started,jobs,scheduled_for):
    delay=max(0,int((datetime.fromisoformat(started.replace("Z","+00:00"))-scheduled_for).total_seconds())) if scheduled_for else None
    return {"DATA_BRIDGE_VERSION":cfg["data_bridge_version"],"PROTOCOL_VERSION":cfg["protocol_version"],"UI_VERSION":cfg["ui_version"],"STATE":cfg["state"],"SEARCH_METADATA":{"SEARCH_ID":search_id,"SCHEDULED_FOR":scheduled_for.isoformat() if scheduled_for else None,"SEARCH_STARTED_AT":started,"SEARCH_COMPLETED_AT":None,"ACTUAL_DELAY_SECONDS":delay,"SEARCH_STATUS":"STARTED","IS_COMPLETE":False,"FETCHED_AT":started,"SOURCE_TIMESTAMP":None,"TTL_STATUS":"UNAVAILABLE","FLIGHT_SEARCH_TTL_MIN":cfg["flight_search_ttl_min"],"QUERY_PARAMETERS":{"jobs":jobs},"ERROR_CODES":[]},"PRIMARY_STATUS":None,"ACTIVE_DISCOVERY_PROVIDER":None,"ACTIVE_DISCOVERY_ROLE":None,"COVERAGE_EQUIVALENCE_NOT_ASSERTED":False,"PROVIDERS_REQUESTED":[],"PROVIDER_RESULTS":[],"SOURCE_HEALTH":"UNAVAILABLE","LATEST_ATTEMPT":search_id,"LAST_COMPLETE_SNAPSHOT":None,"VALID_OFFERS":[],"REJECTED_OFFERS":[],"NON_VALIDATABLE_OFFERS":[],"ALERT_CANDIDATES":[],"VALIDATION_RESULTS":[],"PRICE_HISTORY":{},"COUNTS":{}}
def validate_snapshot(doc,out_dir):
    schema=json.loads((ROOT/"schema/snapshot.schema.json").read_text()); jsonschema.validate(doc,schema); raw=json.dumps(doc); forbidden=["SESSION_TOKEN","REFRESH_SESSION_TOKEN","SKYSCANNER_API_KEY","IGNAV_API_KEY","DUFFEL_ACCESS_TOKEN","ACCESS_TOKEN"]
    if any(x in raw for x in forbidden): raise RuntimeError("SECRET_SERIALIZATION_PROHIBITED")
def write_history(out_dir,doc):
    dt=datetime.fromisoformat(doc["SEARCH_METADATA"]["SEARCH_STARTED_AT"].replace("Z","+00:00")); p=out_dir/"history"/dt.strftime("%Y-%m-%d")/f"{dt:%H%M%S}-{doc['SEARCH_METADATA']['SEARCH_ID']}.json"; atomic_json(p,doc)
def run(out_dir:Path,cfg:dict,providers=None,event_name=None):
    started_dt=datetime.now(timezone.utc); started=started_dt.isoformat(); sid=f"fd-{started_dt:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"; jobs=list(search_jobs(cfg)); scheduled_for=scheduled_slot(started_dt) if event_name=="schedule" else None; doc=build_base(cfg,sid,started,jobs,scheduled_for); out_dir.mkdir(parents=True,exist_ok=True); doc["LAST_COMPLETE_SNAPSHOT"]=_last_complete(out_dir)
    providers=providers or provider_map(cfg); cycles=[]; selected=None; selected_adapter=None
    requested=[p for p in cfg["provider_priority"] if cfg.get(f"enable_{p.lower()}",True)]; doc["PROVIDERS_REQUESTED"]=requested
    for pname in requested:
        adapter=providers[pname]
        if not adapter.configured():
            c=ProviderCycleResult(pname,adapter.role,cfg["expected_queries_per_complete_provider"],0,0,0,0,"FAILED","AUTH_REQUIRED",[],["AUTH_REQUIRED"])
        else: c=provider_cycle(adapter,jobs,sid,cfg)
        cycles.append(c)
        if c.search_status=="COMPLETE": selected=c; selected_adapter=adapter; break
    doc["PROVIDER_RESULTS"]=[cycle_dict(c) for c in cycles]; doc["PRIMARY_STATUS"]=cycles[0].search_status if cycles else "FAILED"
    if not selected:
        completed=now_iso(); any_complete=sum(c.complete for c in cycles); statuses={c.search_status for c in cycles}; status="INCOMPLETE" if any_complete else ("TIMED_OUT" if "TIMED_OUT" in statuses else "FAILED"); health=cycles[-1].source_health if cycles else "UNAVAILABLE"; doc["SEARCH_METADATA"].update({"SEARCH_COMPLETED_AT":completed,"SEARCH_STATUS":status,"IS_COMPLETE":False,"FETCHED_AT":completed,"TTL_STATUS":"UNAVAILABLE","ERROR_CODES":sorted({x for c in cycles for x in c.error_codes})}); doc["SOURCE_HEALTH"]=health; doc["COUNTS"]={"RAW_OFFERS_COUNT":sum(q.raw_offers_count for c in cycles for q in c.query_results),"NORMALIZED_OFFERS_COUNT":0,"VALID_OFFERS_COUNT":0,"REJECTED_OFFERS_COUNT":0,"NON_VALIDATABLE_COUNT":0,"ALERT_CANDIDATES_COUNT":0}; atomic_json(out_dir/"status.json",doc); write_history(out_dir,doc); return 3,doc
    doc["ACTIVE_DISCOVERY_PROVIDER"]=selected.provider
    doc["ACTIVE_DISCOVERY_ROLE"]=selected.role
    fallback_used=bool(cycles and selected.provider!=cycles[0].provider)
    doc["COVERAGE_EQUIVALENCE_NOT_ASSERTED"]=fallback_used
    doc["SOURCE_HEALTH"]="DEGRADED" if fallback_used else "LIVE"
    offers=[]
    for q in selected.query_results: offers.extend(q.offers)
    offers=dedupe(offers)
    for o in offers: evaluate_offer(o,cfg)
    validations=[]
    for idx,o in enumerate(list(offers)):
        if o.derived.get("HARD_FILTER_PASS") and o.derived.get("ALERT_PRICE_PASS"):
            job=o.runtime.get("JOB") or next((j for j in jobs if j["origin"]==(o.outbound.origin if o.outbound else None) and j["return_destination"]==(o.inbound.destination if o.inbound else None) and j["outbound_date"]==((o.outbound.departure_local or "")[:10] if o.outbound else None)),None)
            fresh,meta=selected_adapter.revalidate(o,job); evaluate_offer(fresh,cfg); offers[idx]=fresh; validations.append({"offer_id":fresh.offer_id,"commercial_offer_id":fresh.commercial_offer_id,"itinerary_fingerprint":fresh.itinerary_fingerprint,"status":fresh.validation_status,"validated_at":fresh.last_validated_at,**meta})
    valid=[]; rejected=[]; nonvalid=[]; alerts=[]
    for o in offers:
        d=o.to_dict(); state=o.derived.get("ELIGIBILITY_STATE")
        if state=="ELIGIBLE": valid.append(d)
        elif state=="HARD_REJECTED": rejected.append(d)
        else: nonvalid.append(d)
        if o.derived.get("VERIFIED_ALERT_CANDIDATE"): alerts.append(d)
    completed=now_iso(); doc["SEARCH_METADATA"].update({"SEARCH_COMPLETED_AT":completed,"SEARCH_STATUS":"COMPLETE_WITH_SOURCE_ERRORS" if fallback_used else "COMPLETE","IS_COMPLETE":True,"FETCHED_AT":completed,"SOURCE_TIMESTAMP":completed,"TTL_STATUS":"LIVE","ERROR_CODES":(["PRIMARY_UNAVAILABLE_FALLBACK_USED"]+sorted({x for c in cycles[:-1] for x in c.error_codes})) if fallback_used else []}); doc["VALID_OFFERS"]=valid; doc["REJECTED_OFFERS"]=rejected; doc["NON_VALIDATABLE_OFFERS"]=nonvalid; doc["ALERT_CANDIDATES"]=alerts; doc["VALIDATION_RESULTS"]=validations; doc["COUNTS"]={"RAW_OFFERS_COUNT":sum(q.raw_offers_count for q in selected.query_results),"NORMALIZED_OFFERS_COUNT":len(offers),"VALID_OFFERS_COUNT":len(valid),"REJECTED_OFFERS_COUNT":len(rejected),"NON_VALIDATABLE_COUNT":len(nonvalid),"ALERT_CANDIDATES_COUNT":len(alerts)}; doc["PRICE_HISTORY"]=history_metrics(out_dir/"history",valid,completed)
    validate_snapshot(doc,out_dir); atomic_json(out_dir/"snapshot.json",doc); atomic_json(out_dir/"status.json",doc); write_history(out_dir,doc); return 0,doc

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out-dir",default=str(ROOT)); ap.add_argument("--config",default=None); args=ap.parse_args(); code,_=run(Path(args.out_dir),load_cfg(args.config),event_name=os.getenv("GITHUB_EVENT_NAME")); raise SystemExit(code)
if __name__=="__main__": main()
