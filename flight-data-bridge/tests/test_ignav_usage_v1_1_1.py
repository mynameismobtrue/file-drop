import pytest
import requests

from flight_bridge.providers.ignav import IgnavAdapter, IgnavError


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
    def json(self):
        return self._payload


class StaticSession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = 0
    def request(self, *args, **kwargs):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.response


def cfg():
    return {"max_retries": 1, "request_timeout_sec": 1, "retry_backoff_base_sec": 0}


def test_usage_counter_counts_2xx_as_successful_provider_request():
    session = StaticSession(FakeResponse(200, []))
    adapter = IgnavAdapter("dummy", cfg(), session=session, airport_db={})
    adapter._request("GET", "/airports", usage_role="HEALTH")
    usage = adapter.usage_stats()
    assert usage["REQUEST_ATTEMPTS"] == 1
    assert usage["SUCCESSFUL_PROVIDER_REQUESTS"] == 1
    assert usage["IGNAV_HEALTH_REQUEST_ATTEMPTS"] == 1
    assert usage["IGNAV_HEALTH_REQUESTS"] == 1


def test_usage_counter_does_not_count_401_as_successful():
    session = StaticSession(FakeResponse(401, {"error":{"type":"auth_error","code":"invalid_api_key","message":"bad"}}))
    adapter = IgnavAdapter("dummy", cfg(), session=session, airport_db={})
    with pytest.raises(IgnavError) as exc:
        adapter._request("GET", "/airports", usage_role="HEALTH")
    assert exc.value.code == "AUTH_REQUIRED"
    usage = adapter.usage_stats()
    assert usage["REQUEST_ATTEMPTS"] == 1
    assert usage["SUCCESSFUL_PROVIDER_REQUESTS"] == 0
    assert usage["IGNAV_HEALTH_REQUESTS"] == 0


def test_usage_counter_does_not_count_timeout_as_successful():
    session = StaticSession(exc=requests.Timeout("timeout"))
    adapter = IgnavAdapter("dummy", cfg(), session=session, airport_db={})
    with pytest.raises(IgnavError) as exc:
        adapter._request("POST", "/fares/search", usage_role="SEARCH", json={})
    assert exc.value.code == "PROVIDER_TIMEOUT"
    usage = adapter.usage_stats()
    assert usage["REQUEST_ATTEMPTS"] == 1
    assert usage["SUCCESSFUL_PROVIDER_REQUESTS"] == 0
    assert usage["IGNAV_SEARCH_REQUEST_ATTEMPTS"] == 1
    assert usage["IGNAV_SEARCH_REQUESTS"] == 0


def test_usage_counter_does_not_count_424_as_successful():
    session = StaticSession(FakeResponse(424, {"error":{"type":"upstream_error","code":"upstream_failed","message":"retry"}}))
    adapter = IgnavAdapter("dummy", cfg(), session=session, airport_db={})
    with pytest.raises(IgnavError) as exc:
        adapter._request("POST", "/fares/search", usage_role="SEARCH", json={})
    assert exc.value.code == "UPSTREAM_DEPENDENCY"
    usage = adapter.usage_stats()
    assert usage["REQUEST_ATTEMPTS"] == 1
    assert usage["SUCCESSFUL_PROVIDER_REQUESTS"] == 0
