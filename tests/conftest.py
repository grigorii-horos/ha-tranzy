"""Fixtures for the Home Assistant tests (pytest-homeassistant-custom-component)."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest

from custom_components.tranzy.api import TranzyAuthError

from .data import static, vehicle

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/tranzy."""
    return


class FakeApi:
    """Stands in for the Tranzy API: the synthetic agency, settable vehicles and key."""

    def __init__(self) -> None:
        self.data = static()
        self.vehicles = [vehicle(1, "1_0", 0.25)]
        self.refused = False
        self.calls: list[str] = []

    async def get(self, api, path: str, timeout: float = 30):
        self.calls.append(path)
        if self.refused:
            raise TranzyAuthError(f"{path}: HTTP 403")
        if path == "vehicles":
            return self.vehicles
        return self.data[path]


@pytest.fixture
def api() -> Generator[FakeApi]:
    fake = FakeApi()

    async def _get(self, path, timeout=30):
        return await fake.get(self, path, timeout)

    with patch("custom_components.tranzy.api.TranzyApi._get", _get):
        yield fake
