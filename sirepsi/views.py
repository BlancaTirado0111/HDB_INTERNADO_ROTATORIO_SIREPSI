# sirepsi/views.py
from datetime import datetime, date, timedelta
from io import BytesIO
import csv

from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render

# XLSX opcional con openpyxl (si no está, igual funciona el CSV)
try:
    import openpyxl
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Font
    HAS_OPENPYXL = True
except Exception:
    HAS_OPENPYXL = False

from .dbutils import (
    query_bdfarmacia,
    kardex_encabezado,
    kardex_detalle,
    prescripciones_detalle,   # <-- asegúrate de tener esta función en dbutils.py
)

# ===================== HOME / UTILES =====================

def home(request):
    return render(request, "home.html")


def ping(request):
    return render(request, "base.html", {"content": "pong"})


def _page_window(page_obj, window: int = 2):
    """
    Devuelve una lista con números de página y None donde van los '…'
    Ej.: [1, None, 8, 9, 10, 11, 12, None, 50]
    """
    current = page_obj.number
    total = page_obj.paginator.num_pages

    pages = {1, total}

    for p in range(current - window, current + window + 1):
        if 1 <= p <= total:
            pages.add(p)

    for p in range(2, min(2 + window, total)):
        pages.add(p)
    for p in range(max(total - window + 1, 1), total):
        pages.add(p)

    pages = sorted(pages)

    compact, prev = [], None
    for p in pages:
        if prev is not None and p != prev + 1:
            compact.append(None)
        compact.append(p)
        prev = p
    return compact


# ===================== MEDICAMENTOS (LISTA) =====================

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
    filas = query_bdfarmacia(sql, None)

    paginator = Paginator(filas, 40)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "pages_compact": _page_window(page_obj, window=2),
    }
    return render(request, "medicamentos/lista.html", context)


# ===================== MOVIMIENTOS (KARDEX) =====================

# Lista base (para el modal/autocomplete)
PSYCH_LIST = [
    ("N0501", "Alprazolam"),
    ("N0306", "Clonazepam"),
    ("N0312", "Clonazepam"),
    ("N0504", "Diazepam"),
    ("N0505", "Diazepam"),
    ("N0309", "Fenobarbital"),
    ("N0310", "Fenobarbital"),
    ("N0311", "Fenobarbital"),
    ("N0105", "Fentanilo con conservante"),
    ("N0106", "Fentanilo sin conservante"),
    ("N0511", "Midazolam"),
    ("N0206", "Morfina"),
    ("N0207", "Morfina (con o sin conservante)"),
    ("N0116", "Remifentanilo"),
]

# Almacén por defecto (ajústalo si hace falta)
DEFAULT_ALMACEN = 31


def meds_suggest(request):
    """
    API para el modal/autocomplete: devuelve hasta 20 medicamentos de la lista base,
    filtrados por 'q' (contiene en código o nombre, case-insensitive).
    """
    q = (request.GET.get("q") or "").strip().lower()
    results = []
    for code, name in PSYCH_LIST:
        if not q or (q in code.lower()) or (q in name.lower()):
            results.append({"code": code, "label": f"{code} — {name}"})
        if len(results) >= 20:
            break
    return JsonResponse({"results": results})


