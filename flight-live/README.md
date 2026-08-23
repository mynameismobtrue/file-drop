# Flight Data Bridge Live Data

Public live-data storage explicitly authorized by the repository owner on 2026-08-23.

This branch is data-only for Flight Data Bridge Lisboa.

DATA_BRIDGE_VERSION=1.1.1
PROTOCOL_VERSION=LISBOA_V2.2
LIVE_ENV_VERSION=1.0.0
STATE=PRE_PRODUCTION
APPROVED_CODE_SHA=c1007258ece8c55a2736b117eef75ade10ee8d03

Safety rules:
- Never persist IGNAV_API_KEY, Authorization, X-Api-Key, cookies, OAuth/session/refresh tokens, or provider session state.
- Booking URLs containing sensitive state must be redacted before persistence.
- Live validation is manual only until Production Gate passes.
- ALERT_DELIVERY_ENABLED=false while PRE_PRODUCTION.
- 4 cycles/day is the authorized future cadence, but schedule is disabled until Production Gate.
