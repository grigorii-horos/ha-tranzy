/**
 * tranzy-board-card — departure board of one stop, served by the Tranzy integration.
 *
 *   type: custom:tranzy-board-card
 *   entity: sensor.gara
 *   rows: 6          # optional, default 6: how many arrivals on an automatic height
 *   routes: [47, 48] # optional, only these routes
 *   title: Вокзал    # optional, default the stop name
 *
 * The header is a low line of its own (name and update time) rather than the
 * stock tile's 56px row: on a board the rows are the content.
 *
 * Height follows the cards of ../ha-plugins. On `rows: auto` (the default) the
 * card is as tall as `rows` arrivals. When the height is set by hand in the
 * layout, the card fills its slot, the board takes all the room under the
 * header and lists every arrival — scrolling when they do not fit.
 *
 * Minutes are recomputed in the browser from each arrival's timestamp, so the
 * board counts down between the integration's updates.
 */

const TYPE_COLOR = {
  trolleybus: "#1e88e5",
  bus: "#43a047",
  tram: "#e53935",
  other: "#757575",
};
const TYPE_LETTER_RU = { trolleybus: "Т", bus: "А", tram: "Тр" };
const MAX_ROWS = 20;
const STALE_MS = 3 * 60 * 1000;
const TICK_MS = 15000;

