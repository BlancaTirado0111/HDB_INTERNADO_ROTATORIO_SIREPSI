# sirepsi/views.py
from django.shortcuts import render
from .dbutils import query_bdfarmacia

def home(request):
    return render(request, "home.html")

def ping(request):
    return render(request, "base.html", {"content": "pong"})

def medicamentos(request):
    sql = """
        SELECT
            m.MED_CODIGO         AS codigo,
            m.MED_CODIFICACION   AS codificacion,
            m.MED_COMERCIAL      AS nombre,
            m.med_generico       AS dci,
            m.med_concentracion  AS concentracion,
            m.med_unidad         AS presentacion,
            p.PRO_NOMBRE         AS laboratorio
        FROM dbo.fa_medicamento m
        LEFT JOIN dbo.fa_proveedor p
               ON p.Emp_Codigo = m.emp_codigo
        WHERE m.MED_CODIFICACION IN (
            'N0501','N0306','N0312','N0504','N0505',
            'N0309','N0310','N0311','N0105','N0106',
            'N0511','N0226','N0227','N0116'
        )
        ORDER BY nombre;
    """
    filas = query_bdfarmacia(sql, None)   # <- explícito
    for f in filas:
        f["origen"] = ""
    return render(request, "medicamentos/lista.html", {"filas": filas})
