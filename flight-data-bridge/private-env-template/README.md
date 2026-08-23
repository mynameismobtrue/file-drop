# Flight Data Bridge Live Environment Template

This directory is a template for the separate private repository `mynameismobtrue/flight-data-bridge-live`.

Authoritative versions while this template is prepared:

- DATA_BRIDGE_VERSION: 1.1.1
- PROTOCOL_VERSION: LISBOA_V2.2
- UI_VERSION: 1.0.0
- LIVE_ENV_VERSION: 1.0.0
- STATE: PRE_PRODUCTION

## Security boundary

The public repository contains code only. Real fare snapshots, itinerary history, booking metadata and quota state must be written only to the private live repository.

Never store API keys, Authorization/X-Api-Key headers, cookies, OAuth tokens or provider session tokens in this repository. `IGNAV_API_KEY` must exist only as a GitHub Actions Secret in the private repository.

## Copy target

When the private repository exists, copy the contents of this template to its root. Then replace the `approved_code_sha` placeholder in `config/live-validation.json` with the exact code SHA that passed the final public CI. Do not use `main`, `latest` or an unpinned branch as the code reference.

Expected private structure after the first validation run:

```text
.github/workflows/live-provider-validation.yml
.github/workflows/flight-monitor.yml
config/live-validation.json
scripts/private_runtime.py
live/last-attempt.json
live/last-complete.json
live/status.json
live/quota.json
history/YYYY/MM/DD/<SEARCH_ID>.json
price-history/history.json
audit/validation-runs/<SEARCH_ID>.json
README.md
```

## Workflow states

`live-provider-validation.yml` is manual only. It checks private-repository status, exact code SHA, secret presence, regression, quota, one diagnostic health request, 12/12 provider coverage, sanitization and private persistence.

`flight-monitor.yml` is deliberately PRE_PRODUCTION disabled. It contains only `workflow_dispatch` while the Production Gate is closed. The production cron `0 0,9,14,19 * * *` is documented inside the file but must not be activated until the formal gate passes.

## Quota policy

- Initial estimated free successful requests: 1000
- Warning at estimated remaining <= 150
- Hard reserve: 50
- Base queries per cycle: 12
- Revalidation reserve before starting a cycle: 2
- Paid usage authorized: false

Automatic cycles must not begin when the estimated remaining budget cannot cover the next complete 12-query cycle, revalidation reserve and the 50-request safety reserve.

## Alert policy

This private environment never changes Lisboa V2.2. During live validation `alert_delivery_enabled=false`. A future alert consumer may only use `VERIFIED_ALERT_CANDIDATE=true` after the bridge has completed all V2.2 gates and dedupe checks.
