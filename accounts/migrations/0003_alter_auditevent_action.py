from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_theme"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("login", "Connexion"),
                    ("login_failed", "Échec de connexion"),
                    ("logout", "Déconnexion"),
                    ("user_created", "Utilisateur créé"),
                    ("user_updated", "Utilisateur modifié"),
                    ("mfa_enabled", "MFA activée"),
                    ("mail_settings_updated", "Messagerie modifiée"),
                ],
                max_length=30,
            ),
        ),
    ]
