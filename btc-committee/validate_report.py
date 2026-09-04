#!/usr/bin/env python3
"""Validate the immutable BTC Committee visual envelope using stdlib only."""
from __future__ import annotations

import json
import math
import pathlib
import re
import sys
from typing import Any

ALLOWED_SIGNALS = {0, 50, 100, 150, 200, 300, 400, 500}
WEIGHTS = {"valuation": 25, "trend": 20, "flows": 15, "onchain": 15, "macro": 15, "micro": 10}


def expected_signal(score: int) -> int:
    if score <= 54:
        return 0
    if score <= 61:
        return 50
    if score <= 68:
        return 100
    if score <= 74:
        return 150
    if score <= 79:
        return 200
    if score <= 84:
        return 300
    if score <= 89:
        return 400
    return 500


def load_payload(path: str) -> dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def validate(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != "btc-committee-visual/1.0":
        errors.append("schema_version must be btc-committee-visual/1.0")
    report = payload.get("report")
    if not isinstance(report, dict):
        return errors + ["report is required"]

    cycle = report.get("cycle", {})
    if not re.fullmatch(r"\d{8}-\d{4}-BRT", str(cycle.get("id", ""))):
        errors.append("cycle.id must match YYYYMMDD-HHMM-BRT")
    for field in ("started_at", "completed_at", "cutoff_at", "execution_expires_at"):
        if not isinstance(cycle.get(field), str) or "T" not in cycle[field]:
            errors.append(f"cycle.{field} must be an ISO timestamp")

    decision = report.get("decision", {})
    score = decision.get("score_final")
    raw = report.get("score", {}).get("total_raw")
    theoretical = decision.get("signal_theoretical_brl")
    executable = decision.get("executable_now_brl")
    if not isinstance(score, int) or not 0 <= score <= 100:
        errors.append("decision.score_final must be an integer from 0 to 100")
    if not isinstance(raw, (int, float)) or not math.isfinite(raw):
        errors.append("score.total_raw must be finite")
    elif isinstance(score, int) and math.floor(raw + 0.5) != score:
        errors.append("HALF-UP mismatch between total_raw and score_final")
    if theoretical not in ALLOWED_SIGNALS:
        errors.append("signal_theoretical_brl is outside the frozen tiers")
    elif isinstance(score, int) and theoretical != expected_signal(score):
        errors.append("signal_theoretical_brl does not match score_final")
    if executable not in ALLOWED_SIGNALS:
        errors.append("executable_now_brl is outside the frozen tiers")
    elif decision.get("final") == "AUTORIZADA":
        if executable != theoretical:
            errors.append("authorized report must execute the theoretical signal")
    elif executable != 0:
        errors.append("blocked report must have executable_now_brl=0")

    drivers = report.get("drivers")
    if not isinstance(drivers, list) or len(drivers) != 3:
        errors.append("drivers must contain exactly three entries")

    breakdown = report.get("score", {}).get("breakdown", {})
    total = 0.0
    for key, weight in WEIGHTS.items():
        item = breakdown.get(key)
        if not isinstance(item, dict):
            errors.append(f"score.breakdown.{key} is required")
            continue
        if item.get("weight") != weight:
            errors.append(f"score.breakdown.{key}.weight must be {weight}")
        value = item.get("value")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= weight:
            errors.append(f"score.breakdown.{key}.value is invalid")
        else:
            total += float(value)
    if isinstance(raw, (int, float)) and math.isfinite(raw) and abs(total - float(raw)) > 0.001:
        errors.append("score.total_raw does not equal the breakdown sum")

    dq = report.get("gates", {}).get("dq", {}).get("score")
    if not isinstance(dq, int) or not 0 <= dq <= 100:
        errors.append("gates.dq.score must be an integer from 0 to 100")
    ledger = report.get("dq_ledger", {}).get("items")
    if not isinstance(ledger, list) or len(ledger) != 24:
        errors.append("dq_ledger.items must contain all 24 A1-F4 items")
    else:
        ids = [item.get("id") for item in ledger]
        expected_ids = [f"{block}{n}" for block in "ABCDEF" for n in range(1, 5)]
        if ids != expected_ids:
            errors.append("dq_ledger.items must be ordered A1-A4 through F1-F4")
        for item in ledger:
            if item.get("qualified") not in (0, 1):
                errors.append(f"{item.get('id')}: qualified must be 0 or 1")
            reasons = item.get("reason_codes")
            if not isinstance(reasons, list) or not reasons:
                errors.append(f"{item.get('id')}: reason_codes cannot be empty")

    validator = report.get("validator", {})
    if validator.get("evaluated_count") != 25 or validator.get("result") != "PASS":
        errors.append("validator must be 25/25 PASS")
    asserts = validator.get("asserts")
    if not isinstance(asserts, list) or len(asserts) != 25:
        errors.append("validator.asserts must contain 25 entries")
    else:
        for index, assertion in enumerate(asserts, start=1):
            if assertion.get("id") != f"ASSERT{index}":
                errors.append(f"validator assert order mismatch at {index}")
            if assertion.get("status") not in {"PASS-TRIGGERED", "PASS-NOT_TRIGGERED"}:
                errors.append(f"ASSERT{index} is not a PASS state")

    position = report.get("portfolio", {}).get("position_btc")
    if position != "0.00015382":
        errors.append("portfolio.position_btc must remain 0.00015382 until user confirmation")

    return errors


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "latest.json"
    try:
        payload = load_payload(path)
        errors = validate(payload)
    except Exception as exc:  # noqa: BLE001 - CLI must return a clean failure
        print(f"VALIDATION_ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("BTC_VISUALIZE_CONTRACT=FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    report = payload["report"]
    print("BTC_VISUALIZE_CONTRACT=PASS")
    print(f"CYCLE_ID={report['cycle']['id']}")
    print(f"SCORE_FINAL={report['decision']['score_final']}")
    print(f"EXECUTABLE_NOW_BRL={report['decision']['executable_now_brl']}")
    print("DQ_ITEMS=24")
    print("VALIDATOR=25/25_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
