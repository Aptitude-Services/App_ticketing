from django.urls import path

from . import views

urlpatterns = [
    path("rapport/<int:pk>/", views.report_detail, name="report_detail"),
    path("rapport/<int:pk>/modifier/", views.report_edit, name="report_edit"),
    path("rapport/<int:pk>/<slug:action>/", views.report_action, name="report_action"),
    path("<slug:kind>/", views.report_list, name="report"),
    path("<slug:kind>/nouveau/", views.report_create, name="report_create"),
]
