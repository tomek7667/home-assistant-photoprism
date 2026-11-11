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
 * - Defines `custom:photoprism-library-grid`: a grid of favourites with sorting,
 *   a full-screen viewer and a select mode for deleting or unhearting many at once.
 *
 * Every photo shows a heart (favourites are kept in Home Assistant, one list for
 * everyone) next to the delete button.
 */
const VERSION = "1.4.1";
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
    favorite: "Add to favourites",
    unfavorite: "Remove from favourites",
    favFailed: (err) => `Could not change favourites: ${err}`,
    similar: "Similar photos",
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
    favorite: "Dodaj do ulubionych",
    unfavorite: "Usuń z ulubionych",
    favFailed: (err) => `Nie udało się zmienić ulubionych: ${err}`,
    similar: "Podobne zdjęcia",
  },
};

const BUTTON_CSS = `
  .ppl-anchor { display: block; position: relative; height: 0; z-index: 5; }
  .ppl-tools { position: absolute; z-index: 5; top: 12px; right: 12px; display: flex; gap: 8px; }
  .ppl-tool, .ppl-nav {
    padding: 0; border: none; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.55); color: #fff; cursor: pointer;
    opacity: 0; transition: opacity 0.2s, background 0.2s, color 0.2s;
  }
  .ppl-nav { position: absolute; z-index: 5; }
  .ppl-tool { width: 44px; height: 44px; flex: none; }
  .ppl-host:hover .ppl-tool, .ppl-host:hover .ppl-nav, .ppl-visible .ppl-tool, .ppl-tool:focus-visible,
  .ppl-nav:focus-visible, .ppl-fav.ppl-on { opacity: 1; }
  .ppl-tool:hover, .ppl-nav:hover { background: rgba(0, 0, 0, 0.8); }
  .ppl-del:hover { background: var(--error-color, #db4437); }
  .ppl-fav.ppl-on { color: #ff4d6d; }
  .ppl-tool[disabled] { opacity: 1; cursor: progress; background: rgba(0, 0, 0, 0.35); }
  @media (hover: none) { .ppl-tool, .ppl-nav { opacity: 0.8; } }
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
const HEART_ICON = ICON(
  "M12,21.35L10.55,20.03C5.4,15.36 2,12.27 2,8.5C2,5.41 4.42,3 7.5,3C9.24,3 10.91,3.81 12,5.08C13.09,3.81 14.76,3 16.5,3C19.58,3 22,5.41 22,8.5C22,12.27 18.6,15.36 13.45,20.03L12,21.35Z",
);
const HEART_OUTLINE_ICON = ICON(
  "M12.1,18.55L12,18.65L11.89,18.55C7.14,14.24 4,11.39 4,8.5C4,6.5 5.5,5 7.5,5C9.04,5 10.54,6 11.07,7.36H12.93C13.46,6 14.96,5 16.5,5C18.5,5 20,6.5 20,8.5C20,11.39 16.86,14.24 12.1,18.55M16.5,3C14.76,3 13.09,3.81 12,5.08C10.91,3.81 9.24,3 7.5,3C4.42,3 2,5.41 2,8.5C2,12.27 5.4,15.36 10.55,20.03L12,21.35L13.45,20.03C18.6,15.36 22,12.27 22,8.5C22,5.41 19.58,3 16.5,3Z",
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
const deleteAllowed = async (hass) => (await integrationConfig(hass)).allow_delete === true;

/* ---- Favourites: one subscription per page, shared by every card ------------ */

const FAVORITES_EVENT = "ppl-favorites-changed";
const favorites = {
  items: [], // [{path, added}], most recently added first
  paths: new Set(),
  loaded: false,
  _subscribed: null,
  ensure(hass) {
    if (this._subscribed || !hass?.connection) return;
    this._subscribed = hass.connection
      .subscribeMessage(
        (msg) => {
          this.items = msg.items || [];
          this.paths = new Set(this.items.map((i) => i.path));
          this.loaded = true;
          window.dispatchEvent(new CustomEvent(FAVORITES_EVENT));
        },
        { type: "photoprism_library/favorites/subscribe" },
      )
      .catch(() => {
        this._subscribed = null; // try again with the next card
      });
  },
  has(path) {
    return !!path && this.paths.has(path);
  },
  set(hass, paths, favorite) {
    return hass.callWS({ type: "photoprism_library/favorites/set", paths, favorite });
  },
};

/** A heart that shows and toggles whether the photo from getPath() is a favourite. */
function favoriteButton(hass, getPath, lang) {
  favorites.ensure(hass);
  const button = document.createElement("button");
  button.className = "ppl-tool ppl-fav";
  const refresh = () => {
    const on = favorites.has(getPath());
    const label = text(currentHass() || hass, lang)[on ? "unfavorite" : "favorite"];
    button.classList.toggle("ppl-on", on);
    button.innerHTML = on ? HEART_ICON : HEART_OUTLINE_ICON;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-pressed", String(on));
  };
  button.addEventListener("click", async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const h = currentHass() || hass;
    const path = getPath();
    if (!path) {
      notify(button, text(h, lang).noPhoto);
      return;
    }
    const on = !favorites.has(path);
    // Show the change right away; the subscription confirms it
    button.classList.toggle("ppl-on", on);
    button.innerHTML = on ? HEART_ICON : HEART_OUTLINE_ICON;
    try {
      await favorites.set(h, [path], on);
    } catch (err) {
      notify(button, text(h, lang).favFailed(err?.message || err?.code || err));
      refresh();
    }
  });
  window.addEventListener(FAVORITES_EVENT, refresh);
  button.refresh = refresh;
  button.dispose = () => window.removeEventListener(FAVORITES_EVENT, refresh);
  refresh();
  return button;
}

const toolbar = () => Object.assign(document.createElement("div"), { className: "ppl-tools" });

/** The integration's settings that the cards need (fetched once per page). */
const integrationConfig = async (hass) => {
  if (!hass?.user) return {};
  configPromise ||= hass.callWS({ type: "photoprism_library/config" }).catch(() => ({ allow_delete: false }));
  return configPromise;
};

const SIMILAR_ICON =
  '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round"><circle cx="10" cy="10" r="7"/><path d="M15.2 15.2 21 21"/>' +
  '<path d="M5.6 10c1.2-2 2.7-3 4.4-3s3.2 1 4.4 3c-1.2 2-2.7 3-4.4 3s-3.2-1-4.4-3z" stroke-width="1.6"/>' +
  '<circle cx="10" cy="10" r="1.3" fill="currentColor" stroke="none"/></svg>';

const navigate = (url) => {
  history.pushState(null, "", url);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
};

/**
 * The 🔍 button: opens the dashboard view set in the integration options with the
 * photo, or resolves to null when similar photos aren't set up.
 */
async function similarButton(hass, getPath, lang, beforeNavigate) {
  const config = await integrationConfig(hass);
  if (!config.similar || !config.similar_view) return null;
  const button = document.createElement("button");
  button.className = "ppl-tool ppl-sim";
  const label = text(hass, lang).similar;
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = SIMILAR_ICON;
  button.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const path = getPath();
    if (!path) {
      notify(button, text(currentHass() || hass, lang).noPhoto);
      return;
    }
    beforeNavigate?.();
    navigate(`${config.similar_view}?photo=${encodeURIComponent(path)}`);
  });
  return button;
}

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
  button.className = "ppl-tool ppl-del";
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

function removeAnchor(anchor) {
  anchor?.querySelector(".ppl-fav")?.dispose();
  anchor?.remove();
}

async function decoratePreview(dialog) {
  const root = dialog.shadowRoot;
  const canDelete = await deleteAllowed(dialog.hass || currentHass());
  const img = root?.querySelector("ha-dialog > img");
  const path = photoPath(dialog._params?.sourceUrl);
  const existing = root?.querySelector(".ppl-anchor");
  if (!img || !path) {
    removeAnchor(existing);
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
    existing.querySelector(".ppl-fav")?.refresh();
    return;
  }
  removeAnchor(existing);
  // A zero-height anchor right before the image keeps Lit's own nodes untouched.
  const anchor = document.createElement("span");
  anchor.className = "ppl-anchor";
  anchor.dataset.path = path;
  const tools = toolbar();
  tools.appendChild(favoriteButton(dialog.hass, () => anchor.dataset.path));
  if (canDelete) tools.appendChild(deleteButton(dialog.hass, () => anchor.dataset.path, () => dialog.closeDialog?.()));
  similarButton(dialog.hass, () => anchor.dataset.path, undefined, () => dialog.closeDialog?.()).then(
    (btn) => btn && tools.prepend(btn),
  );
  anchor.appendChild(tools);
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
  for (const el of [img, tools]) {
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

const OWN_KEYS = [
  "type", "delete_button", "favorite_button", "similar_button", "navigation", "show_year", "date_format", "language",
];

class PhotoPrismLibrarySlideshow extends HTMLElement {
  setConfig(config) {
    if (!config?.entity?.startsWith("camera.")) throw new Error("entity (an Album Slideshow camera) is required");
    this._config = { delete_button: true, favorite_button: true, navigation: true, show_year: false, ...config };
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
    this._tools = toolbar();
    host.appendChild(this._tools);
    this._favBtn?.dispose();
    this._favBtn = null;
    if (this._config.favorite_button) {
      // The photo on screen, not the one the slideshow is about to show
      this._favBtn = favoriteButton(this._hass || currentHass(), () => photoPath(this._displayedUrl()), this._config.language);
      this._tools.appendChild(this._favBtn);
    }
    const tools = this._tools;
    if (this._config.similar_button !== false) {
      similarButton(this._hass || currentHass(), () => photoPath(this._displayedUrl()), this._config.language).then(
        (btn) => btn && tools.isConnected !== false && tools.prepend(btn),
      );
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
      this._favBtn?.refresh();
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
      this._favBtn?.refresh();
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
      this._tools.appendChild(this._deleteBtn);
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
  .ppl-viewer .video {
    position: absolute; inset: 0; z-index: 1; width: 100%; height: 100%; object-fit: contain;
    background: #000; display: none;
  }
  .ppl-viewer.is-video .video { display: block; }
  .ppl-viewer.is-video .ppl-year { display: none; }
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
  .ppl-close { top: 12px; left: 12px; width: 44px; height: 44px; opacity: 1; }
  .ppl-viewer.has-close .ppl-count { left: 66px; top: 22px; }
  .ppl-viewer.fill { height: 100%; }
  .ppl-empty {
    position: absolute; inset: 0; z-index: 3; display: none; align-items: center; justify-content: center;
    padding: 24px; text-align: center; color: #ddd;
  }
  .ppl-viewer.is-empty .ppl-empty { display: flex; }
`;
const CLOSE_ICON = ICON(
  "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  26,
);
const SHUFFLE_ICON = ICON(
  "M14.83,13.41L13.42,14.82L16.55,17.95L14.5,20H20V14.5L17.96,16.54L14.83,13.41M14.5,4L16.54,6.04L4,18.59L5.41,20L17.96,7.46L20,9.5V4M10.59,9.17L5.41,4L4,5.41L9.17,10.58L10.59,9.17Z",
);
Object.assign(TEXT.en, {
  shuffle: "New random selection", empty: "No photos here", loadFailed: "Could not load the photos", close: "Close",
});
Object.assign(TEXT.pl, {
  shuffle: "Nowy losowy wybór", empty: "Brak zdjęć", loadFailed: "Nie udało się wczytać zdjęć", close: "Zamknij",
});
const SOURCE = "media-source://photoprism_library";

