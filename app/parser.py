"""Turn a free-form Instagram caption into a structured recipe.

Pure heuristics (Italian + English): section headers ("Ingredienti", "Procedimento", ...),
quantity detection for captions without headers, and cleanup of emoji, hashtags and
"follow me" boilerplate. The result is meant to be reviewed by the user before import.

Convention shared with the UI and the Mealie client: an ingredient or step line ending
with ":" is a section title ("Per la crema:").
"""

import re
import unicodedata
from dataclasses import dataclass, field

ING_HEADERS = (
    r"ingredient[ie]|ingredients?|occorrente|cosa (?:ti |vi )?serve|lista della spesa|"
    r"what you(?:'ll)? need|you(?:'ll)? need"
)
STEP_HEADERS = (
    r"procedimento|preparazione|istruzioni|metodo|come (?:si )?(?:fa|prepara\w*)|"
    r"method|instructions|directions|steps|how to make(?: it)?|preparation"
)
NOTE_HEADERS = r"consigli[oi]?|note?|suggeriment[oi]|tips?|conservazione|varianti?|curiosit[àa]"
ALL_HEADERS = rf"{ING_HEADERS}|{STEP_HEADERS}|{NOTE_HEADERS}|ricetta"

UNITS = (
    r"g|gr|grammi|kg|mg|ml|cl|dl|l|lt|litri?|cucchia\w*|tazz\w*|bicchier\w*|pizzic\w*|"
    r"spicchi?|fett[ae]|foglie?|rametti?|mazzett\w*|bustin\w*|vasett\w*|confezion\w*|"
    r"cups?|tbsp|tsp|oz|lbs?|pz|pezzi|uova|uovo|tuorl[oi]|album[ei]"
)
QTY_RE = re.compile(
    rf"(?:^|\s)(?:\d+(?:[.,/]\d+)?|[½¼¾⅓⅔]|mezz[oa]|un[oa]?|due|tre)\s*(?:{UNITS})\b"
    r"|\bq\.?\s?b\.?(?=\s|$|[,;)])|^\d+(?:[.,/]\d+)?\s+\w|\b\d+(?:[.,]\d+)?\s*(?:g|gr|kg|ml|l)\b",
    re.I,
)
YIELD_RE = re.compile(
    r"(?:\bper|\bfor|\bdosi per|\bserves|\bporzioni:?|\bdose:?)\s*(\d+(?:\s*[-–]\s*\d+)?)\s*"
    r"(persone|porzioni|pezzi|people|servings|persons|commensali|biscotti|muffins?|cookies|"
    r"pancakes?|panini|pizze|crepes|frittelle)?",
    re.I,
)
TIME_LABELS = {
    "prep": "prep_time",
    "preparazione": "prep_time",
    "preparation": "prep_time",
    "cottura": "cook_time",
    "cook": "cook_time",
    "cooking": "cook_time",
    "totale": "total_time",
    "total": "total_time",
}
TIME_RE = re.compile(
    r"^(?:tempo (?:di |della |totale)?\s*)?(prep|preparazione|preparation|cottura|cook|cooking|totale|total)"
    r"(?:\s*time)?\s*[:\-–]?\s*(?:circa\s*)?(\d+\s*(?:ore|ora|h|hours?|min\w*|m)\b.*)$",
    re.I,
)
JUNK_RE = re.compile(
    r"\b(segui(?:mi|teci)?|follow(?: me| us)?|salva(?:lo|la|te)?(?: il| questo)? (?:post|ricetta|reel)|"
    r"save (?:this|for later)|link in (?:bio|descrizione)|commenta|tagga|condividi|share this|"
    r"iscriviti|subscribe|attiva le notifiche|turn on notifications|#adv\b|ad\b|sponsored?|"
    r"in collaborazione con|in collab)",
    re.I,
)
STEP_NUMBER_RE = re.compile(r"^(?:(?:step|passo|fase|punto)\s*)?\d{1,2}\s*(?:[.)°:\-–]|️?⃣)\s*", re.I)
KEYCAP_RE = re.compile(r"^\s*(?:\d+️?⃣|🔟)\s*")
BULLET_CHARS = set("-–—•·▪▫●◦‣*~>|✓✔+")


