from __future__ import annotations
from dataclasses import dataclass
from .base import ProviderAdapter

@dataclass(frozen=True)
class SegmentSignature:
    origin:str; destination:str; departure_utc_or_local:str; marketing_carrier:str|None; operating_carrier:str|None; flight_number:str|None

def signature(offer):
    out=[]
    for d in (offer.outbound,offer.inbound):
        if not d: return tuple()
        for s in d.segments:
            out.append(SegmentSignature(s.origin,s.destination,s.departure_utc or s.departure_local,s.marketing_carrier,s.operating_carrier,s.flight_number))
    return tuple(out)

def exact_segment_match(a,b): return bool(a and b and a==b)

class DuffelAdapter(ProviderAdapter):
    name="DUFFEL"; role="CORROBORATION"
    def __init__(self,access_token:str,cfg:dict): self.access_token=access_token; self.cfg=cfg
    def configured(self): return bool(self.access_token)
    def search(self,job,search_id): raise NotImplementedError("Duffel is optional corroboration in V1.0; not required for discovery completeness")
    def revalidate(self,offer,job): return offer,{"revalidation_provider":self.name,"same_provider_revalidation":False,"independent_source_corroboration":False,"status":"NOT_RUN"}
