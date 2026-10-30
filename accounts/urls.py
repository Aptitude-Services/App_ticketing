from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("connexion/", auth_views.LoginView.as_view(authentication_form=LoginForm, redirect_authenticated_user=True), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("mot-de-passe/oubli/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("mot-de-passe/oubli/envoye/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("mot-de-passe/definir/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("mot-de-passe/termine/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("mot-de-passe/changer/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("mot-de-passe/change/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("mfa/activation/", views.mfa_setup, name="mfa_setup"),
    path("mfa/verification/", views.mfa_verify, name="mfa_verify"),
    path("profil/", views.my_profile, name="my_profile"),
    path("theme/", views.set_theme, name="set_theme"),
    path("utilisateurs/", views.user_list, name="user_list"),
    path("utilisateurs/nouveau/", views.user_create, name="user_create"),
    path("utilisateurs/<int:pk>/", views.user_update, name="user_update"),
]
