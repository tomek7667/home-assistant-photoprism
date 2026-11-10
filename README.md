# PhotoPrism Library for Home Assistant

Browse your photo library in Home Assistant's media browser, **including iPhone HEIC photos**, and get two ready-made smart folders: **On this day** and **Random**.

Built for PhotoPrism's `originals` folder, but it works with any folder of photos that Home Assistant can see.

## Features

- **HEIC/HEIF support.** HEIC photos are converted to JPEG on the fly, so they display in every browser, not only Safari. Pillow can then open HEIC anywhere in Home Assistant, which also helps other image integrations.
- **Thumbnails** in the media browser grid for every photo.
- **On this day.** Photos taken on today's date in earlier years. The date comes from `YYYY/MM/DD` folders or from names like `20230512_143000_ABCD.jpg`, `IMG_20230512_…`, `PXL_20230512…` or `2023-05-12 …`.
- **Random.** A random selection from the whole library (500 by default), refreshed every 6 hours.
- **Live Photos shown once.** The short video that belongs to a Live Photo (`IMG_1234.MOV` or iCloud's `IMG_1234_HEVC.MOV`) is hidden.
- **Screenshots left out** (PNG/GIF) of the smart folders. You can turn this off in the options.
- **Symlink-friendly.** PhotoPrism originals are often symlinks into another folder, and you can allow those target folders. Nothing outside the folders you configure is ever served.
- **Works with slideshow cards.** Point a media-source slideshow such as [Album Slideshow](https://github.com/eyalgal/album_slideshow) at `media-source://photoprism_library/@on_this_day` or `media-source://photoprism_library/@random`.
- **Delete photos for good (optional).** Admins get a trash button when hovering over a photo preview in the media browser and on the slideshow card. After confirming, the photo is removed from PhotoPrism, from disk (with its Live Photo video, edits, RAW and sidecar files) and from Home Assistant.
- **Translations:** English and Polish.

## Installation

### Marketplace

1. Settings → Marketplace → ⋮ → Custom repositories → add `https://github.com/tomek7667/home-assistant-photoprism` as an *Integration*.
2. Install **PhotoPrism Library** and restart Home Assistant.

### Manual

Copy `custom_components/photoprism_library` into your `config/custom_components/` folder and restart Home Assistant.

## Making your photos visible to Home Assistant

Home Assistant must be able to read the photo folder. With Docker, mount PhotoPrism's originals read-only, for example under `/media`:

```yaml
services:
  homeassistant:
    volumes:
      - ./config:/config
      - /srv/photoprism/originals:/media/photos:ro   # drop :ro to allow deleting photos
      # Only if your originals are symlinks into another folder (e.g. an import/source folder):
      # mount that folder at the same path the links point to.
      - /srv/photoprism/import:/photoprism/import:ro
```

Then go to **Settings → Devices & services → Add integration → PhotoPrism Library**:

| Field | Example | |
|---|---|---|
| Photo folder | `/media/photos` | Folder as seen inside Home Assistant |
| Extra allowed folders | `/photoprism/import` | Optional, comma separated. Symlink targets that may be served |

The library appears in **Media → PhotoPrism Library**.

## Options

| Option | Default | |
|---|---|---|
| Photos in the Random folder | 500 | 10 – 5000 |
| Leave PNG/GIF out of On this day and Random | on | Phone screenshots are usually PNG |
| Allow deleting photos | off | See below |
| Also delete in PhotoPrism | no | *No* (files only), *the PhotoPrism integration's connection*, or *an app password* |

## Deleting photos

Deleting is off by default. To use it:

1. Mount the photo folders **writable** (no `:ro`), including the extra allowed folders that links point to.
2. Open the integration options and turn on **Allow deleting photos**. Choose how PhotoPrism is told:
   - reuse the connection of the [PhotoPrism integration](https://github.com/ice413/hass-photoprism), if you have it set up, or
   - an **app password** (PhotoPrism: *Settings → Account → Apps and Devices*) with the PhotoPrism URL.
3. Reload the browser. Admins now see a trash button when hovering over a photo preview (media browser) or the `photoprism-library-slideshow` card.

The button first lists every file that will be deleted and asks for confirmation. Then it:

1. archives the photo in PhotoPrism and deletes it permanently. If this fails, nothing is deleted on disk.
2. deletes the files from disk: the photo, its Live Photo video, edits (`.AAE`), RAW and sidecars with the same name. Links are deleted together with the file they point to. Folders are never deleted.
3. removes the photo from Home Assistant and reloads slideshows that use this library.

Each deletion is logged and fires a `photoprism_library_deleted` event. Deleting cannot be undone.

## Slideshow example

With [Album Slideshow](https://github.com/eyalgal/album_slideshow), add an album with the **Media Source** provider and the content ID `media-source://photoprism_library/@on_this_day`. Then add the card:

```yaml
type: custom:album-slideshow-card
entity: camera.album_slideshow_on_this_day
transition: fade
duration: 1500
```

For a nicer card, use `custom:photoprism-library-slideshow` with the same options. It wraps the Album Slideshow card and adds:

- **◀ ▶ arrows** on the photo (on hover) with a loading spinner, for fast previous/next
- **the year the photo was taken** in the bottom-right corner, e.g. *2020 · 6 years ago* (great for On this day)
- **the delete button** (when deleting is enabled, admins only)

```yaml
type: custom:photoprism-library-slideshow
entity: camera.album_slideshow_on_this_day
transition: fade
duration: 1200
show_year: true        # default false
navigation: true       # default true
delete_button: true    # default true; set false on shared wall panels
language: en           # optional, defaults to your Home Assistant language (en, pl)
```

It sets Album Slideshow's `tap_pause_seconds` to 0 unless you set it yourself. Otherwise the picture freezes for 8 s after tapping it, and previous/next seems to lag. Set the slideshow's *Orientation mismatch mode* to `single` so each slide shows exactly one photo, and raise *Navigation buffer* to preload more slides for quick clicking.

## Photo viewer card (fast browsing and tidying up)

`custom:photoprism-library-viewer` browses a library folder right in the browser, without a slideshow integration. It preloads the photos around the current one, so previous/next is instant. It's the quickest way to go through photos and delete the ones you don't want:

- **◀ ▶ arrows**, the **← → keys** and **Delete** while the pointer is over the card, and **swipe** on touch screens
- a **12 / 500** counter and the **year** the photo was taken
- **🔀** for a new random selection (for the `@random` folder)
- the **delete button** (when deleting is enabled, admins only). It always acts on the photo on screen, and the next photo takes its place immediately

```yaml
type: custom:photoprism-library-viewer
folder: "@random"      # or "@on_this_day", or a folder such as 2023/07
show_year: true
delete_button: true
autoplay: 0            # seconds between photos, 0 = manual
aspect_ratio: 16/9
language: en           # optional
```

## How it works

| URL | |
|---|---|
| `media-source://photoprism_library/<path>` | Browse folders and photos |
| `/api/photoprism_library/image/<path>` | The photo: HEIC as JPEG (max 2560 px), anything else unchanged |
| `/api/photoprism_library/thumb/<path>` | 360 px JPEG thumbnail |
| WebSocket `photoprism_library/delete_plan`, `photoprism_library/delete` | Admin only, when deleting is enabled |

Both HTTP endpoints require a logged-in user or a signed URL. Converted images are cached in memory, and at most two conversions run at once, so small hosts like a Raspberry Pi stay responsive.

## Notes

- Not affiliated with PhotoPrism. Browsing only reads files. The PhotoPrism API is used only to delete photos, and only when you turn that on.
- RAW files (DNG etc.) are listed but not converted.
- Home Assistant signs media URLs with a key that changes on every restart. Album Slideshow keeps signed URLs, so after a restart this integration reloads the slideshows that use it. Until that happens (about a minute), Home Assistant logs a few failed image requests.

## License

MIT
