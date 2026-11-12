"""Sépare le rôle commercial de l'organisation et son statut d'opérateur.

L'ancien type « Aptitude » devient un vendeur (code « client ») marqué opérateur de la
plateforme : Aptitude peut ainsi vendre en direct à ses propres clients finaux.
"""
from django.db import migrations, models


def aptitude_to_operator(apps, schema_editor):
    Organisation = apps.get_model("accounts", "Organisation")
    Organisation.objects.filter(kind="aptitude").update(kind="client", is_operator=True)


def operator_to_aptitude(apps, schema_editor):
    Organisation = apps.get_model("accounts", "Organisation")
    Organisation.objects.filter(is_operator=True).update(kind="aptitude", is_operator=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_job_title_brand_color"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="is_operator",
            field=models.BooleanField(
                default=False, editable=False,
                help_text="Aptitude : ses comptes forment l'équipe interne. Une seule organisation l'est.",
                verbose_name="opérateur de la plateforme"),
        ),
        migrations.RunPython(aptitude_to_operator, operator_to_aptitude),
        migrations.AddConstraint(
            model_name="organisation",
            constraint=models.UniqueConstraint(condition=models.Q(is_operator=True), fields=["is_operator"],
                                               name="single_platform_operator"),
        ),
    ]
