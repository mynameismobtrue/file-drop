#!/usr/bin/env python3
import argparse
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

PAIR = "BTC-BRL"
SOURCE = "MERCADO_BITCOIN"
TZ_BRT = ZoneInfo("America/Sao_Paulo")
CUTOFF_LOCAL_TIME = time(16, 30)
POSITION_BTC = Decimal("0.00015382")
DISPLAY_BASELINE_BRL = Decimal("47.52")
TRADE_FRESHNESS_SECONDS = 120
OUT_DIR = Path(__file__).resolve().parent.parent / "portfolio-history"
TRADES_BASE = f"https://api.mercadobitcoin.net/api/v4/{PAIR}/trades"
CANDLES_BASE = "https://api.mercadobitcoin.net/api/v4/candles"
USER_AGENT = "mb-portfolio-history/1.0"


def q2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q6(value):
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def get_json(base_url, params, attempts=3):
    url = base_url + "?" + urllib.parse.urlencode(params)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                body = response.read().decode("utf-8")
                return {
                    "ok": True,
                    "data": json.loads(body),
                    "url": url,
                    "attempts": attempt,
                    "error": None,
                }
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{exc}"[:300]
    return {"ok": False, "data": None, "url": url, "attempts": attempts, "error": last_error}


def parse_target_date(value):
    if value:
        return date.fromisoformat(value)
    return datetime.now(TZ_BRT).date()


def build_cutoff(target_date):
    local = datetime.combine(target_date, CUTOFF_LOCAL_TIME, tzinfo=TZ_BRT)
    return local, local.astimezone(timezone.utc)


def historical_trade_mark(cutoff_utc):
    cutoff_ts = int(cutoff_utc.timestamp())
    left_ts = cutoff_ts - TRADE_FRESHNESS_SECONDS
    response = get_json(
        TRADES_BASE,
        {"from": left_ts, "to": cutoff_ts, "limit": 1000},
    )
    if not response["ok"] or not isinstance(response["data"], list):
        return None, response

    eligible = []
    for row in response["data"]:
        try:
            ts = int(row.get("date"))
            price = Decimal(str(row.get("price")))
            if left_ts <= ts <= cutoff_ts and price > 0:
                eligible.append((ts, price, row.get("tid")))
        except Exception:
            continue
    if not eligible:
        return None, response

    ts, price, tid = max(eligible, key=lambda item: (item[0], str(item[2] or "")))
    age = cutoff_ts - ts
    if age > TRADE_FRESHNESS_SECONDS:
        return None, response
    return {
        "status": "AVAILABLE",
        "method": "MB_HISTORICAL_LAST_TRADE",
        "price_brl": price,
        "source_timestamp": datetime.fromtimestamp(ts, tz=timezone.utc),
        "age_seconds_at_cutoff": age,
        "trade_id": tid,
        "raw_url": response["url"],
    }, response


def historical_candle_mark(cutoff_utc):
    cutoff_ts = int(cutoff_utc.timestamp())
    # to=cutoff-1 prevents using a candle that starts at the cutoff itself.
    response = get_json(
        CANDLES_BASE,
        {"symbol": PAIR, "resolution": "1m", "to": cutoff_ts - 1, "countback": 5},
    )
    data = response.get("data")
    if not response["ok"] or not isinstance(data, dict):
        return None, response
    timestamps = data.get("t") or []
    closes = data.get("c") or []
    eligible = []
    for idx, bucket_start in enumerate(timestamps):
        try:
            start_ts = int(bucket_start)
            close = Decimal(str(closes[idx]))
            bucket_end = start_ts + 60
            if bucket_end <= cutoff_ts and close > 0:
                eligible.append((start_ts, bucket_end, close))
        except Exception:
            continue
    if not eligible:
        return None, response

    start_ts, end_ts, close = max(eligible, key=lambda item: item[0])
    return {
        "status": "AVAILABLE",
        "method": "MB_HISTORICAL_CANDLE_1M_CLOSE",
        "price_brl": close,
        "source_timestamp": datetime.fromtimestamp(end_ts, tz=timezone.utc),
        "candle_start_timestamp": datetime.fromtimestamp(start_ts, tz=timezone.utc),
        "age_seconds_at_cutoff": cutoff_ts - end_ts,
        "raw_url": response["url"],
    }, response


