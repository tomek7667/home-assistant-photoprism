"""Constants for PhotoPrism Library."""
from __future__ import annotations

DOMAIN = "photoprism_library"

CONF_FOLDER = "folder"
CONF_EXTRA_FOLDERS = "extra_folders"
CONF_RANDOM_COUNT = "random_count"
CONF_SKIP_SCREENSHOTS = "skip_screenshots"

# Deleting photos (off by default) and the PhotoPrism connection used for it.
CONF_ALLOW_DELETE = "allow_delete"
CONF_PHOTOPRISM = "photoprism"
CONF_PHOTOPRISM_URL = "photoprism_url"
CONF_PHOTOPRISM_TOKEN = "photoprism_token"
PHOTOPRISM_NONE = "none"  # files only, PhotoPrism is not told
PHOTOPRISM_INTEGRATION = "integration"  # reuse the PhotoPrism integration's connection
PHOTOPRISM_APP_PASSWORD = "app_password"
PHOTOPRISM_INTEGRATION_DOMAIN = "photoprism"
EVENT_DELETED = "photoprism_library_deleted"

DEFAULT_FOLDER = "/media"
DEFAULT_RANDOM_COUNT = 500
DEFAULT_SKIP_SCREENSHOTS = True

PHOTO_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".gif"}
CONVERT_EXTS = {".heic", ".heif"}  # browsers can't show these, so they are served as JPEG
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
# Left out of the "On this day" and "Random" folders when skip_screenshots is on:
# phone screenshots are PNG and GIFs are animations.
SCREENSHOT_EXTS = {".png", ".gif"}

MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
}

FULL_SIZE = 2560  # long edge of converted HEIC photos
FULL_QUALITY = 85
THUMB_SIZE = 360
THUMB_QUALITY = 75
INDEX_TTL = 6 * 3600  # rescan the library every 6 hours

IMAGE_URL = "/api/photoprism_library/image/"
THUMB_URL = "/api/photoprism_library/thumb/"

ON_THIS_DAY = "@on_this_day"
RANDOM = "@random"
FAVORITES = "@favorites"
