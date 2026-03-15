from django.urls import path

from .views import LoginView, MeView


urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('v1/auth/login/', LoginView.as_view(), name='auth-login-v1'),
    path('auth/me/', MeView.as_view(), name='auth-me'),
]