# sirepsi/views.py
from __future__ import annotations

from datetime import datetime
from io import BytesIO
import csv
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

# XLSX opcional con openpyxl (si no está, igual funciona el CSV)
try:
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    HAS_OPENPYXL = True
except Exception:
    HAS_OPENPYXL = False

from .dbutils import (
    kardex_detalle,
    kardex_encabezado,
    prescripciones_detalle,
    query_bdfarmacia,
)

# ===================== HOME / UTILES =====================


def home(request):
    """Vista de inicio del sistema."""
    return render(request, "home.html")


def ping(request):
    """Health-check sencillo para supervisión básica."""
    return render(request, "base.html", {"content": "pong"})


def _page_window(page_obj, window: int = 2) -> List[Optional[int]]:
    """
    Devuelve una lista con números de página y None donde van los '…'.
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

    compact: List[Optional[int]] = []
    prev: Optional[int] = None
    for p in pages:
        if prev is not None and p != prev + 1:
            compact.append(None)
        compact.append(p)
        prev = p
    return compact


# ===================== MEDICAMENTOS (LISTA) =====================


def medicamentos(request):
    """
    Lista paginada (40 por página) de medicamentos psicotrópicos
    con filtros por texto, laboratorio, presentación y orden dinámico.
    GET:
      - q     : texto libre (nombre, DCI, código, codificación)
      - lab   : nombre exacto de laboratorio
      - pres  : presentación exacta
      - order : nombre | codigo | codificacion | lab
    """
    q = (request.GET.get("q") or "").strip()
    lab = (request.GET.get("lab") or "").strip()
    pres = (request.GET.get("pres") or "").strip()
    order = (request.GET.get("order") or "nombre").lower()

    # 1) WHERE base: solo los psicotrópicos
    base_where = """
        m.MED_CODIFICACION IN (
            'N0501','N0306','N0312','N0504','N0505',
            'N0309','N0310','N0311','N0105','N0106',
            'N0511','N0226','N0227','N0116'
        )
    """

    # 2) Valores únicos para combos (laboratorio/presentación)
    sql_choices = f"""
        SELECT DISTINCT
            RTRIM(ISNULL(p.PRO_NOMBRE,''))  AS laboratorio,
            RTRIM(ISNULL(m.med_unidad,'')) AS presentacion
        FROM dbo.fa_medicamento m
        LEFT JOIN dbo.fa_proveedor p
               ON p.Emp_Codigo = m.emp_codigo
        WHERE {base_where}
    """
    choice_rows = query_bdfarmacia(sql_choices, None)

    laboratorios = sorted(
        {
            (row.get("laboratorio") or "").strip()
            for row in choice_rows
            if (row.get("laboratorio") or "").strip()
        }
    )
    presentaciones = sorted(
        {
            (row.get("presentacion") or "").strip()
            for row in choice_rows
            if (row.get("presentacion") or "").strip()
        }
    )

    # 3) Consulta principal con filtros dinámicos
    sql = f"""
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
        WHERE {base_where}
    """

    where_clauses: List[str] = []
    params: List[Any] = []

    # 3.1 Texto libre
    if q:
        like = f"%{q}%"
        where_clauses.append(
            "("
            "m.MED_COMERCIAL    LIKE %s OR "
            "m.med_generico     LIKE %s OR "
            "m.MED_CODIGO       LIKE %s OR "
            "m.MED_CODIFICACION LIKE %s"
            ")"
        )
        params.extend([like, like, like, like])

    # 3.2 Laboratorio
    if lab:
        where_clauses.append("p.PRO_NOMBRE = %s")
        params.append(lab)

    # 3.3 Presentación
    if pres:
        where_clauses.append("m.med_unidad = %s")
        params.append(pres)

    if where_clauses:
        sql += " AND " + " AND ".join(where_clauses)

    # 4) Orden dinámico (evitando columnas duplicadas en ORDER BY)
    order_map: Dict[str, List[str]] = {
        "nombre": ["m.MED_COMERCIAL", "m.med_generico"],
        "codigo": ["m.MED_CODIGO"],
        "codificacion": ["m.MED_CODIFICACION", "m.MED_COMERCIAL"],
        "lab": ["p.PRO_NOMBRE", "m.MED_COMERCIAL"],
    }
    order_parts = order_map.get(order, order_map["nombre"])
    order_parts = order_parts + ["m.MED_CODIGO"]  # orden estable

    seen: set[str] = set()
    unique_order_parts: List[str] = []
    for part in order_parts:
        if part not in seen:
            unique_order_parts.append(part)
            seen.add(part)

    sql += " ORDER BY " + ", ".join(unique_order_parts)

    # 5) Ejecutar y paginar
    filas = query_bdfarmacia(sql, params or None)

    paginator = Paginator(filas, 40)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    no_results_message = ""
    if (q or lab or pres) and paginator.count == 0:
        no_results_message = "No hay existencias para esta combinación de filtros."

    # 6) Querystring para mantener filtros en la paginación
    qs_params: Dict[str, str] = {}
    if q:
        qs_params["q"] = q
    if lab:
        qs_params["lab"] = lab
    if pres:
        qs_params["pres"] = pres
    if order:
        qs_params["order"] = order

    querystring = "&" + urlencode(qs_params) if qs_params else ""

    context = {
        "page_obj": page_obj,
        "pages_compact": _page_window(page_obj, window=2),
        "q": q,
        "lab": lab,
        "pres": pres,
        "order": order,
        "laboratorios": laboratorios,
        "presentaciones": presentaciones,
        "total": paginator.count,
        "no_results_message": no_results_message,
        "querystring": querystring,
    }
    return render(request, "medicamentos/lista.html", context)


# ===================== MOVIMIENTOS (KARDEX) =====================

PSYCH_LIST: List[Tuple[str, str]] = [
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

# (No se usan por ahora, pero las dejamos por si reactivas el filtro por tipo)
MED_TYPES_CHOICES = [
    ("benzo", "Benzodiacepinas"),
    ("barbiturico", "Barbitúricos"),
    ("opioide", "Opioides"),
]

MED_TYPES_CODES = {
    "benzo": {"N0501", "N0306", "N0312", "N0504", "N0505", "N0511"},
    "barbiturico": {"N0309", "N0310", "N0311"},
    "opioide": {"N0105", "N0106", "N0206", "N0207", "N0116"},
}

DEFAULT_ALMACEN: int = 31


def meds_suggest(request):
    """Autocomplete para medicamentos (kardex/prescripciones)."""
    q = (request.GET.get("q") or "").strip().lower()
    results: List[Dict[str, str]] = []

    for code, name in PSYCH_LIST:
        if not q or (q in code.lower()) or (q in name.lower()):
            results.append({"code": code, "label": f"{code} — {name}"})
        if len(results) >= 20:
            break

    return JsonResponse({"results": results})


def _resolve_med_by_name_or_code(name_or_code: str) -> Optional[Dict[str, Any]]:
    """
    Resuelve un medicamento a partir de nombre o código.
    Retorna dict con:
      med_codigo, codificacion, nombre, dci, concentracion, presentacion, laboratorio
    """
    q = (name_or_code or "").strip()
    if not q:
        return None

    pick_code: Optional[str] = None
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
    Vista Kardex: movimientos por medicamento y rango de fechas.
    """
    q = (request.GET.get("q") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    ctx: Dict[str, Any] = {
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

    if not (q or desde or hasta):
        return render(request, "movimientos/kardex.html", ctx)

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

    med = _resolve_med_by_name_or_code(q)
    if not med:
        ctx["error"] = "No se encontró un medicamento con ese nombre."
        return render(request, "movimientos/kardex.html", ctx)

    cache_key = (
        f"kardex:{DEFAULT_ALMACEN}:{med['med_codigo']}:"
        f"{d_desde.isoformat()}:{d_hasta.isoformat()}"
    )
    data = cache.get(cache_key)
    if data is None:
        enc = kardex_encabezado(med["med_codigo"])
        rows = kardex_detalle(
            med_codigo=med["med_codigo"],
            almacen=DEFAULT_ALMACEN,
            fecha_desde=d_desde,
            fecha_hasta=d_hasta,
        )
        cache.set(cache_key, (enc, rows), 300)
    else:
        enc, rows = data

    sum_ing = sum(float(r.get("cantidad_ingreso") or 0) for r in rows)
    sum_egr = sum(float(r.get("cantidad_egreso") or 0) for r in rows)
    saldo_ini = float(rows[0]["saldo_anterior"]) if rows else 0.0
    saldo_fin = float(rows[-1]["saldo_actual"]) if rows else saldo_ini

    ctx.update(
        {
            "q": enc["nombre_del_producto"] if enc else med["nombre"],
            "encabezado": {
                "nombre": enc["nombre_del_producto"] if enc else med["nombre"],
                "dci": enc["dci"] if enc else med["dci"],
                "concentracion": enc["concentracion"] if enc else med["concentracion"],
                "presentacion": enc["presentacion"] if enc else med["presentacion"],
                "laboratorio": enc["laboratorio"] if enc else None,
            },
            "rows": rows,
            "saldo_inicial": saldo_ini,
            "sum_ingresos": sum_ing,
            "sum_egresos": sum_egr,
            "saldo_final": saldo_fin,
            "total_movs": len(rows),
        }
    )
    return render(request, "movimientos/kardex.html", ctx)


# ===================== PRESCRIPCIONES =====================


def prescripciones(request):
    """
    Lista de prescripciones por medicamento y rango de fechas.
    Nuevo: filtro opcional por nombre de médico (desde un combo).
    """
    q = (request.GET.get("q") or "").strip()
    medico = (request.GET.get("medico") or "").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()

    ctx: Dict[str, Any] = {
        "q": q,
        "medico": medico,
        "desde": desde,
        "hasta": hasta,
        "encabezado": None,
        "rows": [],
        "error": "",
        "total_presc": 0,
        "pacientes_unicos": 0,
        "medicos_unicos": 0,
        "medicos_disponibles": [],   # 👈 importante para el combo
    }

    # Pantalla vacía
    if not (q or desde or hasta):
        return render(request, "prescripciones/lista.html", ctx)

    if len(q) < 3:
        ctx["error"] = "Escribe al menos 3 letras del nombre del medicamento."
        return render(request, "prescripciones/lista.html", ctx)

    # Fechas
    try:
        d_desde = datetime.strptime(desde, "%Y-%m-%d").date()
        d_hasta = datetime.strptime(hasta, "%Y-%m-%d").date()
    except Exception:
        ctx["error"] = "Fechas inválidas. Usa el selector de fechas."
        return render(request, "prescripciones/lista.html", ctx)

    if d_hasta < d_desde:
        ctx["error"] = "La fecha hasta debe ser mayor o igual a la fecha desde."
        return render(request, "prescripciones/lista.html", ctx)

    # Limitar rango máximo
    delta_dias = (d_hasta - d_desde).days
    if delta_dias > 31:
        ctx["error"] = (
            "Por ahora el reporte de prescripciones solo permite rangos "
            "de hasta 31 días. Reduce el rango."
        )
        return render(request, "prescripciones/lista.html", ctx)

    # Resolver medicamento
    med = _resolve_med_by_name_or_code(q)
    if not med:
        ctx["error"] = "No se encontró un medicamento con ese nombre."
        return render(request, "prescripciones/lista.html", ctx)

    # Caché (mismo dataset, sin filtro por médico)
    cache_key = (
        f"presc:{DEFAULT_ALMACEN}:{med['med_codigo']}:"
        f"{d_desde.isoformat()}:{d_hasta.isoformat()}"
    )
    data = cache.get(cache_key)
    if data is None:
        enc = kardex_encabezado(med["med_codigo"])
        rows = prescripciones_detalle(
            med_codigo=med["med_codigo"],
            almacen=DEFAULT_ALMACEN,
            fecha_desde=d_desde,
            fecha_hasta=d_hasta,
        )
        cache.set(cache_key, (enc, rows), 300)  # 5 minutos
    else:
        enc, rows = data

    # 👇 lista de médicos disponibles para el combo
    medicos_disponibles = sorted(
        {
            (r.get("nombre_medico") or "").strip()
            for r in rows
            if (r.get("nombre_medico") or "").strip()
        }
    )

    # 🔎 Filtro por médico (exacto, pero ignorando mayúsculas y espacios)
    rows_filtradas = rows
    if medico:
        m_ref = medico.strip().lower()
        rows_filtradas = [
            r
            for r in rows
            if (r.get("nombre_medico") or "").strip().lower() == m_ref
        ]

    # Métricas
    total = len(rows_filtradas)
    pacientes = len(
        {
            (r.get("nombre_paciente") or "").strip()
            for r in rows_filtradas
            if (r.get("nombre_paciente") or "").strip()
        }
    )
    medicos = len(
        {
            (r.get("nombre_medico") or "").strip()
            for r in rows_filtradas
            if (r.get("nombre_medico") or "").strip()
        }
    )

    ctx.update(
        {
            "q": enc["nombre_del_producto"] if enc else med["nombre"],
            "medico": medico,
            "encabezado": {
                "nombre": enc["nombre_del_producto"] if enc else med["nombre"],
                "dci": enc["dci"] if enc else med["dci"],
                "concentracion": enc["concentracion"] if enc else med["concentracion"],
                "presentacion": enc["presentacion"] if enc else med["presentacion"],
                "laboratorio": enc["laboratorio"] if enc else None,
            },
            "rows": rows_filtradas,
            "total_presc": total,
            "pacientes_unicos": pacientes,
            "medicos_unicos": medicos,
            "medicos_disponibles": medicos_disponibles,
        }
    )
    return render(request, "prescripciones/lista.html", ctx)



# ===================== EXPORTS (CSV / XLSX) =====================


def _resolver_kardex_dataset(request):
    """
    Reusa la misma lógica de la vista para armar el dataset para export.
    GET esperados:
      - q (str): nombre/código de medicamento (obligatorio)
      - desde, hasta (YYYY-MM-DD)
      - alm (int, opcional): almacén. Si falta, usa DEFAULT_ALMACEN
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
        alm_int = int(alm) if alm not in (None, "", "null") else DEFAULT_ALMACEN
    except Exception:
        alm_int = DEFAULT_ALMACEN

    enc = kardex_encabezado(med["med_codigo"])
    rows = kardex_detalle(
        med_codigo=med["med_codigo"],
        almacen=alm_int,
        fecha_desde=d_desde,
        fecha_hasta=d_hasta,
    )
    return enc or {}, rows, d_desde, d_hasta, alm_int


def export_kardex_csv(request):
    """Exporta el Kardex a CSV (UTF-8 BOM + CRLF)."""
    try:
        enc, rows, d_desde, d_hasta, alm = _resolver_kardex_dataset(request)
    except Exception as e:
        return HttpResponse(
            f"Error: {e}", status=400, content_type="text/plain; charset=utf-8"
        )

    base = enc.get("nombre_del_producto", "medicamento")
    safe = (
        "".join(ch for ch in base if ch.isalnum() or ch in ("_", "-", ".")).strip()
        or "medicamento"
    )
    filename = f"Kardex_{safe}{d_desde}{d_hasta}.csv"

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename=\"{filename}\"'

    resp.write("\ufeff")  # BOM

    w = csv.writer(resp, lineterminator="\r\n")

    w.writerow(["KARDEX"])
    w.writerow([f"Producto: {enc.get('nombre_del_producto','')}"])
    w.writerow([f"DCI: {enc.get('dci','')}"])
    w.writerow([f"Concentración: {enc.get('concentracion','')}"])
    w.writerow([f"Presentación: {enc.get('presentacion','')}"])
    w.writerow([f"Laboratorio: {enc.get('laboratorio','')}"])
    w.writerow([f"Rango: {d_desde} a {d_hasta}"])
    w.writerow([])

    w.writerow(
        [
            "Fecha",
            "Cantidad Ingreso",
            "Nombre Paciente",
            "Nombre Médico",
            "No Receta",
            "Cantidad Egreso",
            "Saldo Anterior",
            "Saldo Actual",
            "Observaciones",
        ]
    )

    for r in rows:
        w.writerow(
            [
                r.get("fecha", ""),
                r.get("cantidad_ingreso", ""),
                r.get("nombre_paciente", ""),
                r.get("nombre_medico", ""),
                r.get("no_receta", ""),
                r.get("cantidad_egreso", ""),
                r.get("saldo_anterior", ""),
                r.get("saldo_actual", ""),
                (r.get("observaciones", "") or "")
                .replace("\r", " ")
                .replace("\n", " "),
            ]
        )

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
        return HttpResponse(
            f"Error: {e}", status=400, content_type="text/plain; charset=utf-8"
        )

    base = enc.get("nombre_del_producto", "medicamento")
    safe = (
        "".join(ch for ch in base if ch.isalnum() or ch in ("_", "-", ".")).strip()
        or "medicamento"
    )
    filename = f"Kardex_{safe}{d_desde}{d_hasta}.xlsx"

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

    ws.append([""])
    headers = [
        "Fecha",
        "Cantidad Ingreso",
        "Nombre Paciente",
        "Nombre Médico",
        "No Receta",
        "Cantidad Egreso",
        "Saldo Anterior",
        "Saldo Actual",
        "Observaciones",
    ]
    ws.append(headers)

    for r in rows:
        ws.append(
            [
                r.get("fecha", ""),
                r.get("cantidad_ingreso", 0),
                r.get("nombre_paciente", ""),
                r.get("nombre_medico", ""),
                r.get("no_receta", ""),
                r.get("cantidad_egreso", 0),
                r.get("saldo_anterior", 0),
                r.get("saldo_actual", 0),
                r.get("observaciones", ""),
            ]
        )

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
    resp["Content-Disposition"] = f'attachment; filename=\"{filename}\"'
    return resp