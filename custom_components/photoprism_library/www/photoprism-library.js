/**
 * PhotoPrism Library frontend.
 *
 * - Adds a hover "delete permanently" button to photo previews opened from the
 *   media browser (only for photos of this integration, only for admins, only
 *   when deleting is enabled in the integration options).
 * - Defines `custom:photoprism-library-slideshow`: an Album Slideshow card
 *   with the same button for the photo currently shown.
 */
const VERSION = "1.1.0";
const PHOTO_URL = /\/api\/photoprism_library\/(?:image|thumb)\/([^?#]+)/;

const TEXT = {
  en: {
    button: "Delete permanently",
    confirm: (files, photoprism) =>
      `Permanently delete this photo?\n\n${files.join("\n")}\n\n` +
      `The files are removed from disk${photoprism ? ", from PhotoPrism" : ""} and from Home Assistant. ` +
      "This cannot be undone.",
    deleted: (files) => `Deleted ${files}`,
    failed: (err) => `Could not delete: ${err}`,
    noPhoto: "No photo is shown right now",
  },
  pl: {
    button: "Usuń trwale",
    confirm: (files, photoprism) =>
      `Trwale usunąć to zdjęcie?\n\n${files.join("\n")}\n\n` +
      `Pliki zostaną usunięte z dysku${photoprism ? ", z PhotoPrism" : ""} i z Home Assistant. ` +
      "Tej operacji nie można cofnąć.",
    deleted: (files) => `Usunięto ${files}`,
    failed: (err) => `Nie udało się usunąć: ${err}`,
    noPhoto: "Teraz nie jest wyświetlane żadne zdjęcie",
  },
};

const BUTTON_CSS = `
  .ppl-anchor { display: block; position: relative; height: 0; z-index: 5; }
  .ppl-del {
    position: absolute; top: 12px; right: 12px; z-index: 5;
    width: 44px; height: 44px; padding: 0; border: none; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.55); color: #fff; cursor: pointer;
    opacity: 0; transition: opacity 0.2s, background 0.2s;
  }
  .ppl-host:hover .ppl-del, .ppl-visible .ppl-del, .ppl-del:focus-visible { opacity: 1; }
  .ppl-del:hover { background: var(--error-color, #db4437); }
  .ppl-del[disabled] { opacity: 1; cursor: progress; background: rgba(0, 0, 0, 0.35); }
  @media (hover: none) { .ppl-del { opacity: 0.8; } }
`;
const TRASH_ICON =
  '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor" ' +
  'd="M9,3V4H4V6H5V19A2,2 0 0,0 7,21H17A2,2 0 0,0 19,19V6H20V4H15V3H9M7,6H17V19H7V6M9,8V17H11V8H9M13,8V17H15V8H13Z"/></svg>';

const text = (hass) => {
  const lang = (hass?.locale?.language || hass?.language || "en").split("-")[0];
  return TEXT[lang] || TEXT.en;
};
const currentHass = () => document.querySelector("home-assistant")?.hass;
const photoPath = (url) => {
  const match = (url || "").match(PHOTO_URL);
  return match ? decodeURIComponent(match[1]) : null;
};
const notify = (el, message) =>
  el.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));

let configPromise;
const deleteAllowed = async (hass) => {
  if (!hass?.user?.is_admin) return false;
  configPromise ||= hass.callWS({ type: "photoprism_library/config" }).catch(() => ({ allow_delete: false }));
  return (await configPromise).allow_delete;
};

async function deletePhoto(hass, path, el) {
  const t = text(hass);
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

function deleteButton(hass, getPath, afterDelete) {
  const button = document.createElement("button");
  button.className = "ppl-del";
  button.title = text(hass).button;
  button.setAttribute("aria-label", text(hass).button);
  button.innerHTML = TRASH_ICON;
  button.addEventListener("click", async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    const h = currentHass() || hass;
    const path = getPath();
    if (!path) {
      notify(button, text(h).noPhoto);
      return;
    }
    button.disabled = true;
    const ok = await deletePhoto(h, path, button);
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

/* ---- Slideshow card with a delete button ---------------------------------- */

class PhotoPrismLibrarySlideshow extends HTMLElement {
  setConfig(config) {
    if (!config?.entity?.startsWith("camera.")) throw new Error("entity (an Album Slideshow camera) is required");
    this._config = config;
    this._build();
  }

  async _build() {
    const helpers = await window.loadCardHelpers();
    const { type, ...cardConfig } = this._config;
    const inner = await helpers.createCardElement({ ...cardConfig, type: "custom:album-slideshow-card" });
    inner.addEventListener("ll-rebuild", (ev) => {
      ev.stopPropagation();
      this._build();
    });
    if (this._hass) inner.hass = this._hass;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>:host { display: block; height: 100%; } .ppl-host { position: relative; height: 100%; } ${BUTTON_CSS}</style>`;
    const host = document.createElement("div");
    host.className = "ppl-host";
    host.appendChild(inner);
    this.shadowRoot.appendChild(host);
    this._inner = inner;
    this._host = host;
    this._button = null;
    this._syncButton();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._inner) this._inner.hass = hass;
    this._syncButton();
  }

  async _syncButton() {
    if (!this._host || !this._hass) return;
    const allowed = await deleteAllowed(this._hass);
    if (allowed && !this._button) {
      this._button = deleteButton(this._hass, () =>
        photoPath(this._hass.states[this._config.entity]?.attributes?.current_url),
      );
      this._host.appendChild(this._button);
    } else if (!allowed && this._button) {
      this._button.remove();
      this._button = null;
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
    return { entity, transition: "fade", duration: 1200 };
  }
}

if (!customElements.get("photoprism-library-slideshow")) {
  customElements.define("photoprism-library-slideshow", PhotoPrismLibrarySlideshow);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "photoprism-library-slideshow",
    name: "PhotoPrism Library slideshow",
    description: "Album Slideshow card with a button to permanently delete the photo shown.",
    preview: false,
  });
  console.info(`%c PHOTOPRISM-LIBRARY %c ${VERSION} `, "background:#3478f6;color:#fff", "");
}
