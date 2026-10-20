"""Fetch the caption, author and cover image of a public Instagram post."""

import html
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from yt_dlp import YoutubeDL

log = logging.getLogger(__name__)

SHORTCODE_RE = re.compile(r"instagram\.com/(?:[\w.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
URL_RE = re.compile(r"https?://\S+")

# Instagram serves Open Graph tags (including the caption) to link-preview crawlers.
CRAWLER_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
BROWSER_UA = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Mobile Safari/537.36"
)


class InstagramError(Exception):
    pass


@dataclass
class InstagramPost:
    shortcode: str
    url: str
    caption: str
    author: str = ""
    image_url: str = ""


def find_shortcode(text: str) -> str | None:
    """Extract the post shortcode from a link or from shared text containing a link."""
    m = SHORTCODE_RE.search(text or "")
    return m.group(1) if m else None


def canonical_url(shortcode: str) -> str:
    return f"https://www.instagram.com/p/{shortcode}/"


def fetch_post(text: str, cookies_file: str | None = None) -> InstagramPost:
    shortcode = find_shortcode(text)
    if not shortcode:
        raise InstagramError("Non trovo un link a un post Instagram nel testo.")

    post = None
    try:
        post = _fetch_with_ytdlp(shortcode, cookies_file)
    except Exception as e:  # yt-dlp raises many different error types
        log.warning("yt-dlp failed for %s: %s", shortcode, e)

    if not post or not post.caption:
        try:
            og = _fetch_with_opengraph(shortcode)
            if post:
                post.caption = og.caption
                post.image_url = post.image_url or og.image_url
                post.author = post.author or og.author
            else:
                post = og
        except Exception as e:
            log.warning("Open Graph fallback failed for %s: %s", shortcode, e)

    if not post or not post.caption:
        raise InstagramError(
            "Non riesco a leggere la descrizione del post (privato, rimosso o Instagram blocca le richieste)."
        )
    return post


def _fetch_with_ytdlp(shortcode: str, cookies_file: str | None) -> InstagramPost:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Photo posts have no video formats: we only want the metadata anyway.
        "ignore_no_formats_error": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 20,
        "cachedir": False,  # the container filesystem is read-only
    }
    with tempfile.TemporaryDirectory() as tmp:
        if cookies_file:
            # yt-dlp writes the cookie jar back on exit: give it a private copy, so the
            # mounted file can stay read-only and concurrent requests don't clash.
            # copyfile, not copy: the copy must be writable even if the original is read-only.
            opts["cookiefile"] = str(shutil.copyfile(cookies_file, Path(tmp) / "cookies.txt"))
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_url(shortcode), download=False)

    entries = [e for e in (info.get("entries") or []) if e]
    first = entries[0] if entries else {}

    caption = info.get("description") or first.get("description") or ""
    image = info.get("thumbnail") or first.get("thumbnail") or ""
    if not image:
        thumbs = info.get("thumbnails") or first.get("thumbnails") or []
        if thumbs:
            image = thumbs[-1].get("url", "")

    return InstagramPost(
        shortcode=shortcode,
        url=canonical_url(shortcode),
        caption=caption.strip(),
        author=info.get("channel") or info.get("uploader_id") or info.get("uploader") or "",
        image_url=image,
    )


def _meta(page: str, prop: str) -> str:
    m = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else ""


def _fetch_with_opengraph(shortcode: str) -> InstagramPost:
    r = httpx.get(
        canonical_url(shortcode),
        headers={"User-Agent": CRAWLER_UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"},
        follow_redirects=True,
        timeout=20,
    )
    r.raise_for_status()
    page = r.text

    # Format: '123 likes, 4 comments - user on March 1, 2024: "caption text". ' (localized:
    # "Mi piace", "su", ... so only the punctuation is relied upon).
    desc = _meta(page, "og:description") or _meta(page, "description")
    m = re.search(r'^[^"]*? - ([\w.]+) [^":]+: "(.*)"\.?\s*$', desc, re.S)
    caption, author = (m.group(2), m.group(1)) if m else (desc, "")

    return InstagramPost(
        shortcode=shortcode,
        url=canonical_url(shortcode),
        caption=caption.strip(),
        author=author,
        image_url=_meta(page, "og:image"),
    )


IMAGE_HOSTS = (".cdninstagram.com", ".fbcdn.net")
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def download_image(url: str) -> tuple[bytes, str] | None:
    """Download the cover image from Instagram's CDN; returns (bytes, extension).

    The URL can come from the client, so: https only, Instagram CDN hosts only, no redirects
    (they could leave the allowlist), image content types only, bounded size.
    """
    try:
        parsed = httpx.URL(url)
    except (httpx.InvalidURL, TypeError):
        return None
    if parsed.scheme != "https" or not parsed.host.endswith(IMAGE_HOSTS):
        return None
    try:
        with httpx.stream("GET", parsed, headers={"User-Agent": BROWSER_UA}, follow_redirects=False, timeout=20) as r:
            r.raise_for_status()
            ext = IMAGE_TYPES.get(r.headers.get("content-type", "").split(";")[0].strip())
            if not ext:
                return None
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_IMAGE_BYTES:
                    log.warning("Image too large, skipped: %s", parsed.host)
                    return None
    except httpx.HTTPError as e:
        log.warning("Image download failed: %s", e)
        return None
    return bytes(data), ext
