"""Filtres d'affichage des rapports (dates ISO stockées en JSON, pastilles de résultat)."""
import datetime

from django import template

register = template.Library()


def _parse(value):
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time())
    try:
        return datetime.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


@register.filter
def dt(value):
    """« 2026-11-04T08:42 » → « 04/11/2026 à 08:42 »."""
    d = _parse(value)
    if not d:
        return value or "—"
    if len(str(value)) <= 10:
        return d.strftime("%d/%m/%Y")
    return d.strftime("%d/%m/%Y à %H:%M")


@register.filter
def day(value):
    d = _parse(value)
    return d.strftime("%d/%m/%Y") if d else (value or "—")


@register.filter
def hour(value):
    d = _parse(value)
    return d.strftime("%H:%M") if d else (value or "")


@register.filter
def duration_between(start, end):
    a, b = _parse(start), _parse(end)
    if not (a and b) or b <= a:
        return ""
    minutes = int((b - a).total_seconds() // 60)
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d}" if h else f"{m} min"


TONES = {
    "conforme": "ok", "validé": "ok", "ok": "ok", "appliquée": "ok", "cause identifiée": "ok", "atteint": "ok",
    "contrat": "ok", "basse": "info",
    "à surveiller": "warn", "attention": "warn", "moyenne": "warn", "planifiée": "warn", "en attente": "warn",
    "cause probable": "warn", "en cours": "warn",
    "non conforme": "ko", "échec": "ko", "haute": "ko", "critique": "ko", "sous l'objectif": "ko",
}


@register.filter
def tone(value):
    """Classe de pastille (ok / warn / ko / info / neutral) d'après le libellé."""
    return TONES.get(str(value or "").strip().lower(), "neutral")


@register.filter
def cell(row, index):
    try:
        return row[int(index)]
    except (IndexError, TypeError, ValueError):
        return ""


@register.filter
def pct_value(value):
    """« 99,92 » → 99.92 (pour les jauges)."""
    try:
        return float(str(value).replace(",", ".").replace("%", "").strip())
    except ValueError:
        return None


@register.filter
def fr_number(value):
    if value is None or value == "":
        return "—"
    try:
        text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return value
    return text.replace(".", ",")