def load_previous_latest(target_date):
    latest_path = OUT_DIR / "latest.json"
    if not latest_path.exists():
        return None
    try:
        previous = json.loads(latest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    previous_date = previous.get("target_date")
    if previous_date == target_date.isoformat():
        return previous.get("previous_archive")
    return previous


def serialize_mark(mark):
    if not mark:
        return None
    out = dict(mark)
    for key in ("price_brl",):
        if isinstance(out.get(key), Decimal):
            out[key] = float(out[key])
    for key in ("source_timestamp", "candle_start_timestamp"):
        if isinstance(out.get(key), datetime):
            out[key] = out[key].isoformat().replace("+00:00", "Z")
    return out


def previous_summary(previous, current_value):
    if not previous or previous.get("mark_status") != "AVAILABLE":
        return None
    try:
        previous_value = Decimal(str(previous["portfolio"]["value_brl_raw"]))
        delta = current_value - previous_value
        delta_pct = (current_value / previous_value - Decimal("1")) * Decimal("100") if previous_value else Decimal("0")
        direction = "AUMENTOU" if delta > 0 else ("CAIU" if delta < 0 else "ESTÁVEL")
        return {
            "target_date": previous.get("target_date"),
            "value_brl": float(q2(previous_value)),
            "value_brl_raw": float(previous_value),
            "delta_brl": float(q2(delta)),
            "delta_pct": float(q6(delta_pct)),
            "direction": direction,
        }
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="Archive a 16:30 BRT Mercado Bitcoin mark for the portfolio tracker.")
    parser.add_argument("--date", dest="target_date", help="Target BRT date in YYYY-MM-DD. Defaults to today in America/Sao_Paulo.")
    args = parser.parse_args()

    target_date = parse_target_date(args.target_date)
    cutoff_local, cutoff_utc = build_cutoff(target_date)
    generated_at = datetime.now(timezone.utc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    trade_mark, trade_response = historical_trade_mark(cutoff_utc)
    candle_response = None
    mark = trade_mark
    if mark is None:
        mark, candle_response = historical_candle_mark(cutoff_utc)

    previous = load_previous_latest(target_date)
    record = {
        "schema_version": "1.0.0",
        "purpose": "PORTFOLIO_TRACKER_ONLY",
        "not_for_research_reference": True,
        "source": SOURCE,
        "pair": PAIR,
        "target_date": target_date.isoformat(),
        "cutoff_local": cutoff_local.isoformat(),
        "cutoff_utc": cutoff_utc.isoformat().replace("+00:00", "Z"),
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "position_btc_confirmed": float(POSITION_BTC),
        "display_baseline_brl": float(DISPLAY_BASELINE_BRL),
    }

    if mark:
        mark_price = mark["price_brl"]
        portfolio_value = POSITION_BTC * mark_price
        gain = portfolio_value - DISPLAY_BASELINE_BRL
        gain_pct = (portfolio_value / DISPLAY_BASELINE_BRL - Decimal("1")) * Decimal("100")
        direction = "AUMENTOU" if gain > 0 else ("CAIU" if gain < 0 else "ESTÁVEL")
        record.update({
            "mark_status": "AVAILABLE",
            "mark": serialize_mark(mark),
            "portfolio": {
                "value_brl": float(q2(portfolio_value)),
                "value_brl_raw": float(portfolio_value),
                "gain_since_2026_06_11_brl": float(q2(gain)),
                "gain_since_2026_06_11_pct": float(q6(gain_pct)),
                "direction_since_2026_06_11": direction,
                "baseline_is_display_estimate": True,
            },
        })
        record["previous_archive"] = previous_summary(previous, portfolio_value)
    else:
        record.update({
            "mark_status": "UNAVAILABLE",
            "mark": None,
            "portfolio": None,
            "previous_archive": None,
            "reason_codes": ["NO_ELIGIBLE_MB_TRADE_WITHIN_120S", "NO_ELIGIBLE_CLOSED_MB_1M_CANDLE"],
        })

    record["retrieval"] = {
        "trades": {"ok": trade_response.get("ok"), "attempts": trade_response.get("attempts"), "error": trade_response.get("error")},
        "candles": None if candle_response is None else {"ok": candle_response.get("ok"), "attempts": candle_response.get("attempts"), "error": candle_response.get("error")},
    }

    dated_path = OUT_DIR / f"{target_date.isoformat()}-1630-BRT.json"
    payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    dated_path.write_text(payload, encoding="utf-8")
    (OUT_DIR / "latest.json").write_text(payload, encoding="utf-8")
    print(f"portfolio archive date={target_date} status={record['mark_status']} method={(record.get('mark') or {}).get('method')}")


if __name__ == "__main__":
    main()
