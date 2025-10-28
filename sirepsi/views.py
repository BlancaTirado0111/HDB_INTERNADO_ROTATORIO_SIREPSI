# sirepsi/views.py
from datetime import datetime, date, timedelta

from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render

from .dbutils import query_bdfarmacia


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
# -------- Lista base (para el modal) ----------
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


def meds_suggest(request):
    """
    API para el modal: devuelve hasta 20 medicamentos de la lista base,
    filtrados por 'q' (contiene en código o nombre, sin mayúsculas).
    """
    q = (request.GET.get("q") or "").strip().lower()
    results = []
    for code, name in PSYCH_LIST:
        if not q or (q in code.lower()) or (q in name.lower()):
            results.append({"code": code, "label": f"{code} — {name}"})
        if len(results) >= 20:
            break
    return JsonResponse({"results": results})


# -------- Resolver medicamento (solo por nombre/código) ----------
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

    # ¿match por lista base?
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

    # fallback: por nombre (contiene) en toda la BD (comercial o genérico)
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


# -------- Consulta Kardex (SIN almacén) ----------
def _kardex_consulta_sin_almacen(med_codigo: int, f_desde: date, f_hasta: date):
    """
    Devuelve:
      encabezado(dict), movimientos(list[dict]), saldo_inicial, sum_ingresos, sum_egresos, saldo_final
    Rango inclusivo [f_desde, f_hasta], orden por fecha ascendente.
    CLA_CODIGO: 1 = Entrada, 2 = Salida.
    """
    # Encabezado
    sql_hdr = """
        SELECT
          m.MED_CODIGO         AS med_codigo,
          m.MED_CODIFICACION   AS codificacion,
          m.MED_COMERCIAL      AS nombre,
          m.med_generico       AS dci,
          m.med_concentracion  AS concentracion,
          m.med_unidad         AS presentacion,
          p.PRO_NOMBRE         AS laboratorio
        FROM dbo.fa_medicamento m
        LEFT JOIN dbo.fa_proveedor p ON p.Emp_Codigo = m.emp_codigo
        WHERE m.MED_CODIGO = %s
    """
    enc = query_bdfarmacia(sql_hdr, [med_codigo])
    encabezado = enc[0] if enc else None

    # Fin de día inclusivo
    hasta_plus = (datetime.combine(f_hasta, datetime.min.time()) + timedelta(days=1)).date()

    # Movimientos (raw) + qty_signed
    sql = """
    WITH mov_raw AS (
      SELECT
          n.NOT_FECHA_MOV, n.NOT_CODIGO, n.NOT_SEC_CLASE, n.CLA_CODIGO,
          n.NOT_OBSERVACIONES, n.USU_CODIGO, n.PER_CODIGO,
          m.MOV_CODIGO, m.MED_CODIGO, m.MOV_CANTIDAD
      FROM dbo.fa_nota n
      JOIN dbo.fa_movimiento m ON m.NOT_CODIGO = n.NOT_CODIGO
      WHERE m.MED_CODIGO = %s
        AND n.NOT_ESTADO = 'V'
    ),
    rango AS (
      SELECT *
      FROM mov_raw
      WHERE NOT_FECHA_MOV >= %s AND NOT_FECHA_MOV < %s
    ),
    qty AS (
      SELECT r.*,
             CASE WHEN r.CLA_CODIGO=1 THEN r.MOV_CANTIDAD
                  WHEN r.CLA_CODIGO=2 THEN -r.MOV_CANTIDAD
                  ELSE 0 END AS qty_signed
      FROM rango r
    )
    SELECT
      CONVERT(VARCHAR(10), q.NOT_FECHA_MOV, 103) AS fecha,        -- dd/mm/aaaa
      CASE WHEN q.qty_signed>0 THEN q.qty_signed ELSE 0 END AS cantidad_ingreso,
      NULL AS nombre_paciente,
      NULL AS nombre_medico,
      q.NOT_SEC_CLASE AS no_receta,
      CASE WHEN q.qty_signed<0 THEN -q.qty_signed ELSE 0 END AS cantidad_egreso,
      q.NOT_FECHA_MOV AS __orden_fecha,
      q.NOT_CODIGO    AS __orden_nota,
      q.NOT_SEC_CLASE AS __orden_sec
    FROM qty q
    ORDER BY q.NOT_FECHA_MOV, q.NOT_CODIGO, q.NOT_SEC_CLASE
    """
    rows = query_bdfarmacia(sql, [med_codigo, f_desde, hasta_plus])

    # Saldo inicial previo al rango
    sql_ini = """
        SELECT ISNULL(SUM(
            CASE WHEN r.CLA_CODIGO=1 THEN r.MOV_CANTIDAD
                 WHEN r.CLA_CODIGO=2 THEN -r.MOV_CANTIDAD
                 ELSE 0 END
        ),0) AS s
        FROM (
            SELECT n.CLA_CODIGO, m.MOV_CANTIDAD, n.NOT_FECHA_MOV
            FROM dbo.fa_nota n
            JOIN dbo.fa_movimiento m ON n.NOT_CODIGO=m.NOT_CODIGO
            WHERE m.MED_CODIGO=%s AND n.NOT_ESTADO='V'
        ) r
        WHERE r.NOT_FECHA_MOV < %s;
    """
    tmp = query_bdfarmacia(sql_ini, [med_codigo, f_desde])
    saldo_inicial = (tmp[0]["s"] if tmp else 0) or 0

    # Recálculo de saldos y totales en Python
    running = float(saldo_inicial)
    sum_ing = 0.0
    sum_egr = 0.0
    out = []
    for r in rows:
        ingreso = float(r["cantidad_ingreso"] or 0)
        egreso  = float(r["cantidad_egreso"] or 0)
        saldo_anterior = running
        running = running + ingreso - egreso
        r["saldo_anterior"] = saldo_anterior
        r["saldo_actual"] = running
        # quitar columnas internas de orden
        r.pop("__orden_fecha", None)
        r.pop("__orden_nota", None)
        r.pop("__orden_sec", None)
        sum_ing += ingreso
        sum_egr += egreso
        out.append(r)

    saldo_final = running
    return encabezado, out, saldo_inicial, sum_ing, sum_egr, saldo_final


def movimientos_kardex(request):
    """
    Formulario: medicamento (obligatorio), desde (obligatorio), hasta (obligatorio).
    SIN almacén. Modal para elegir medicamento (en el template).
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

    enc, rows, s_ini, t_in, t_eg, s_fin = _kardex_consulta_sin_almacen(
        med["med_codigo"], d_desde, d_hasta
    )

    ctx.update({
        "q": med["nombre"],        # mostrar el nombre “bonito”
        "encabezado": enc,
        "rows": rows,
        "saldo_inicial": s_ini,
        "sum_ingresos": t_in,
        "sum_egresos": t_eg,
        "saldo_final": s_fin,
        "total_movs": len(rows),
    })
    return render(request, "movimientos/kardex.html", ctx)
