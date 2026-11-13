"""Default challenges for the drawing game.

Elements are concrete, everyday objects the OWLv2 detector finds reliably
(people, animals, vehicles, furniture, food). Forbidden words are the
obvious ones a team would reach for first, in Italian and English, so the
team has to describe around them.
"""

import json

from extensions import db
from models import DrawingChallenge


def _el(it, en, query=None):
    return {"it": it, "en": en, "query": query or f"a photo of a {en}"}


CHALLENGES = [
    {
        "title_it": "Giornata al mare", "title_en": "A day at the beach",
        "brief_it": "Fate disegnare all'AI una giornata d'estate in spiaggia.",
        "brief_en": "Get the AI to draw a summer day at the beach.",
        "elements": [_el("ombrellone", "umbrella", "a beach umbrella"), _el("barca", "boat"),
                     _el("pallone", "ball", "a beach ball"), _el("cane", "dog"), _el("sedia a sdraio", "chair", "a deck chair")],
        "forbidden": ["mare", "spiaggia", "sabbia", "ombrellone", "sea", "beach", "sand", "umbrella"],
    },
    {
        "title_it": "La fattoria", "title_en": "The farm",
        "brief_it": "Una fattoria piena di animali.",
        "brief_en": "A farm full of animals.",
        "elements": [_el("mucca", "cow"), _el("cavallo", "horse"), _el("pecora", "sheep"),
                     _el("trattore", "tractor"), _el("gallina", "chicken")],
        "forbidden": ["fattoria", "mucca", "vacca", "cavallo", "farm", "cow", "horse"],
    },
    {
        "title_it": "In cucina", "title_en": "In the kitchen",
        "brief_it": "Una cucina dove qualcuno sta preparando la colazione.",
        "brief_en": "A kitchen where someone is making breakfast.",
        "elements": [_el("tazza", "cup", "a cup"), _el("frigorifero", "refrigerator"), _el("banana", "banana"),
                     _el("bottiglia", "bottle"), _el("forno", "oven")],
        "forbidden": ["cucina", "colazione", "tazza", "frigo", "frigorifero", "kitchen", "breakfast", "cup", "fridge"],
    },
    {
        "title_it": "Strada di città", "title_en": "City street",
        "brief_it": "Una strada trafficata in centro città.",
        "brief_en": "A busy street downtown.",
        "elements": [_el("auto", "car"), _el("autobus", "bus"), _el("semaforo", "traffic light"),
                     _el("bicicletta", "bicycle"), _el("persona", "person")],
        "forbidden": ["citta", "strada", "macchina", "auto", "automobile", "city", "street", "car"],
    },
    {
        "title_it": "Festa di compleanno", "title_en": "Birthday party",
        "brief_it": "La festa di compleanno di un bambino.",
        "brief_en": "A child's birthday party.",
        "elements": [_el("torta", "cake"), _el("palloncino", "balloon"), _el("regalo", "gift", "a gift box"),
                     _el("candela", "candle"), _el("bambino", "child")],
        "forbidden": ["compleanno", "festa", "torta", "palloncino", "birthday", "party", "cake", "balloon"],
    },
    {
        "title_it": "In classe", "title_en": "In the classroom",
        "brief_it": "Un'aula scolastica durante la lezione.",
        "brief_en": "A school classroom during a lesson.",
        "elements": [_el("lavagna", "blackboard"), _el("banco", "desk"), _el("libro", "book"),
                     _el("orologio", "clock"), _el("zaino", "backpack")],
        "forbidden": ["scuola", "classe", "aula", "lavagna", "libro", "school", "classroom", "book"],
    },
    {
        "title_it": "Nello spazio", "title_en": "In space",
        "brief_it": "Un'avventura tra le stelle.",
        "brief_en": "An adventure among the stars.",
        "elements": [_el("astronauta", "astronaut"), _el("razzo", "rocket"), _el("pianeta", "planet"),
                     _el("luna", "moon"), _el("bandiera", "flag")],
        "forbidden": ["spazio", "astronauta", "razzo", "stella", "space", "astronaut", "rocket", "star"],
    },
    {
        "title_it": "Picnic nel bosco", "title_en": "Picnic in the woods",
        "brief_it": "Un picnic all'ombra degli alberi.",
        "brief_en": "A picnic in the shade of the trees.",
        "elements": [_el("cestino", "basket", "a picnic basket"), _el("albero", "tree"), _el("mela", "apple"),
                     _el("panino", "sandwich"), _el("scoiattolo", "squirrel")],
        "forbidden": ["picnic", "bosco", "foresta", "albero", "cestino", "forest", "woods", "tree", "basket"],
    },
    {
        "title_it": "Partita di calcio", "title_en": "Football match",
        "brief_it": "Una partita di calcio allo stadio.",
        "brief_en": "A football match at the stadium.",
        "elements": [_el("pallone", "ball", "a soccer ball"), _el("porta", "goal", "a soccer goal"),
                     _el("giocatore", "player", "a soccer player"), _el("arbitro", "referee"), _el("bandierina", "flag")],
        "forbidden": ["calcio", "pallone", "palla", "stadio", "gol", "football", "soccer", "ball", "stadium"],
    },
    {
        "title_it": "L'acquario", "title_en": "The aquarium",
        "brief_it": "La vasca più bella di un grande acquario.",
        "brief_en": "The most beautiful tank of a big aquarium.",
        "elements": [_el("pesce", "fish"), _el("tartaruga", "turtle"), _el("medusa", "jellyfish"),
                     _el("squalo", "shark"), _el("stella marina", "starfish")],
        "forbidden": ["acquario", "pesce", "acqua", "mare", "aquarium", "fish", "water", "sea"],
    },
]


def seed():
    if DrawingChallenge.query.first() is not None:
        return "drawing: content already present, skipped"
    for item in CHALLENGES:
        db.session.add(DrawingChallenge(
            title_it=item["title_it"], title_en=item["title_en"],
            brief_it=item["brief_it"], brief_en=item["brief_en"],
            elements_json=json.dumps(item["elements"], ensure_ascii=False),
            forbidden_words="\n".join(item["forbidden"]),
        ))
    db.session.commit()
    return f"drawing: {len(CHALLENGES)} challenges added"
