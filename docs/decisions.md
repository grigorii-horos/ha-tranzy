# Findings and decisions

A log of what was learned while building this integration and why it is the way
it is. Newest understanding wins; superseded decisions are kept with the reason
they were dropped, so they are not tried again.

## The Tranzy open-data API

- **Docs**: OpenAPI at `https://api.tranzy.ai/v1/opendata/openapi.json`, rendered
  at `/v1/opendata/docs`. The developer portal has no other documentation.
- **Auth**: header `X-API-KEY`; every endpoint except `/agency` also needs
  `X-Agency-Id`. Endpoints: `/agency`, `/vehicles`, `/routes`, `/trips`, `/shapes`
  (optional `shape_id`), `/stops`, `/stop_times`.
- **Keys** belong to an *application* in the account portal
  (`apps.tranzy.ai/accounts`); the application lists the agencies the key may
  read. A key used for another agency gets `403 Forbidden resource`.
- **A brand-new key answers 403 for a while** (minutes) on every endpoint,
  `/agency` included, and the portal's usage chart stays at zero — the requests
  are refused before they are counted. This looked like a wrong key at first.
  Hence the hint in the setup form.
- **Limits** (free plan): 5 req/s, burst 20, 5000 req/day per key.
- **Agencies** (2026-11): 1 SCTP Iași, 2 CTP Cluj, 4 RTEC&PUA Chișinău, plus
  OTL Oradea, Eltrans Botoșani and CT BUS (ids not checked); STPT Timișoara left
  the platform on 2026-02-19.
- The public live map (`apps.tranzy.ai/map/<city>`) ships its own key in its JS
  bundle. Not used: a personal key is free and the map's key is not ours to use.

### What the data does and does not have (Chișinău, agency 4)

| table | rows | notes |
|---|---|---|
| routes | 88 | `route_type` 3 = bus (57), 11 = trolleybus (31); `route_color` often `#000` |
| trips | 163 | one per route and direction; `trip_id` = `<route>_<dir>`, `shape_id` = `trip_id` |
| stops | 1277 | name, `stop_code` (filled for about half — city yes, villages no), lat/lon; **no description** |
| stop_times | 3833 | **only the order of stops** — `arrival_time`/`departure_time` are absent |
| shapes | ~68 000 points, 6.2 MB | **no `shape_dist_traveled`** |
| vehicles | ~680, ~330–480 on a trip at a time | position, `speed`, `timestamp`, `trip_id`; some timestamps are years old |

Consequences:

- **There are no arrival times anywhere** — not scheduled, not predicted. They
  have to be estimated from positions.
- Both sides of a street are separate stops **with the same name**; the only
  stop-level data to tell them apart is `stop_code` (when present) and
  coordinates.
- Names of the same place vary (`str. V. Alecsandri` / `str. Vasile Alecsandri`),
  and the same name exists in several towns (`str. Vasile Alecsandri` in Cricova,
  Budești, Băcioi, …). Twins are therefore "same normalized name within 400 m".

## The arrival estimate

Pure Python in `model.py`, no Home Assistant imports, so it is testable and
runnable from a terminal (`script/board.py`).

1. Shapes are projected to local metres (equirectangular around the agency's
   mean latitude) with cumulative distance per point.
2. Each stop of a trip is placed on the trip's shape **in order**: the search
   for stop *n* starts where stop *n−1* was placed, so loops cannot pull a later
   stop back.
3. A vehicle on a trip is placed at the nearest point of that trip's shape;
   more than 200 m off the line → ignored; position older than 5 min → ignored.
4. Distance **along the line** to the stop, driven at an average speed; the
   vehicle's fix time (not "now") is the start, which absorbs feed lag.
5. A vehicle on the **opposite trip of the same route** is counted too: to the
   end of its line, a wait at the terminus, then along the stop's trip (`via`, ↻).
6. A stop that is the **last** stop of a trip is not a boarding point for that
   trip: its vehicles appear as departures of the return trip (arrival + wait).
   Without this, a terminus board listed buses that terminate there, labelled
   with the terminus's own name.
7. One row per vehicle (the earliest), sorted, 60-minute horizon.

### Calibration

`script/accuracy.py` predicts every board every 30 s and watches every vehicle:
the moment its along-line position crosses a stop is that stop's real arrival,
interpolated between the two fixes. Earlier predictions are then scored.

Run 2026-11-02, 16:00–17:30 local (evening rush), whole city: 239 593 predictions,
13 124 real arrivals.

- At the first default, **20 km/h**, the board was early everywhere and the error
  grew with distance: −2.2 min at 5–10 min ahead, −8.9 at 20–40.
- Fitted: **13.1 km/h**, **2.5 min** wait at the terminus.
- Chosen defaults: **14 km/h, 4 min** — rounded towards off-peak traffic. Median
  error ≈ 0 up to 20 min ahead; 83 % within ±2 min at 0–5 min ahead, 52 % at 5–10.
- Open: the sample is rush hour only. Off-peak vehicles are faster; a second run
  at midday would show whether the default should move up or become
  time-of-day dependent.

