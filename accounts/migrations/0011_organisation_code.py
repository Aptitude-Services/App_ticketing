"""Code court des organisations (ex. HUD, BLAG), repris dans les références de contrat.

Ajouté sans contrainte, rempli depuis le nom pour les organisations existantes,
puis rendu unique.
"""
from django.db import migrations, models


def fill_codes(apps, schema_editor):
    from accounts.codes import suggest_code

    Organisation = apps.get_model("accounts", "Organisation")
    taken = set()
    for org in Organisation.objects.order_by("created_at", "pk"):
        org.code = suggest_code(org.name, taken)
        taken.add(org.code)
        org.save(update_fields=["code"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_organisation_activity_sectors"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="code",
            field=models.CharField(blank=True, default="", max_length=8, verbose_name="code"),
            preserve_default=False,
        ),
        migrations.RunPython(fill_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="organisation",
            name="code",
            field=models.CharField(
                blank=True, max_length=8, unique=True, verbose_name="code",
                help_text="2 à 8 lettres ou chiffres, repris dans les références de contrat (ex. HUD). "
                          "Vide : calculé depuis le nom.",
            ),
        ),
    ]
