"""Supprime un utilisateur par son email.

    python manage.py delete_user personne@exemple.ci

Si le compte a déjà servi (tickets, réponses, pièces jointes, rapports), la base refuse
de le supprimer pour garder l'historique : il est alors désactivé (plus de connexion possible).
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import ProtectedError

from accounts.models import User


class Command(BaseCommand):
    help = "Supprime un utilisateur (ou le désactive s'il a déjà un historique)."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Adresse email de l'utilisateur")

    def handle(self, *args, email, **options):
        try:
            user = User.objects.get(email__iexact=email.strip())
        except User.DoesNotExist:
            raise CommandError(f"Aucun utilisateur avec l'email {email}.")

        try:
            user.delete()
        except ProtectedError:
            if user.is_active:
                user.is_active = False
                user.save(update_fields=["is_active"])
            self.stdout.write(self.style.WARNING(
                f"{user.email} a déjà un historique (tickets, réponses ou rapports) : "
                "il ne peut pas être supprimé. Le compte est désactivé, il ne peut plus se connecter."))
            return
        self.stdout.write(self.style.SUCCESS(f"{user.email} supprimé."))
