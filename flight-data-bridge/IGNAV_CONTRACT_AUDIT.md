# Ignav Adapter Contract Audit — DATA_BRIDGE 1.1.0

**Protocol authority:** `LISBOA_V2.2` (unchanged)  
**Bridge state:** `PRE_PRODUCTION`  
**OpenAPI audited:** `voxgig-sdk/ignav-flight-sdk/.sdk/def/ignav-flight_0.1.0.json`  
**OpenAPI blob SHA:** `7f57f5dbfb8e2d8ebbc9956a4c2860e8c887be50`  
**Upstream contract version:** OpenAPI 3.1.0 / Ignav Public API 1.0.0

## Decision: direct requests vs generated SDK

`requests` remains the runtime integration. The generated Python SDK is not added as a dependency.

Reasons:
- the generated Python package identifies itself as unofficial and version `0.0.1`;
- the repository documentation still describes publishing as pending;
- the generated entity abstraction does not reduce the protocol-specific normalization and revalidation risk;
- direct HTTP keeps request/response/error evidence transparent for audit;
- the OpenAPI, test-mode concept and mock patterns are still useful and are reused as contract/test inputs.

No source code was copied from the audited projects. Reuse is selective at the level of public contract, patterns and tests.

## Field matrix

| Our adapter | OpenAPI / documented field | Compatible | Divergence | Action |
|---|---|---:|---|---|
| `legs[]` request | `FareSearchRequest.legs[]` | Yes | None | Keep |
| per-leg `max_stops` | `SearchLegInput.max_stops` | Yes | None | Keep |
| `adults` | `FareSearchRequest.adults` | Yes | None | Keep |
| `cabin_class=economy` | `FareSearchRequest.cabin_class` | Yes | None | Keep |
| `market=BR` | `FareSearchRequest.market` | Yes | None | Keep |
| `allow_self_transfer=false` | `FareSearchRequest.allow_self_transfer` | Yes | None | Keep |
| `airlines_exclude=["DT"]` | `FareSearchRequest.airlines_exclude` | Yes | None | Keep; hard filter remains second defense |
| response `legs` | `FareSearchModel.legs` | Yes | None | Validate exact two-leg shape for this bridge |
| response `itineraries` | `FareSearchModel.itineraries` | Yes | None | Validate type |
| `price.amount` | `PriceModel.amount` | Yes | None | Require numeric |
| `price.currency` | `PriceModel.currency` | Yes | None | Require string; BRL policy stays protocol-side |
| `price.status` | `verified|unverified` | Yes | Old refresh defaulted missing status to verified | Missing/invalid status is schema-invalid or unconfirmed; never default to verified |
| `ignav_id` | `SearchItineraryModel.ignav_id` nullable | Yes | Can be null | Preserve result but mark handoff unavailable; no verified alert |
| segment marketing code | `marketing_carrier_code` | Yes | None | Keep |
| segment marketing name | no segment field; leg has `carrier` display name | Partial | Old code read undocumented `marketing_carrier_name` | Use documented leg `carrier` as display name |
| segment operating name | `operating_carrier_name` | Yes | None | Keep |
| segment operating code | **not in OpenAPI v1.0.0** | No | Old code read `operating_carrier_code` | `UNVERIFIED_FIELD`; never promote to confirmed operating code |
| local timestamps | `departure_time_local`, `arrival_time_local` | Yes | None | Keep |
| UTC timestamps | `departure_time_utc`, `arrival_time_utc` | Yes | Nullable | Use for connection math only when present |
| timezones | departure/arrival timezone | Yes | Nullable | Preserve; do not infer |
| `duration_minutes` | segment/leg duration | Yes | None | Preserve provider value |
| `aircraft` | `aircraft` nullable | Yes | None | Preserve UNKNOWN |
| baggage | `bags.carry_on`, `bags.checked` | Yes | Nullable | Preserve UNKNOWN |
| self-transfer | itinerary-level `requires_self_transfer` | Yes | Old code looked for it on each leg | Pass itinerary state to each direction/connection |
| synthetic `segment_id` | no public field | Internal only | Old code read optional raw `segment_id` | Generate deterministic internal ID; do not claim provider field |
| booking request | `BookingLinksRequest.ignav_id` | Yes | None | Keep ID-only request as preferred path |
| booking itinerary | flexible `itinerary.legs` or standard outbound/inbound | Yes | None | Validate both contract variants |
| booking coverage | `booking_options[].leg_indexes` for flexible | Yes | Old named-leg fallback accepted any two names | Require exact `{0,1}` or exact `{outbound,inbound}` |
| booking links | provider name/type, optional price, URL | Yes | None | Preserve provider order; never choose by cheapest price |

## Error mapping

Documented contract/status behavior:
- `400` → invalid request, no retry;
- `401` → auth required, no retry;
- `402` + `billing_required` → billing required, no retry;
- `404` → not found, no retry;
- `424` → upstream dependency failure, retry with exponential backoff;
- `429` + `monthly_spend_limit_reached` → spending/billing gate, not normal API throttling;
- network failure / timeout → retry with backoff;
- unknown `429` → operational `RATE_LIMITED` only with `PROVISIONAL_HTTP_429` confidence;
- `5xx` → `PROVIDER_HTTP_ERROR`; no undocumented automatic retry policy is frozen here.

Ignav documents no provider-imposed per-account throttle. Therefore `429` is not generically interpreted as ordinary rate limiting.

## Health check

`IgnavAdapter.health_check()` uses the authenticated, OpenAPI-covered airport endpoint:

`GET /api/airports?q=GRU&limit=1`

It records:
- `STATUS`
- `LATENCY_MS`
- `CHECKED_AT`
- `HTTP_STATUS`
- `ERROR_CODE`
- `ERROR_MAPPING_CONFIDENCE`

This health check is **explicit/diagnostic** and is not added as an automatic extra request to every 90-minute collection cycle, avoiding unnecessary successful API calls.

## Revalidation changes

Ignav alert revalidation is now:

`DISCOVERY → exact candidate → SECOND /fares/search → exact_itinerary_match → /fares/booking-links using fresh ignav_id → exact_itinerary_match again → full-journey booking coverage → price/status refresh`

Selection is never based on `min(price)`. If multiple exact physical matches are returned, provider order is preserved and the first exact match is used. A changed booking itinerary is not silently substituted.

## Audited public implementations

### voxgig-sdk/ignav-flight-sdk
Used: OpenAPI, generated-SDK test/mocking concepts, error/model comparison.  
Rejected: adding the SDK as runtime dependency.

### gusgordon/ignav-skill
Used: price-observation/polling concepts and `ignav_id → booking-links` flow.  
Rejected: `min(price)` as decision logic and MCP as bridge replacement.

### borski/travel-hacking-toolkit
Used: environment-key/configuration and direct REST request patterns.  
Rejected: no provider logic is imported.

### Edesiomartins/DrFlights
Used: explicit timeout/health-check pattern.  
Rejected: fallback `operating carrier = marketing carrier`; this violates Lisboa V2.2. Also rejected its less-capable non-flexible provider abstraction for our open-jaw requirement.

### dn-cuong/Farewatch
Used: bounded worker/retry/health separation as conceptual reference.  
Rejected: Redis/Postgres/Kubernetes/server infrastructure and generic rate-limiter stack for Bridge V1.

## MCP and playground

The hosted MCP is auxiliary only. It may help diagnostics or development but does not own completeness, history, filters, revalidation or audit trail.

The public playground is classified only as `CONTRACT_SMOKE_TEST`. It cannot promote the provider to `LIVE_PROVIDER_VALIDATION`.