/**
 * `custom:photoprism-library-viewer`: browses a library folder right in the browser.
 * Photos are preloaded around the current one, so previous/next is instant; ← → and
 * Delete work while the pointer is over the card, and swiping works on touch screens.
 * The delete button always targets the photo on screen.
 */
class PhotoPrismLibraryViewer extends HTMLElement {
  /**
   * Besides the YAML options, the full-screen viewer of the grid passes
   * items ([{id, path, kind}]), start, fill and onClose / onDeleted callbacks.
   */
  setConfig(config) {
    this._config = {
      folder: "@random", show_year: true, delete_button: true, favorite_button: true,
      aspect_ratio: "16/9", autoplay: 0, ...config,
    };
    // Random photos are from any day, so their whole date says more than "N years ago"
    this._config.date_format ||= this._config.folder === "@random" || this._config.items ? "date" : "year";
    this._items = null;
    this._index = 0;
    this._token = 0;
    this._render();
    if (this._hass) {
      this._load();
      this._syncDelete(); // _render() started a fresh toolbar
    }
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this._config) {
      this._addFavorite();
      this._load();
      this._syncDelete();
    }
  }

  _addFavorite() {
    if (!this._hass) return;
    if (this._config.favorite_button && !this._favBtn) {
      this._favBtn = favoriteButton(this._hass, () => this._shown?.path, this._config.language);
      // Left of the delete button
      this._tools.insertBefore(this._favBtn, this._deleteBtn || null);
    }
    if (this._config.similar_button !== false && !this._simPending) {
      const tools = this._tools;
      this._simPending = similarButton(
        this._hass, () => this._shown?.path, this._config.language, () => this._config.onClose?.(),
      ).then((btn) => {
        if (btn && tools === this._tools) tools.insertBefore(btn, this._favBtn || this._deleteBtn || null);
      });
    }
  }

  get _t() {
    return text(this._hass || currentHass(), this._config.language);
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const ratio = String(this._config.aspect_ratio || "16/9").replace(":", "/");
    const fill = !!this._config.fill;
    this.shadowRoot.innerHTML = `<style>${BUTTON_CSS}${CARD_CSS}${VIEWER_CSS}${
      fill ? "ha-card { border-radius: 0; border: none; box-shadow: none; }" : ""
    }</style>
      <ha-card><div class="ppl-host ppl-viewer ppl-loading${fill ? " fill" : ""}"${fill ? "" : ` style="aspect-ratio:${ratio}"`}>
        <img class="bg" alt=""><img class="photo" alt=""><img class="photo" alt="">
        <video class="video" playsinline controls preload="metadata"></video>
        <div class="ppl-count"></div><div class="ppl-year"></div><div class="ppl-spinner"></div>
        <div class="ppl-empty"></div>
      </div></ha-card>`;
    const host = this.shadowRoot.querySelector(".ppl-viewer");
    this._host = host;
    this._bg = host.querySelector(".bg");
    this._layers = [...host.querySelectorAll(".photo")];
    this._video = host.querySelector(".video");
    this._front = 0;
    this._count = host.querySelector(".ppl-count");
    this._year = host.querySelector(".ppl-year");
    this._empty = host.querySelector(".ppl-empty");
    this._deleteBtn = null;
    this._favBtn?.dispose();
    this._favBtn = null;
    this._simPending = null;
    this._tools = toolbar();
    host.append(this._tools);
    host.append(this._button("ppl-nav prev", PREV_ICON, this._t.previous, () => this._step(-1)));
    host.append(this._button("ppl-nav next", NEXT_ICON, this._t.next, () => this._step(1)));
    if (this._config.folder === "@random" && !this._config.items) {
      this._tools.append(this._button("ppl-tool ppl-shuffle", SHUFFLE_ICON, this._t.shuffle, () => this._load()));
    }
    if (this._config.onClose) {
      host.classList.add("has-close");
      host.append(this._button("ppl-nav ppl-close", CLOSE_ICON, this._t.close, () => this._config.onClose()));
    }
    if (fill) this._hover = true; // full screen: the keys always apply
    this._addFavorite();
    host.addEventListener("pointerenter", () => (this._hover = true));
    host.addEventListener("pointerleave", () => (this._hover = !!this._config.fill));
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
      else if ((ev.key === "f" || ev.key === "F") && this._favBtn) this._favBtn.click();
      else if (ev.key === "Escape" && this._config.onClose) this._config.onClose();
      else return;
      ev.preventDefault();
    };
    window.addEventListener("keydown", this._onKey);
    this._restartAutoplay();
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
    clearInterval(this._autoplay);
    this._video?.pause();
  }

  _restartAutoplay() {
    clearInterval(this._autoplay);
    const seconds = Number(this._config?.autoplay) || 0;
    if (seconds > 0) this._autoplay = setInterval(() => !this._hover && this._step(1), seconds * 1000);
  }

  async _load() {
    if (!this._hass) return;
    if (Array.isArray(this._config.items)) {
      this._items = this._config.items.map((item) => ({ ...item }));
      this._show(Number(this._config.start) || 0);
      return;
    }
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
        .filter((c) => c.media_class === "image" || c.media_class === "video")
        .map((c) => ({ id: c.media_content_id, path: c.media_content_id.slice(SOURCE.length + 1), kind: c.media_class }));
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
    this._stopVideo();
    this._favBtn?.refresh();
  }

  _stopVideo() {
    this._host.classList.remove("is-video");
    if (this._video?.getAttribute("src")) {
      this._video.pause();
      this._video.removeAttribute("src");
      this._video.load();
    }
  }

  /** Resolve (signed URL) and decode a photo once; later calls reuse the promise. */
  _preload(item) {
    if (item.ready && Date.now() - item.readyAt > 5 * 3600 * 1000) item.ready = item.url = null; // signed URL ages out
    if (!item.ready) item.readyAt = Date.now();
    item.ready ||= this._hass
      .callWS({ type: "media_source/resolve_media", media_content_id: item.id, expires: 6 * 3600 })
      .then((res) =>
        item.kind === "video"
          ? res.url // the browser streams it when shown
          : new Promise((resolve, reject) => {
            const img = new Image();
            img.decoding = "async";
            img.onload = () => {
              item.url = res.url;
              resolve(res.url);
            };
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
    // A thumbnail from the grid shows at once; the full photo replaces it when loaded
    const placeholder = item.thumb && item.kind !== "video" && !item.url;
    if (placeholder) this._display(item, item.thumb, index);
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
    this._host.classList.remove("ppl-loading");
    if (placeholder) {
      // Same layer, sharper picture: no second fade
      this._layers[this._front].src = url;
      this._bg.src = url;
    } else {
      this._display(item, url, index);
    }
    for (const k of [1, 2, 3, 4, 5, -1]) this._preload(items[(index + k + items.length) % items.length]).catch(() => {});
  }

  /** Put a photo (or video) on screen; from now on the buttons act on it. */
  _display(item, url, index) {
    this._host.classList.remove("is-empty");
    if (item.kind === "video") {
      this._layers.forEach((l) => l.classList.remove("show"));
      this._bg.classList.remove("show");
      this._host.classList.add("is-video");
      this._video.src = url;
      this._video.play?.().catch(() => {}); // may need a tap where autoplay is blocked
    } else {
      this._stopVideo();
      const next = this._layers[1 - this._front];
      next.src = url;
      next.classList.add("show");
      this._layers[this._front].classList.remove("show");
      this._front = 1 - this._front;
      this._bg.src = url;
      this._bg.classList.add("show");
    }
    this._shown = item; // what the delete, heart and similar buttons act on
    this._favBtn?.refresh();
    this._count.textContent = `${index + 1} / ${this._items.length}`;
    this._renderYear(item.path);
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
        this._config.onDeleted?.(gone.path);
        this._show(at); // the next photo moves into this slot
      },
      this._config.language,
    );
    this._tools.appendChild(this._deleteBtn);
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

/* ---- Full-screen viewer (lightbox) ------------------------------------------ */

const VIDEO_FILE = /\.(mov|mp4|m4v)$/i;
const mediaItem = (path) => ({ id: `${SOURCE}/${path}`, path, kind: VIDEO_FILE.test(path) ? "video" : "image" });

/** Show items full screen, starting at index; the viewer card does the work. */
function openLightbox(hass, items, index, lang, onDeleted) {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;z-index:10000;background:#000;";
  const scroll = document.documentElement.style.overflow;
  document.documentElement.style.overflow = "hidden";
  const viewer = document.createElement("photoprism-library-viewer");
  viewer.style.cssText = "display:block;height:100%;";
  const close = () => {
    overlay.remove();
    document.documentElement.style.overflow = scroll;
  };
  viewer.setConfig({
    items, start: index, fill: true, show_year: true, date_format: "date", language: lang,
    onClose: close, onDeleted,
  });
  overlay.appendChild(viewer);
  document.body.appendChild(overlay);
  viewer.hass = hass;
  return close;
}

/* ---- Grid card: favourites ------------------------------------------------------ */

const CHECK_ICON = ICON("M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z", 18);
const PLAY_ICON = ICON("M8,5.14V19.14L19,12.14L8,5.14Z", 26);
const TRASH_SMALL = ICON(
  "M9,3V4H4V6H5V19A2,2 0 0,0 7,21H17A2,2 0 0,0 19,19V6H20V4H15V3H9M7,6H17V19H7V6M9,8V17H11V8H9M13,8V17H15V8H13Z",
  18,
);
const HEART_SMALL = ICON(
  "M12,21.35L10.55,20.03C5.4,15.36 2,12.27 2,8.5C2,5.41 4.42,3 7.5,3C9.24,3 10.91,3.81 12,5.08C13.09,3.81 14.76,3 16.5,3C19.58,3 22,5.41 22,8.5C22,12.27 18.6,15.36 13.45,20.03L12,21.35Z",
  18,
);

Object.assign(TEXT.en, {
  favorites: "Favourites",
  sortAdded: "Recently added",
  sortNewest: "Newest photos",
  sortOldest: "Oldest photos",
  sortYear: "By year",
  noDate: "No date",
  select: "Select",
  selectAll: "Select all",
  cancel: "Cancel",
  selected: (n) => `${n} selected`,
  heartMany: "Add to favourites",
  unheartMany: "Remove from favourites",
  deleteMany: "Delete",
  confirmMany: (n, files, photoprism) =>
    `Permanently delete ${n} ${n === 1 ? "photo" : "photos"}?\n\n${files}\n\n` +
    `The files are removed from disk${photoprism ? ", from PhotoPrism" : ""} and from Home Assistant. ` +
    "This cannot be undone.",
  more: (n) => `… and ${n} more`,
  deletedMany: (n) => `Deleted ${n} ${n === 1 ? "photo" : "photos"}`,
  deletedSome: (ok, failed) => `Deleted ${ok}, ${failed} could not be deleted`,
  noFavorites: "No favourites yet. Tap ♡ on a photo to add it here.",
  loading: "Loading…",
  preparing: "Preparing…",
  deleting: (done, total, name) => `Deleting ${done}/${total} · ${name}`,
  stop: "Stop",
  stopped: (ok) => `Stopped after deleting ${ok}`,
});
Object.assign(TEXT.pl, {
  favorites: "Ulubione",
  sortAdded: "Ostatnio dodane",
  sortNewest: "Najnowsze zdjęcia",
  sortOldest: "Najstarsze zdjęcia",
  sortYear: "Według roku",
  noDate: "Bez daty",
  select: "Zaznacz",
  selectAll: "Zaznacz wszystkie",
  cancel: "Anuluj",
  selected: (n) => `Zaznaczono: ${n}`,
  heartMany: "Dodaj do ulubionych",
  unheartMany: "Usuń z ulubionych",
  deleteMany: "Usuń",
  confirmMany: (n, files, photoprism) =>
    `Trwale usunąć zaznaczone zdjęcia (${n})?\n\n${files}\n\n` +
    `Pliki zostaną usunięte z dysku${photoprism ? ", z PhotoPrism" : ""} i z Home Assistant. ` +
    "Tej operacji nie można cofnąć.",
  more: (n) => `… i ${n} więcej`,
  deletedMany: (n) => `Usunięto zdjęcia: ${n}`,
  deletedSome: (ok, failed) => `Usunięto ${ok}, nie udało się usunąć ${failed}`,
  noFavorites: "Nie ma jeszcze ulubionych. Dotknij ♡ na zdjęciu, żeby je tu dodać.",
  loading: "Wczytywanie…",
  preparing: "Przygotowywanie…",
  deleting: (done, total, name) => `Usuwanie ${done}/${total} · ${name}`,
  stop: "Zatrzymaj",
  stopped: (ok) => `Zatrzymano po usunięciu ${ok}`,
});

const GRID_CSS = `
  /* No overflow: hidden here, it would keep the slider and the action bar from sticking */
  ha-card { overflow: visible; }
  .head { display: flex; align-items: center; gap: 8px; padding: 12px 16px; flex-wrap: wrap; }
  .head .title { flex: 1; min-width: 120px; font-size: 20px; font-weight: 500; color: var(--primary-text-color); }
  .head .title small { font-size: 14px; font-weight: 400; color: var(--secondary-text-color); margin-left: 6px; }
  .head select, .btn {
    font: inherit; font-size: 14px; line-height: 20px; padding: 6px 12px; border-radius: 18px; cursor: pointer;
    border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color);
  }
  /* The browser's own arrow hugs the rounded border; draw one with room around it */
  .sort { position: relative; display: inline-flex; align-items: center; }
  .sort select { appearance: none; -webkit-appearance: none; padding-right: 34px; }
  .sort select option { background: var(--card-background-color); color: var(--primary-text-color); }
  .sort .chev { position: absolute; right: 12px; pointer-events: none; color: var(--secondary-text-color); display: flex; }
  .btn { display: inline-flex; align-items: center; gap: 6px; }
  .btn.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn.danger { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color: #fff; }
  .btn[disabled] { opacity: 0.5; cursor: default; }
  .year { padding: 12px 16px 6px; font-weight: 600; color: var(--secondary-text-color); }
  .tiles {
    display: grid; gap: 4px; padding: 0 4px 4px;
    grid-template-columns: repeat(auto-fill, minmax(var(--ppl-tile, 140px), 1fr));
  }
  .tile {
    position: relative; aspect-ratio: 1; overflow: hidden; border-radius: 4px; cursor: pointer;
    background: rgba(127, 127, 127, 0.15); user-select: none; -webkit-user-select: none; -webkit-touch-callout: none;
  }
  .tile img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform 0.15s; pointer-events: none; }
  .tile .play {
    position: absolute; left: 6px; bottom: 6px; color: #fff; pointer-events: none;
    filter: drop-shadow(0 0 3px rgba(0, 0, 0, 0.9));
  }
  .tile .check {
    position: absolute; top: 6px; right: 6px; width: 24px; height: 24px; border-radius: 50%; pointer-events: none;
    border: 2px solid #fff; background: rgba(0, 0, 0, 0.3); color: #fff; display: none; align-items: center; justify-content: center;
  }
  .selecting .tile .check { display: flex; }
  .tile.sel .check { background: var(--primary-color); border-color: var(--primary-color); }
  .tile.sel img { transform: scale(0.88); }
  .empty { padding: 32px 16px; text-align: center; color: var(--secondary-text-color); }
  .actions {
    position: sticky; bottom: 0; z-index: 2; display: none; align-items: center; gap: 8px; flex-wrap: wrap;
    padding: 10px 16px; background: var(--card-background-color); border-top: 1px solid var(--divider-color);
  }
  .selecting .actions { display: flex; }
  .actions .count { flex: 1; min-width: 140px; color: var(--primary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .actions .progress { display: none; flex-basis: 100%; height: 4px; border-radius: 2px; background: var(--divider-color); overflow: hidden; }
  .actions .progress div { height: 100%; width: 0; background: var(--error-color, #db4437); transition: width 0.3s; }
  .deleting .actions .progress { display: block; }
  .deleting .actions .all, .deleting .actions .heart, .deleting .actions .delete { display: none; }
  .tile.busy img { opacity: 0.35; }
  .tile.busy::after {
    content: ""; position: absolute; top: 50%; left: 50%; width: 28px; height: 28px; margin: -14px 0 0 -14px;
    border-radius: 50%; border: 3px solid rgba(255, 255, 255, 0.35); border-top-color: #fff; animation: ppl-spin 0.8s linear infinite;
  }
  .tile.failed { outline: 3px solid var(--error-color, #db4437); outline-offset: -3px; }
  .tile.gone { opacity: 0; transform: scale(0.6); transition: opacity 0.25s, transform 0.25s; }
  @keyframes ppl-spin { to { transform: rotate(360deg); } }
`;

Object.assign(TEXT.en, {
  similarTitle: "Similar photos",
  sortScore: "Most similar",
  similarity: "Similarity",
  loose: "loosely related",
  near: "near-duplicates",
  found: (n) => `${n} found`,
  shownOf: (shown, n) => `showing ${shown} of ${n}`,
  pickPhoto: "Open a photo and tap 🔍 to see photos like it.",
  noSimilar: "Nothing this similar. Move the slider to the left to see more.",
  searching: "Looking for similar photos…",
  similarFailed: (err) => `Could not search: ${err}`,
  sourceGone: "This photo was deleted",
});
Object.assign(TEXT.pl, {
  similarTitle: "Podobne zdjęcia",
  sortScore: "Najbardziej podobne",
  similarity: "Podobieństwo",
  loose: "luźno powiązane",
  near: "prawie identyczne",
  found: (n) => `znaleziono: ${n}`,
  shownOf: (shown, n) => `pokazano ${shown} z ${n}`,
  pickPhoto: "Otwórz zdjęcie i dotknij 🔍, żeby zobaczyć podobne.",
  noSimilar: "Nic tak podobnego. Przesuń suwak w lewo, żeby zobaczyć więcej.",
  searching: "Szukam podobnych zdjęć…",
  similarFailed: (err) => `Nie udało się wyszukać: ${err}`,
  sourceGone: "To zdjęcie zostało usunięte",
});

const SIMILAR_CSS = `
  .source { display: flex; gap: 16px; align-items: center; padding: 0 16px 12px; }
  .source .tile.src { aspect-ratio: auto; height: 180px; max-width: 50%; border-radius: 8px; flex: none; }
  .source .tile.src img { width: auto; height: 100%; max-width: 100%; object-fit: contain; }
  .source .tile.src .ppl-tools { top: 8px; right: 8px; gap: 6px; }
  .source .tile.src .ppl-tool { width: 36px; height: 36px; }
  .selecting .source .tile.src .ppl-tools { display: none; }
  .source .tile.src .check { top: 8px; right: 8px; }
  .source.deleted .tile.src { opacity: 0.35; pointer-events: none; }
  .source .meta { color: var(--secondary-text-color); font-size: 14px; line-height: 1.5; word-break: break-all; }
  .source .meta b { display: block; font-size: 22px; color: var(--primary-text-color); word-break: normal; }
  .tile .score {
    position: absolute; left: 6px; top: 6px; padding: 1px 6px; border-radius: 10px; font-size: 12px;
    color: #fff; background: rgba(0, 0, 0, 0.55); pointer-events: none;
  }
  .slider {
    position: sticky; bottom: 0; z-index: 2; padding: 10px 16px 12px;
    background: var(--card-background-color); border-top: 1px solid var(--divider-color);
  }
  .slider .row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; color: var(--primary-text-color); }
  .slider .row b { font-size: 16px; }
  .slider .hints { display: flex; justify-content: space-between; font-size: 12px; color: var(--secondary-text-color); }
  .slider input { width: 100%; margin: 8px 0 2px; accent-color: var(--primary-color); }
  .selecting .slider { display: none; }
`;

const SORTS = ["added", "newest", "oldest", "year"];
const dateKey = (path) => {
  const d = photoDate(path);
  return d ? `${d.year}${d.month}${d.day}` : null;
};
const queryPhoto = () => new URLSearchParams(window.location.search).get("photo") || "";

/**
 * `custom:photoprism-library-grid`: a grid of photos with a full-screen viewer and a
 * select mode (delete, heart/unheart several at once).
 *   source: favorites  the favourites (newest hearts first)
 *   source: similar    photos like the one in the page URL (?photo=...), with a slider
 *                      for how similar they must be
 */
class PhotoPrismLibraryGrid extends HTMLElement {
  setConfig(config) {
    this._config = {
      source: "favorites", tile_size: 140, min_similarity: 30, max_similarity: 100, similarity: 80, limit: 300,
      ...config,
    };
    this._similar = this._config.source === "similar";
    this._selected = new Set();
    this._selecting = false;
    this._urls = new Map(); // path -> signed thumbnail URL
    this._signedAt = 0;
    this._results = []; // similar: [{path, score}]
    this._total = 0;
    this._photo = null;
    this._status = null; // similar: message instead of results
    const sort = localStorage.getItem(this._sortKey);
    this._sort = SORTS.includes(sort) ? sort : "added";
    const saved = Number(localStorage.getItem("ppl-similarity"));
    this._threshold = saved >= this._config.min_similarity && saved <= this._config.max_similarity
      ? saved : Number(this._config.similarity);
    this._built = false;
    if (this._hass) this._build();
  }

  get _sortKey() {
    return `ppl-grid-sort-${this._config.source}`;
  }

  get _t() {
    return text(this._hass || currentHass(), this._config.language);
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this._config) this._build();
  }

  connectedCallback() {
    this._onFavorites ||= () => {
      if (this._deleting) return; // redrawn when the deleting is done
      if (this._similar) this._syncSelection();
      else this._refresh();
    };
    this._onLocation ||= () => {
      if (this._similar && this._built && queryPhoto() !== this._photo) this._refresh();
    };
    window.addEventListener(FAVORITES_EVENT, this._onFavorites);
    window.addEventListener("location-changed", this._onLocation);
    window.addEventListener("popstate", this._onLocation);
    if (this._built) this._refresh();
  }

  disconnectedCallback() {
    window.removeEventListener(FAVORITES_EVENT, this._onFavorites);
    window.removeEventListener("location-changed", this._onLocation);
    window.removeEventListener("popstate", this._onLocation);
  }

  _build() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const t = this._t;
    const sortLabel = (s) => (s === "added" && this._similar ? t.sortScore : t[`sort${s[0].toUpperCase()}${s.slice(1)}`]);
    const { min_similarity: lo, max_similarity: hi } = this._config;
    this.shadowRoot.innerHTML = `<style>${BUTTON_CSS}${GRID_CSS}${SIMILAR_CSS}</style>
      <ha-card style="--ppl-tile:${Number(this._config.tile_size) || 140}px">
        <div class="head">
          <div class="title"></div>
          <label class="sort"><select aria-label="sort">${SORTS.map((s) => `<option value="${s}">${sortLabel(s)}</option>`).join("")}</select><span class="chev"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z"/></svg></span></label>
          <button class="btn select-toggle">${t.select}</button>
        </div>
        ${this._similar ? '<div class="source"></div>' : ""}
        <div class="body"></div>
        ${this._similar ? `<div class="slider">
          <div class="row"><span>${t.similarity} ≥ <b class="value"></b></span><span class="found"></span></div>
          <input type="range" min="${lo}" max="${hi}" step="1" aria-label="${t.similarity}">
          <div class="hints"><span>${t.loose}</span><span>${t.near}</span></div>
        </div>` : ""}
        <div class="actions">
          <div class="progress"><div></div></div>
          <span class="count"></span>
          <button class="btn all">${t.selectAll}</button>
          <button class="btn heart">${HEART_SMALL}<span></span></button>
          <button class="btn danger delete">${TRASH_SMALL}${t.deleteMany}</button>
          <button class="btn cancel">${t.cancel}</button>
        </div>
      </ha-card>`;
    const root = this.shadowRoot;
    this._card = root.querySelector("ha-card");
    this._title = root.querySelector(".title");
    this._body = root.querySelector(".body");
    this._countEl = root.querySelector(".count");
    const select = root.querySelector("select");
    select.value = this._sort;
    select.addEventListener("change", () => {
      this._sort = select.value;
      localStorage.setItem(this._sortKey, this._sort);
      this._render();
    });
    root.querySelector(".select-toggle").addEventListener("click", () => this._setSelecting(!this._selecting));
    root.querySelector(".cancel").addEventListener("click", () => {
      if (this._deleting) this._stopDeleting = true; // finish the photos in progress, then stop
      else this._setSelecting(false);
    });
    root.querySelector(".all").addEventListener("click", () => {
      const all = this._selectable();
      this._selected = this._selected.size === all.length ? new Set() : new Set(all);
      this._syncSelection();
    });
    this._heartBtn = root.querySelector(".heart");
    this._heartBtn.addEventListener("click", () => this._heartSelection());
    this._deleteBtn = root.querySelector(".delete");
    this._deleteBtn.addEventListener("click", () => this._deleteSelection());
    if (this._similar) {
      this._sourceEl = root.querySelector(".source");
      this._range = root.querySelector(".slider input");
      this._value = root.querySelector(".slider .value");
      this._found = root.querySelector(".slider .found");
      this._range.value = String(this._threshold);
      this._value.textContent = `${this._threshold}%`;
      let timer;
      this._range.addEventListener("input", () => {
        this._threshold = Number(this._range.value);
        this._value.textContent = `${this._threshold}%`;
        clearTimeout(timer);
        timer = setTimeout(() => {
          localStorage.setItem("ppl-similarity", String(this._threshold));
          this._search();
        }, 250);
      });
    }
    this._built = true;
    favorites.ensure(this._hass);
    deleteAllowed(this._hass).then((ok) => (this._deleteBtn.hidden = !ok));
    this._refresh();
  }

  /** The grid's items before sorting: favourites by recency, similar ones by score. */
  _baseItems() {
    if (this._similar) {
      return this._results.map((r, i) => ({ ...mediaItem(r.path), score: r.score, added: -i, date: dateKey(r.path) }));
    }
    return favorites.items.map((i) => ({ ...mediaItem(i.path), added: i.added, date: dateKey(i.path) }));
  }

  /** Everything select mode can pick: the grid, plus the photo searched for. */
  _selectable() {
    const paths = this._ordered().map((i) => i.path);
    if (this._similar && this._photo && !this._sourceGone) paths.unshift(this._photo);
    return paths;
  }

  _ordered() {
    const items = this._baseItems();
    if (this._sort === "added") return items;
    const dir = this._sort === "oldest" ? 1 : -1;
    return items.sort((a, b) => {
      if (!a.date || !b.date) return a.date ? -1 : b.date ? 1 : b.added - a.added; // undated last
      return a.date === b.date ? b.added - a.added : a.date < b.date ? -dir : dir;
    });
  }

  async _refresh() {
    if (!this._built) return;
    if (this._similar) {
      await this._search();
      return;
    }
    if (!favorites.loaded) {
      this._body.innerHTML = `<div class="empty">${this._t.loading}</div>`;
      return;
    }
    // Drop selections of photos that are gone
    this._selected = new Set([...this._selected].filter((p) => favorites.has(p)));
    await this._sign(favorites.items.map((i) => i.path));
    this._render();
  }

  /** Similar: (re)load the results for the photo in the URL at the current threshold. */
  async _search() {
    const photo = queryPhoto();
    const token = (this._searchToken = (this._searchToken || 0) + 1);
    if (photo !== this._photo) {
      this._photo = photo;
      this._sourceGone = false;
      this._selected.clear();
      this._results = [];
      this._renderSource();
    }
    if (!photo) {
      this._status = this._t.pickPhoto;
      this._render();
      return;
    }
    if (!this._results.length) {
      this._status = this._t.searching;
      this._render();
    }
    try {
      const res = await this._hass.callWS({
        type: "photoprism_library/similar", path: photo, min: this._threshold / 100,
        limit: Number(this._config.limit) || 300,
      });
      if (token !== this._searchToken) return; // a newer search won
      this._results = res.results;
      this._total = res.total;
      this._status = res.results.length ? null : this._t.noSimilar;
      const keep = new Set(res.results.map((r) => r.path));
      this._selected = new Set([...this._selected].filter((p) => keep.has(p)));
      await this._sign(res.results.map((r) => r.path));
    } catch (err) {
      if (token !== this._searchToken) return;
      this._results = [];
      this._total = 0;
      this._status = this._t.similarFailed(err?.message || err?.code || err);
    }
    this._render();
  }

  async _renderSource() {
    if (!this._sourceEl) return;
    const photo = this._photo;
    if (!photo) {
      this._sourceEl.innerHTML = "";
      return;
    }
    const date = photoDate(photo);
    const name = photo.split("/").pop();
    this._sourceEl.classList.remove("deleted");
    this._sourceEl.innerHTML =
      `<div class="tile src ppl-host"><img alt=""><span class="check">${CHECK_ICON}</span></div>` +
      `<div class="meta">${date ? `<b>${date.day}.${date.month}.${date.year}</b>` : ""}${name}</div>`;
    const tile = this._sourceEl.querySelector(".tile");
    tile.dataset.path = photo;
    const img = tile.querySelector("img");
    // The same heart and delete button as everywhere, for the photo searched for too
    const tools = toolbar();
    tools.appendChild(favoriteButton(this._hass, () => photo, this._config.language));
    if (await deleteAllowed(this._hass)) {
      tools.appendChild(deleteButton(this._hass, () => photo, () => this._markSourceGone(photo), this._config.language));
    }
    if (photo !== this._photo) return;
    tile.appendChild(tools);
    this._pressable(tile, photo, () =>
      openLightbox(this._hass, [{ ...mediaItem(photo), thumb: img.src || undefined }], 0, this._config.language,
        () => this._markSourceGone(photo)),
    );
    this._syncSelection();
    try {
      const res = await this._hass.callWS({ type: "photoprism_library/sign", paths: [photo] });
      if (photo === this._photo) img.src = res.urls[photo];
    } catch {
      // the name and date still show
    }
  }

  /** The photo searched for was deleted: keep its similar photos, show it as gone. */
  _markSourceGone(photo) {
    if (photo !== this._photo || !this._sourceEl) return;
    this._sourceGone = true;
    this._selected.delete(photo);
    this._sourceEl.classList.add("deleted");
    this._sourceEl.querySelector(".ppl-tools")?.remove();
    const meta = this._sourceEl.querySelector(".meta");
    if (meta) meta.insertAdjacentHTML("beforeend", `<div>${this._t.sourceGone}</div>`);
    this._syncSelection();
  }

  /** Signed thumbnail URLs, fetched for many photos at once and renewed before they expire. */
  async _sign(paths) {
    if (Date.now() - this._signedAt > 5 * 3600 * 1000) this._urls.clear();
    const missing = paths.filter((p) => !this._urls.has(p));
    if (!missing.length) return;
    try {
      for (let i = 0; i < missing.length; i += 1000) {
        const res = await this._hass.callWS({ type: "photoprism_library/sign", paths: missing.slice(i, i + 1000) });
        if (!this._urls.size) this._signedAt = Date.now();
        for (const [path, url] of Object.entries(res.urls)) this._urls.set(path, url);
      }
    } catch (err) {
      notify(this, `${this._t.loadFailed}: ${err?.message || err}`);
    }
  }

  _render() {
    const t = this._t;
    const items = this._ordered();
    const title = this._config.title || (this._similar ? t.similarTitle : t.favorites);
    this._title.innerHTML = `${title}<small>${items.length || ""}</small>`;
    this._card.classList.toggle("selecting", this._selecting);
    if (this._similar && this._found) {
      this._found.textContent = this._results.length < this._total
        ? t.shownOf(this._results.length, this._total) : this._total ? t.found(this._total) : "";
    }
    if (!items.length) {
      this._body.innerHTML = `<div class="empty">${this._status || (this._similar ? t.noSimilar : t.noFavorites)}</div>`;
      if (!this._deleting) this._setSelecting(false);
      this._syncSelection();
      return;
    }
    const groups = [];
    if (this._sort === "year") {
      for (const item of items) {
        const label = item.date ? item.date.slice(0, 4) : t.noDate;
        if (!groups.length || groups[groups.length - 1].label !== label) groups.push({ label, items: [] });
        groups[groups.length - 1].items.push(item);
      }
    } else {
      groups.push({ label: null, items });
    }
    this._body.innerHTML = "";
    let index = 0;
    for (const group of groups) {
      if (group.label) this._body.insertAdjacentHTML("beforeend", `<div class="year">${group.label}</div>`);
      const tiles = document.createElement("div");
      tiles.className = "tiles";
      for (const item of group.items) tiles.appendChild(this._tile(item, items, index++));
      this._body.appendChild(tiles);
    }
    this._syncSelection();
  }

  _tile(item, items, index) {
    const tile = document.createElement("div");
    tile.className = "tile";
    tile.dataset.path = item.path;
    tile.innerHTML =
      `<img loading="lazy" alt="">${item.kind === "video" ? `<span class="play">${PLAY_ICON}</span>` : ""}` +
      `${item.score != null ? `<span class="score">${Math.round(item.score * 100)}%</span>` : ""}` +
      `<span class="check">${CHECK_ICON}</span>`;
    const url = this._urls.get(item.path);
    if (url) tile.querySelector("img").src = url;
    this._pressable(tile, item.path, () =>
      openLightbox(
        this._hass, items.map(({ id, path, kind }) => ({ id, path, kind, thumb: this._urls.get(path) })), index,
        this._config.language, (gone) => this._forget(gone),
      ),
    );
    return tile;
  }

  /** Tap opens (or selects in select mode); a long press starts selecting. */
  _pressable(tile, path, open) {
    let timer;
    let longPressed = false;
    let start;
    tile.addEventListener("pointerdown", (ev) => {
      if (ev.composedPath().some((el) => el.classList?.contains("ppl-tool"))) return; // heart / delete
      longPressed = false;
      start = [ev.clientX, ev.clientY];
      timer = setTimeout(() => {
        longPressed = true;
        if (this._deleting) return;
        if (!this._selecting) this._setSelecting(true);
        this._toggle(path);
      }, 500);
    });
    tile.addEventListener("pointermove", (ev) => {
      if (start && Math.hypot(ev.clientX - start[0], ev.clientY - start[1]) > 10) clearTimeout(timer);
    });
    for (const type of ["pointerup", "pointerleave", "pointercancel"]) tile.addEventListener(type, () => clearTimeout(timer));
    tile.addEventListener("contextmenu", (ev) => ev.preventDefault());
    tile.addEventListener("click", (ev) => {
      if (longPressed || this._deleting) return;
      if (ev.composedPath().some((el) => el.classList?.contains("ppl-tool"))) return;
      if (this._selecting) this._toggle(path);
      else open();
    });
  }

  /** A photo was deleted in the full-screen viewer. */
  _forget(path) {
    if (!this._similar) return; // favourites update by themselves
    this._results = this._results.filter((r) => r.path !== path);
    this._total = Math.max(0, this._total - 1);
    this._render();
  }

  _setSelecting(on) {
    this._selecting = on;
    if (!on) this._selected.clear();
    this._card?.classList.toggle("selecting", on);
    this.shadowRoot?.querySelector(".select-toggle")?.classList.toggle("on", on);
    this._syncSelection();
  }

  _toggle(path) {
    if (this._selected.has(path)) this._selected.delete(path);
    else this._selected.add(path);
    this._syncSelection();
  }

  _syncSelection() {
    if (!this._body) return;
    for (const tile of this.shadowRoot.querySelectorAll(".tile[data-path]")) {
      tile.classList.toggle("sel", this._selected.has(tile.dataset.path));
    }
    if (this._deleting) return; // the action bar shows the progress
    const n = this._selected.size;
    const t = this._t;
    this._countEl.textContent = t.selected(n);
    const allFav = n > 0 && [...this._selected].every((p) => favorites.has(p));
    this._heartBtn.querySelector("span").textContent = allFav ? t.unheartMany : t.heartMany;
    this._heartBtn.dataset.favorite = String(!allFav);
    this._heartBtn.disabled = this._deleteBtn.disabled = n === 0;
  }

  async _heartSelection() {
    const paths = [...this._selected];
    if (!paths.length) return;
    try {
      await favorites.set(this._hass, paths, this._heartBtn.dataset.favorite === "true");
      this._setSelecting(false);
    } catch (err) {
      notify(this, this._t.favFailed(err?.message || err?.code || err));
    }
  }

  async _deleteSelection() {
    const paths = this._selectable().filter((p) => this._selected.has(p)); // in grid order
    if (!paths.length || this._deleting) return;
    const t = this._t;
    const bar = this.shadowRoot.querySelector(".actions .progress div");
    const cancel = this.shadowRoot.querySelector(".actions .cancel");
    this._deleteBtn.disabled = true;
    this._countEl.textContent = t.preparing;
    let plans;
    try {
      plans = await Promise.all(paths.map((path) => this._hass.callWS({ type: "photoprism_library/delete_plan", path })));
    } catch (err) {
      notify(this, t.failed(err?.message || err?.code || err));
      this._syncSelection();
      return;
    }
    const files = plans.flatMap((p) => p.files);
    const shown = files.slice(0, 15).join("\n") + (files.length > 15 ? `\n${t.more(files.length - 15)}` : "");
    if (!window.confirm(t.confirmMany(paths.length, shown, plans.some((p) => p.photoprism)))) {
      this._syncSelection();
      return;
    }
    this._deleting = true;
    this._stopDeleting = false;
    this._card.classList.add("deleting");
    cancel.textContent = t.stop;
    const tileOf = (path) => this.shadowRoot.querySelector(`.tile[data-path="${CSS.escape(path)}"]`);
    const deleted = [];
    const failed = [];
    let started = 0;
    const show = (name) => {
      this._countEl.textContent = t.deleting(Math.min(started, paths.length), paths.length, name);
      bar.style.width = `${(100 * (deleted.length + failed.length)) / paths.length}%`;
    };
    // Two at a time: quicker, and the bar still moves photo by photo
    const queue = [...paths];
    const worker = async () => {
      while (queue.length && !this._stopDeleting) {
        const path = queue.shift();
        started += 1;
        show(path.split("/").pop());
        const tile = tileOf(path);
        tile?.classList.add("busy");
        try {
          await this._hass.callWS({ type: "photoprism_library/delete", path });
          deleted.push(path);
          this._selected.delete(path);
          tile?.classList.replace("busy", "gone");
          if (path === this._photo) this._markSourceGone(path);
        } catch {
          failed.push(path);
          tile?.classList.replace("busy", "failed");
        }
        show(path.split("/").pop());
      }
    };
    await Promise.all([worker(), worker()]);
    const stopped = this._stopDeleting && queue.length > 0;
    this._deleting = false;
    this._card.classList.remove("deleting");
    cancel.textContent = t.cancel;
    bar.style.width = "0";
    notify(this, stopped ? t.stopped(deleted.length)
      : failed.length ? t.deletedSome(deleted.length, failed.length) : t.deletedMany(deleted.length));
    if (this._similar && deleted.length) {
      const gone = new Set(deleted);
      this._results = this._results.filter((r) => !gone.has(r.path));
      this._total = Math.max(0, this._total - deleted.length);
    }
    // Failed (or not yet deleted) photos stay selected to try again
    this._selected = new Set(paths.filter((p) => !deleted.includes(p)));
    if (!this._selected.size) this._setSelecting(false);
    this._render();
  }

  getCardSize() {
    return 10;
  }

  getGridOptions() {
    return { columns: "full", rows: "auto" };
  }

  static getStubConfig() {
    return { source: "favorites" };
  }
}

if (!customElements.get("photoprism-library-grid")) {
  customElements.define("photoprism-library-grid", PhotoPrismLibraryGrid);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "photoprism-library-grid",
    name: "PhotoPrism Library grid",
    description: "Favourites or similar photos as a grid: sorting, full-screen viewer, select several to delete or (un)heart.",
    preview: false,
  });
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