@dataclass
class ParsedRecipe:
    name: str = ""
    description: str = ""
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    recipe_yield: str = ""
    prep_time: int | None = None  # minutes
    cook_time: int | None = None
    total_time: int | None = None


def _is_deco(ch: str) -> bool:
    return ch in BULLET_CHARS or unicodedata.category(ch) in ("So", "Sk", "Cf", "Mn", "Co", "Cs")


def clean_line(line: str) -> str:
    """Strip bullets/emoji at both ends and hashtags, keep the text."""
    line = KEYCAP_RE.sub("", line)
    line = re.sub(r"(?:\s*#[\wÀ-ɏ]+)+\s*$", "", line)  # trailing hashtags
    line = re.sub(r"#([\wÀ-ɏ]+)", r"\1", line)  # inline hashtags -> plain words
    i = 0
    while i < len(line) and (line[i].isspace() or _is_deco(line[i]) or line[i] in ".:"):
        i += 1
    j = len(line)
    while j > i and (line[j - 1].isspace() or _is_deco(line[j - 1])):
        j -= 1
    return re.sub(r"\s{2,}", " ", line[i:j]).strip()


def _has_bullet(raw: str) -> bool:
    s = raw.lstrip()
    return bool(s) and (_is_deco(s[0]) or bool(KEYCAP_RE.match(s)))


def parse_duration(text: str) -> int | None:
    """'1 ora e 30 minuti' -> 90, '45 min' -> 45."""
    m = re.match(r"(\d+)\s*(ore|ora|h|hours?)\b(?:\s*(?:e|and)?\s*(\d+)\s*(?:min\w*|m)\b)?", text, re.I)
    if m:
        return int(m.group(1)) * 60 + int(m.group(3) or 0)
    m = re.match(r"(\d+)\s*(?:min\w*|m)\b", text, re.I)
    return int(m.group(1)) if m else None


def _match_header(line: str) -> tuple[str, str] | None:
    """Return (section, inline_rest) if the line is a section header."""
    low = line.lower()
    for section, pattern in (("ingredients", ING_HEADERS), ("steps", STEP_HEADERS), ("notes", NOTE_HEADERS)):
        m = re.match(rf"^(?:{pattern})\b\s*(.*)$", low, re.S)
        if not m:
            continue
        rest = line[len(line) - len(m.group(1)) :] if m.group(1) else ""
        if rest.startswith(":"):
            return section, rest[1:].strip()
        # "Ingredienti per 4 persone", "Ingredienti (per una teglia)", "Procedimento"
        if not rest or (len(rest) <= 40 and re.match(r"^[(\-–]|^(per|for|x)\b", rest, re.I)):
            return section, rest
        return None
    if re.fullmatch(r"ricetta\s*:?", low):
        return "steps", ""
    return None


def _looks_like_ingredient(line: str, raw: str) -> bool:
    if len(line) > 90:
        return False
    if QTY_RE.search(line):
        return True
    # Bulleted short item without a final period ("- sale", "• pepe nero")
    return _has_bullet(raw) and len(line.split()) <= 6 and not line.endswith(".")


def _looks_like_step(line: str) -> bool:
    words = len(line.split())
    return len(line) > 90 or (words >= 7 and line.rstrip().endswith((".", "!"))) or bool(STEP_NUMBER_RE.match(line))


def _split_inline_list(text: str) -> list[str]:
    parts = re.split(r",\s+|;\s*|\s+[-–•]\s+|•", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý0-9])", text)
    return [p.strip() for p in parts if p.strip()]


