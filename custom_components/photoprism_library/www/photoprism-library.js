/**
 * PhotoPrism Library frontend.
 *
 * - Adds a hover "delete permanently" button to photo previews opened from the
 *   media browser (only for photos of this integration, only for admins, only
 *   when deleting is enabled in the integration options).
 * - Defines `custom:photoprism-library-slideshow`: an Album Slideshow card with
 *   previous/next arrows on the photo, a loading spinner, the year the photo
 *   was taken and the delete button.
 */
const VERSION = "1.2.1";
const PHOTO_URL = /\/api\/photoprism_library\/(?:image|thumb)\/([^?#]+)/;
const PATH_DATE = /(?:^|\/)((?:19|20)\d{2})\/(0[1-9]|1[0-2])\/(0[1-9]|[12]\d|3[01])(?:\/|$)/;
const NAME_DATE = /(?<!\d)((?:19|20)\d{2})[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])(?!\d)/;

const TEXT = {
  en: {
    button: "Delete permanently",
    previous: "Previous photo",
    next: "Next photo",
    confirm: (files, photoprism) =>
      `Permanently delete this photo?\n\n${files.join("\n")}\n\n` +
      `The files are removed from disk${photoprism ? ", from PhotoPrism" : ""} and from Home Assistant. ` +
      "This cannot be undone.",
    deleted: (files) => `Deleted ${files}`,
    failed: (err) => `Could not delete: ${err}`,
    noPhoto: "No photo is shown right now",
    yearsAgo: (n) => (n === 0 ? "this year" : n === 1 ? "1 year ago" : `${n} years ago`),
  },
  pl: {
    button: "Usuń trwale",
    previous: "Poprzednie zdjęcie",
    next: "Następne zdjęcie",
    confirm: (files, photoprism) =>
      `Trwale usunąć to zdjęcie?\n\n${files.join("\n")}\n\n` +
      `Pliki zostaną usunięte z dysku${photoprism ? ", z PhotoPrism" : ""} i z Home Assistant. ` +
      "Tej operacji nie można cofnąć.",
    deleted: (files) => `Usunięto ${files}`,
    failed: (err) => `Nie udało się usunąć: ${err}`,
    noPhoto: "Teraz nie jest wyświetlane żadne zdjęcie",
    yearsAgo: (n) => {
      if (n === 0) return "w tym roku";
      if (n === 1) return "rok temu";
      const few = n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14);
      return `${n} ${few ? "lata" : "lat"} temu`;
    },
  },
};

