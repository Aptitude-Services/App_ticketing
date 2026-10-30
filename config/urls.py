from django.contrib import admin
from django.urls import include, path

from core.views import dashboard

admin.site.site_header = "Aptitude Support — administration"
admin.site.site_title = "Aptitude Support"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("compte/", include("accounts.urls")),
    path("contrats/", include("contracts.urls")),
    path("tickets/", include("tickets.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
    path("gestion/", admin.site.urls),
]
