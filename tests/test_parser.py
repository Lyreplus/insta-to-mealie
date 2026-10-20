from app.parser import clean_line, parse_caption, parse_duration

CLASSIC = """TORTA DI MELE SOFFICISSIMA 🍎🍰
La torta della nonna, pronta in un attimo!

⏱ Preparazione: 20 min
🔥 Cottura: 45 minuti

📝 INGREDIENTI per 8 persone:
▪️ 300 g di farina 00
▪️ 3 uova
▪️ 150 g di zucchero
▪️ 1 bustina di lievito
▪️ 3 mele
▪️ scorza di limone q.b.

👩‍🍳 PROCEDIMENTO:
1️⃣ Montate le uova con lo zucchero fino a ottenere un composto chiaro.
2️⃣ Aggiungete la farina setacciata con il lievito.
3. Unite le mele a fette e versate in una teglia da 24 cm.
4) Cuocete a 180° per 45 minuti.

💡 Consiglio: potete sostituire le mele con le pere.

Salva il post per non perderlo e seguimi per altre ricette! 👉 @nonnapapera
.
.
#tortadimele #ricettefacili #dolci #food"""

SECTIONS = """Tiramisù classico

Ingredienti:
Per la crema:
- 4 tuorli
- 500 g di mascarpone
- 100 g di zucchero
Per la base:
- 300 g di savoiardi
- caffè q.b.

Procedimento:
Per la crema:
Montate i tuorli con lo zucchero.
Aggiungete il mascarpone.
Per la base:
Inzuppate i savoiardi nel caffè e alternate con la crema."""

NO_HEADERS = """Pasta al limone 🍋 velocissima
320 g di spaghetti
2 limoni
50 g di burro
parmigiano q.b.
Cuocete la pasta in acqua salata e nel frattempo sciogliete il burro in padella con la scorza dei limoni.
Scolate la pasta al dente, mantecate con il succo di limone e il parmigiano. Servite subito!"""

ONE_PARAGRAPH = (
    "Crepes dolci 🥞 Ingredienti: 250 ml di latte, 2 uova, 125 g di farina, 1 pizzico di sale. "
    "Procedimento: sbattete le uova con il latte. Aggiungete la farina e lasciate riposare 30 minuti. "
    "Cuocete un mestolo di impasto alla volta in una padella calda. #crepes #colazione"
)

ENGLISH = """Easy banana bread
Serves 8

Ingredients:
• 3 ripe bananas
• 2 cups flour
• 1 tsp baking soda

Instructions:
1. Mash the bananas.
2. Mix everything together.
3. Bake at 350F for 60 minutes.
Follow me for more recipes!"""


def test_classic_caption():
    r = parse_caption(CLASSIC)
    assert r.name == "Torta di mele sofficissima"
    assert r.description.startswith("La torta della nonna")
    assert r.notes == ["potete sostituire le mele con le pere."]
    assert r.recipe_yield == "8 persone"
    assert r.prep_time == 20 and r.cook_time == 45
    assert r.ingredients == [
        "300 g di farina 00",
        "3 uova",
        "150 g di zucchero",
        "1 bustina di lievito",
        "3 mele",
        "scorza di limone q.b.",
    ]
    assert r.instructions[0].startswith("Montate le uova")
    assert r.instructions[2].startswith("Unite le mele")
    assert r.instructions[3] == "Cuocete a 180° per 45 minuti."
    assert len(r.instructions) == 4


def test_sub_sections_are_kept_as_titles():
    r = parse_caption(SECTIONS)
    assert r.name == "Tiramisù classico"
    assert r.ingredients[0] == "Per la crema:"
    assert "Per la base:" in r.ingredients
    assert r.ingredients[-1] == "caffè q.b."
    assert r.instructions[0] == "Per la crema:"
    assert r.instructions[-1].startswith("Inzuppate")


def test_caption_without_headers():
    r = parse_caption(NO_HEADERS)
    assert r.name == "Pasta al limone velocissima" or r.name.startswith("Pasta al limone")
    assert r.ingredients == ["320 g di spaghetti", "2 limoni", "50 g di burro", "parmigiano q.b."]
    assert len(r.instructions) == 2
    assert r.instructions[1].endswith("Servite subito!")


def test_single_paragraph():
    r = parse_caption(ONE_PARAGRAPH)
    assert r.name == "Crepes dolci"
    assert r.ingredients == ["250 ml di latte", "2 uova", "125 g di farina", "1 pizzico di sale"]
    assert r.instructions[0].startswith("sbattete le uova")
    assert not any("#" in s for s in r.instructions)


def test_english():
    r = parse_caption(ENGLISH)
    assert r.name == "Easy banana bread"
    assert r.recipe_yield == "8"
    assert r.ingredients == ["3 ripe bananas", "2 cups flour", "1 tsp baking soda"]
    assert r.instructions == ["Mash the bananas.", "Mix everything together.", "Bake at 350F for 60 minutes."]


def test_fallback_title_uses_author():
    r = parse_caption("Ingredienti:\n200 g riso", author="chef")
    assert r.name == "Ricetta di @chef"
    assert r.ingredients == ["200 g riso"]


def test_helpers():
    assert clean_line("▪️ 300 g di farina 🌾") == "300 g di farina"
    assert clean_line("Buonissima #pasta #food") == "Buonissima"
    assert parse_duration("1 ora e 30 minuti") == 90
    assert parse_duration("45 min") == 45
