from .base import ProviderAdapter
from .ignav import IgnavAdapter
from .duffel import DuffelAdapter
try:
    from .skyscanner import SkyscannerAdapter
except Exception:
    SkyscannerAdapter=None
