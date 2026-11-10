# PhotoPrism Library for Home Assistant

Browse your photo library in Home Assistant's media browser, **including iPhone HEIC photos**, and get two ready-made smart folders: **On this day** and **Random**.

Built for PhotoPrism's `originals` folder, but it works with any folder of photos that Home Assistant can see.

## Features

- **HEIC/HEIF support.** HEIC photos are converted to JPEG on the fly, so they display in every browser, not only Safari. Pillow can then open HEIC anywhere in Home Assistant, which also helps other image integrations.
- **Thumbnails** in the media browser grid for every photo.
- **On this day.** Photos taken on today's date in earlier years. The date comes from `YYYY/MM/DD` folders or from names like `20230512_143000_ABCD.jpg`, `IMG_20230512_…`, `PXL_20230512…` or `2023-05-12 …`.
- **Random.** A random selection from the whole library (500 by default), refreshed every 6 hours.
- **Live Photos shown once.** The short video that belongs to a Live Photo is hidden.
- **Screenshots left out** (PNG/GIF) of the smart folders. You can turn this off in the options.
- **Symlink-friendly.** PhotoPrism originals are often symlinks into another folder, and you can allow those target folders. Nothing outside the folders you configure is ever served.
- **Works with slideshow cards.** Point a media-source slideshow such as [Album Slideshow](https://github.com/eyalgal/album_slideshow) at `media-source://photoprism_library/@on_this_day` or `media-source://photoprism_library/@random`.
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
      - /srv/photoprism/originals:/media/photos:ro
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

## Slideshow example

With [Album Slideshow](https://github.com/eyalgal/album_slideshow), add an album with the **Media Source** provider and the content ID `media-source://photoprism_library/@on_this_day`. Then add the card:

```yaml
type: custom:album-slideshow-card
entity: camera.album_slideshow_on_this_day
transition: fade
duration: 1500
```

## How it works

| URL | |
|---|---|
| `media-source://photoprism_library/<path>` | Browse folders and photos |
| `/api/photoprism_library/image/<path>` | The photo: HEIC as JPEG (max 2560 px), anything else unchanged |
| `/api/photoprism_library/thumb/<path>` | 360 px JPEG thumbnail |

Both HTTP endpoints require a logged-in user or a signed URL. Converted images are cached in memory, and at most two conversions run at once, so small hosts like a Raspberry Pi stay responsive.

## Notes

- Not affiliated with PhotoPrism. This integration reads files only and never talks to the PhotoPrism API.
- RAW files (DNG etc.) are listed but not converted.

## License

MIT
