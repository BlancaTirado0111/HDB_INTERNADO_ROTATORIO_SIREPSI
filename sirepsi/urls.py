# sirepsi/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("ping/", views.ping, name="ping"),
    path("medicamentos/", views.medicamentos, name="medicamentos"),
    path("movimientos/", views.movimientos_kardex, name="movimientos"),
    path("prescripciones/", views.prescripciones, name="prescripciones"),
    path("meds-suggest/", views.meds_suggest, name="meds_suggest"),
    path("movimientos/kardex/export/csv/",  views.export_kardex_csv,  name="kardex_export_csv"),
    path("movimientos/kardex/export/xlsx/", views.export_kardex_xlsx, name="kardex_export_xlsx"),
]
