"""Web API for the Guardian Console: approval service + SSE + read models."""

from aegis.api.app import create_api_app
from aegis.api.config import ApiConfig

__all__ = ["ApiConfig", "create_api_app"]