const TEXT = {
  en: {
    now: "now",
    min: "min",
    empty: "No vehicles on the way",
    unavailable: "No data",
    stale: "data is stale",
    updated: "updated",
    entity: "Stop sensor",
    rows: "Rows",
    routes: "Only routes",
    title: "Title",
    via: "after the terminus",
  },
  ru: {
    now: "сейчас",
    min: "мин",
    empty: "Нет машин на линии",
    unavailable: "Нет данных",
    stale: "данные устарели",
    updated: "обновлено",
    entity: "Сенсор остановки",
    rows: "Строк",
    routes: "Только маршруты",
    title: "Заголовок",
    via: "после конечной",
  },
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const lang = (hass) => ((hass?.locale?.language || hass?.language || "en").startsWith("ru") ? "ru" : "en");

const STYLES = `
  :host { display: block; }
  /* Fill the slot only when the height was set by hand; on auto keep the natural height. */
  :host([filled]) { height: 100%; }
  ha-card {
    height: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    cursor: pointer;
  }
  .head {
    flex: none;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    padding: var(--ha-space-2, 8px) var(--ha-space-3, 12px) var(--ha-space-1, 4px);
  }
  .title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
    color: var(--primary-text-color);
  }
  .sub {
    flex: none;
    white-space: nowrap;
    font-size: var(--ha-font-size-s, 12px);
    color: var(--secondary-text-color);
  }
  /* The board takes whatever height is left and scrolls inside it. */
  .board {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0 var(--ha-space-3, 12px) var(--ha-space-2, 8px);
    scrollbar-width: thin;
  }
  .row {
    display: grid;
    grid-template-columns: 48px 1fr auto;
    gap: 10px;
    align-items: center;
    min-height: 32px;
    border-top: 1px solid var(--divider-color);
  }
  .badge {
    justify-self: start;
    min-width: 36px;
    box-sizing: border-box;
    padding: 2px 5px;
    border-radius: var(--ha-border-radius-sm, 6px);
    text-align: center;
    font-weight: 700;
    font-size: var(--ha-font-size-s, 13px);
    font-variant-numeric: tabular-nums;
    color: #fff;
  }
  .dest {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: var(--ha-font-size-m, 14px);
    color: var(--primary-text-color);
  }
  .via { color: var(--secondary-text-color); }
  .min {
    white-space: nowrap;
    font-weight: 600;
    font-size: var(--ha-font-size-m, 14px);
    font-variant-numeric: tabular-nums;
    color: var(--primary-text-color);
  }
  .min.now { color: var(--warning-color, #ffa600); }
  .empty {
    padding: 6px 0;
    border-top: 1px solid var(--divider-color);
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
  }
  .sub.stale { color: var(--warning-color, #ffa600); }
`;

class TranzyBoardCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { filter: { integration: "tranzy", domain: "sensor" } } } },
        { name: "rows", selector: { number: { min: 1, max: MAX_ROWS, mode: "box" } } },
        { name: "routes", selector: { text: { multiple: true } } },
        { name: "title", selector: { text: {} } },
      ],
      computeLabel: (s) => TEXT[lang(document.querySelector("home-assistant")?.hass)][s.name],
    };
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("sensor.") && Array.isArray(hass.states[id].attributes?.arrivals),
    );
    return { entity: entity || "" };
  }

  setConfig(config) {
    if (!config?.entity) throw new Error("entity is required");
    this._config = { rows: 6, ...config };
    this._update();
  }

  set hass(hass) {
    const before = this._hass?.states?.[this._config?.entity];
    const langBefore = this._hass && lang(this._hass);
    this._hass = hass;
    if (hass.states[this._config?.entity] !== before || lang(hass) !== langBefore) this._update();
  }

  connectedCallback() {
    this._timer = setInterval(() => this._update(), TICK_MS);
    this._update();
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  getCardSize() {
    return 1 + Math.ceil((this._config?.rows ?? 6) / 2);
  }

  /** Like the ha-plugins tiles: height from the content unless set by hand. */
  getGridOptions() {
    return { columns: 6, rows: "auto", min_columns: 6, min_rows: 2 };
  }

  get _fixedHeight() {
    return typeof this._config?.grid_options?.rows === "number";
  }

  _moreInfo() {
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId: this._config.entity };
    this.dispatchEvent(ev);
  }

  /** The skeleton is built once; ticks only refresh texts and the board. */
  _build() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLES}</style>
      <ha-card>
        <div class="head"><span class="title"></span><span class="sub"></span></div>
        <div class="board"></div>
      </ha-card>`;
    this.shadowRoot.querySelector("ha-card").addEventListener("click", () => this._moreInfo());
    this._built = true;
  }

  _update() {
    if (!this._config || !this._hass || !this.isConnected) return;
    if (!this._built) this._build();
    const root = this.shadowRoot;
    const t = TEXT[lang(this._hass)];
    const ru = lang(this._hass) === "ru";
    const st = this._hass.states[this._config.entity];
    const a = st?.attributes ?? {};
    const fixed = this._fixedHeight;
    this.toggleAttribute("filled", fixed);

    // the line: name, and when the data was fetched
    root.querySelector(".title").textContent =
      this._config.title || a.friendly_name || a.stop_name || this._config.entity;
    let secondary = "";
    let stale = false;
    if (a.updated) {
      const u = new Date(a.updated);
      stale = Date.now() - u.getTime() > STALE_MS;
      const time = u.toLocaleTimeString(this._hass.locale?.language || undefined, { hour: "2-digit", minute: "2-digit" });
      secondary = `${stale ? t.stale : t.updated} ${time}`;
    }
    const sec = root.querySelector(".sub");
    sec.textContent = secondary;
    sec.classList.toggle("stale", stale);

    // the board
    let body;
    if (!st || st.state === "unavailable") {
      body = `<div class="empty">${esc(t.unavailable)}</div>`;
    } else {
      const now = Date.now();
      const only = (this._config.routes ?? []).map((r) => String(r).trim()).filter(Boolean);
      const rows = (a.arrivals ?? [])
        .filter((x) => !only.length || only.includes(String(x.route)))
        .map((x) => ({ ...x, ms: new Date(x.arrival).getTime() - now }))
        .filter((x) => x.ms > -60000)
        .sort((p, q) => p.ms - q.ms)
        .slice(0, fixed ? MAX_ROWS : this._config.rows);
      body = rows.length
        ? rows
            .map((x) => {
              const minutes = Math.floor(x.ms / 60000);
              const soon = minutes <= 0;
              const letter = ru ? TYPE_LETTER_RU[x.type] : "";
              const label = letter ? `${letter}&nbsp;${esc(x.route)}` : esc(x.route);
              const bg = TYPE_COLOR[x.type] ?? TYPE_COLOR.other;
              const via = x.via_terminal ? ` title="${esc(t.via)}"` : "";
              return `<div class="row">
                <span class="badge" style="background:${bg}">${label}</span>
                <span class="dest"${via}>${esc(x.headsign)}${x.via_terminal ? ' <span class="via">↻</span>' : ""}</span>
                <span class="min${soon ? " now" : ""}">${soon ? esc(t.now) : `${minutes}&nbsp;${esc(t.min)}`}</span>
              </div>`;
            })
            .join("")
        : `<div class="empty">${esc(t.empty)}</div>`;
    }
    const board = root.querySelector(".board");
    const scroll = board.scrollTop;
    board.innerHTML = body;
    board.scrollTop = scroll;
  }
}

if (!customElements.get("tranzy-board-card")) {
  customElements.define("tranzy-board-card", TranzyBoardCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "tranzy-board-card",
    name: "Tranzy board",
    description: "Departure board of a public-transport stop",
    preview: true,
  });
}
