from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

@dataclass
class Segment:
    segment_id: str
    origin: str
    destination: str
    departure_local: str
    arrival_local: str
    departure_utc: Optional[str] = None
    arrival_utc: Optional[str] = None
    marketing_carrier: Optional[str] = None
    operating_carrier: Optional[str] = None
    marketing_carrier_name: Optional[str] = None
    operating_carrier_name: Optional[str] = None
    flight_number: Optional[str] = None
    aircraft: Optional[str] = None
    duration_min: Optional[int] = None

@dataclass
class Connection:
    connection_airport: str
    connection_country: Optional[str]
    connection_duration_min: Optional[int]
    transfer_type: Optional[str] = None
    airport_change: Optional[bool] = None
    self_transfer: Optional[bool] = None

@dataclass
class Direction:
    origin: str
    destination: str
    departure_local: str
    arrival_local: str
    arrival_date_local: str
    total_duration_min: Optional[int]
    connection_count: Optional[int]
    departure_utc: Optional[str] = None
    arrival_utc: Optional[str] = None
    segments: list[Segment] = field(default_factory=list)
    connections: list[Connection] = field(default_factory=list)

@dataclass
class Offer:
    offer_id: Optional[str]
    commercial_offer_id: Optional[str]
    source_offer_id: Optional[str]
    itinerary_id: Optional[str]
    source: str
    search_id: Optional[str]
    itinerary_fingerprint: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    price_brl: Optional[float]
    fx_source: Optional[str]
    fx_timestamp: Optional[str]
    total_price_confirmed: bool
    taxes_included: Optional[bool]
    cabin_class: Optional[str]
    personal_item: Any = None
    carry_on: Any = None
    checked_bag: Any = None
    booking_source: Optional[str] = None
    booking_agent: Optional[str] = None
    booking_url: Optional[str] = None
    offer_expires_at: Optional[str] = None
    discovered_at: Optional[str] = None
    last_validated_at: Optional[str] = None
    validation_status: str = "NOT_REQUIRED"
    outbound: Optional[Direction] = None
    inbound: Optional[Direction] = None
    transfer_type: Optional[str] = None
    booking_option_count: int = 0
    source_payload_ref: Optional[str] = None
    derived: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        doc = asdict(self)
        doc.pop("runtime", None)
        return doc

@dataclass
class ProviderQueryResult:
    provider: str
    query_id: str
    status: str
    started_at: str
    completed_at: Optional[str]
    offers: list[Offer] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    raw_offers_count: int = 0
    response_sha256: Optional[str] = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ProviderCycleResult:
    provider: str
    role: str
    expected: int
    started: int
    complete: int
    failed: int
    timed_out: int
    search_status: str
    source_health: str
    query_results: list[ProviderQueryResult] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
