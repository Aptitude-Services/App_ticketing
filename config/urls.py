from django.contrib import admin
from django.urls import include, path

from core.mail_views import mail_settings, mail_test
from core.notification_views import (notification_list, notification_open, notification_panel,
                                     notification_read_all)
from core.pwa_views import manifest, offline, service_worker
from core.views import dashboard

admin.site.site_header = "Aptitude Support — administration"
admin.site.site_title = "Aptitude Support"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("manifest.webmanifest", manifest, name="pwa_manifest"),
    path("sw.js", service_worker, name="service_worker"),
    path("hors-ligne/", offline, name="offline"),
    path("compte/", include("accounts.urls")),
    path("contrats/", include("contracts.urls")),
    path("tickets/", include("tickets.urls")),
    path("rapports/", include("reports.urls")),
    path("notifications/", notification_list, name="notifications"),
    path("notifications/panneau/", notification_panel, name="notification_panel"),
    path("notifications/tout-lu/", notification_read_all, name="notification_read_all"),
    path("notifications/<int:pk>/", notification_open, name="notification_open"),
    path("configuration/messagerie/", mail_settings, name="mail_settings"),
    path("configuration/messagerie/test/", mail_test, name="mail_test"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("gestion/", admin.site.urls),
]