def _resolve_med_by_name_or_code(name_or_code: str):
    """
    1) Intenta contra la lista base: si coincide por nombre (contiene) o código exacto,
       busca el medicamento por MED_CODIFICACION.
    2) Si no, intenta por nombre (LIKE %nombre%) en MED_COMERCIAL o MED_GENERICO.
    Devuelve dict con: med_codigo, codificacion, nombre, dci, concentracion, presentacion, laboratorio.
    """
    q = (name_or_code or "").strip()
    if not q:
        return None

    pick_code = None
    for code, name in PSYCH_LIST:
        if q.lower() in name.lower() or q.upper() == code.upper():
            pick_code = code
            break

    if pick_code:
        sql = """
            SELECT TOP(1)
              m.MED_CODIGO         AS med_codigo,
              m.MED_CODIFICACION   AS codificacion,
              m.MED_COMERCIAL      AS nombre,
              m.med_generico       AS dci,
              m.med_concentracion  AS concentracion,
              m.med_unidad         AS presentacion,
              p.PRO_NOMBRE         AS laboratorio
            FROM dbo.fa_medicamento m
            LEFT JOIN dbo.fa_proveedor p ON p.Emp_Codigo = m.emp_codigo
            WHERE m.MED_CODIFICACION = %s
        """
        rows = query_bdfarmacia(sql, [pick_code])
        if rows:
            return rows[0]

    sql = """
        SELECT TOP(1)
          m.MED_CODIGO         AS med_codigo,
          m.MED_CODIFICACION   AS codificacion,
          m.MED_COMERCIAL      AS nombre,
          m.med_generico       AS dci,
          m.med_concentracion  AS concentracion,
          m.med_unidad         AS presentacion,
          p.PRO_NOMBRE         AS laboratorio
        FROM dbo.fa_medicamento m
        LEFT JOIN dbo.fa_proveedor p ON p.Emp_Codigo = m.emp_codigo
        WHERE     m.MED_COMERCIAL LIKE %s
            OR    m.MED_GENERICO  LIKE %s
        ORDER BY LEN(m.MED_COMERCIAL), m.MED_COMERCIAL
    """
    rows = query_bdfarmacia(sql, [f"%{q}%", f"%{q}%"])
    return rows[0] if rows else None


