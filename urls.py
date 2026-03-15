from django.urls import path
from . import views

urlpatterns = [
    path('<str:project_id>/generate', views.generate_report_view),
    path('<str:project_id>/', views.get_report_view),
]
