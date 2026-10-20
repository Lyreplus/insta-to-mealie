"""Minimal Mealie API client: create a recipe from parsed data (or via Mealie's AI) and attach the image."""

import json
import logging

import httpx

log = logging.getLogger(__name__)


class MealieError(Exception):
    pass


def is_section_title(line: str) -> bool:
    """'Per la crema:' -> section title (same convention as the parser and the UI)."""
    return line.endswith(":") and len(line) <= 60


def _split_sections(lines: list[str]) -> tuple[list[str], dict[int, str]]:
    """Return the plain lines and {index_of_first_line_in_section: title}."""
    items: list[str] = []
    titles: dict[int, str] = {}
    for line in (line.strip() for line in lines):
        if not line:
            continue
        if is_section_title(line):
            titles[len(items)] = line.rstrip(":").strip()
        else:
            items.append(line)
    return items, titles


def _iso_minutes(minutes: int | None) -> str | None:
    return f"PT{minutes}M" if minutes else None


class MealieClient:
    def __init__(self, base_url: str, token: str, public_url: str = "", tag: str = ""):
        self.base_url = base_url.rstrip("/")
        self.public_url = (public_url or base_url).rstrip("/")
        self.tag = tag
        self._group_slug: str | None = None
        self.http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(30, read=180),  # AI imports can be slow
        )

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.is_success:
            return r
        try:
            detail = r.json().get("detail", r.text)
            if isinstance(detail, dict):
                detail = detail.get("message") or detail.get("details") or json.dumps(detail)
        except ValueError:
            detail = r.text[:300]
        if r.status_code == 401:
            detail = "token API di Mealie non valido"
        raise MealieError(f"Mealie ha risposto {r.status_code}: {detail}")

    def recipe_url(self, slug: str) -> str:
        if self._group_slug is None:
            try:
                self._group_slug = self._check(self.http.get("/api/users/self")).json().get("groupSlug", "")
            except (MealieError, httpx.HTTPError):
                self._group_slug = ""
        if self._group_slug:
            return f"{self.public_url}/g/{self._group_slug}/r/{slug}"
        return f"{self.public_url}/recipe/{slug}"

    def create_recipe(self, recipe: dict, source_url: str, author: str = "") -> str:
        """Create through Mealie's own schema.org importer, then restore section titles."""
        ingredients, ing_titles = _split_sections(recipe.get("ingredients", []))
        steps, step_titles = _split_sections(recipe.get("instructions", []))

        ld = {
            "@context": "https://schema.org",
            "@type": "Recipe",
            "name": recipe.get("name") or "Ricetta da Instagram",
            "description": recipe.get("description") or "",
            "url": source_url,
            "recipeIngredient": ingredients,
            "recipeInstructions": [{"@type": "HowToStep", "text": s} for s in steps],
        }
        if author:
            ld["author"] = {"@type": "Person", "name": f"@{author}"}
        if recipe.get("recipe_yield"):
            ld["recipeYield"] = recipe["recipe_yield"]
        for key, ld_key in (("prep_time", "prepTime"), ("cook_time", "cookTime"), ("total_time", "totalTime")):
            if iso := _iso_minutes(recipe.get(key)):
                ld[ld_key] = iso
        if self.tag:
            ld["keywords"] = self.tag

        r = self.http.post(
            "/api/recipes/create/html-or-json",
            json={"data": json.dumps(ld, ensure_ascii=False), "url": source_url, "includeTags": bool(self.tag)},
        )
        if r.status_code == 404:
            raise MealieError("Questa versione di Mealie è troppo vecchia (manca /create/html-or-json): aggiornala.")
        slug = self._check(r).json()

        notes = [n.strip() for n in recipe.get("notes", []) if n.strip()]
        description = recipe.get("description") or ""
        if ing_titles or step_titles or notes or "\n" in description:
            self._finalize(slug, ing_titles, step_titles, notes, description)
        return slug

    def create_with_ai(self, caption: str, source_url: str) -> str:
        """Let Mealie's configured AI provider parse the raw caption."""
        r = self.http.post("/api/recipes/create/ai", data={"content": caption})
        if r.status_code == 404:
            raise MealieError("Questa versione di Mealie non supporta l'import con AI.")
        slug = self._check(r).json()
        try:
            self._check(self.http.patch(f"/api/recipes/{slug}", json={"orgURL": source_url}))
        except MealieError as e:
            log.warning("Could not set source URL on %s: %s", slug, e)
        return slug

    def _finalize(
        self,
        slug: str,
        ing_titles: dict[int, str],
        step_titles: dict[int, str],
        notes: list[str],
        description: str,
    ) -> None:
        """Set what the schema.org importer can't carry: section titles, notes, multi-line description."""
        try:
            full = self._check(self.http.get(f"/api/recipes/{slug}")).json()
            for field, titles in (("recipeIngredient", ing_titles), ("recipeInstructions", step_titles)):
                items = full.get(field) or []
                for idx, title in titles.items():
                    if idx < len(items):
                        items[idx]["title"] = title
            if notes:
                full["notes"] = [{"title": "", "text": n} for n in notes]
            if description:
                full["description"] = description
            self._check(self.http.put(f"/api/recipes/{slug}", json=full))
        except (MealieError, httpx.HTTPError) as e:
            # Not fatal: the recipe exists, only these extras are missing.
            log.warning("Could not finalize %s: %s", slug, e)

    def upload_image(self, slug: str, data: bytes, extension: str) -> None:
        try:
            self._check(
                self.http.put(
                    f"/api/recipes/{slug}/image",
                    files={"image": (f"image.{extension}", data, f"image/{extension}")},
                    data={"extension": extension},
                )
            )
        except (MealieError, httpx.HTTPError) as e:
            log.warning("Image upload failed for %s: %s", slug, e)
