from __future__ import annotations
from typing import Any

OPENAPI_VERSION = "3.1.0"
IGNAV_API_CONTRACT_VERSION = "1.0.0"
OPENAPI_SOURCE_SHA = "7f57f5dbfb8e2d8ebbc9956a4c2860e8c887be50"

class IgnavContractError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

def _dict(v: Any, name: str) -> dict:
    if not isinstance(v, dict): raise IgnavContractError("SCHEMA_INVALID", f"{name} must be object")
    return v

def _list(v: Any, name: str) -> list:
    if not isinstance(v, list): raise IgnavContractError("SCHEMA_INVALID", f"{name} must be array")
    return v

def _str_or_none(v: Any, name: str):
    if v is not None and not isinstance(v, str): raise IgnavContractError("SCHEMA_INVALID", f"{name} must be string|null")

def _int_or_none(v: Any, name: str):
    if v is not None and (not isinstance(v, int) or isinstance(v, bool)): raise IgnavContractError("SCHEMA_INVALID", f"{name} must be integer|null")

def _bool_or_none(v: Any, name: str):
    if v is not None and not isinstance(v, bool): raise IgnavContractError("SCHEMA_INVALID", f"{name} must be boolean|null")

def _price(p: Any, name: str="price") -> dict:
    p=_dict(p,name)
    amount=p.get("amount")
    if not isinstance(amount,(int,float)) or isinstance(amount,bool): raise IgnavContractError("SCHEMA_INVALID",f"{name}.amount must be number")
    if not isinstance(p.get("currency"),str): raise IgnavContractError("SCHEMA_INVALID",f"{name}.currency must be string")
    if p.get("status") not in {"verified","unverified"}: raise IgnavContractError("SCHEMA_INVALID",f"{name}.status must be verified|unverified")
    return p

def _segment(s: Any, path: str):
    s=_dict(s,path)
    _str_or_none(s.get("marketing_carrier_code"),path+".marketing_carrier_code")
    _str_or_none(s.get("flight_number"),path+".flight_number")
    _str_or_none(s.get("operating_carrier_name"),path+".operating_carrier_name")
    for k in ("departure_airport","departure_time_local","arrival_airport","arrival_time_local"):
        if not isinstance(s.get(k),str): raise IgnavContractError("SCHEMA_INVALID",f"{path}.{k} must be string")
    for k in ("departure_timezone","departure_time_utc","arrival_timezone","arrival_time_utc","aircraft"):
        _str_or_none(s.get(k),path+"."+k)
    if not isinstance(s.get("duration_minutes"),int) or isinstance(s.get("duration_minutes"),bool):
        raise IgnavContractError("SCHEMA_INVALID",f"{path}.duration_minutes must be integer")

def _leg(leg: Any, path: str):
    leg=_dict(leg,path)
    _str_or_none(leg.get("carrier"),path+".carrier")
    _int_or_none(leg.get("duration_minutes"),path+".duration_minutes")
    segments=_list(leg.get("segments"),path+".segments")
    if not segments: raise IgnavContractError("SCHEMA_INVALID",f"{path}.segments empty")
    for i,s in enumerate(segments): _segment(s,f"{path}.segments[{i}]")

