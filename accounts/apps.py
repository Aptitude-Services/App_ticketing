from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Comptes et organisations"

    def ready(self):
        from . import audit  # noqa: F401  (branche les signaux d'audit)
