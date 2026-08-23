import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "private-env-template" / "scripts" / "private_runtime.py"
spec = importlib.util.spec_from_file_location("private_runtime_template", SCRIPT)
private_runtime = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(private_runtime)


def test_private_quota_usage_accumulates_search_revalidation_and_health_separately():
    previous = {
        "IGNAV_SUCCESSFUL_REQUESTS_ESTIMATED": 10,
        "REQUEST_ATTEMPTS": 12,
        "IGNAV_SEARCH_REQUEST_ATTEMPTS": 8,
        "IGNAV_SEARCH_REQUESTS": 7,
        "IGNAV_REVALIDATION_REQUEST_ATTEMPTS": 3,
        "IGNAV_REVALIDATION_REQUESTS": 2,
        "IGNAV_HEALTH_REQUEST_ATTEMPTS": 1,
        "IGNAV_HEALTH_REQUESTS": 1,
    }
    bridge = {
        "REQUEST_ATTEMPTS": 15,
        "SUCCESSFUL_PROVIDER_REQUESTS": 13,
        "IGNAV_SEARCH_REQUEST_ATTEMPTS": 12,
        "IGNAV_SEARCH_REQUESTS": 11,
        "IGNAV_REVALIDATION_REQUEST_ATTEMPTS": 3,
        "IGNAV_REVALIDATION_REQUESTS": 2,
    }
    health = {
        "REQUEST_ATTEMPTS": 1,
        "SUCCESSFUL_PROVIDER_REQUESTS": 1,
        "IGNAV_HEALTH_REQUEST_ATTEMPTS": 1,
        "IGNAV_HEALTH_REQUESTS": 1,
    }
    totals = private_runtime.accumulate_usage(previous, bridge, health)
    assert totals["REQUEST_ATTEMPTS"] == 28
    assert totals["SUCCESSFUL_PROVIDER_REQUESTS"] == 24
    assert totals["IGNAV_SEARCH_REQUEST_ATTEMPTS"] == 20
    assert totals["IGNAV_SEARCH_REQUESTS"] == 18
    assert totals["IGNAV_REVALIDATION_REQUEST_ATTEMPTS"] == 6
    assert totals["IGNAV_REVALIDATION_REQUESTS"] == 4
    assert totals["IGNAV_HEALTH_REQUEST_ATTEMPTS"] == 2
    assert totals["IGNAV_HEALTH_REQUESTS"] == 2


def test_private_secret_scan_detects_actual_secret_and_sensitive_field_names():
    assert private_runtime.token_like_secret_reason('{"safe":"SECRET123"}', actual_secret="SECRET123") == "ACTUAL_SECRET_VALUE"
    assert private_runtime.token_like_secret_reason('{"Authorization":"redacted"}') == "SECRET_FIELD_NAME"
    assert private_runtime.token_like_secret_reason('{"x_api_key":"redacted"}') == "SECRET_FIELD_NAME"


def test_private_secret_scan_detects_token_like_patterns():
    jwt = "eyJaaaaaaaaaaa.bbbbbbbbbbb.ccccccccccc"
    assert private_runtime.token_like_secret_reason('{"value":"' + jwt + '"}') == "JWT_PATTERN"
    assert private_runtime.token_like_secret_reason('{"value":"Bearer abcdefghijklmnopqrstuvwxyz"}') == "BEARER_TOKEN_PATTERN"
    assert private_runtime.token_like_secret_reason('{"value":"sk-abcdefghijklmnopqrstuvwx"}') == "KNOWN_TOKEN_PREFIX"


def test_private_secret_scan_does_not_flag_normal_sha_or_search_id():
    text = '{"APPROVED_CODE_SHA":"4e62ca799f93e4f87189421609aaf061ccef7264","SEARCH_ID":"20260822-214400-BRT"}'
    assert private_runtime.token_like_secret_reason(text) is None
