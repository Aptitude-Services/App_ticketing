"""Cloisonnement : point unique où se décide ce qu'un utilisateur peut voir.

Règle d'or : toute vue, tout export et toute API passent par ces fonctions.
Aucun filtrage « à la main » ailleurs dans le code.
"""
from django.db.models import Q, QuerySet

from .models import APTITUDE_PROFILES, CLIENT_PROFILES, STANDBY_PROFILES, Organisation, Profile, User


def _active(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.organisation.is_active)


def visible_contracts(user) -> QuerySet:
    """Contrats visibles par l'utilisateur."""
    from contracts.models import Contract

    qs = Contract.objects.select_related("client", "contract_type__sla")
    if not _active(user):
        return qs.none()

    if user.is_aptitude:
        if user.sees_all_contracts:
            return qs
        # Technicien « contrats affectés »
        return qs.filter(accesses__user=user).distinct()

    # Visibilité par contrat : chacun ne voit que les contrats dont il est partie.
    # Vendeur (ESN) : les contrats qu'il a vendus, jamais ceux d'Aptitude en direct
    # ni ceux d'une autre ESN, même pour un client final partagé.
    # Client final : les contrats dont il est bénéficiaire, directs ou via ESN.
    org = user.organisation
    if org.is_end_client:
        qs = qs.filter(Q(client_id=org.pk) | Q(end_clients=org.pk)).distinct()
    else:
        qs = qs.filter(client_id__in=org.scope_ids())
    if user.profile == Profile.CLIENT_ADMIN or user.all_contracts:
        return qs
    return qs.filter(accesses__user=user).distinct()


def can_view_contract(user, contract) -> bool:
    return visible_contracts(user).filter(pk=contract.pk).exists()


def visible_solutions(user) -> QuerySet:
    """Solutions des contrats visibles. Un client ne voit que les solutions actives."""
    from contracts.models import Solution

    qs = Solution.objects.filter(contract__in=visible_contracts(user)).select_related("contract")
    if not (_active(user) and user.is_aptitude):
        qs = qs.filter(is_active=True)
    return qs


def manageable_users(actor) -> QuerySet:
    """Utilisateurs que l'acteur peut consulter et modifier."""
    qs = User.objects.select_related("organisation")
    if not _active(actor):
        return qs.none()
    if actor.profile == Profile.APTITUDE_ADMIN:
        return qs
    if actor.profile == Profile.APTITUDE_MANAGER:
        # Comptes clients : ESN et clients finaux (Aptitude gère ceux de ses ventes directes).
        return qs.filter(organisation__is_operator=False)
    if actor.profile == Profile.CLIENT_ADMIN:
        return qs.filter(organisation_id__in=actor.organisation.scope_ids())
    return qs.none()


def assignable_profiles(actor) -> list:
    """Profils que l'acteur a le droit d'attribuer."""
    if not _active(actor):
        return []
    if actor.profile == Profile.APTITUDE_ADMIN:
        return [p for p in Profile if p in (APTITUDE_PROFILES | CLIENT_PROFILES) - STANDBY_PROFILES]
    if actor.profile in {Profile.APTITUDE_MANAGER, Profile.CLIENT_ADMIN}:
        return [p for p in Profile if p in CLIENT_PROFILES]
    return []


def manageable_organisations(actor) -> QuerySet:
    """Organisations dans lesquelles l'acteur peut créer des utilisateurs."""
    qs = Organisation.objects.filter(is_active=True)
    if not _active(actor):
        return qs.none()
    if actor.profile == Profile.APTITUDE_ADMIN:
        return qs
    if actor.profile == Profile.APTITUDE_MANAGER:
        return qs.filter(is_operator=False)
    if actor.profile == Profile.CLIENT_ADMIN:
        return qs.filter(pk__in=actor.organisation.scope_ids())
    return qs.none()


def is_last_client_admin(user) -> bool:
    """Vrai si l'utilisateur est le dernier admin client actif de son organisation."""
    if user.pk is None or user.profile != Profile.CLIENT_ADMIN:
        return False
    others = User.objects.filter(
        organisation_id=user.organisation_id, profile=Profile.CLIENT_ADMIN, is_active=True
    ).exclude(pk=user.pk)
    return not others.exists()
