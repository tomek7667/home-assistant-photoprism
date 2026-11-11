/**
 * PhotoPrism Library frontend.
 *
 * - Adds a hover "delete permanently" button to photo previews opened from the
 *   media browser (only for photos of this integration, only for admins, only
 *   when deleting is enabled in the integration options).
 * - Defines `custom:photoprism-library-viewer`: a fast in-browser photo browser
 *   (instant previous/next, keyboard, swipe, delete) for a library folder.
 * - Defines `custom:photoprism-library-slideshow`: an Album Slideshow card with
 *   previous/next arrows on the photo, a loading spinner, the year the photo
 *   was taken and the delete button.
 */
const VERSION = "1.3.2";
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
  .ppl-year b.ppl-date { font-size: 24px; }
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
/** The date a photo was taken, from its YYYY/MM/DD folders or its file name. */
const photoDate = (path) => {
  if (!path) return null;
  const slash = path.lastIndexOf("/");
  const match = `${path.slice(0, slash + 1)}`.match(PATH_DATE) || path.slice(slash + 1).match(NAME_DATE);
  return match ? { year: Number(match[1]), month: match[2], day: match[3] } : null;
};
/**
 * The date overlay: "date" shows DD.MM.YYYY, "year" the year and how long ago
 * (made for On this day, where only the year differs).
 */
