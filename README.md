# Tranzy for Home Assistant

Live departure boards for public-transport stops, from the
[Tranzy open-data API](https://tranzy.ai/opendata/) (Chișinău, Iași, Cluj-Napoca,
Botoșani, Oradea, …). One sensor per stop you pick, and a board card that ships
with the integration.

## Install

Copy `custom_components/tranzy` into `<config>/custom_components/` (or add this
repository to HACS as a custom integration) and restart Home Assistant. The board
card is served by the integration itself: no dashboard resource to add.

## Set up

1. Get a key at <https://apps.tranzy.ai/accounts>: create an application with your
   agency, then a key in it. A brand-new key answers HTTP 403 for a few minutes.
2. *Settings → Devices & services → Add integration → Tranzy*: paste the key, pick
   the agency.
3. On the Tranzy entry, **Add stop**: type part of the name (`gara`, diacritics
   optional), then pick the pole. A stop usually has a pole on each side of the
   street; the list shows where the routes of each pole go.
4. Add the card:

```yaml
type: custom:tranzy-board-card
entity: sensor.gara_parcul_de_troleibuze_nr_2
rows: 6        # optional
title: Вокзал  # optional, default the stop's name
routes: [47, 48]  # optional, show only these routes
```

At a terminus the board shows departures: a vehicle arriving there is listed with
its return trip, after the layover.

## How arrivals are estimated

The feed has live vehicle positions but **no arrival times**: `stop_times` only
gives the order of stops, `shapes` no distances. So each vehicle is placed on the
line of its trip, the distance along the line to the stop is driven at an average
speed, and the age of the position is subtracted. A vehicle on the opposite
direction of the same route is counted too: to the terminus, a layover there, and
back to the stop (marked ↻ on the board).

Options (*Configure* on the entry): average speed (20 km/h), layover at the
terminus (5 min), update interval (30 s — one request each, against a free quota
of 5000/day), and the age after which a vehicle position is ignored (5 min).

Static data (routes, trips, stops, shapes — about 6 MB for Chișinău) is loaded once
a day.

## The sensor

State: minutes to the next vehicle. Attributes: `stop_id`, `stop_name`,
`stop_code`, `updated`, and `arrivals` — up to 20 of
`{route, type, color, headsign, arrival, minutes, vehicle, distance_m, via_terminal}`.
`arrivals` and `updated` are not recorded in history.

## Development

```sh
python3 -m unittest discover -s tests          # model tests, no Home Assistant needed
TRANZY_API_KEY=… script/board.py --agency 4 gara   # live board in the terminal
script/publish.sh                              # copy to the HA host (restart HA after Python changes)
```

`custom_components/tranzy/model.py` is pure Python: the index and the estimate
live there; everything else is Home Assistant glue.
