from __future__ import annotations
import hashlib, json
from .models import Offer

def _seg_token(seg):
    return [
        seg.origin,
        seg.destination,
        seg.departure_utc or seg.departure_local,
        seg.arrival_utc or seg.arrival_local,
        seg.marketing_carrier,
        seg.operating_carrier,
        seg.flight_number,
    ]

def normalized_itinerary_components(offer: Offer):
    rows=[]
    for direction in (offer.outbound, offer.inbound):
        if direction is None:
            return None
        rows.append([_seg_token(s) for s in direction.segments])
    if not all(rows) or not all(all(v not in (None, "") for v in s) for direction in rows for s in direction):
        return None
    return rows

def itinerary_fingerprint(offer: Offer) -> str | None:
    rows=normalized_itinerary_components(offer)
    if rows is None:
        return None
    raw=json.dumps(rows, ensure_ascii=False, separators=(",",":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:40]

def commercial_offer_id(offer: Offer) -> str | None:
    fp=offer.itinerary_fingerprint or itinerary_fingerprint(offer)
    if not fp:
        return None
    token=[fp, offer.source, offer.booking_agent, offer.source_offer_id]
    return hashlib.sha256(json.dumps(token,separators=(",",":"),default=str).encode()).hexdigest()[:40]

def exact_itinerary_match(a: Offer,b: Offer) -> bool:
    fa=a.itinerary_fingerprint or itinerary_fingerprint(a)
    fb=b.itinerary_fingerprint or itinerary_fingerprint(b)
    return bool(fa and fb and fa==fb)
