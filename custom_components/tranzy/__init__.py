"""Tranzy: live departure boards for public-transport stops."""

from __future__ import annotations

import pathlib

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import TranzyApi
from .const import CARD_URL, CONF_AGENCY_ID, CONF_STOP_ID, DOMAIN
from .coordinator import TranzyCoordinator

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TranzyConfigEntry = ConfigEntry[TranzyCoordinator]

CARD_FILE = pathlib.Path(__file__).parent / "www" / "tranzy-board-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the board card with the integration, so one install brings both."""
    version = (await async_get_integration(hass, DOMAIN)).version
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TranzyConfigEntry) -> bool:
    api = TranzyApi(async_get_clientsession(hass), entry.data[CONF_API_KEY], entry.data[CONF_AGENCY_ID])
    coordinator = TranzyCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _migrate_stop_titles(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _migrate_stop_titles(hass: HomeAssistant, entry: TranzyConfigEntry, coordinator: TranzyCoordinator) -> None:
    """0.1.0 titled stops `name → destination`; give them their own name back.

    Runs before the update listener is added, so it does not trigger a reload.
    Titles without the arrow (the new form, or renamed by hand) are left alone.
    """
    index = coordinator.index
    for sub in list(entry.subentries.values()):
        stop_id = int(sub.data.get(CONF_STOP_ID, -1))
        if " → " in sub.title and index and stop_id in index.stops:
            hass.config_entries.async_update_subentry(entry, sub, title=index.stop_title(stop_id))


async def _async_reload(hass: HomeAssistant, entry: TranzyConfigEntry) -> None:
    """Stops added or removed, options changed: rebuild the entities."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TranzyConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
