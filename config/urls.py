from django.contrib import admin
from django.urls import include, path

from core.mail_views import mail_settings, mail_test
from core.report_views import report
from core.views import dashboard

admin.site.site_header = "Aptitude Support — administration"
admin.site.site_title = "Aptitude Support"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("compte/", include("accounts.urls")),
    path("contrats/", include("contracts.urls")),
    path("tickets/", include("tickets.urls")),
    path("rapports/<slug:kind>/", report, name="report"),
    path("configuration/messagerie/", mail_settings, name="mail_settings"),
    path("configuration/messagerie/test/", mail_test, name="mail_test"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("gestion/", admin.site.urls),
]
