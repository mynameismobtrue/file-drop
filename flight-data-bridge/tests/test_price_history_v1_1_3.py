from flight_bridge.bridge import _summary, history_metrics


def _offer(code=None, name="LATAM", price=4674.0):
    return {
        "price_brl": price,
        "offer_id": "offer-1",
        "commercial_offer_id": "commercial-1",
        "outbound": {
            "origin": "GRU",
            "segments": [
                {
                    "operating_carrier": code,
                    "operating_carrier_name": name,
                }
            ],
        },
        "inbound": {
            "segments": [
                {
                    "operating_carrier": code,
                    "operating_carrier_name": name,
                }
            ],
        },
        "derived": {
            "QUALITY_CLASS": "A",
            "MAX_CONNECTIONS": 0,
        },
    }


def test_summary_uses_operating_name_when_code_is_absent():
    assert _summary(_offer())["operating_carriers"] == ["LATAM"]


def test_summary_prefers_operating_code_when_available():
    assert _summary(_offer(code="TP", name="Tap Air Portugal"))["operating_carriers"] == ["TP"]


def test_history_metrics_preserves_ignav_operating_name(tmp_path):
    completed = "2026-08-23T03:42:13+00:00"
    metrics = history_metrics(tmp_path, [_offer()], completed)
    assert metrics["CHEAPEST_OPERATING_CARRIER"] == ["LATAM"]
    assert metrics["MIN_CYCLE"]["operating_carriers"] == ["LATAM"]
    assert metrics["MIN_SINCE_START"]["operating_carriers"] == ["LATAM"]