const BUTTON_CSS = `
  .ppl-anchor { display: block; position: relative; height: 0; z-index: 5; }
  .ppl-del, .ppl-nav {
    position: absolute; z-index: 5; padding: 0; border: none; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.55); color: #fff; cursor: pointer;
    opacity: 0; transition: opacity 0.2s, background 0.2s;
  }
  .ppl-del { top: 12px; right: 12px; width: 44px; height: 44px; }
  .ppl-host:hover .ppl-del, .ppl-host:hover .ppl-nav, .ppl-visible .ppl-del, .ppl-del:focus-visible,
  .ppl-nav:focus-visible { opacity: 1; }
  .ppl-del:hover { background: var(--error-color, #db4437); }
  .ppl-nav:hover { background: rgba(0, 0, 0, 0.8); }
  .ppl-del[disabled] { opacity: 1; cursor: progress; background: rgba(0, 0, 0, 0.35); }
  @media (hover: none) { .ppl-del, .ppl-nav { opacity: 0.8; } }
`;
const CARD_CSS = `
  :host { display: block; height: 100%; }
  .ppl-host { position: relative; height: 100%; }
  .ppl-nav { top: 50%; width: 48px; height: 48px; margin-top: -24px; }
  .ppl-nav.prev { left: 12px; }
  .ppl-nav.next { right: 12px; }
  .ppl-spinner {
    position: absolute; z-index: 6; top: 50%; left: 50%; width: 44px; height: 44px; margin: -22px 0 0 -22px;
    border-radius: 50%; border: 4px solid rgba(255, 255, 255, 0.35); border-top-color: #fff;
    animation: ppl-spin 0.8s linear infinite; pointer-events: none; display: none;
    filter: drop-shadow(0 0 4px rgba(0, 0, 0, 0.6));
  }
  .ppl-loading .ppl-spinner { display: block; }
  @keyframes ppl-spin { to { transform: rotate(360deg); } }
  .ppl-year {
    position: absolute; z-index: 4; right: 14px; bottom: 12px; pointer-events: none;
    color: #fff; text-align: right; line-height: 1.1; text-shadow: 0 1px 6px rgba(0, 0, 0, 0.85);
    transition: opacity 0.3s;
  }
  .ppl-year b { display: block; font-size: 30px; font-weight: 600; letter-spacing: 0.5px; }
  .ppl-year span { font-size: 13px; opacity: 0.9; }
  .ppl-year:empty { opacity: 0; }
`;
const ICON = (d, size = 22) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path fill="currentColor" d="${d}"/></svg>`;
const TRASH_ICON = ICON(
  "M9,3V4H4V6H5V19A2,2 0 0,0 7,21H17A2,2 0 0,0 19,19V6H20V4H15V3H9M7,6H17V19H7V6M9,8V17H11V8H9M13,8V17H15V8H13Z",
);
const PREV_ICON = ICON("M15.41,16.58L10.83,12L15.41,7.41L14,6L8,12L14,18L15.41,16.58Z", 30);
const NEXT_ICON = ICON("M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z", 30);

const text = (hass, override) => {
  const lang = (override || hass?.locale?.language || hass?.language || "en").split("-")[0];
  return TEXT[lang] || TEXT.en;
};
const currentHass = () => document.querySelector("home-assistant")?.hass;
const photoPath = (url) => {
  const match = (url || "").match(PHOTO_URL);
  return match ? decodeURIComponent(match[1]) : null;
};
const photoYear = (path) => {
  if (!path) return null;
  const slash = path.lastIndexOf("/");
  const match = `${path.slice(0, slash + 1)}`.match(PATH_DATE) || path.slice(slash + 1).match(NAME_DATE);
  return match ? Number(match[1]) : null;
};
const notify = (el, message) =>
  el.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));

let configPromise;
const deleteAllowed = async (hass) => {
  if (!hass?.user?.is_admin) return false;
  configPromise ||= hass.callWS({ type: "photoprism_library/config" }).catch(() => ({ allow_delete: false }));
  return (await configPromise).allow_delete;
};

async function deletePhoto(hass, path, el, lang) {
  const t = text(hass, lang);
  try {
    const plan = await hass.callWS({ type: "photoprism_library/delete_plan", path });
    if (!window.confirm(t.confirm(plan.files, plan.photoprism))) return false;
    const result = await hass.callWS({ type: "photoprism_library/delete", path });
    notify(el, t.deleted(result.removed.join(", ") || path));
    return true;
  } catch (err) {
    notify(el, t.failed(err?.message || err?.code || err));
    return false;
  }
}

function deleteButton(hass, getPath, afterDelete, lang) {
  const button = document.createElement("button");
  button.className = "ppl-del";
  button.title = text(hass, lang).button;
  button.setAttribute("aria-label", text(hass, lang).button);
  button.innerHTML = TRASH_ICON;
  button.addEventListener("click", async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const h = currentHass() || hass;
    const path = getPath();
    if (!path) {
      notify(button, text(h, lang).noPhoto);
      return;
    }
    button.disabled = true;
    const ok = await deletePhoto(h, path, button, lang);
    button.disabled = false;
    if (ok && afterDelete) afterDelete();
  });
  return button;
}

/* ---- Media browser photo preview ------------------------------------------ */

async function decoratePreview(dialog) {
  const root = dialog.shadowRoot;
  const img = root?.querySelector("ha-dialog > img");
  const path = photoPath(dialog._params?.sourceUrl);
  const existing = root?.querySelector(".ppl-anchor");
  if (!img || !path || !(await deleteAllowed(dialog.hass || currentHass()))) {
    existing?.remove();
    return;
  }
  if (!root.querySelector("style.ppl-style")) {
    const style = document.createElement("style");
    style.className = "ppl-style";
    style.textContent = BUTTON_CSS;
    root.appendChild(style);
  }
  if (existing && existing.nextElementSibling === img) {
    existing.dataset.path = path;
    return;
  }
  existing?.remove();
  // A zero-height anchor right before the image keeps Lit's own nodes untouched.
  const anchor = document.createElement("span");
  anchor.className = "ppl-anchor";
  anchor.dataset.path = path;
  const button = deleteButton(dialog.hass, () => anchor.dataset.path, () => dialog.closeDialog?.());
  anchor.appendChild(button);
  img.before(anchor);
  // :hover does not reach into the dialog's top layer, so track the pointer here.
  let hideTimer;
  const show = () => {
    clearTimeout(hideTimer);
    anchor.classList.add("ppl-visible");
  };
  const hide = () => {
    hideTimer = setTimeout(() => anchor.classList.remove("ppl-visible"), 200);
  };
  for (const el of [img, button]) {
    el.addEventListener("pointerenter", show);
    el.addEventListener("pointerleave", hide);
  }
}

customElements.whenDefined("hui-dialog-web-browser-play-media").then(() => {
  const proto = customElements.get("hui-dialog-web-browser-play-media").prototype;
  if (proto.__pplPatched) return;
  const updated = proto.updated;
  proto.updated = function (changed) {
    if (updated) updated.call(this, changed);
    decoratePreview(this);
  };
  proto.__pplPatched = true;
});

/* ---- Slideshow card ------------------------------------------------------- */

const OWN_KEYS = ["type", "delete_button", "navigation", "show_year", "language"];

class PhotoPrismLibrarySlideshow extends HTMLElement {
  setConfig(config) {
    if (!config?.entity?.startsWith("camera.")) throw new Error("entity (an Album Slideshow camera) is required");
    this._config = { delete_button: true, navigation: true, show_year: false, ...config };
    this._build();
  }

  async _build() {
    const helpers = await window.loadCardHelpers();
    const inner = {};
    for (const [key, value] of Object.entries(this._config)) if (!OWN_KEYS.includes(key)) inner[key] = value;
    // Album Slideshow freezes the picture for 8 s after a tap; with arrows on the
    // photo that only makes navigation feel broken.
    inner.tap_pause_seconds ??= 0;
    const card = await helpers.createCardElement({ ...inner, type: "custom:album-slideshow-card" });
    card.addEventListener("ll-rebuild", (ev) => {
      ev.stopPropagation();
      this._build();
    });
    if (this._hass) card.hass = this._hass;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${BUTTON_CSS}${CARD_CSS}</style>`;
    const host = document.createElement("div");
    host.className = "ppl-host";
    host.appendChild(card);
    this._spinner = Object.assign(document.createElement("div"), { className: "ppl-spinner" });
    this._year = Object.assign(document.createElement("div"), { className: "ppl-year" });
    host.append(this._spinner, this._year);
    if (this._config.navigation) {
      host.append(this._navButton("prev", PREV_ICON, -1), this._navButton("next", NEXT_ICON, 1));
    }
    this.shadowRoot.appendChild(host);
    this._inner = card;
    this._host = host;
    this._deleteBtn = null;
    this._frame = undefined;
    this._syncOverlay();
    this._syncDelete();
  }

  _navButton(cls, icon, direction) {
    const button = document.createElement("button");
    button.className = `ppl-nav ${cls}`;
    const t = text(this._hass || currentHass(), this._config.language);
    const label = direction > 0 ? t.next : t.previous;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = icon;
    button.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      this._navigate(direction);
    });
    return button;
  }

  /** The slideshow's own previous/next button entities (same device as the camera). */
  _navEntity(direction) {
    const suffix = direction > 0 ? "_next_slide" : "_previous_slide";
    const camera = this._config.entity;
    const device = this._hass?.entities?.[camera]?.device_id;
    if (device) {
      const match = Object.values(this._hass.entities).find(
        (e) => e.device_id === device && e.entity_id.startsWith("button.") && e.entity_id.endsWith(suffix),
      );
      if (match) return match.entity_id;
    }
    return `button.${camera.slice("camera.".length)}${suffix}`;
  }

  _navigate(direction) {
    if (!this._hass) return;
    this._host.classList.add("ppl-loading");
    clearTimeout(this._spinnerTimeout);
    this._spinnerTimeout = setTimeout(() => this._host.classList.remove("ppl-loading"), 8000);
    this._hass.callService("button", "press", { entity_id: this._navEntity(direction) }).catch(() => {
      this._host.classList.remove("ppl-loading");
    });
  }

  set hass(hass) {
    this._hass = hass;
    if (this._inner) this._inner.hass = hass;
    this._syncOverlay();
    this._syncDelete();
  }

  _syncOverlay() {
    if (!this._host || !this._hass) return;
    const attrs = this._hass.states[this._config.entity]?.attributes || {};
    if (attrs.frame_id === this._frame) return;
    const first = this._frame === undefined;
    this._frame = attrs.frame_id;
    // Change the label together with the picture's cross-fade, then stop the spinner.
    const delay = first ? 0 : Number(this._config.duration ?? 600) / 2;
    clearTimeout(this._overlayTimer);
    this._overlayTimer = setTimeout(() => {
      this._host.classList.remove("ppl-loading");
      clearTimeout(this._spinnerTimeout);
      this._renderYear(attrs.current_url);
    }, delay);
  }

  _renderYear(url) {
    if (!this._config.show_year) {
      this._year.innerHTML = "";
      return;
    }
    const year = photoYear(photoPath(url));
    if (!year) {
      this._year.innerHTML = "";
      return;
    }
    const ago = new Date().getFullYear() - year;
    this._year.innerHTML = `<b>${year}</b><span>${text(this._hass, this._config.language).yearsAgo(ago)}</span>`;
  }

  async _syncDelete() {
    if (!this._host || !this._hass) return;
    const allowed = this._config.delete_button && (await deleteAllowed(this._hass));
    if (allowed && !this._deleteBtn) {
      this._deleteBtn = deleteButton(
        this._hass,
        () => photoPath(this._hass.states[this._config.entity]?.attributes?.current_url),
        undefined,
        this._config.language,
      );
      this._host.appendChild(this._deleteBtn);
    } else if (!allowed && this._deleteBtn) {
      this._deleteBtn.remove();
      this._deleteBtn = null;
    }
  }

  getCardSize() {
    return this._inner?.getCardSize?.() ?? 6;
  }

  getGridOptions() {
    return this._inner?.getGridOptions?.() ?? { columns: "full", rows: "auto" };
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find((e) => e.startsWith("camera.album_slideshow")) || "";
    return { entity, transition: "fade", duration: 1200, show_year: true };
  }
}

if (!customElements.get("photoprism-library-slideshow")) {
  customElements.define("photoprism-library-slideshow", PhotoPrismLibrarySlideshow);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "photoprism-library-slideshow",
    name: "PhotoPrism Library slideshow",
    description: "Album Slideshow card with arrows, the year a photo was taken and a delete button.",
    preview: false,
  });
  console.info(`%c PHOTOPRISM-LIBRARY %c ${VERSION} `, "background:#3478f6;color:#fff", "");
}
