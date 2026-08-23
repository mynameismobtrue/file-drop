from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from ..models import ProviderQueryResult, Offer

class ProviderAdapter(ABC):
    name: str
    role: str
    @abstractmethod
    def configured(self)->bool: ...
    @abstractmethod
    def search(self, job:dict[str,Any], search_id:str)->ProviderQueryResult: ...
    @abstractmethod
    def revalidate(self, offer:Offer, job:dict[str,Any])->tuple[Offer,dict[str,Any]]: ...
