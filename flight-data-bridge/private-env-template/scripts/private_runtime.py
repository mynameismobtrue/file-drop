from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "live-validation.json"

USAGE_COUNTER_FIELDS = (
    "REQUEST_ATTEMPTS",
    "SUCCESSFUL_PROVIDER_REQUESTS",
    "IGNAV_SEARCH_REQUEST_ATTEMPTS",
    "IGNAV_SEARCH_REQUESTS",
    "IGNAV_REVALIDATION_REQUEST_ATTEMPTS",
    "IGNAV_REVALIDATION_REQUESTS",
    "IGNAV_HEALTH_REQUEST_ATTEMPTS",
    "IGNAV_HEALTH_REQUESTS",
)

_SECRET_KEY_RE = re.compile(
    r'(?i)"(?:authorization|x[-_]?api[-_]?key|api[-_]?key|access[-_]?token|refresh[-_]?token|session[-_]?token|oauth[-_]?token|cookie)"\s*:'
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_KNOWN_TOKEN_PREFIX_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,})\b"
)


def load_private_config():
    return json.loads(CONFIG_PATH.read_text())


def code_root():
    root = Path(os.environ.get("FLIGHT_BRIDGE_CODE_DIR", ROOT / "_code" / "flight-data-bridge"))
    sys.path.insert(0, str(root))
    return root


def load_quota():
    path = ROOT / "live" / "quota.json"
    if not path.exists():
        return {
            "IGNAV_SUCCESSFUL_REQUESTS_ESTIMATED": 0,
            "REQUEST_ATTEMPTS": 0,
            "SUCCESSFUL_PROVIDER_REQUESTS": 0,
            "IGNAV_SEARCH_REQUEST_ATTEMPTS": 0,
            "IGNAV_SEARCH_REQUESTS": 0,
            "IGNAV_REVALIDATION_REQUEST_ATTEMPTS": 0,
            "IGNAV_REVALIDATION_REQUESTS": 0,
            "IGNAV_HEALTH_REQUEST_ATTEMPTS": 0,
            "IGNAV_HEALTH_REQUESTS": 0,
        }
    return json.loads(path.read_text())


