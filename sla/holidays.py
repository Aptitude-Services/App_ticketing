"""Génération des jours fériés ivoiriens.

Source : décret n°96-205 du 7 mars 1996, modifié par le décret n°2011-371 du
4 novembre 2011. Les fêtes musulmanes dépendent de l'observation lunaire : leurs
dates sont saisies chaque année dès le communiqué officiel du gouvernement.
"""
import datetime

FIXED = [
    (1, 1, "Jour de l'An"),
    (5, 1, "Fête du Travail"),
    (8, 7, "Fête nationale"),
    (8, 15, "Assomption"),
    (11, 1, "Toussaint"),
    (11, 15, "Journée nationale de la Paix"),
    (12, 25, "Noël"),
]

# Dates annoncées connues (communiqués officiels).
ANNOUNCED = {
    2026: [
        (datetime.date(2026, 3, 16), "Lendemain de la Nuit du Destin"),
        (datetime.date(2026, 3, 20), "Aïd el-Fitr (fin du Ramadan)"),
        (datetime.date(2026, 5, 27), "Tabaski (Aïd el-Kébir)"),
        (datetime.date(2026, 8, 25), "Lendemain du Maouloud"),
    ],
}


def easter(year: int) -> datetime.date:
    """Dimanche de Pâques (calendrier grégorien, algorithme de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, month, day + 1)


def holidays_for(year: int):
    """Liste (date, nom, type) des fériés connus pour l'année."""
    items = [(datetime.date(year, m, d), name, "fixed") for m, d, name in FIXED]
    e = easter(year)
    items += [
        (e + datetime.timedelta(days=1), "Lundi de Pâques", "computed"),
        (e + datetime.timedelta(days=39), "Ascension", "computed"),
        (e + datetime.timedelta(days=50), "Lundi de Pentecôte", "computed"),
    ]
    items += [(d, name, "announced") for d, name in ANNOUNCED.get(year, [])]
    # Report au lundi quand ces fêtes tombent un dimanche (les fêtes musulmanes
    # concernées sont ajoutées à la main, avec leur date officielle).
    for d, name, _kind in list(items):
        if name in SUBSTITUTED and d.weekday() == 6:
            items.append((d + datetime.timedelta(days=1), f"{name} (lundi chômé)", "substitute"))
    return sorted(items)


SUBSTITUTED = {"Fête du Travail", "Fête nationale", "Noël"}