const dateOverlay = (path, format, t) => {
  const date = photoDate(path);
  if (!date) return "";
  if (format === "date") return `<b class="ppl-date">${date.day}.${date.month}.${date.year}</b>`;
  return `<b>${date.year}</b><span>${t.yearsAgo(new Date().getFullYear() - date.year)}</span>`;
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

const OWN_KEYS = ["type", "delete_button", "navigation", "show_year", "date_format", "language"];

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
    this._frameUrls = new Map(); // frame_id -> photo URL, to know which photo is on screen
    this._observer?.disconnect();
    this._observer = null;
    this._syncOverlay();
    this._syncDelete();
  }

  /** URL of the photo the inner card is showing right now (it swaps only after loading and fading). */
  _displayedUrl() {
    const img = this._inner?.shadowRoot?.querySelector("img.layer.show");
    const match = img?.getAttribute("src")?.match(/[?&]_?frame=(\d+)/);
    if (match && this._frameUrls.has(Number(match[1]))) return this._frameUrls.get(Number(match[1]));
    return img ? null : this._hass?.states[this._config.entity]?.attributes?.current_url;
  }

  /** Follow the inner card's picture swaps, so the year and the spinner change with the picture. */
  _observeInner() {
    const root = this._inner?.shadowRoot;
    if (this._observer || !root) return;
    let shown = null;
    this._observer = new MutationObserver(() => {
      const url = this._displayedUrl();
      if (url === shown) return;
      shown = url;
      this._host.classList.remove("ppl-loading");
      clearTimeout(this._spinnerTimeout);
      this._renderYear(url);
    });
    this._observer.observe(root, { subtree: true, attributes: true, attributeFilter: ["class", "src"] });
  }

  disconnectedCallback() {
    this._observer?.disconnect();
    this._observer = null;
  }

  connectedCallback() {
    if (this._inner) this._observeInner();
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
    if (attrs.frame_id != null && attrs.current_url) {
      this._frameUrls.set(Number(attrs.frame_id), attrs.current_url);
      while (this._frameUrls.size > 40) this._frameUrls.delete(this._frameUrls.keys().next().value);
    }
    this._observeInner();
    if (attrs.frame_id === this._frame) return;
    const first = this._frame === undefined;
    this._frame = attrs.frame_id;
    // The observer updates the year when the picture really changes; this is the fallback.
    clearTimeout(this._overlayTimer);
    this._overlayTimer = setTimeout(() => {
      this._host.classList.remove("ppl-loading");
      clearTimeout(this._spinnerTimeout);
      this._renderYear(this._displayedUrl() ?? attrs.current_url);
    }, first ? 0 : Number(this._config.duration ?? 600) + 1500);
  }

  _renderYear(url) {
    if (!this._config.show_year) {
      this._year.innerHTML = "";
      return;
    }
    const overlay = dateOverlay(photoPath(url), this._config.date_format, text(this._hass, this._config.language));
    if (!overlay) {
      this._year.innerHTML = "";
      return;
    }
    this._year.innerHTML = overlay;
  }

  async _syncDelete() {
    if (!this._host || !this._hass) return;
    const allowed = this._config.delete_button && (await deleteAllowed(this._hass));
    if (allowed && !this._deleteBtn) {
      // Delete the photo that is on screen, not the one the slideshow is about to show.
      this._deleteBtn = deleteButton(
        this._hass,
        () => photoPath(this._displayedUrl()),
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

/* ---- Viewer card: fast browsing and tidying up ---------------------------- */

const VIEWER_CSS = `
  ha-card { overflow: hidden; height: 100%; }
  .ppl-viewer { position: relative; width: 100%; background: #000; outline: none; overflow: hidden; touch-action: pan-y; }
  .ppl-viewer .bg {
    position: absolute; inset: -40px; width: calc(100% + 80px); height: calc(100% + 80px);
    object-fit: cover; filter: blur(30px) brightness(0.5); opacity: 0; transition: opacity 0.2s;
  }
  .ppl-viewer .photo {
    position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain;
    opacity: 0; transition: opacity 0.15s ease;
  }
  .ppl-viewer .photo.show, .ppl-viewer .bg.show { opacity: 1; }
  /* Only the photo on screen takes clicks, so "Open image in new tab", "Copy image"
     and "Save image as" act on it, not on the previous photo kept in the other layer */
  .ppl-viewer .photo:not(.show), .ppl-viewer .bg { pointer-events: none; }
  .ppl-viewer .photo.show { z-index: 1; }
  .ppl-count {
    position: absolute; z-index: 4; left: 12px; top: 12px; padding: 3px 9px; border-radius: 12px;
    color: #fff; font-size: 13px; background: rgba(0, 0, 0, 0.45); pointer-events: none;
  }
  .ppl-count:empty { display: none; }
  .ppl-shuffle { top: 12px; right: 64px; width: 44px; height: 44px; margin-top: 0; }
  .ppl-empty {
    position: absolute; inset: 0; z-index: 3; display: none; align-items: center; justify-content: center;
    padding: 24px; text-align: center; color: #ddd;
  }
  .ppl-viewer.is-empty .ppl-empty { display: flex; }
`;
const SHUFFLE_ICON = ICON(
  "M14.83,13.41L13.42,14.82L16.55,17.95L14.5,20H20V14.5L17.96,16.54L14.83,13.41M14.5,4L16.54,6.04L4,18.59L5.41,20L17.96,7.46L20,9.5V4M10.59,9.17L5.41,4L4,5.41L9.17,10.58L10.59,9.17Z",
);
Object.assign(TEXT.en, { shuffle: "New random selection", empty: "No photos here", loadFailed: "Could not load the photos" });
Object.assign(TEXT.pl, { shuffle: "Nowy losowy wybór", empty: "Brak zdjęć", loadFailed: "Nie udało się wczytać zdjęć" });
const SOURCE = "media-source://photoprism_library";

/**
 * `custom:photoprism-library-viewer`: browses a library folder right in the browser.
 * Photos are preloaded around the current one, so previous/next is instant; ← → and
 * Delete work while the pointer is over the card, and swiping works on touch screens.
 * The delete button always targets the photo on screen.
 */
class PhotoPrismLibraryViewer extends HTMLElement {
  setConfig(config) {
    this._config = { folder: "@random", show_year: true, delete_button: true, aspect_ratio: "16/9", autoplay: 0, ...config };
    // Random photos are from any day, so their whole date says more than "N years ago"
    this._config.date_format ||= this._config.folder === "@random" ? "date" : "year";
    this._items = null;
    this._index = 0;
    this._token = 0;
    this._render();
    if (this._hass) this._load();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this._config) {
      this._load();
      this._syncDelete();
    }
  }

  get _t() {
    return text(this._hass || currentHass(), this._config.language);
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const ratio = String(this._config.aspect_ratio || "16/9").replace(":", "/");
    this.shadowRoot.innerHTML = `<style>${BUTTON_CSS}${CARD_CSS}${VIEWER_CSS}</style>
      <ha-card><div class="ppl-host ppl-viewer ppl-loading" style="aspect-ratio:${ratio}">
        <img class="bg" alt=""><img class="photo" alt=""><img class="photo" alt="">
        <div class="ppl-count"></div><div class="ppl-year"></div><div class="ppl-spinner"></div>
        <div class="ppl-empty"></div>
      </div></ha-card>`;
    const host = this.shadowRoot.querySelector(".ppl-viewer");
    this._host = host;
    this._bg = host.querySelector(".bg");
    this._layers = [...host.querySelectorAll(".photo")];
    this._front = 0;
    this._count = host.querySelector(".ppl-count");
    this._year = host.querySelector(".ppl-year");
    this._empty = host.querySelector(".ppl-empty");
    this._deleteBtn = null;
    host.append(this._button("ppl-nav prev", PREV_ICON, this._t.previous, () => this._step(-1)));
    host.append(this._button("ppl-nav next", NEXT_ICON, this._t.next, () => this._step(1)));
    if (this._config.folder === "@random") {
      host.append(this._button("ppl-nav ppl-shuffle", SHUFFLE_ICON, this._t.shuffle, () => this._load()));
    }
    host.addEventListener("pointerenter", () => (this._hover = true));
    host.addEventListener("pointerleave", () => (this._hover = false));
    host.addEventListener("pointerdown", (ev) => (this._swipeX = ev.pointerType === "mouse" ? null : ev.clientX));
    host.addEventListener("pointerup", (ev) => {
      if (this._swipeX == null) return;
      const dx = ev.clientX - this._swipeX;
      this._swipeX = null;
      if (Math.abs(dx) > 50) this._step(dx < 0 ? 1 : -1);
    });
  }

  _button(cls, icon, label, onClick) {
    const button = document.createElement("button");
    button.className = cls;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = icon;
    button.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      onClick();
    });
    return button;
  }

  connectedCallback() {
    this._onKey ||= (ev) => {
      if (!this._hover || ev.defaultPrevented || ev.altKey || ev.ctrlKey || ev.metaKey) return;
      const tag = ev.composedPath()[0]?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (ev.key === "ArrowRight") this._step(1);
      else if (ev.key === "ArrowLeft") this._step(-1);
      else if ((ev.key === "Delete" || ev.key === "Backspace") && this._deleteBtn) this._deleteBtn.click();
      else return;
      ev.preventDefault();
    };
    window.addEventListener("keydown", this._onKey);
    this._restartAutoplay();
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
    clearInterval(this._autoplay);
  }

  _restartAutoplay() {
    clearInterval(this._autoplay);
    const seconds = Number(this._config?.autoplay) || 0;
    if (seconds > 0) this._autoplay = setInterval(() => !this._hover && this._step(1), seconds * 1000);
  }

  async _load() {
    if (!this._hass) return;
    const token = ++this._token;
    this._host.classList.add("ppl-loading");
    const folder = String(this._config.folder || "").replace(/^\/+|\/+$/g, "");
    try {
      const res = await this._hass.callWS({
        type: "media_source/browse_media",
        media_content_id: folder ? `${SOURCE}/${folder}` : SOURCE,
      });
      if (token !== this._token) return;
      this._items = (res.children || [])
        .filter((c) => c.media_class === "image")
        .map((c) => ({ id: c.media_content_id, path: c.media_content_id.slice(SOURCE.length + 1) }));
    } catch (err) {
      this._items = [];
      this._showEmpty(`${this._t.loadFailed}: ${err?.message || err}`);
      return;
    }
    this._show(0);
  }

  _showEmpty(message) {
    this._host.classList.remove("ppl-loading");
    this._host.classList.add("is-empty");
    this._empty.textContent = message;
    this._count.textContent = "";
    this._year.innerHTML = "";
    this._shown = null;
    this._layers.forEach((l) => l.classList.remove("show"));
    this._bg.classList.remove("show");
  }

  /** Resolve (signed URL) and decode a photo once; later calls reuse the promise. */
  _preload(item) {
    if (item.ready && Date.now() - item.readyAt > 5 * 3600 * 1000) item.ready = null; // signed URL ages out
    if (!item.ready) item.readyAt = Date.now();
    item.ready ||= this._hass
      .callWS({ type: "media_source/resolve_media", media_content_id: item.id, expires: 6 * 3600 })
      .then(
        (res) =>
          new Promise((resolve, reject) => {
            const img = new Image();
            img.decoding = "async";
            img.onload = () => resolve(res.url);
            img.onerror = () => reject(new Error("load failed"));
            img.src = res.url;
          }),
      );
    return item.ready;
  }

  _step(delta) {
    if (this._items?.length) this._show(this._index + delta);
    this._restartAutoplay();
  }

  async _show(index) {
    const items = this._items;
    if (!items?.length) {
      this._showEmpty(this._t.empty);
      return;
    }
    index = ((index % items.length) + items.length) % items.length;
    this._index = index;
    const item = items[index];
    const token = ++this._token;
    this._host.classList.add("ppl-loading");
    let url;
    try {
      url = await this._preload(item);
    } catch {
      // Gone or unreadable (e.g. deleted elsewhere): drop it and show the next one.
      if (token !== this._token) return;
      const at = items.indexOf(item);
      if (at >= 0) items.splice(at, 1);
      this._show(index);
      return;
    }
    if (token !== this._token) return; // a newer click won
    this._host.classList.remove("is-empty", "ppl-loading");
    const next = this._layers[1 - this._front];
    next.src = url;
    next.classList.add("show");
    this._layers[this._front].classList.remove("show");
    this._front = 1 - this._front;
    this._bg.src = url;
    this._bg.classList.add("show");
    this._shown = item; // what the delete button acts on
    this._count.textContent = `${index + 1} / ${items.length}`;
    this._renderYear(item.path);
    for (const k of [1, 2, 3, 4, 5, -1]) this._preload(items[(index + k + items.length) % items.length]).catch(() => {});
  }

  _renderYear(path) {
    this._year.innerHTML = this._config.show_year ? dateOverlay(path, this._config.date_format, this._t) : "";
  }

  async _syncDelete() {
    if (!this._config.delete_button || this._deleteBtn || !(await deleteAllowed(this._hass))) return;
    this._deleteBtn = deleteButton(
      this._hass,
      () => this._shown?.path,
      () => {
        const gone = this._shown;
        const at = this._items.indexOf(gone);
        if (at < 0) return;
        this._items.splice(at, 1);
        this._show(at); // the next photo moves into this slot
      },
      this._config.language,
    );
    this._host.appendChild(this._deleteBtn);
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: "full", rows: "auto" };
  }

  static getStubConfig() {
    return { folder: "@random", show_year: true };
  }
}

if (!customElements.get("photoprism-library-viewer")) {
  customElements.define("photoprism-library-viewer", PhotoPrismLibraryViewer);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "photoprism-library-viewer",
    name: "PhotoPrism Library viewer",
    description: "Fast photo browser for a library folder (e.g. Random): instant previous/next, keyboard and swipe, delete.",
    preview: false,
  });
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
