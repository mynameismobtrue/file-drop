from __future__ import annotations
from datetime import datetime, timedelta, timezone
from .models import Offer, Direction
from .fingerprints import itinerary_fingerprint, commercial_offer_id

AFRICAN_ISO2={
"DZ","AO","BJ","BW","BF","BI","CV","CM","CF","TD","KM","CG","CD","CI","DJ","EG","GQ","ER","SZ","ET","GA","GM","GH","GN","GW","KE","LS","LR","LY","MG","MW","ML","MR","MU","MA","MZ","NA","NE","NG","RW","ST","SN","SC","SL","SO","ZA","SS","SD","TZ","TG","TN","UG","ZM","ZW"
}

def _parse_ts(v):
    if not v: return None
    try:
        dt=datetime.fromisoformat(v.replace("Z","+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _date(v): return v[:10] if v else None

def _forbidden_carrier(code,name,cfg):
    c=(code or "").upper().strip(); n=(name or "").upper()
    for row in cfg["forbidden_carriers"]:
        if row.get("iata") and c==row["iata"].upper(): return True
        if row.get("name_contains") and row["name_contains"].upper() in n: return True
    return False

def _shape(direction: Direction|None, hard:list[str], unknown:list[str]):
    if direction is None:
        unknown.append("INCOMPLETE_ITINERARY"); return
    for v in [direction.origin,direction.destination,direction.departure_local,direction.arrival_local,direction.arrival_date_local]:
        if v in (None,""):
            unknown.append("INCOMPLETE_ITINERARY"); break
    if direction.total_duration_min is None: unknown.append("TOTAL_DURATION_UNKNOWN")
    if direction.connection_count is None: unknown.append("CONNECTION_COUNT_UNKNOWN")
    if not direction.segments: unknown.append("INCOMPLETE_ITINERARY")

def evaluate_offer(offer: Offer,cfg:dict,now:datetime|None=None)->Offer:
    now=now or datetime.now(timezone.utc)
    hard=[]; unknown=[]; alert_blocks=[]
    _shape(offer.outbound,hard,unknown); _shape(offer.inbound,hard,unknown)

    if offer.outbound and offer.inbound:
        ob,ib=offer.outbound,offer.inbound
        if ob.origin not in cfg["origins"]: hard.append("WRONG_ORIGIN")
        if ob.destination!=cfg["destination"]: hard.append("WRONG_DESTINATION")
        if _date(ob.departure_local) not in cfg["outbound_departure_dates"]: hard.append("WRONG_OUTBOUND_DATE")
        if ob.arrival_date_local not in cfg["allowed_lis_arrival_dates"]: hard.append("WRONG_ARRIVAL_DATE")
        if ib.origin!=cfg["destination"]: hard.append("WRONG_RETURN_ORIGIN")
        if _date(ib.departure_local)!=cfg["return_departure_date"]: hard.append("WRONG_RETURN_DATE")
        if ib.destination not in cfg["return_destinations"]: hard.append("WRONG_RETURN_DESTINATION")

        for d in (ob,ib):
            if d.connection_count is not None and d.connection_count>cfg["max_connections_per_direction"]:
                hard.append("TOO_MANY_CONNECTIONS")
            if d.total_duration_min is not None and d.total_duration_min>cfg["max_total_duration_per_direction_min"]:
                hard.append("TOTAL_DURATION")
            for s in d.segments:
                if not s.marketing_carrier: unknown.append("MARKETING_CARRIER_UNKNOWN")
                if not s.operating_carrier: unknown.append("OPERATING_CARRIER_UNKNOWN")
                if _forbidden_carrier(s.marketing_carrier,s.marketing_carrier_name,cfg): hard.append("TAAG_MARKETING")
                if _forbidden_carrier(s.operating_carrier,s.operating_carrier_name,cfg): hard.append("TAAG_OPERATING")
                if not s.flight_number: unknown.append("FLIGHT_NUMBER_UNKNOWN")
            if d.connection_count and len(d.connections)!=d.connection_count:
                unknown.append("CONNECTION_DATA_INCOMPLETE")
            for c in d.connections:
                if c.connection_duration_min is None: unknown.append("CONNECTION_DURATION_UNKNOWN")
                elif c.connection_duration_min>cfg["max_connection_duration_min"]: hard.append("CONNECTION_TOO_LONG")
                if cfg.get("forbid_africa_connections"):
                    if not c.connection_country: unknown.append("CONNECTION_COUNTRY_UNKNOWN")
                    elif c.connection_country.upper() in AFRICAN_ISO2: hard.append("FORBIDDEN_CONNECTION")
                if c.airport_change is None: unknown.append("AIRPORT_CHANGE_UNKNOWN")
                elif cfg.get("reject_airport_change") and c.airport_change: hard.append("AIRPORT_CHANGE")
                if c.self_transfer is None: unknown.append("SELF_TRANSFER_UNKNOWN")
                elif c.self_transfer: hard.append("SELF_TRANSFER")
                if not c.transfer_type: unknown.append("TRANSFER_TYPE_UNKNOWN")

    transfer=(offer.transfer_type or "").upper()
    if transfer in {"TRANSFER_TYPE_SELF_TRANSFER","SELF_TRANSFER"}: hard.append("SELF_TRANSFER")
    if transfer in {"TRANSFER_TYPE_PROTECTED_SELF_TRANSFER","PROTECTED_SELF_TRANSFER"}: hard.append("PROTECTED_SELF_TRANSFER")
    if offer.booking_option_count>1 and cfg.get("reject_multiple_booking_required"):
        hard.append("MULTIPLE_BOOKING_REQUIRED")

    if offer.cabin_class and offer.cabin_class.lower() not in {"economy","cabin_class_economy"}:
        hard.append("WRONG_CABIN_CLASS")
    if not offer.cabin_class: unknown.append("CABIN_CLASS_UNKNOWN")

    if not offer.total_price_confirmed or offer.price_brl is None or offer.currency!="BRL":
        unknown.append("PRICE_UNCONFIRMED")
    elif offer.price_brl>=cfg["alert_price_brl_strict_lt"]:
        alert_blocks.append("PRICE_LIMIT")

    if offer.offer_expires_at:
        exp=_parse_ts(offer.offer_expires_at)
        if exp is None: unknown.append("OFFER_EXPIRY_INVALID")
        elif now>=exp.astimezone(timezone.utc): hard.append("OFFER_EXPIRED")

    # A physical itinerary fingerprint is mandatory for safe dedupe/revalidation.
    fp=offer.itinerary_fingerprint or itinerary_fingerprint(offer)
    if not fp: unknown.append("ITINERARY_FINGERPRINT_UNAVAILABLE")
    else:
        offer.itinerary_fingerprint=fp
        offer.offer_id=fp
        offer.commercial_offer_id=commercial_offer_id(offer)

    hard=sorted(set(hard)); unknown=sorted(set(unknown)); alert_blocks=sorted(set(alert_blocks))
    state="ELIGIBLE"
    if hard: state="HARD_REJECTED"
    elif unknown: state="NON_VALIDATABLE"
    hard_pass=state=="ELIGIBLE"

    quality=None
    if hard_pass:
        dirs=[offer.outbound,offer.inbound]
        if all(d and d.connection_count==0 and d.total_duration_min is not None and d.total_duration_min<=cfg["quality_a_max_duration_min"] for d in dirs):
            quality="A"
        elif all(d and d.connection_count is not None and d.connection_count<=1 and d.total_duration_min is not None and d.total_duration_min<=cfg["quality_b_max_duration_min"] and all(c.connection_duration_min is not None and c.connection_duration_min<=cfg["preferred_connection_duration_min"] for c in d.connections) for d in dirs):
            quality="B"
        else: quality="C"

    price_pass=hard_pass and offer.price_brl is not None and offer.price_brl<cfg["alert_price_brl_strict_lt"]
    validation_ts=_parse_ts(offer.last_validated_at)
    validation_fresh=False
    if offer.validation_status in {"VALIDATED","PRICE_CHANGED"} and validation_ts:
        validation_fresh=(now-validation_ts.astimezone(timezone.utc)).total_seconds()<=cfg["alert_validation_ttl_min"]*60
    if price_pass:
        if offer.validation_status=="DISAPPEARED": alert_blocks.append("OFFER_DISAPPEARED")
        elif offer.validation_status not in {"VALIDATED","PRICE_CHANGED"}: alert_blocks.append("NOT_REVALIDATED")
        elif not validation_fresh: alert_blocks.append("VALIDATION_STALE")
        if not offer.booking_url: alert_blocks.append("BOOKING_OPTION_MISSING")

    effective_until=None
    if validation_ts:
        effective=validation_ts+timedelta(minutes=cfg["alert_validation_ttl_min"])
        exp=_parse_ts(offer.offer_expires_at)
        if exp: effective=min(effective,exp)
        effective_until=effective.isoformat()

    alert_blocks=sorted(set(alert_blocks))
    verified=bool(price_pass and validation_fresh and offer.booking_url and not alert_blocks and state=="ELIGIBLE")

    hard_codes=[f"REJECT_{x}" for x in hard]
    unknown_codes=[x if x.startswith("NON_VALIDATABLE_") else f"NON_VALIDATABLE_{x}" for x in unknown]
    offer.derived.update({
        "ORIGIN_VALID": None if not offer.outbound else offer.outbound.origin in cfg["origins"],
        "DESTINATION_VALID": None if not offer.outbound else offer.outbound.destination==cfg["destination"],
        "OUTBOUND_DATE_VALID": None if not offer.outbound else _date(offer.outbound.departure_local) in cfg["outbound_departure_dates"],
        "LIS_ARRIVAL_DATE_VALID": None if not offer.outbound else offer.outbound.arrival_date_local in cfg["allowed_lis_arrival_dates"],
        "RETURN_DATE_VALID": None if not offer.inbound else _date(offer.inbound.departure_local)==cfg["return_departure_date"],
        "RETURN_DESTINATION_VALID": None if not offer.inbound else offer.inbound.destination in cfg["return_destinations"],
        "TAAG_PRESENT": any(x in hard for x in ["TAAG_MARKETING","TAAG_OPERATING"]),
        "AFRICA_CONNECTION_PRESENT": "FORBIDDEN_CONNECTION" in hard,
        "MAX_CONNECTIONS": max([d.connection_count or 0 for d in [offer.outbound,offer.inbound] if d],default=0),
        "MAX_CONNECTION_MIN": max([c.connection_duration_min or 0 for d in [offer.outbound,offer.inbound] if d for c in d.connections],default=0),
        "MAX_DIRECTION_DURATION_MIN": max([d.total_duration_min or 0 for d in [offer.outbound,offer.inbound] if d],default=0),
        "SELF_TRANSFER_PRESENT": any(x in hard for x in ["SELF_TRANSFER","PROTECTED_SELF_TRANSFER"]),
        "AIRPORT_CHANGE_PRESENT": "AIRPORT_CHANGE" in hard,
        "OPERATING_CARRIER_CONFIRMED": "OPERATING_CARRIER_UNKNOWN" not in unknown,
        "HARD_FILTER_PASS": hard_pass,
        "HARD_REJECTED": state=="HARD_REJECTED",
        "NON_VALIDATABLE": state=="NON_VALIDATABLE",
        "ELIGIBILITY_STATE": state,
        "QUALITY_CLASS": quality,
        "ALERT_PRICE_PASS": price_pass,
        "VALIDATION_STATUS": offer.validation_status,
        "VALIDATION_FRESH": validation_fresh,
        "VERIFIED_ALERT_CANDIDATE": verified,
        "REJECTION_REASON_CODES": hard_codes,
        "NON_VALIDATABLE_REASON_CODES": unknown_codes,
        "ALERT_BLOCK_REASON_CODES": [f"REJECT_{x}" for x in alert_blocks],
        "ALERT_VALID_UNTIL": effective_until,
        "ITINERARY_FINGERPRINT": offer.itinerary_fingerprint,
        "COMMERCIAL_OFFER_ID": offer.commercial_offer_id,
    })
    return offer
