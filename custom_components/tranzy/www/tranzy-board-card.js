/**
 * tranzy-board-card — departure board of one stop, served by the Tranzy integration.
 *
 *   type: custom:tranzy-board-card
 *   entity: sensor.gara
 *   rows: 6          # optional, default 6
 *   routes: [47, 48] # optional, only these routes
 *   title: Вокзал    # optional, default the stop name
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

const TEXT = {
  en: {
    now: "now",
    min: "min",
    empty: "No vehicles on the way",
    unavailable: "No data",
    stale: "data is stale",
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
    entity: "Сенсор остановки",
    rows: "Строк",
    routes: "Только маршруты",
    title: "Заголовок",
    via: "после конечной",
  },
};

const STALE_MS = 3 * 60 * 1000;

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const lang = (hass) => (hass?.locale?.language || hass?.language || "en").startsWith("ru") ? "ru" : "en";

class TranzyBoardCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { filter: { integration: "tranzy", domain: "sensor" } } } },
        { name: "rows", selector: { number: { min: 1, max: 20, mode: "box" } } },
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
    return { entity: entity || "", rows: 6 };
  }

  setConfig(config) {
    if (!config?.entity) throw new Error("entity is required");
    this._config = { rows: 6, ...config };
    this._render();
  }

  set hass(hass) {
    const before = this._hass?.states?.[this._config?.entity];
    const langBefore = this._hass && lang(this._hass);
    this._hass = hass;
    if (hass.states[this._config?.entity] !== before || lang(hass) !== langBefore) this._render();
  }

  connectedCallback() {
    this._timer = setInterval(() => this._render(), 15000);
    this._render();
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  getCardSize() {
    return 1 + Math.ceil((this._config?.rows ?? 6) / 2);
  }

  getGridOptions() {
    const rows = this._config?.rows ?? 6;
    return { columns: 12, min_columns: 6, rows: Math.max(2, Math.ceil((48 + rows * 33) / 64)) };
  }

  _moreInfo() {
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId: this._config.entity };
    this.dispatchEvent(ev);
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", () => this._moreInfo());
    }
    const t = TEXT[lang(this._hass)];
    const ru = lang(this._hass) === "ru";
    const st = this._hass.states[this._config.entity];
    const a = st?.attributes ?? {};
    const title = this._config.title || a.friendly_name || a.stop_name ||this._config.entity;

    let updated = "";
    let stale = false;
    if (a.updated) {
      const u = new Date(a.updated);
      stale = Date.now() - u.getTime() > STALE_MS;
      updated = u.toLocaleTimeString(this._hass.locale?.language || undefined, { hour: "2-digit", minute: "2-digit" });
    }

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
        .slice(0, this._config.rows);
      body = rows.length
        ? rows
            .map((x) => {
              const minutes = Math.floor(x.ms / 60000);
              const soon = minutes <= 0;
              const letter = ru ? TYPE_LETTER_RU[x.type] : "";
              const label = letter ? `${letter}&nbsp;${esc(x.route)}` : esc(x.route);
              const color = TYPE_COLOR[x.type] ?? TYPE_COLOR.other;
              const via = x.via_terminal ? ` title="${esc(t.via)}"` : "";
              return `<div class="row">
                <span class="badge" style="background:${color}">${label}</span>
                <span class="dest"${via}>${esc(x.headsign)}${x.via_terminal ? ' <span class="via">↻</span>' : ""}</span>
                <span class="min${soon ? " now" : ""}">${soon ? esc(t.now) : `${minutes}&nbsp;${esc(t.min)}`}</span>
              </div>`;
            })
            .join("")
        : `<div class="empty">${esc(t.empty)}</div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { height: 100%; box-sizing: border-box; padding: 12px 16px; cursor: pointer; overflow: hidden; }
        .head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin-bottom: 6px; }
        .title { font-size: 16px; font-weight: 500; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .upd { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; }
        .upd.stale { color: var(--warning-color, #ffa600); }
        .row { display: grid; grid-template-columns: 48px 1fr auto; gap: 10px; align-items: center; min-height: 32px; border-top: 1px solid var(--divider-color); }
        .badge { justify-self: start; min-width: 36px; text-align: center; border-radius: 6px; padding: 2px 5px; box-sizing: border-box;
                 font-weight: 700; font-size: 13px; color: #fff; font-variant-numeric: tabular-nums; }
        .dest { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; color: var(--primary-text-color); }
        .via { color: var(--secondary-text-color); }
        .min { font-weight: 600; font-size: 14px; font-variant-numeric: tabular-nums; color: var(--primary-text-color); white-space: nowrap; }
        .min.now { color: var(--warning-color, #ffa600); }
        .empty { padding: 8px 0; color: var(--secondary-text-color); border-top: 1px solid var(--divider-color); }
      </style>
      <ha-card>
        <div class="head">
          <span class="title">${esc(title)}</span>
          <span class="upd${stale ? " stale" : ""}">${stale ? esc(t.stale) + " · " : ""}${esc(updated)}</span>
        </div>
        ${body}
      </ha-card>`;
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