def validate_search_response(data: Any, expected_legs: int=2) -> dict:
    data=_dict(data,"response")
    top_legs=_list(data.get("legs"),"response.legs")
    if len(top_legs)!=expected_legs: raise IgnavContractError("SCHEMA_INVALID",f"response.legs expected {expected_legs}")
    for i,l in enumerate(top_legs):
        l=_dict(l,f"response.legs[{i}]")
        for k in ("origin","destination","departure_date"):
            if not isinstance(l.get(k),str): raise IgnavContractError("SCHEMA_INVALID",f"response.legs[{i}].{k} must be string")
    its=_list(data.get("itineraries"),"response.itineraries")
    for i,it in enumerate(its):
        it=_dict(it,f"itineraries[{i}]"); _price(it.get("price"),f"itineraries[{i}].price")
        legs=_list(it.get("legs"),f"itineraries[{i}].legs")
        if len(legs)!=expected_legs: raise IgnavContractError("SCHEMA_INVALID",f"itineraries[{i}].legs expected {expected_legs}")
        for j,l in enumerate(legs): _leg(l,f"itineraries[{i}].legs[{j}]")
        _str_or_none(it.get("cabin_class"),f"itineraries[{i}].cabin_class")
        _bool_or_none(it.get("requires_self_transfer"),f"itineraries[{i}].requires_self_transfer")
        _str_or_none(it.get("ignav_id"),f"itineraries[{i}].ignav_id")
        if it.get("bags") is not None:
            b=_dict(it["bags"],f"itineraries[{i}].bags"); _int_or_none(b.get("carry_on"),"bags.carry_on"); _int_or_none(b.get("checked"),"bags.checked")
    return data

def validate_booking_response(data: Any, expected_legs: int=2) -> dict:
    data=_dict(data,"booking_response")
    it=_dict(data.get("itinerary"),"booking_response.itinerary")
    _price(it.get("price"),"booking_response.itinerary.price")
    flexible="legs" in it
    if flexible:
        legs=_list(it.get("legs"),"booking_response.itinerary.legs")
        if len(legs)!=expected_legs: raise IgnavContractError("SCHEMA_INVALID","booking itinerary leg count mismatch")
        for i,l in enumerate(legs): _leg(l,f"booking_response.itinerary.legs[{i}]")
    else:
        _leg(it.get("outbound"),"booking_response.itinerary.outbound")
        inbound=it.get("inbound")
        if expected_legs==2 and inbound is None: raise IgnavContractError("SCHEMA_INVALID","booking inbound missing")
        if inbound is not None: _leg(inbound,"booking_response.itinerary.inbound")
    _str_or_none(it.get("cabin_class"),"booking_response.itinerary.cabin_class")
    _bool_or_none(it.get("requires_self_transfer"),"booking_response.itinerary.requires_self_transfer")
    options=_list(data.get("booking_options"),"booking_response.booking_options")
    for i,opt in enumerate(options):
        opt=_dict(opt,f"booking_options[{i}]")
        if flexible:
            indexes=_list(opt.get("leg_indexes"),f"booking_options[{i}].leg_indexes")
            if any(not isinstance(x,int) or isinstance(x,bool) for x in indexes): raise IgnavContractError("SCHEMA_INVALID","leg_indexes must be integers")
        else:
            legs=_list(opt.get("legs"),f"booking_options[{i}].legs")
            if any(x not in {"outbound","inbound"} for x in legs): raise IgnavContractError("SCHEMA_INVALID","booking legs invalid")
        links=_list(opt.get("links"),f"booking_options[{i}].links")
        for j,link in enumerate(links):
            link=_dict(link,f"booking_options[{i}].links[{j}]")
            if not isinstance(link.get("provider_name"),str): raise IgnavContractError("SCHEMA_INVALID","provider_name must be string")
            if link.get("provider_type") not in {"airline","third_party"}: raise IgnavContractError("SCHEMA_INVALID","provider_type invalid")
            if not isinstance(link.get("url"),str): raise IgnavContractError("SCHEMA_INVALID","url must be string")
            if link.get("price") is not None: _price(link["price"],f"booking_options[{i}].links[{j}].price")
    return data

def parse_error_payload(data: Any) -> dict:
    if not isinstance(data,dict) or not isinstance(data.get("error"),dict): return {}
    e=data["error"]
    return {"type":e.get("type") if isinstance(e.get("type"),str) else None,
            "code":e.get("code") if isinstance(e.get("code"),str) else None,
            "message":e.get("message") if isinstance(e.get("message"),str) else None,
            "field":e.get("field") if isinstance(e.get("field"),str) else None}
