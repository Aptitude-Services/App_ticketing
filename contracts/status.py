"""État de couverture d'un contrat à un instant donné, pour l'affichage."""
from django.utils import timezone

from sla import engine


def coverage_status(contract, now=None):
    """Renvoie {"state": "always" | "open" | "closed" | "none", "next_open": datetime|None}."""
    now = now or timezone.now()
    sla = contract.sla
    if sla is None:
        return {"state": "none", "next_open": None}
    if sla.is_24x7:
        return {"state": "always", "next_open": None}
    if engine.is_covered(sla, now):
        return {"state": "open", "next_open": None}
    return {"state": "closed", "next_open": engine.next_coverage_start(sla, now)}


def with_coverage(contracts, now=None):
    """Attache `coverage_now` à chaque contrat ; un seul calcul par SLA."""
    now = now or timezone.now()
    cache = {}
    rows = []
    for c in contracts:
        key = c.contract_type.sla_id if c.contract_type_id else None
        if key not in cache:
            cache[key] = coverage_status(c, now)
        c.coverage_now = cache[key]
        rows.append(c)
    return rows
