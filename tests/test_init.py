"""Config flow, stop subentries, the sensor and the card's static path."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tranzy.const import (
    CARD_URL,
    CONF_AGENCY_ID,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DOMAIN,
    SUBENTRY_STOP,
)

from .data import vehicle

KEY = "test-key"


def make_entry(stops: list[tuple[int, str]] = ()) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="RTEC&PUA Chisinau",
        unique_id="4",
        data={CONF_API_KEY: KEY, CONF_AGENCY_ID: "4"},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_STOP,
                title=title,
                unique_id=str(stop_id),
                data={CONF_STOP_ID: stop_id, CONF_STOP_NAME: title},
            )
            for stop_id, title in stops
        ],
    )


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# ---- config flow -------------------------------------------------------------


async def test_flow_creates_entry_for_the_picked_agency(hass: HomeAssistant, api) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: f"  {KEY} "})
    assert result["step_id"] == "agency"
    labels = [o["label"] for o in result["data_schema"].schema[CONF_AGENCY_ID].config["options"]]
    assert labels == ["CTP Cluj", "RTEC&PUA Chisinau"]  # sorted by name

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AGENCY_ID: "4"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "RTEC&PUA Chisinau"
    assert result["data"] == {CONF_API_KEY: KEY, CONF_AGENCY_ID: "4"}  # key stripped


async def test_flow_refused_key(hass: HomeAssistant, api) -> None:
    api.refused = True
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: KEY})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_flow_key_not_allowed_for_agency(hass: HomeAssistant, api) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: KEY})
    api.refused = True  # /agency answered, /routes for the agency does not
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AGENCY_ID: "2"})
    assert result["errors"] == {"base": "agency_forbidden"}


async def test_flow_agency_already_configured(hass: HomeAssistant, api) -> None:
    make_entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: KEY})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_AGENCY_ID: "4"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_refused_key_starts_reauth_and_new_key_fixes_it(hass: HomeAssistant, api) -> None:
    api.refused = True
    entry = make_entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]

    api.refused = False
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {CONF_API_KEY: "new-key"})
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.state is ConfigEntryState.LOADED


# ---- stops --------------------------------------------------------------------


async def test_add_stop_by_name_then_pole(hass: HomeAssistant, api) -> None:
    entry = make_entry()
    await setup(hass, entry)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_STOP), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"query": "nothing like it"})
    assert result["errors"] == {"base": "no_stops"}

    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"query": "CENTRU"})
    assert result["step_id"] == "pick"
    options = {o["value"]: o["label"] for o in result["data_schema"].schema[CONF_STOP_ID].config["options"]}
    assert options == {
        "11": "Centru (W side) [5] · next: Nord",
        "21": "Centru (E side) [5] · next: Șoseaua Sud",
    }

    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_STOP_ID: "11"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Centru (W side)"
    await hass.async_block_till_done()  # the entry reloads with the new stop

    state = hass.states.get("sensor.centru_w_side")
    assert state is not None
    assert state.attributes["stop_id"] == 11


async def test_added_stops_are_not_offered_again(hass: HomeAssistant, api) -> None:
    entry = make_entry([(11, "Centru (W side)")])
    await setup(hass, entry)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_STOP), context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"query": "centru"})
    options = [o["value"] for o in result["data_schema"].schema[CONF_STOP_ID].config["options"]]
    assert options == ["21"]


async def test_old_arrow_titles_are_migrated(hass: HomeAssistant, api) -> None:
    entry = make_entry([(11, "Centru → North"), (12, "My own name")])
    await setup(hass, entry)
    titles = sorted(s.title for s in entry.subentries.values())
    assert titles == ["Centru (W side)", "My own name"]


# ---- sensor -------------------------------------------------------------------


async def test_sensor_state_and_board(hass: HomeAssistant, api) -> None:
    api.vehicles = [
        vehicle(1, "1_0", 0.25),  # northbound, ~278 m before the stop
        vehicle(2, "1_1", 0.25),  # southbound, comes back via the north terminus
        vehicle(3, "1_0", 0.75),  # already past the stop
        vehicle(4, "1_0", 0.30, age_s=900),  # position too old
    ]
    entry = make_entry([(11, "Centru (W side)")])
    await setup(hass, entry)

    state = hass.states.get("sensor.centru_w_side")
    assert state.state == "1"  # 278 m at 14 km/h: 71 s
    assert state.attributes["unit_of_measurement"] == "min"
    board = state.attributes["arrivals"]
    assert [(a["vehicle"], a["via_terminal"]) for a in board] == [("V1", False), ("V2", True)]
    assert abs(board[0]["distance_m"] - 278) <= 5
    assert board[0] | {"arrival": None, "minutes": None, "distance_m": None} == {
        "route": "5",
        "type": "trolleybus",
        "color": "#123456",
        "headsign": "North",
        "arrival": None,
        "minutes": None,
        "vehicle": "V1",
        "distance_m": None,
        "via_terminal": False,
    }
    assert 6 <= board[1]["minutes"] <= 8  # 834 m at 14 km/h (3.6 min) + 4 min at the terminus


async def test_sensor_unknown_when_nothing_is_coming(hass: HomeAssistant, api) -> None:
    api.vehicles = []
    entry = make_entry([(11, "Centru (W side)")])
    await setup(hass, entry)
    state = hass.states.get("sensor.centru_w_side")
    assert state.state == "unknown"
    assert state.attributes["arrivals"] == []


async def test_stop_device_links_to_the_map(hass: HomeAssistant, api) -> None:
    entry = make_entry([(11, "Centru (W side)")])
    await setup(hass, entry)
    ent = er.async_get(hass).async_get("sensor.centru_w_side")
    device = dr.async_get(hass).async_get(ent.device_id)
    assert device.name == "Centru (W side)"
    assert device.configuration_url.startswith("https://www.openstreetmap.org/?mlat=47.005")
    assert device.entry_type is dr.DeviceEntryType.SERVICE


async def test_one_vehicles_request_per_update_for_all_stops(hass: HomeAssistant, api) -> None:
    entry = make_entry([(11, "Centru (W side)"), (21, "Centru (E side)"), (12, "Nord")])
    await setup(hass, entry)
    assert api.calls.count("vehicles") == 1
    assert api.calls.count("shapes") == 1


async def test_unload(hass: HomeAssistant, api) -> None:
    entry = make_entry([(11, "Centru (W side)")])
    await setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_card_is_served(hass: HomeAssistant, hass_client, api) -> None:
    await setup(hass, make_entry())
    client = await hass_client()
    resp = await client.get(CARD_URL)
    assert resp.status == 200
    assert "customElements.define(\"tranzy-board-card\"" in await resp.text()
