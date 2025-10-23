# sirepsi/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("ping/", views.ping, name="ping"),
    path("medicamentos/", views.medicamentos, name="medicamentos"),

    # Movimientos (Kardex)
    path("movimientos/", views.movimientos_kardex, name="movimientos"),

    # Endpoint de autocompletado (¡ojo con el name!)
    path("meds-suggest/", views.meds_suggest, name="meds_suggest"),
]
