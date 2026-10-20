"""Insta → Mealie: web app (PWA) + API to import Instagram recipe posts into Mealie."""

import dataclasses
import logging
import os
import secrets
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .instagram import InstagramError, download_image, fetch_post, find_shortcode
from .mealie import MealieClient, MealieError
from .parser import MAX_CAPTION_LENGTH, parse_caption

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MEALIE_URL = os.environ["MEALIE_URL"]
MEALIE_API_TOKEN = os.environ["MEALIE_API_TOKEN"]
MEALIE_PUBLIC_URL = os.getenv("MEALIE_PUBLIC_URL", MEALIE_URL)
MEALIE_TAG = os.getenv("MEALIE_TAG", "Instagram")
MEALIE_AI = os.getenv("MEALIE_AI", "false").lower() in ("1", "true", "yes")
APP_TOKEN = os.getenv("APP_TOKEN", "")
INSTAGRAM_COOKIES_FILE = os.getenv("INSTAGRAM_COOKIES_FILE") or None

STATIC_DIR = Path(__file__).parent / "static"

MAX_BODY_BYTES = 256 * 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

log = logging.getLogger("insta_mealie")
if not APP_TOKEN:
    log.warning("APP_TOKEN is not set: anyone who can reach this server can create recipes in Mealie.")

mealie = MealieClient(MEALIE_URL, MEALIE_API_TOKEN, MEALIE_PUBLIC_URL, MEALIE_TAG)
app = FastAPI(title="Insta → Mealie", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def harden(request: Request, call_next):
    # Real captions are tiny: refuse big bodies before they are read (put a limit on the
    # reverse proxy too, chunked requests carry no Content-Length).
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "Richiesta troppo grande"}, status_code=413)
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


# Cover images downloaded at preview time, reused at import time.
# Sync endpoints run in a thread pool, hence the lock.
_images: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_images_lock = threading.Lock()
_IMAGE_CACHE_SIZE = 30


def _cache_image(shortcode: str, image: tuple[bytes, str]) -> None:
    with _images_lock:
        _images[shortcode] = image
        _images.move_to_end(shortcode)
        while len(_images) > _IMAGE_CACHE_SIZE:
            _images.popitem(last=False)


def _cached_image(shortcode: str) -> tuple[bytes, str] | None:
    with _images_lock:
        return _images.get(shortcode)


def check_token(x_app_token: str = Header(default="")) -> None:
    if APP_TOKEN and not secrets.compare_digest(x_app_token, APP_TOKEN):
        raise HTTPException(401, "Codice di accesso errato")


Caption = Annotated[str, Field(max_length=MAX_CAPTION_LENGTH)]
Line = Annotated[str, Field(max_length=2_000)]
Lines = Annotated[list[Line], Field(max_length=300)]
Short = Annotated[str, Field(max_length=300)]
Minutes = Annotated[int | None, Field(ge=0, le=100_000)]


class FetchRequest(BaseModel):
    text: Annotated[str, Field(max_length=2_000, description="Instagram link, or the text shared by Instagram")]


class ParseRequest(BaseModel):
    caption: Caption
    author: Short = ""


class RecipeIn(BaseModel):
    name: Short = ""
    description: Caption = ""
    ingredients: Lines = []
    instructions: Lines = []
    notes: Lines = []
    recipe_yield: Short = ""
    prep_time: Minutes = None
    cook_time: Minutes = None
    total_time: Minutes = None


class ImportRequest(BaseModel):
    recipe: RecipeIn
    source_url: Short = ""
    shortcode: Annotated[str, Field(max_length=64, pattern=r"^[A-Za-z0-9_-]*$")] = ""
    author: Short = ""
    image_url: Line = ""
    caption: Caption = ""
    use_ai: bool = False


@app.get("/api/config")
def config():
    return {"auth_required": bool(APP_TOKEN), "ai_available": MEALIE_AI, "mealie_url": MEALIE_PUBLIC_URL}


@app.post("/api/fetch", dependencies=[Depends(check_token)])
def fetch(req: FetchRequest):
    try:
        post = fetch_post(req.text, INSTAGRAM_COOKIES_FILE)
    except InstagramError as e:
        raise HTTPException(422, str(e)) from e

    has_image = False
    if image := download_image(post.image_url):
        _cache_image(post.shortcode, image)
        has_image = True

    return {
        "shortcode": post.shortcode,
        "url": post.url,
        "author": post.author,
        "caption": post.caption,
        "image_url": post.image_url,
        "image": f"/api/image/{post.shortcode}" if has_image else None,
        "recipe": dataclasses.asdict(parse_caption(post.caption, post.author)),
    }


@app.post("/api/parse", dependencies=[Depends(check_token)])
def parse(req: ParseRequest):
    return {"recipe": dataclasses.asdict(parse_caption(req.caption, req.author))}


@app.get("/api/image/{shortcode}")
def image(shortcode: str):
    if not (cached := _cached_image(shortcode)):
        raise HTTPException(404)
    data, ext = cached
    return Response(data, media_type=f"image/{'jpeg' if ext == 'jpg' else ext}")


@app.post("/api/import", dependencies=[Depends(check_token)])
def import_recipe(req: ImportRequest):
    source_url = req.source_url
    shortcode = req.shortcode or find_shortcode(source_url) or ""
    try:
        if req.use_ai:
            if not MEALIE_AI:
                raise HTTPException(400, "Import con AI non abilitato (MEALIE_AI=false)")
            slug = mealie.create_with_ai(req.caption, source_url)
        else:
            slug = mealie.create_recipe(req.recipe.model_dump(), source_url, req.author)
    except MealieError as e:
        raise HTTPException(502, str(e)) from e

    image = _cached_image(shortcode) or download_image(req.image_url)
    if image:
        mealie.upload_image(slug, *image)

    return {"slug": slug, "url": mealie.recipe_url(slug)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sw.js")
def service_worker():
    # Served from the root so its scope covers the whole app.
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
