import json
import time

from app.instagram import download_image, find_shortcode
from app.mealie import ld_json_for_html, safe_text
from app.parser import parse_caption


def test_parser_is_linear_on_hostile_captions():
    # These used to backtrack quadratically (~20 s for 60 KB).
    for caption in (" #a" * 3_000 + " x", "#a" * 5_000 + "!", " " * 10_000 + "x"):
        start = time.perf_counter()
        parse_caption(caption)
        assert time.perf_counter() - start < 0.5


def test_ld_json_cannot_close_the_script_tag():
    data = ld_json_for_html({"name": 'x</script><script>alert(1)</script>', "d": "a & b"})
    assert "<" not in data and ">" not in data and "&" not in data
    assert json.loads(data)["name"] == "x</script><script>alert(1)</script>"


def test_safe_text_drops_html_and_markdown_images():
    assert safe_text('Mescola <img src=x onerror=alert(1)> bene') == "Mescola  bene"
    assert safe_text("Vedi ![](https://evil.example/pixel.gif) qui") == "Vedi  qui"
    assert safe_text("200 g di farina") == "200 g di farina"


def test_image_download_only_from_instagram_cdn():
    for url in (
        "http://scontent.cdninstagram.com/x.jpg",  # not https
        "https://169.254.169.254/latest/meta-data",
        "https://cdninstagram.com.evil.example/x.jpg",
        "https://evil.example/x.jpg?.cdninstagram.com",
        "file:///etc/passwd",
        "not a url",
        "",
    ):
        assert download_image(url) is None


def test_opengraph_caption_any_language(monkeypatch):
    import app.instagram as ig

    for prefix in ("487 likes, 31 comments - chef.x on December 26, 2022", "487 Mi piace, 31 commenti - chef.x su 26 dicembre 2022"):
        page = f'<meta property="og:description" content="{prefix}: &quot;Torta - facile: 2 uova&quot;. " />'
        monkeypatch.setattr(ig.httpx, "get", lambda *a, **k: type("R", (), {"text": page, "raise_for_status": lambda s: None})())
        post = ig._fetch_with_opengraph("abc")
        assert (post.author, post.caption) == ("chef.x", "Torta - facile: 2 uova")


def test_readonly_cookies_file_is_usable(tmp_path):
    from yt_dlp import YoutubeDL

    import app.instagram as ig

    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    cookies.chmod(0o444)
    captured = {}

    class FakeYDL(YoutubeDL):
        def extract_info(self, url, download=False):
            captured["cookiefile"] = self.params["cookiefile"]
            return {"description": "ok"}

    original = ig.YoutubeDL
    ig.YoutubeDL = FakeYDL
    try:
        assert ig._fetch_with_ytdlp("abc", str(cookies)).caption == "ok"  # no PermissionError on exit
    finally:
        ig.YoutubeDL = original
    assert captured["cookiefile"] != str(cookies)


def test_shortcode_extraction_is_strict():
    assert find_shortcode("https://www.instagram.com/reel/AbC_1-2/?igsh=x") == "AbC_1-2"
    assert find_shortcode("https://evil.example/p/AbC") is None
