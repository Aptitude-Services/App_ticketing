import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MailSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(choices=[("env", "Paramètres du serveur (fichier .env)"), ("smtp", "Serveur SMTP"), ("graph", "Microsoft 365 (API Graph)"), ("off", "Désactivé (aucun envoi, journal seulement)")], default="env", max_length=10, verbose_name="mode d'envoi")),
                ("from_email", models.CharField(blank=True, help_text="Ex. Aptitude Support <support@aptitudes.net>. Vide : DEFAULT_FROM_EMAIL du serveur.", max_length=254, verbose_name="expéditeur")),
                ("reply_to", models.EmailField(blank=True, max_length=254, verbose_name="adresse de réponse")),
                ("smtp_host", models.CharField(blank=True, max_length=255, verbose_name="serveur SMTP")),
                ("smtp_port", models.PositiveIntegerField(default=587, verbose_name="port")),
                ("smtp_security", models.CharField(choices=[("starttls", "STARTTLS (port 587)"), ("ssl", "SSL/TLS implicite (port 465)"), ("none", "Aucun chiffrement (relais interne uniquement)")], default="starttls", max_length=10, verbose_name="chiffrement")),
                ("smtp_username", models.CharField(blank=True, max_length=254, verbose_name="identifiant")),
                ("smtp_password_encrypted", models.TextField(blank=True, editable=False)),
                ("graph_tenant_id", models.CharField(blank=True, max_length=100, verbose_name="ID de locataire (tenant)")),
                ("graph_client_id", models.CharField(blank=True, max_length=100, verbose_name="ID d'application (client)")),
                ("graph_client_secret_encrypted", models.TextField(blank=True, editable=False)),
                ("graph_sender", models.EmailField(blank=True, help_text="Vide : l'adresse de l'expéditeur.", max_length=254, verbose_name="boîte d'envoi")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "configuration de la messagerie",
                "verbose_name_plural": "configuration de la messagerie",
            },
        ),
        migrations.CreateModel(
            name="OutgoingMail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("provider", models.CharField(choices=[("env", "Paramètres du serveur (fichier .env)"), ("smtp", "Serveur SMTP"), ("graph", "Microsoft 365 (API Graph)"), ("off", "Désactivé (aucun envoi, journal seulement)")], max_length=10, verbose_name="mode d'envoi")),
                ("sender", models.CharField(max_length=254, verbose_name="expéditeur")),
                ("recipients", models.TextField(verbose_name="destinataires")),
                ("subject", models.CharField(max_length=500, verbose_name="sujet")),
                ("status", models.CharField(choices=[("sent", "Envoyé"), ("failed", "Échec"), ("skipped", "Non envoyé (messagerie désactivée)")], max_length=10, verbose_name="statut")),
                ("error", models.TextField(blank=True, verbose_name="erreur")),
            ],
            options={
                "verbose_name": "email envoyé",
                "verbose_name_plural": "journal des emails",
                "ordering": ["-created_at"],
            },
        ),
    ]
