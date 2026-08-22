#!/usr/bin/env python3
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.2.0"
TICKER_URL = "https://api.mercadobitcoin.net/api/v4/tickers?symbols=BTC-BRL"
BOOK_LIMIT_REQUESTED = 1000
BOOK_URL = f"https://api.mercadobitcoin.net/api/v4/BTC-BRL/orderbook?limit={BOOK_LIMIT_REQUESTED}"
AMOUNTS = [50, 100, 150, 200, 300, 400, 500]
OUT_DIR = Path(__file__).resolve().parent


def now_iso(): return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def get_json(url, attempts=3):
    last_error = None; last_status = None
    for i in range(attempts):
        if i: time.sleep([0, 0.4, 1.0][min(i, 2)])
        req = urllib.request.Request(url, headers={"Accept":"application/json","User-Agent":"mb-data-bridge-github/1.2"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                last_status = getattr(r, "status", 200); body = r.read().decode("utf-8")
                if not body.strip(): last_error = "EMPTY_BODY"; continue
                return {"ok":True,"data":json.loads(body),"attempts":i+1,"status":last_status,"error":None}
        except Exception as e: last_error = f"{type(e).__name__}:{e}"[:240]
    return {"ok":False,"data":None,"attempts":attempts,"status":last_status,"error":last_error or "UNKNOWN_ERROR"}

def n(v):
    try:
        if v is None or v == "": return None
        return float(str(v).replace(",", "."))
    except Exception: return None

def iso_ts(v):
    if v is None or v == "": return None
    try:
        x=float(v); x=x/1000.0 if x>1e12 else x
        if x>1e9: return datetime.fromtimestamp(x,tz=timezone.utc).isoformat().replace("+00:00","Z")
    except Exception: pass
    try:
        dt=datetime.fromisoformat(str(v).replace("Z","+00:00")); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
    except Exception: return None

def unwrap_ticker(raw):
    if isinstance(raw,list): return raw[0] if raw else None
    if isinstance(raw,dict):
        for k in ("data","tickers"):
            if isinstance(raw.get(k),list) and raw[k]: return raw[k][0]
            if isinstance(raw.get(k),dict): return raw[k]
        return raw
    return None

def normalize_ticker(raw):
    x=unwrap_ticker(raw)
    if not isinstance(x,dict): return None
    return {"pair":str(x.get("pair") or x.get("symbol") or "BTC-BRL"),
            "last":n(x.get("last") or x.get("last_price") or x.get("close") or x.get("price")),
            "high":n(x.get("high") or x.get("high_24h") or x.get("max")),
            "low":n(x.get("low") or x.get("low_24h") or x.get("min")),
            "open":n(x.get("open") or x.get("open_24h")),
            "volume":n(x.get("vol") or x.get("volume") or x.get("volume_24h") or x.get("base_volume")),
            "timestamp":iso_ts(x.get("date") or x.get("timestamp") or x.get("ts") or x.get("updated_at") or x.get("time"))}

def unwrap_book(raw):
    if isinstance(raw,dict):
        if "bids" in raw or "asks" in raw: return raw
        d=raw.get("data")
        if isinstance(d,dict) and ("bids" in d or "asks" in d): return d
        if isinstance(d,list) and d and isinstance(d[0],dict): return d[0]
    if isinstance(raw,list) and raw and isinstance(raw[0],dict): return raw[0]
    return None

def levels(v):
    out=[]
    if not isinstance(v,list): return out
    for row in v:
        price=qty=None
        if isinstance(row,list) and len(row)>=2: price,qty=n(row[0]),n(row[1])
        elif isinstance(row,dict):
            price=n(row.get("price") or row.get("unit_price") or row.get("limit_price") or row.get("rate"))
            qty=n(row.get("amount") or row.get("qty") or row.get("quantity") or row.get("volume") or row.get("size"))
        if price and qty and price>0 and qty>0: out.append((price,qty))
    return out

def normalize_book(raw):
    x=unwrap_book(raw)
    if not isinstance(x,dict): return None
    bids=sorted(levels(x.get("bids") or x.get("bid") or []),key=lambda z:z[0],reverse=True)
    asks=sorted(levels(x.get("asks") or x.get("ask") or []),key=lambda z:z[0])
    return {"bids":bids,"asks":asks,"best_bid":bids[0][0] if bids else None,"best_ask":asks[0][0] if asks else None,
            "timestamp":iso_ts(x.get("timestamp") or x.get("date") or x.get("ts") or x.get("updated_at") or x.get("time"))}

def validate_book(b):
    if not b: return False,"BOOK_NOT_FOUND"
    if not b["bids"]: return False,"BIDS_EMPTY"
    if not b["asks"]: return False,"ASKS_EMPTY"
    if not b["best_bid"] or not b["best_ask"]: return False,"BEST_PRICE_INVALID"
    if b["best_ask"]<=b["best_bid"]: return False,"ASK_NOT_GREATER_THAN_BID"
    return True,None

def vwap_buy(asks,brl,best_ask):
    remaining=float(brl); spent=btc=0.0
    for price,qty in asks:
        if remaining<=1e-9: break
        cap=price*qty; take=min(remaining,cap); spent+=take; btc+=take/price; remaining-=take
    if remaining>1e-6 or btc<=0: return {"amount_brl":brl,"sufficient_depth":False,"vwap_brl":None,"slippage_pct_vs_best_ask":None,"btc_acquired":None}
    vwap=spent/btc; slip=((vwap/best_ask)-1)*100 if best_ask else None
    return {"amount_brl":brl,"sufficient_depth":True,"vwap_brl":round(vwap,8),"slippage_pct_vs_best_ask":round(slip,8),"btc_acquired":round(btc,12)}

def age_seconds(ts):
    if not ts: return None
    try: return max(0,round((datetime.now(timezone.utc)-datetime.fromisoformat(ts.replace("Z","+00:00"))).total_seconds()))
    except Exception: return None

def fmt(v):
    if v is None: return "NA"
    if isinstance(v,bool): return "true" if v else "false"
    return str(v)

def main():
    fetched_at=now_iso(); ticker_raw=get_json(TICKER_URL,2); book_raw=get_json(BOOK_URL,3)
    ticker=normalize_ticker(ticker_raw["data"]) if ticker_raw["ok"] else None
    book=normalize_book(book_raw["data"]) if book_raw["ok"] else None
    ticker_valid=bool(ticker and ticker.get("last") and ticker["last"]>0); book_valid,book_reason=validate_book(book)
    ticker_ts=ticker.get("timestamp") if ticker_valid else None; book_ts=book.get("timestamp") if book_valid else None
    book_freshness_ts=(book_ts or fetched_at) if book_valid else None; book_time_basis="BOOK_TIMESTAMP" if book_ts else ("FETCHED_AT" if book_valid else None)
    bid=book["best_bid"] if book_valid else None; ask=book["best_ask"] if book_valid else None
    spread_brl=ask-bid if book_valid else None; mid=(ask+bid)/2 if book_valid else None; spread_pct=(spread_brl/mid)*100 if mid else None
    source_ts=book_freshness_ts or ticker_ts or fetched_at
    bid_levels=len(book["bids"]) if book_valid else 0; ask_levels=len(book["asks"]) if book_valid else 0
    bid_limit_reached=bool(book_valid and bid_levels>=BOOK_LIMIT_REQUESTED); ask_limit_reached=bool(book_valid and ask_levels>=BOOK_LIMIT_REQUESTED)
    empty=lambda x:{"amount_brl":x,"sufficient_depth":False,"vwap_brl":None,"slippage_pct_vs_best_ask":None,"btc_acquired":None}
    vwaps={str(x):vwap_buy(book["asks"],x,ask) if book_valid else empty(x) for x in AMOUNTS}
    status="OK" if ticker_valid and book_valid else ("DEGRADED" if ticker_valid or book_valid else "ERROR")
    snapshot={"service":"mb-data-bridge-github","version":VERSION,"status":status,"source":"MERCADO_BITCOIN","pair":"BTC-BRL","fetched_at":fetched_at,"source_timestamp":source_ts,
      "ticker":{"valid":ticker_valid,"attempts":ticker_raw["attempts"],"http_status":ticker_raw["status"],"last_brl":ticker.get("last") if ticker_valid else None,"high_brl":ticker.get("high") if ticker_valid else None,"low_brl":ticker.get("low") if ticker_valid else None,"open_brl":ticker.get("open") if ticker_valid else None,"volume_btc":ticker.get("volume") if ticker_valid else None,"timestamp":ticker_ts,"error":ticker_raw.get("error")},
      "orderbook":{"valid":book_valid,"attempts":book_raw["attempts"],"http_status":book_raw["status"],"validation_error":book_reason,"timestamp":book_ts,"freshness_timestamp":book_freshness_ts,"time_basis":book_time_basis,"limit_requested":BOOK_LIMIT_REQUESTED,"bid_levels":bid_levels,"ask_levels":ask_levels,"bid_limit_reached":bid_limit_reached,"ask_limit_reached":ask_limit_reached,"best_bid_brl":bid,"best_ask_brl":ask,"spread_brl":spread_brl,"spread_pct":spread_pct,"error":book_raw.get("error")},
      "execution":{"vwap_buy":vwaps},"integrity":{"execution_book_ready":book_valid,"read_only":True,"no_trading_credentials":True}}
    OUT_DIR.mkdir(parents=True,exist_ok=True); (OUT_DIR/"snapshot.json").write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=[]
    def put(k,v): lines.append(f"{k}={fmt(v)}")
    put("SERVICE",snapshot["service"]);put("VERSION",VERSION);put("STATUS",status);put("SOURCE","MERCADO_BITCOIN");put("PAIR","BTC-BRL");put("FETCHED_AT",fetched_at);put("SOURCE_TIMESTAMP",source_ts)
    put("TICKER_VALID",ticker_valid);put("TICKER_ATTEMPTS",ticker_raw["attempts"]);put("TICKER_TIMESTAMP",ticker_ts);put("LAST_BRL",snapshot["ticker"]["last_brl"]);put("HIGH_BRL",snapshot["ticker"]["high_brl"]);put("LOW_BRL",snapshot["ticker"]["low_brl"]);put("OPEN_BRL",snapshot["ticker"]["open_brl"]);put("VOLUME_BTC",snapshot["ticker"]["volume_btc"])
    put("BOOK_VALID",book_valid);put("BOOK_ATTEMPTS",book_raw["attempts"]);put("BOOK_TIMESTAMP",book_ts);put("BOOK_FRESHNESS_TIMESTAMP",book_freshness_ts);put("BOOK_TIME_BASIS",book_time_basis);put("BOOK_LIMIT_REQUESTED",BOOK_LIMIT_REQUESTED);put("BOOK_BID_LEVELS",bid_levels);put("BOOK_ASK_LEVELS",ask_levels);put("BOOK_BID_LIMIT_REACHED",bid_limit_reached);put("BOOK_ASK_LIMIT_REACHED",ask_limit_reached);put("BOOK_VALIDATION_ERROR",book_reason)
    put("BEST_BID_BRL",bid);put("BEST_ASK_BRL",ask);put("SPREAD_BRL",spread_brl);put("SPREAD_PCT",spread_pct)
    for x in AMOUNTS:
        r=vwaps[str(x)];put(f"VWAP_BUY_R{x}",r["vwap_brl"]);put(f"SLIPPAGE_R{x}_PCT",r["slippage_pct_vs_best_ask"]);put(f"DEPTH_OK_R{x}",r["sufficient_depth"])
    put("EXECUTION_BOOK_READY",book_valid);put("EXECUTION_DATA_READY",book_valid);put("READ_ONLY",True);put("NO_TRADING_CREDENTIALS",True)
    if ticker_raw.get("error"):put("TICKER_ERROR",ticker_raw["error"])
    if book_raw.get("error"):put("BOOK_ERROR",book_raw["error"])
    (OUT_DIR/"snapshot.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"snapshot version={VERSION} status={status} ticker={ticker_valid} book={book_valid} levels={bid_levels}/{ask_levels} book_time={book_time_basis}")
if __name__=="__main__": main()