def movimientos_kardex(request):
    """
    Formulario: medicamento (obligatorio), desde (obligatorio), hasta (obligatorio).
    Usa DEFAULT_ALMACEN por ahora.
    """
    q = (request.GET.get("q") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    ctx = {
        "q": q,
        "desde": desde,
        "hasta": hasta,
        "encabezado": None,
        "rows": [],
        "error": "",
        "saldo_inicial": 0,
        "sum_ingresos": 0,
        "sum_egresos": 0,
        "saldo_final": 0,
        "total_movs": 0,
    }

    # Pantalla vacía si no hay búsqueda
    if not (q or desde or hasta):
        return render(request, "movimientos/kardex.html", ctx)

    # Validaciones UX
    if len(q) < 3:
        ctx["error"] = "Escribe al menos 3 letras del nombre del medicamento."
        return render(request, "movimientos/kardex.html", ctx)

    try:
        d_desde = datetime.strptime(desde, "%Y-%m-%d").date()
        d_hasta = datetime.strptime(hasta, "%Y-%m-%d").date()
    except Exception:
        ctx["error"] = "Fechas inválidas. Usa el selector de fechas."
        return render(request, "movimientos/kardex.html", ctx)

    if d_hasta < d_desde:
        ctx["error"] = "La fecha hasta debe ser mayor o igual a la fecha desde."
        return render(request, "movimientos/kardex.html", ctx)

    # Resolver medicamento
    med = _resolve_med_by_name_or_code(q)
    if not med:
        ctx["error"] = "No se encontró un medicamento con ese nombre."
        return render(request, "movimientos/kardex.html", ctx)

    # Encabezado + detalle (con Paciente y Médico)
    enc = kardex_encabezado(med["med_codigo"])
    rows = kardex_detalle(
        med_codigo=med["med_codigo"],
        almacen=DEFAULT_ALMACEN,
        fecha_desde=d_desde,
        fecha_hasta=d_hasta
    )

    # Totales
    sum_ing = sum(float(r.get("cantidad_ingreso") or 0) for r in rows)
    sum_egr = sum(float(r.get("cantidad_egreso") or 0) for r in rows)
    saldo_ini = float(rows[0]["saldo_anterior"]) if rows else 0.0
    saldo_fin = float(rows[-1]["saldo_actual"]) if rows else saldo_ini

    ctx.update({
        "q": enc["nombre_del_producto"] if enc else med["nombre"],
        "encabezado": {
            "nombre":        enc["nombre_del_producto"] if enc else med["nombre"],
            "dci":           enc["dci"] if enc else med["dci"],
            "concentracion": enc["concentracion"] if enc else med["concentracion"],
            "presentacion":  enc["presentacion"] if enc else med["presentacion"],
            "laboratorio":   enc["laboratorio"] if enc else None,
        },
        "rows": rows,
        "saldo_inicial": saldo_ini,
        "sum_ingresos":  sum_ing,
        "sum_egresos":   sum_egr,
        "saldo_final":   saldo_fin,
        "total_movs":    len(rows),
    })
    return render(request, "movimientos/kardex.html", ctx)


# ===================== PRESCRIPCIONES =====================

def prescripciones(request):
    """
    Busca por medicamento + rango, y lista solo Paciente / Médico / Nº Receta / Fecha / Obs.
    """
    q = (request.GET.get("q") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    ctx = {
        "q": q,
        "desde": desde,
        "hasta": hasta,
        "encabezado": None,
        "rows": [],
        "error": "",
        "total_presc": 0,
        "pacientes_unicos": 0,
        "medicos_unicos": 0,
    }

    # pantalla vacía
    if not (q or desde or hasta):
        return render(request, "prescripciones/lista.html", ctx)

    if len(q) < 3:
        ctx["error"] = "Escribe al menos 3 letras del nombre del medicamento."
        return render(request, "prescripciones/lista.html", ctx)

    try:
        d_desde = datetime.strptime(desde, "%Y-%m-%d").date()
        d_hasta = datetime.strptime(hasta, "%Y-%m-%d").date()
    except Exception:
        ctx["error"] = "Fechas inválidas. Usa el selector de fechas."
        return render(request, "prescripciones/lista.html", ctx)

    if d_hasta < d_desde:
        ctx["error"] = "La fecha hasta debe ser mayor o igual a la fecha desde."
        return render(request, "prescripciones/lista.html", ctx)

    med = _resolve_med_by_name_or_code(q)
    if not med:
        ctx["error"] = "No se encontró un medicamento con ese nombre."
        return render(request, "prescripciones/lista.html", ctx)

    enc = kardex_encabezado(med["med_codigo"])
    rows = prescripciones_detalle(
        med_codigo=med["med_codigo"],
        almacen=DEFAULT_ALMACEN,
        fecha_desde=d_desde,
        fecha_hasta=d_hasta
    )

    total = len(rows)
    pacientes = len({(r.get("nombre_paciente") or "").strip() for r in rows if (r.get("nombre_paciente") or "").strip()})
    medicos = len({(r.get("nombre_medico") or "").strip() for r in rows if (r.get("nombre_medico") or "").strip()})

    ctx.update({
        "q": enc["nombre_del_producto"] if enc else med["nombre"],
        "encabezado": {
            "nombre":        enc["nombre_del_producto"] if enc else med["nombre"],
            "dci":           enc["dci"] if enc else med["dci"],
            "concentracion": enc["concentracion"] if enc else med["concentracion"],
            "presentacion":  enc["presentacion"] if enc else med["presentacion"],
            "laboratorio":   enc["laboratorio"] if enc else None,
        },
        "rows": rows,
        "total_presc": total,
        "pacientes_unicos": pacientes,
        "medicos_unicos": medicos,
    })
    return render(request, "prescripciones/lista.html", ctx)


# ===================== EXPORTS (CSV / XLSX) =====================

def _resolver_kardex_dataset(request):
    """
    Reusa la misma lógica de la vista para armar dataset para export.
    GET: q, desde (YYYY-MM-DD), hasta (YYYY-MM-DD), alm (opcional)
    Devuelve: (encabezado, rows, d_desde, d_hasta, alm)
    """
    q = (request.GET.get("q") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()
    alm = request.GET.get("alm")

    if not q:
        raise ValueError("Falta el nombre del medicamento")
    try:
        d_desde = datetime.strptime(desde, "%Y-%m-%d").date()
        d_hasta = datetime.strptime(hasta, "%Y-%m-%d").date()
    except Exception:
        raise ValueError("Fechas inválidas. Usa el formato YYYY-MM-DD.")

    med = _resolve_med_by_name_or_code(q)
    if not med:
        raise ValueError("No se encontró el medicamento")

    try:
        alm = int(alm) if alm not in (None, "", "null") else DEFAULT_ALMACEN
    except Exception:
        alm = DEFAULT_ALMACEN

    enc = kardex_encabezado(med["med_codigo"])
    rows = kardex_detalle(
        med_codigo=med["med_codigo"],
        almacen=alm,
        fecha_desde=d_desde,
        fecha_hasta=d_hasta
    )
    return enc or {}, rows, d_desde, d_hasta, alm


def export_kardex_csv(request):
    """Exporta el Kardex a CSV (Excel-friendly: UTF-8 BOM + CRLF)."""
    try:
        enc, rows, d_desde, d_hasta, alm = _resolver_kardex_dataset(request)
    except Exception as e:
        return HttpResponse(f"Error: {e}", status=400, content_type="text/plain; charset=utf-8")

    base = enc.get("nombre_del_producto", "medicamento")
    safe = "".join(ch for ch in base if ch.isalnum() or ch in ("_", "-", ".")).strip() or "medicamento"
    filename = f"Kardex_{safe}_{d_desde}_{d_hasta}.csv"

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'

    # BOM para que Excel detecte UTF-8
    resp.write("\ufeff")

    w = csv.writer(resp, lineterminator="\r\n")

    w.writerow(["KARDEX"])
    w.writerow([f"Producto: {enc.get('nombre_del_producto','')}"])
    w.writerow([f"DCI: {enc.get('dci','')}"])
    w.writerow([f"Concentración: {enc.get('concentracion','')}"])
    w.writerow([f"Presentación: {enc.get('presentacion','')}"])
    w.writerow([f"Laboratorio: {enc.get('laboratorio','')}"])
    w.writerow([f"Rango: {d_desde} a {d_hasta}"])
    w.writerow([])

    w.writerow([
        "Fecha", "Cantidad Ingreso", "Nombre Paciente", "Nombre Médico",
        "No Receta", "Cantidad Egreso", "Saldo Anterior", "Saldo Actual", "Observaciones"
    ])

    for r in rows:
        w.writerow([
            r.get("fecha", ""),
            r.get("cantidad_ingreso", ""),
            r.get("nombre_paciente", ""),
            r.get("nombre_medico", ""),
            r.get("no_receta", ""),
            r.get("cantidad_egreso", ""),
            r.get("saldo_anterior", ""),
            r.get("saldo_actual", ""),
            (r.get("observaciones", "") or "").replace("\r", " ").replace("\n", " "),
        ])

    return resp


def export_kardex_xlsx(request):
    """Exporta el Kardex a XLSX con openpyxl."""
    if not HAS_OPENPYXL:
        return HttpResponse(
            "Para exportar a XLSX instala openpyxl: pip install openpyxl\n"
            "Alternativa inmediata: usa 'Exportar CSV (Excel)'.",
            status=501,
            content_type="text/plain; charset=utf-8",
        )

    try:
        enc, rows, d_desde, d_hasta, alm = _resolver_kardex_dataset(request)
    except Exception as e:
        return HttpResponse(f"Error: {e}", status=400, content_type="text/plain; charset=utf-8")

    base = enc.get("nombre_del_producto", "medicamento")
    safe = "".join(ch for ch in base if ch.isalnum() or ch in ("_", "-", ".")).strip() or "medicamento"
    filename = f"Kardex_{safe}_{d_desde}_{d_hasta}.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Kardex"

    ws["A1"] = "KARDEX"
    ws["A2"] = f"Producto: {enc.get('nombre_del_producto','')}"
    ws["A3"] = f"DCI: {enc.get('dci','')}"
    ws["A4"] = f"Concentración: {enc.get('concentracion','')}"
    ws["A5"] = f"Presentación: {enc.get('presentacion','')}"
    ws["A6"] = f"Laboratorio: {enc.get('laboratorio','')}"
    ws["A7"] = f"Rango: {d_desde} a {d_hasta}"

    ws.append([""])  # fila 8
    headers = ["Fecha", "Cantidad Ingreso", "Nombre Paciente", "Nombre Médico",
               "No Receta", "Cantidad Egreso", "Saldo Anterior", "Saldo Actual", "Observaciones"]
    ws.append(headers)  # fila 9

    for r in rows:
        ws.append([
            r.get("fecha", ""),
            r.get("cantidad_ingreso", 0),
            r.get("nombre_paciente", ""),
            r.get("nombre_medico", ""),
            r.get("no_receta", ""),
            r.get("cantidad_egreso", 0),
            r.get("saldo_anterior", 0),
            r.get("saldo_actual", 0),
            r.get("observaciones", ""),
        ])

    # Formato: negrita en la fila de encabezados + ancho
    for cell in ws["A9":"I9"][0]:
        cell.font = Font(bold=True)
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 18

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    resp = HttpResponse(
        bio.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
