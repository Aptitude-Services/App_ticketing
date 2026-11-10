"""Suppression en cascade réservée au Super Admin, dans l'administration.

Par défaut, l'historique est protégé : un contrat qui a des tickets, ou un ticket qui a un
rapport, ne peut pas être supprimé (on le passe plutôt en « Résilié » / « Clos »). Le Super Admin
peut cependant nettoyer des données de test : supprimer un contrat emporte alors ses rapports et
ses tickets (avec leurs suivis, pièces jointes et historique) ; supprimer un ticket emporte ses
rapports curatifs. La page de confirmation de Django liste tout ce qui sera supprimé.
"""
from collections import Counter

from django.contrib.admin.utils import NestedObjects
from django.db import router, transaction

from accounts.models import Profile


def is_super_admin(request):
    return request.user.is_active and request.user.profile == Profile.APTITUDE_ADMIN


class SuperAdminCascadeDeleteMixin:
    """À combiner avec ModelAdmin. `cascade_querysets(objs)` renvoie, dans l'ordre de
    suppression, les objets protégés à supprimer avant `objs`."""

    def cascade_querysets(self, objs):
        return []

    def _cascades(self, request, objs):
        if not is_super_admin(request):
            return []
        return [qs for qs in self.cascade_querysets(objs) if qs.exists()]

    def get_deleted_objects(self, objs, request):
        cascades = self._cascades(request, objs)
        if not cascades:
            return super().get_deleted_objects(objs, request)

        # Tout ce qui sera supprimé : un objet protégé de cette liste ne bloque plus.
        doomed = {(type(o), o.pk) for o in objs}
        for qs in cascades:
            doomed |= {(qs.model, pk) for pk in qs.values_list("pk", flat=True)}

        to_delete, counts, perms, protected = [], Counter(), set(), []
        for group in [*cascades, objs]:
            d, c, p, pr = super().get_deleted_objects(group, request)
            to_delete += d
            counts.update(c)
            perms |= set(p)
            if pr:
                collector = NestedObjects(using=router.db_for_write(self.model))
                collector.collect(list(group))
                if any((type(o), o.pk) not in doomed for o in collector.protected):
                    protected += pr
        return to_delete, dict(counts), perms, protected

    def delete_model(self, request, obj):
        with transaction.atomic():
            for qs in self._cascades(request, [obj]):
                qs.delete()
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for qs in self._cascades(request, queryset):
                qs.delete()
            super().delete_queryset(request, queryset)
