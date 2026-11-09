"""Codes courts des organisations (ex. HUD, BLAG), utilisés dans les références de contrat."""
import re
import unicodedata

CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")
_STOPWORDS = {"DE", "DU", "DES", "LA", "LE", "LES", "ET", "D", "L", "EN", "AU", "AUX", "SA", "SARL", "SAS", "GROUPE"}


def _words(name):
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", ascii_name.upper())
    meaningful = [w for w in words if w not in _STOPWORDS]
    return meaningful or words


def suggest_code(name, taken=()):
    """Code de 2 à 8 caractères tiré du nom, unique parmi `taken`.

    Un mot : ses 3 premières lettres (HUDSON → HUD). Deux mots : initiale du premier
    et 3 lettres du second (Banque Lagune → BLAG). Trois mots ou plus : initiales
    (Aptitude Services Côte d'Ivoire → ASCI).
    """
    words = _words(name) or ["ORG"]
    if len(words) == 1:
        base = words[0][:3]
    elif len(words) == 2:
        base = words[0][:1] + words[1][:3]
    else:
        base = "".join(w[0] for w in words)[:6]
    base = base if len(base) >= 2 else (base + "X")
    taken = {t.upper() for t in taken}
    code, n = base, 1
    while code in taken:
        n += 1
        suffix = str(n)
        code = base[: 8 - len(suffix)] + suffix
    return code
