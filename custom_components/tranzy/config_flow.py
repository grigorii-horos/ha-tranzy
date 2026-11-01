"""Config flow: key + agency, then stops as subentries found by name."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import TranzyApi, TranzyAuthError, TranzyError
from .const import (
    CONF_AGENCY_ID,
    CONF_LAYOVER,
    CONF_MAX_AGE,
    CONF_SCAN_INTERVAL,
    CONF_SPEED,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DEFAULT_LAYOVER,
    DEFAULT_MAX_AGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SPEED,
    DOMAIN,
    LOGGER,
    SUBENTRY_STOP,
)

KEY_SCHEMA = vol.Schema(
    {vol.Required(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}
)
CONF_QUERY = "query"


class TranzyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._key: str | None = None
        self._agencies: dict[str, str] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_STOP: StopSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TranzyOptionsFlow()

    async def _check(self, key: str, agency: str | None) -> str | None:
        """Return an error key, or None when the key works (for the agency)."""
        api = TranzyApi(async_get_clientsession(self.hass), key, agency)
        try:
            if agency is None:
                agencies = await api.agencies()
                self._agencies = {str(a["agency_id"]): a["agency_name"] for a in agencies}
            else:
                await api._get("routes")
        except TranzyAuthError:
            return "invalid_auth"
        except TranzyError:
            LOGGER.exception("Tranzy API check failed")
            return "cannot_connect"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if not (error := await self._check(key, None)):
                self._key = key
                return await self.async_step_agency()
            errors["base"] = error
        return self.async_show_form(step_id="user", data_schema=KEY_SCHEMA, errors=errors)

    async def async_step_agency(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            agency = user_input[CONF_AGENCY_ID]
            await self.async_set_unique_id(agency)
            self._abort_if_unique_id_configured()
            if not (error := await self._check(self._key, agency)):
                return self.async_create_entry(
                    title=self._agencies.get(agency, f"Agency {agency}"),
                    data={CONF_API_KEY: self._key, CONF_AGENCY_ID: agency},
                )
            errors["base"] = "agency_forbidden" if error == "invalid_auth" else error
        options = [
            SelectOptionDict(value=k, label=v)
            for k, v in sorted(self._agencies.items(), key=lambda kv: kv[1])
        ]
        schema = vol.Schema(
            {vol.Required(CONF_AGENCY_ID): SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST))}
        )
        return self.async_show_form(step_id="agency", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            if not (error := await self._check(key, entry.data[CONF_AGENCY_ID])):
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: key})
            errors["base"] = error
        return self.async_show_form(step_id="reauth_confirm", data_schema=KEY_SCHEMA, errors=errors)


class TranzyOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options

        def num(lo: float, hi: float, step: float, unit: str) -> NumberSelector:
            return NumberSelector(
                NumberSelectorConfig(min=lo, max=hi, step=step, unit_of_measurement=unit, mode=NumberSelectorMode.BOX)
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_SPEED, default=o.get(CONF_SPEED, DEFAULT_SPEED)): num(5, 60, 0.5, "km/h"),
                vol.Required(CONF_LAYOVER, default=o.get(CONF_LAYOVER, DEFAULT_LAYOVER)): num(0, 60, 1, "min"),
                vol.Required(CONF_SCAN_INTERVAL, default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): num(20, 600, 5, "s"),
                vol.Required(CONF_MAX_AGE, default=o.get(CONF_MAX_AGE, DEFAULT_MAX_AGE)): num(1, 30, 1, "min"),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class StopSubentryFlow(ConfigSubentryFlow):
    """Add a stop: type part of its name, then pick the pole by its routes."""

    def __init__(self) -> None:
        self._matches: list[tuple[int, str]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        entry = self._get_entry()
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        errors: dict[str, str] = {}
        if user_input is not None:
            coordinator = entry.runtime_data
            index = coordinator.index or await coordinator.async_load_index()
            taken = {int(s.data[CONF_STOP_ID]) for s in entry.subentries.values()}
            self._matches = [m for m in index.search_stops(user_input[CONF_QUERY]) if m[0] not in taken]
            if self._matches:
                return await self.async_step_pick()
            errors["base"] = "no_stops"
        schema = vol.Schema({vol.Required(CONF_QUERY): TextSelector()})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        index = self._get_entry().runtime_data.index
        if user_input is not None:
            stop = index.stops[int(user_input[CONF_STOP_ID])]
            return self.async_create_entry(
                title=index.stop_title(stop.stop_id),
                data={CONF_STOP_ID: stop.stop_id, CONF_STOP_NAME: stop.name},
                unique_id=str(stop.stop_id),
            )
        options = [SelectOptionDict(value=str(stop_id), label=label) for stop_id, label in self._matches]
        schema = vol.Schema(
            {vol.Required(CONF_STOP_ID): SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST))}
        )
        return self.async_show_form(step_id="pick", data_schema=schema)
