"""Extract plain text and images from HTML email bodies."""
from __future__ import annotations

import base64
import re
import urllib.request
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# HTML → plain text
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = {"p", "br", "div", "h1", "h2", "h3", "h4", "h5", "li", "tr"}
    _SKIP_TAGS  = {"script", "style", "head"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip = True
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.get_text()


# ---------------------------------------------------------------------------
# Image URL extraction
# ---------------------------------------------------------------------------

_SKIP_URL = re.compile(
    r"(pixel|track|beacon|icon|avatar|logo|badge|button|spacer|1x1|\.gif|,w_3[0-9],|,w_[1-9],)",
    re.IGNORECASE,
)


def extract_image_urls(html: str, max_images: int = 8) -> list[str]:
    """Return a list of candidate content image URLs from an HTML email."""
    raw = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    out = []
    for url in raw:
        if not url.startswith("http"):
            continue
        if url.startswith("data:"):
            continue
        if _SKIP_URL.search(url):
            continue
        out.append(url)
        if len(out) >= max_images:
            break
    return out


def fetch_image_as_b64(url: str, timeout: int = 12) -> tuple[str, str] | None:
    """Download image at URL, return (base64_data, media_type) or None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            if not ct.startswith("image/"):
                return None
            return base64.b64encode(data).decode(), ct
    except Exception:
        return None