## Home Assistant design

- **One config entry per agency** (key + agency, `unique_id` = agency id).
  **Stops are config subentries** (HA 2025.3+): added from the integration page
  with "Add stop", each its own device (`entry_type: service`) with one sensor.
  Chosen over options-flow lists: each stop gets a device, an entity, a delete
  button, and HA's own UI.
- **One coordinator per entry**: static data once a day (5 requests), vehicles
  every 30 s in **one request shared by all stops** (~2900/day of 5000). CPU work
  (index build, locating vehicles) runs in the executor.
- **Sensor**: state = minutes to the next vehicle (`device_class: duration`),
  `unknown` when none; the board in attribute `arrivals` (≤ 20). `arrivals` and
  `updated` are in `_unrecorded_attributes` — the board changes every 30 s and
  must not fill the recorder.
- **Options**: speed, terminus wait, scan interval, max position age. An entry
  without saved options follows the defaults, so a release can retune them.
- **Reauth**: a 401/403 at runtime raises `ConfigEntryAuthFailed` → re-enter the key.
- **The card ships inside the integration**: served from `www/` via
  `async_register_static_paths` + `add_extra_js_url(…?v=<version>)`. One install,
  versions cannot drift, no Lovelace resource to add. (HACS could not ship it
  separately anyway: one repository is one category.)
- **Brand icon** in `custom_components/tranzy/brand/` (`icon.png`, `icon@2x.png`).
  HA serves custom-integration brand images itself — but decides `has_branding`
  **at startup**: adding the folder needs a restart before the icon shows.

### Naming stops — how it got here

The picker and the device titles went through three versions:

1. **`name → destination`** (most common headsign). Rejected by the user: the
   arrow reads as part of an address, and the destination is the far end of
   *some* route — often not one the rider takes.
2. **Destinations grouped with routes** in the picker. Still read as noise.
3. **Current** — only the stop's own data in the title, context in the picker:
   - title: the stop name; a twin gets ` #<stop_code>` or, without codes,
     ` (<compass side> side)` relative to the twin pair's centre;
   - picker line: `Name #13 [routes] · next: <next stop> (routes) / … · terminus (routes)`.
     The **next stop** is shown because it is a place the rider knows; routes are
     attached to each next stop because routes **split** right after a stop, so
     a single "next" would lie.
   - each stop device links to OpenStreetMap at the pole (`configuration_url`).
   - titles of the form `… → …` from v0.1 are migrated on setup; titles without
     an arrow (new form or renamed by hand) are left alone.

A stop is a **pole, not a route**: its sensor lists every route serving it. The
card's `routes` filter is how a board shows only the lines one rides.

### The card

- Layout chosen from mockups: an **arrivals feed** (airport style), nearest on
  top — over per-route rows, a street-style LED board and compact chips.
- **Low header** (name + update time, ~28 px), not the stock tile's 56 px row: on
  a board the rows are the content. The `ha-tile-*` components were tried and
  dropped for this card for that reason.
- **Height like the ha-plugins tiles**: `rows: "auto"` by default (the card is as
  tall as `rows` arrivals); when the layout height is set by hand the card fills
  it (`:host([filled])`), lists up to 20 and **scrolls inside the board**, the
  header fixed.
- Minutes are recomputed in the browser from each arrival's timestamp every 15 s,
  so the board counts down between updates; the header turns amber "data is
  stale" after 3 min without an update.
- Badge colour by vehicle type (trolleybus blue, bus green, tram red), not
  `route_color` (mostly `#000` in the feed). In Russian the badge reads `Т 5` /
  `А 47`.
- Vanilla custom element, no build step.

## Tooling and gotchas

- **hassfest** rejects URLs inside translation strings → `{accounts_url}`
  description placeholder.
- **HACS validation** needs: repository description, topics, `hacs.json`,
  a release made after the actions pass (for the default list).
- **Tests**: `tests/test_model.py` (stdlib unittest, no HA) and `tests/test_init.py`
  (pytest-homeassistant-custom-component, pinned to the HA version, plus
  `home-assistant-frontend` because the integration depends on `frontend`).
  `python3 -I -m unittest tests/...` fails once `tests/` is a package; run the
  file directly.
- A dashboard tab opened before a card update shows "Configuration error" until
  reloaded (Ctrl+Shift+R).
- Screenshots for the docs: HA's English UI; cards rendered as temporary elements
  on the HA page with live data computed by `model.py`, so no dashboard is edited.
- HACS: `hacs/repositories/add` + `hacs/repository/download` over the HA
  websocket install a custom repository without the UI; after a download HACS
  reports "pending restart".

## Status (2026-11-03)

- v0.3.1 released; CI (tests, hassfest, HACS) green.
- Submitted to the HACS default list: hacs/default#13199.
- Open: off-peak calibration run; time-of-day speed if it differs much;
  `stop_title` for a busy terminus with no twin is just its name (fine), but a
  terminus that has a twin gets a compass side, which says little.
