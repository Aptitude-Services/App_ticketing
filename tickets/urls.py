from django.urls import path

from . import views

urlpatterns = [
    path("", views.ticket_list, name="ticket_list"),
    path("nouveau/", views.ticket_create, name="ticket_create"),
    path("<str:ref>/", views.ticket_detail, name="ticket_detail"),
    path("<str:ref>/suivi/", views.ticket_comment, name="ticket_comment"),
    path("<str:ref>/statut/", views.ticket_status, name="ticket_status"),
    path("<str:ref>/priorite/", views.ticket_priority, name="ticket_priority"),
    path("<str:ref>/assignation/", views.ticket_assign, name="ticket_assign"),
    path("<str:ref>/escalade/", views.ticket_escalate, name="ticket_escalate"),
    path("<str:ref>/pieces-jointes/<int:pk>/", views.attachment_download, name="attachment_download"),
]
