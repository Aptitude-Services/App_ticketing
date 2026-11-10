"""Commande de création ou réinitialisation d'utilisateurs de test.

Usage :
    python manage.py create_test_user
    python manage.py create_test_user --email=user@test.ci --password=MonMotDePasse --client
"""
from django.core.management.base import BaseCommand

from accounts.models import Organisation, Profile, User

DEFAULT_PASSWORD = "Demo-Aptitude-2026"


class Command(BaseCommand):
    help = "Crée ou met à jour des comptes utilisateurs de test (Admin Aptitude et Client)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="test@aptitudes.net",
            help="Adresse email de l'utilisateur à créer (défaut : test@aptitudes.net)",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=f"Mot de passe (défaut : {DEFAULT_PASSWORD})",
        )
        parser.add_argument(
            "--client",
            action="store_true",
            help="Créer un compte client (sans MFA obligatoire) plutôt qu'un compte administrateur Aptitude.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        is_client = options["client"]

        if is_client:
            org, _ = Organisation.objects.get_or_create(
                name="Banque Lagune",
                defaults={"kind": Organisation.Kind.CLIENT, "activity_sector": Organisation.ActivitySector.BANK, "email_domains": "banque-lagune.ci"},
            )
            profile = Profile.CLIENT_ADMIN
            first_name = "Test"
            last_name = "Client"
            is_super = False
        else:
            org, _ = Organisation.objects.get_or_create(
                kind=Organisation.Kind.APTITUDE,
                defaults={"name": "Aptitude Services"},
            )
            profile = Profile.APTITUDE_ADMIN
            first_name = "Test"
            last_name = "Aptitude"
            is_super = True

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "organisation": org,
                "profile": profile,
                "first_name": first_name,
                "last_name": last_name,
                "is_active": True,
                "is_superuser": is_super,
                "all_contracts": True,
            },
        )

        user.set_password(password)
        user.is_active = True
        user.profile = profile
        user.organisation = org
        if is_super:
            user.is_superuser = True
        user.save()

        action = "créé" if created else "mis à jour"
        self.stdout.write(
            self.style.SUCCESS(
                f"Utilisateur {action} avec succès :\n"
                f"  - Email : {email}\n"
                f"  - Mot de passe : {password}\n"
                f"  - Profil : {user.get_profile_display()} ({'Aptitude' if user.is_aptitude else 'Client'})\n"
                f"  - Organisation : {org.name}"
            )
        )