def _make_title(line: str) -> str:
    title = re.split(r"(?<=[.!?])\s|\s[-–|]\s", line, maxsplit=1)[0].strip()
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0] + "…"
    title = title.rstrip(".:!,; ")
    letters = [c for c in title if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        title = title.capitalize()
    return title


def parse_caption(caption: str, author: str = "") -> ParsedRecipe:
    # Drop zero-width spaces, turn Unicode line separators into newlines.
    text = caption.replace("\r\n", "\n").replace(chr(0x200B), "").replace(chr(0x2028), "\n")
    # Single-paragraph captions: put each header on its own line.
    if text.count("\n") < 3:
        text = re.sub(rf"\s*\b({ALL_HEADERS})\b\s*:", r"\n\1:", text, flags=re.I)

    r = ParsedRecipe()
    intro: list[str] = []
    notes: list[str] = []
    ingredients: list[str] = []
    steps: list[str] = []
    section = "intro"

    for raw in text.split("\n"):
        line = clean_line(raw)
        if not line or not re.search(r"\w", line):
            continue
        if JUNK_RE.search(line) and len(line) < 140 and section != "ingredients":
            continue

        m = TIME_RE.match(line)
        if m and len(line) < 60 and (minutes := parse_duration(m.group(2))):
            setattr(r, TIME_LABELS[m.group(1).lower()], minutes)
            continue

        header = _match_header(line)
        if header:
            section, rest = header
            if rest and (y := YIELD_RE.search(rest)) and not r.recipe_yield:
                r.recipe_yield = " ".join(filter(None, (y.group(1), y.group(2))))
                rest = ""
            if rest.startswith("("):
                rest = ""
            if rest:
                if section == "ingredients":
                    ingredients.extend(_split_inline_list(rest) if "," in rest or ";" in rest else [rest])
                elif section == "steps":
                    steps.append(rest)
                else:
                    notes.append(rest)
            continue

        y = YIELD_RE.search(line) if not r.recipe_yield and len(line) < 50 else None
        # "Serves 8" / "Porzioni: 4" on their own line, or "... per 4 persone" anywhere
        if y and (y.group(2) or y.start() == 0):
            r.recipe_yield = " ".join(filter(None, (y.group(1), y.group(2))))
            if section != "ingredients" or len(line) < 25:
                continue

        if section == "intro":
            # No header yet: the first ingredient-looking line opens the ingredient list.
            if intro and _looks_like_ingredient(line, raw):
                section = "ingredients"
            else:
                intro.append(line)
                continue

        if section == "ingredients":
            if _looks_like_step(line) and not _looks_like_ingredient(line, raw):
                section = "steps"  # ingredient list ended, no explicit header
            else:
                if "•" in line or line.count(" - ") >= 2:
                    ingredients.extend(_split_inline_list(line))
                else:
                    ingredients.append(line.rstrip(",;"))
                continue

        if section == "steps":
            steps.append(STEP_NUMBER_RE.sub("", line).strip())
        elif section == "notes":
            notes.append(line)

    # Captions without any header and no detected ingredients: the intro is the recipe text.
    if not ingredients and not steps and len(intro) > 1:
        steps = intro[1:]
        intro = intro[:1]

    if len(steps) == 1 and len(steps[0]) > 250:
        steps = _sentences(steps[0])

    r.name = _make_title(intro[0]) if intro else ""
    if not r.name:
        r.name = f"Ricetta di @{author}" if author else "Ricetta da Instagram"
    # Keep the first line in the description when the title is only a piece of it.
    title_is_whole_line = intro and len(intro[0]) <= 80 and not re.search(r"[.!?]\s+\S|\s[-–|]\s", intro[0])
    r.description = "\n".join(intro[1:] if title_is_whole_line else intro)
    r.notes = notes
    r.ingredients = [i for i in ingredients if i]
    r.instructions = [s for s in steps if s]
    return r
