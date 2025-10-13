from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("ping/", views.ping, name="ping"),
    path("medicamentos/", views.medicamentos, name="medicamentos"),
]