def write_json(path: Path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(path)


def accumulate_usage(previous: dict, *run_usage_docs: dict) -> dict[str, int]:
    totals = {}
    for field in USAGE_COUNTER_FIELDS:
        if field == "SUCCESSFUL_PROVIDER_REQUESTS":
            prior = int(previous.get(field, previous.get("IGNAV_SUCCESSFUL_REQUESTS_ESTIMATED", 0)) or 0)
        else:
            prior = int(previous.get(field, 0) or 0)
        delta = sum(int((doc or {}).get(field, 0) or 0) for doc in run_usage_docs)
        totals[field] = prior + delta
    return totals


def token_like_secret_reason(text: str, *, actual_secret: str | None = None) -> str | None:
    if actual_secret and actual_secret in text:
        return "ACTUAL_SECRET_VALUE"
    if _SECRET_KEY_RE.search(text):
        return "SECRET_FIELD_NAME"
    if _JWT_RE.search(text):
        return "JWT_PATTERN"
    if _BEARER_RE.search(text):
        return "BEARER_TOKEN_PATTERN"
    if _KNOWN_TOKEN_PREFIX_RE.search(text):
        return "KNOWN_TOKEN_PREFIX"
    return None


def cmd_quota(args):
    code_root()
    from flight_bridge.operational import quota_gate
    cfg = load_private_config()
    prior = load_quota()
    gate = quota_gate(
        prior.get("IGNAV_SUCCESSFUL_REQUESTS_ESTIMATED", 0),
        free_initial=cfg["ignav_free_requests_initial"],
        warning_threshold=cfg["free_tier_warning_threshold"],
        hard_stop_buffer=cfg["free_tier_hard_stop_buffer"],
        base_search_requests=cfg["base_search_requests_per_cycle"],
        revalidation_reserve=cfg["revalidation_request_reserve"],
        extra_requests=1 if args.include_health else 0,
        paid_usage_authorized=cfg["paid_usage_authorized"],
    )
    print(json.dumps(gate, sort_keys=True))
    if not gate["QUOTA_GATE_ALLOWED"]:
        raise SystemExit(42)


def cmd_runtime_config(args):
    code = code_root()
    private = load_private_config()
    public_cfg = json.loads((code / "config" / "protocol_v2_2.json").read_text())
    assert public_cfg["data_bridge_version"] == private["data_bridge_version"]
    assert public_cfg["protocol_version"] == private["protocol_version"] == "LISBOA_V2.2"
    assert public_cfg["ui_version"] == private["ui_version"]
    runtime = dict(public_cfg)
    runtime["provider_priority"] = ["IGNAV"]
    runtime["enable_skyscanner"] = False
    runtime["enable_ignav"] = True
    runtime["enable_duffel_corroboration"] = False
    write_json(Path(args.output), runtime)


def cmd_health(args):
    code = code_root()
    from flight_bridge.providers.ignav import IgnavAdapter
    cfg = json.loads((code / "config" / "protocol_v2_2.json").read_text())
    key = os.environ.get("IGNAV_API_KEY", "")
    if not key:
        raise SystemExit("AUTH_REQUIRED: IGNAV_API_KEY missing")
    adapter = IgnavAdapter(key, cfg)
    result = adapter.health_check()
    doc = {"HEALTH": result, "USAGE": adapter.usage_stats()}
    write_json(Path(args.output), doc)
    if result.get("STATUS") != "UP":
        raise SystemExit(43)


def add_live_metadata(doc: dict, private: dict):
    out = dict(doc)
    out["LIVE_ENV_VERSION"] = private["live_env_version"]
    out["APPROVED_CODE_SHA"] = private["approved_code_sha"]
    return out


def cmd_persist(args):
    code_root()
    from flight_bridge.operational import sanitize_document, quota_gate

    private = load_private_config()
    secret = os.environ.get("IGNAV_API_KEY", "")
    output = Path(args.output_dir)
    status_path = output / "status.json"
    if not status_path.exists():
        raise SystemExit("PERSISTENCE_FAILED: status.json missing")

    status_raw = json.loads(status_path.read_text())
    status = sanitize_document(add_live_metadata(status_raw, private), actual_secret=secret)
    meta = status.get("SEARCH_METADATA") or {}
    search_id = meta.get("SEARCH_ID")
    if not search_id:
        raise SystemExit("PERSISTENCE_FAILED: SEARCH_ID missing")

    health = json.loads(Path(args.health_file).read_text()) if Path(args.health_file).exists() else {"HEALTH": None, "USAGE": {}}
    bridge_usage = ((status.get("PROVIDER_USAGE") or {}).get("IGNAV") or {})
    health_usage = health.get("USAGE") or {}

    previous_quota = load_quota()
    usage_totals = accumulate_usage(previous_quota, bridge_usage, health_usage)
    successful_total = usage_totals["SUCCESSFUL_PROVIDER_REQUESTS"]
    gate = quota_gate(
        successful_total,
        free_initial=private["ignav_free_requests_initial"],
        warning_threshold=private["free_tier_warning_threshold"],
        hard_stop_buffer=private["free_tier_hard_stop_buffer"],
        base_search_requests=private["base_search_requests_per_cycle"],
        revalidation_reserve=private["revalidation_request_reserve"],
        paid_usage_authorized=private["paid_usage_authorized"],
    )
    run_usage = {
        field: int(bridge_usage.get(field, 0) or 0) + int(health_usage.get(field, 0) or 0)
        for field in USAGE_COUNTER_FIELDS
    }
    quota = {
        **gate,
        **usage_totals,
        "LAST_RUN_REQUEST_ATTEMPTS": run_usage["REQUEST_ATTEMPTS"],
        "LAST_RUN_SUCCESSFUL_PROVIDER_REQUESTS": run_usage["SUCCESSFUL_PROVIDER_REQUESTS"],
        "LAST_RUN_IGNAV_SEARCH_REQUEST_ATTEMPTS": run_usage["IGNAV_SEARCH_REQUEST_ATTEMPTS"],
        "LAST_RUN_IGNAV_SEARCH_REQUESTS": run_usage["IGNAV_SEARCH_REQUESTS"],
        "LAST_RUN_IGNAV_REVALIDATION_REQUEST_ATTEMPTS": run_usage["IGNAV_REVALIDATION_REQUEST_ATTEMPTS"],
        "LAST_RUN_IGNAV_REVALIDATION_REQUESTS": run_usage["IGNAV_REVALIDATION_REQUESTS"],
        "LAST_RUN_IGNAV_HEALTH_REQUEST_ATTEMPTS": run_usage["IGNAV_HEALTH_REQUEST_ATTEMPTS"],
        "LAST_RUN_IGNAV_HEALTH_REQUESTS": run_usage["IGNAV_HEALTH_REQUESTS"],
        "UPDATED_AT": meta.get("SEARCH_COMPLETED_AT") or meta.get("SEARCH_STARTED_AT"),
    }

    write_json(ROOT / "live" / "last-attempt.json", status)
    write_json(ROOT / "live" / "status.json", status)
    write_json(ROOT / "live" / "quota.json", quota)

    started = datetime.fromisoformat(meta["SEARCH_STARTED_AT"].replace("Z", "+00:00"))
    history_path = ROOT / "history" / started.strftime("%Y") / started.strftime("%m") / started.strftime("%d") / f"{search_id}.json"
    write_json(history_path, status)

    if meta.get("IS_COMPLETE") and (output / "snapshot.json").exists():
        snapshot_raw = json.loads((output / "snapshot.json").read_text())
        snapshot_clean = sanitize_document(add_live_metadata(snapshot_raw, private), actual_secret=secret)
        write_json(ROOT / "live" / "last-complete.json", snapshot_clean)
        write_json(history_path, snapshot_clean)

        price_file = ROOT / "price-history" / "history.json"
        price_doc = json.loads(price_file.read_text()) if price_file.exists() else {"observations": []}
        price_doc.setdefault("observations", []).append({
            "SEARCH_ID": search_id,
            "COMPLETED_AT": meta.get("SEARCH_COMPLETED_AT"),
            "PRICE_HISTORY": snapshot_clean.get("PRICE_HISTORY") or {},
        })
        write_json(price_file, price_doc)

    active = status.get("ACTIVE_DISCOVERY_PROVIDER")
    provider_result = next((x for x in status.get("PROVIDER_RESULTS", []) if x.get("provider") == active), None)
    audit = {
        "DATA_BRIDGE_VERSION": private["data_bridge_version"],
        "PROTOCOL_VERSION": private["protocol_version"],
        "UI_VERSION": private["ui_version"],
        "LIVE_ENV_VERSION": private["live_env_version"],
        "STATE": private["state"],
        "APPROVED_CODE_SHA": private["approved_code_sha"],
        "SEARCH_ID": search_id,
        "HEALTH": health.get("HEALTH"),
        "PROVIDER_USAGE": bridge_usage,
        "QUOTA": quota,
        "SEARCH_STATUS": meta.get("SEARCH_STATUS"),
        "QUERY_COVERAGE": {
            "EXPECTED": (provider_result or {}).get("PROVIDER_QUERIES_EXPECTED"),
            "STARTED": (provider_result or {}).get("PROVIDER_QUERIES_STARTED"),
            "COMPLETE": (provider_result or {}).get("PROVIDER_QUERIES_COMPLETE"),
            "FAILED": (provider_result or {}).get("PROVIDER_QUERIES_FAILED"),
            "TIMED_OUT": (provider_result or {}).get("PROVIDER_QUERIES_TIMED_OUT"),
            "QUERY_GRID_VALID": (provider_result or {}).get("QUERY_GRID_VALID"),
        },
        "COUNTS": status.get("COUNTS"),
        "CONTRACT_AUDIT": status.get("PROVIDER_CONTRACT_AUDIT"),
        "VALIDATION_RESULTS": status.get("VALIDATION_RESULTS"),
        "ALERT_DELIVERY_ENABLED": False,
        "PRODUCTION_VALIDATED": False,
    }
    audit = sanitize_document(audit, actual_secret=secret)
    write_json(ROOT / "audit" / "validation-runs" / f"{search_id}.json", audit)


def cmd_scan(args):
    secret = os.environ.get("IGNAV_API_KEY", "")
    roots = [ROOT / "live", ROOT / "history", ROOT / "price-history", ROOT / "audit"]
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            text = path.read_text(errors="replace")
            reason = token_like_secret_reason(text, actual_secret=secret)
            if reason:
                raise SystemExit(f"SECRET_SCAN_FAILED: {reason} in {path}")
    print("SECRET_SCAN_PASS")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    quota = sub.add_parser("quota-check")
    quota.add_argument("--include-health", action="store_true")
    quota.set_defaults(func=cmd_quota)

    runtime = sub.add_parser("runtime-config")
    runtime.add_argument("--output", required=True)
    runtime.set_defaults(func=cmd_runtime_config)

    health = sub.add_parser("health")
    health.add_argument("--output", required=True)
    health.set_defaults(func=cmd_health)

    persist = sub.add_parser("persist")
    persist.add_argument("--output-dir", required=True)
    persist.add_argument("--health-file", required=True)
    persist.set_defaults(func=cmd_persist)

    scan = sub.add_parser("scan")
    scan.set_defaults(func=cmd_scan)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
