# sirepsi/views.py
from datetime import datetime, date, timedelta
from django.core.paginator import Paginator
from django.shortcuts import render

from .dbutils import query_bdfarmacia


# sirepsi/views.py  (añade los imports si no los tienes)
from django.http import JsonResponse
from django.db import connection  # no imprescindible; usamos tu helper query_bdfarmacia
from .dbutils import query_bdfarmacia

# ---------------------- HOME / UTILES ----------------------

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

    pages = set()
    pages.add(1)
    pages.add(total)

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


# ---------------------- MEDICAMENTOS (LISTA) ----------------------

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


# ---------------------- MOVIMIENTOS (KARDEX) ----------------------

def _parse_med_query(q: str):
    """
    Acepta entradas como:
      - "355" (MED_CODIGO)
      - "N0501" (MED_CODIFICACION)
      - "355/N0501/ALPRAZOLAM" (combinado)
      - "ALPRAZOLAM" (parte del nombre)
    Devuelve un dict con med_codigo / codificacion / nombre o None.
    IMPORTANTE: el comodín va en el parámetro (LIKE %s) para evitar errores
    del driver mssql con los porcentajes en el SQL.
    """
    if not q:
        return None

    q = str(q).strip()
    parts = [p.strip() for p in q.split("/") if p.strip()]

    med_codigo = None
    if parts and parts[0].isdigit():
        med_codigo = int(parts[0])

    cod = None
    for p in parts:
        if len(p) <= 10 and any(ch.isalpha() for ch in p) and any(ch.isdigit() for ch in p):
            cod = p
            break

    sql = """
        SELECT TOP(1)
            m.MED_CODIGO       AS med_codigo,
            m.MED_CODIFICACION AS codificacion,
            m.MED_COMERCIAL    AS nombre,
            m.med_generico     AS dci,
            m.med_concentracion AS concentracion,
            m.med_unidad       AS presentacion
        FROM dbo.fa_medicamento m
        WHERE
              ( %s IS NOT NULL AND m.MED_CODIGO = %s )
           OR ( %s IS NOT NULL AND m.MED_CODIFICACION = %s )
           OR ( m.MED_COMERCIAL LIKE %s )
        ORDER BY
          CASE WHEN %s IS NOT NULL AND m.MED_CODIGO = %s THEN 0 ELSE 1 END,
          CASE WHEN %s IS NOT NULL AND m.MED_CODIFICACION = %s THEN 0 ELSE 1 END
    """
    like_param = f"%{q}%"
    params = [
        med_codigo, med_codigo,
        cod, cod,
        like_param,
        med_codigo, med_codigo,
        cod, cod,
    ]

    filas = query_bdfarmacia(sql, params)
    return filas[0] if filas else None


# ---------------------- MOVIMIENTOS (KARDEX) ----------------------
from datetime import datetime, date, timedelta
from django.shortcuts import render
from .dbutils import query_bdfarmacia

def _resolve_med_from_name_or_code(q: str):
    """
    Prioriza BUSCAR POR NOMBRE (exacto / empieza / contiene).
    Si no encuentra, cae a MED_CODIGO o MED_CODIFICACION.
    Devuelve un dict con med_codigo, codificacion, nombre, dci, etc. o None.
    """
    if not q:
        return None
    q = q.strip()

    # 1) nombre exacto (case-insensitive)
    sql = """
        SELECT TOP(1)
           m.MED_CODIGO AS med_codigo, m.MED_CODIFICACION AS codificacion,
           m.MED_COMERCIAL AS nombre, m.med_generico AS dci,
           m.med_concentracion AS concentracion, m.med_unidad AS presentacion
        FROM dbo.fa_medicamento m
        WHERE UPPER(m.MED_COMERCIAL) = UPPER(%s)
        ORDER BY m.MED_COMERCIAL
    """
    rows = query_bdfarmacia(sql, [q])
    if rows: return rows[0]

    # 2) nombre que empieza por...
    sql = """
        SELECT TOP(1)
           m.MED_CODIGO AS med_codigo, m.MED_CODIFICACION AS codificacion,
           m.MED_COMERCIAL AS nombre, m.med_generico AS dci,
           m.med_concentracion AS concentracion, m.med_unidad AS presentacion
        FROM dbo.fa_medicamento m
        WHERE m.MED_COMERCIAL LIKE %s
        ORDER BY LEN(m.MED_COMERCIAL), m.MED_COMERCIAL
    """
    rows = query_bdfarmacia(sql, [q + "%"])
    if rows: return rows[0]

    # 3) nombre que contiene...
    rows = query_bdfarmacia(sql, ["%" + q + "%"])
    if rows: return rows[0]

    # 4) ¿vino MED_CODIGO?
    if q.isdigit():
        sql = """
            SELECT TOP(1)
               m.MED_CODIGO AS med_codigo, m.MED_CODIFICACION AS codificacion,
               m.MED_COMERCIAL AS nombre, m.med_generico AS dci,
               m.med_concentracion AS concentracion, m.med_unidad AS presentacion
            FROM dbo.fa_medicamento m
            WHERE m.MED_CODIGO = %s
        """
        rows = query_bdfarmacia(sql, [int(q)])
        if rows: return rows[0]

    # 5) ¿vino codificación tipo N0501?
    sql = """
        SELECT TOP(1)
           m.MED_CODIGO AS med_codigo, m.MED_CODIFICACION AS codificacion,
           m.MED_COMERCIAL AS nombre, m.med_generico AS dci,
           m.med_concentracion AS concentracion, m.med_unidad AS presentacion
        FROM dbo.fa_medicamento m
        WHERE m.MED_CODIFICACION = %s
    """
    rows = query_bdfarmacia(sql, [q])
    return rows[0] if rows else None


def _kardex_consulta(med_codigo: int, almacen: int, f_desde: date, f_hasta: date):
    """
    Devuelve (encabezado, movimientos) para el Anexo 15.
    Rango inclusivo: [f_desde, f_hasta]
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

    # Detalle con saldo anterior + acumulado
    hasta_plus = (datetime.combine(f_hasta, datetime.min.time()) + timedelta(days=1)).date()
    sql_det = """
    WITH mov_raw AS (
      SELECT
          n.NOT_FECHA_MOV, n.NOT_CODIGO, n.NOT_SEC_CLASE, n.CLA_CODIGO,
          n.NOT_OBSERVACIONES, n.USU_CODIGO, n.PER_CODIGO,
          m.MOV_CODIGO, m.MED_CODIGO, m.MOV_CANTIDAD
      FROM dbo.fa_nota n
      JOIN dbo.fa_movimiento m ON m.NOT_CODIGO = n.NOT_CODIGO
      WHERE n.ALM_CODIGO = %s
        AND m.MED_CODIGO = %s
        AND n.NOT_ESTADO = 'V'
    ),
    saldo_anterior AS (
      SELECT ISNULL(SUM(CASE WHEN r.CLA_CODIGO=1 THEN r.MOV_CANTIDAD
                             WHEN r.CLA_CODIGO=2 THEN -r.MOV_CANTIDAD
                             ELSE 0 END),0) AS saldo_ant
      FROM mov_raw r
      WHERE r.NOT_FECHA_MOV < %s
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
      CONVERT(date, q.NOT_FECHA_MOV) AS fecha,
      CASE WHEN q.qty_signed>0 THEN q.qty_signed ELSE 0 END AS cantidad_ingreso,
      CASE WHEN q.qty_signed<0 THEN -q.qty_signed ELSE 0 END AS cantidad_egreso,
      (SELECT saldo_ant FROM saldo_anterior) AS saldo_anterior,
      (SELECT saldo_ant FROM saldo_anterior)
        + SUM(q.qty_signed) OVER (ORDER BY q.NOT_FECHA_MOV, q.NOT_CODIGO
                                  ROWS UNBOUNDED PRECEDING) AS saldo_actual,
      q.NOT_SEC_CLASE AS no_receta,
      NULL AS nombre_paciente,
      NULL AS nombre_medico,
      NULL AS observaciones
    FROM qty q
    ORDER BY q.NOT_FECHA_MOV, q.NOT_CODIGO
    """
    rows = query_bdfarmacia(sql_det, [almacen, med_codigo, f_desde, f_desde, hasta_plus])
    return encabezado, rows


def movimientos_kardex(request):
    """
    Form principal:
      - q: NOMBRE del medicamento (también acepta código/codificación).
      - desde / hasta: obligatorio (YYYY-MM-DD).
      - almacen: por defecto 31.
    Auto-llena el encabezado con los datos del medicamento resuelto.
    Soporta ?print=1 para vista de impresión.
    """
    q = (request.GET.get("q") or "").strip()
    almacen = (request.GET.get("almacen") or "31").strip()
    desde = (request.GET.get("desde") or "").strip()
    hasta = (request.GET.get("hasta") or "").strip()
    want_print = (request.GET.get("print") or "") == "1"

    ctx = {
        "q": q, "almacen": almacen, "desde": desde, "hasta": hasta,
        "encabezado": None, "rows": [], "error": "",
        "print_mode": want_print,
    }

    # Si solo se abre la pantalla, no buscar todavía
    if not (q and desde and hasta):
        return render(request, "movimientos/kardex.html", ctx)

    # Validaciones
    try:
        alm_int = int(almacen)
    except ValueError:
        ctx["error"] = "El almacén debe ser numérico."
        return render(request, "movimientos/kardex.html", ctx)

    try:
        d_desde = datetime.strptime(desde, "%Y-%m-%d").date()
        d_hasta = datetime.strptime(hasta, "%Y-%m-%d").date()
    except Exception:
        ctx["error"] = "Fechas inválidas. Usa el selector de fechas."
        return render(request, "movimientos/kardex.html", ctx)

    if d_hasta < d_desde:
        ctx["error"] = "La fecha 'Hasta' no puede ser menor que 'Desde'."
        return render(request, "movimientos/kardex.html", ctx)

    # Resolver medicamento (prioriza NOMBRE)
    med = _resolve_med_from_name_or_code(q)
    if not med:
        ctx["error"] = "No se encontró el medicamento. Escribe parte del NOMBRE (o código/codificación)."
        return render(request, "movimientos/kardex.html", ctx)

    enc, rows = _kardex_consulta(med["med_codigo"], alm_int, d_desde, d_hasta)

    # Actualiza q con “bonito” (para que se vea y sirva al imprimir)
    q_pretty = f"{med['nombre']}"
    ctx.update({"encabezado": enc, "rows": rows, "q": q_pretty})

    # Si viene print=1 se puede usar el mismo template (CSS @media print lo deja limpio)
    return render(request, "movimientos/kardex.html", ctx)

def meds_suggest(request):
    """
    Devuelve hasta 20 medicamentos que coincidan con el texto buscado.
    Formato: {"results": [{"id": 355, "label": "355 / N0501 / ALPRAZOLAM"}, ...]}
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})

    # Armamos búsqueda por nombre, codificación y código exacto.
    # Usamos parámetros con %s para evitar el formato con % () que te daba error.
    sql = """
        SELECT TOP (20)
            m.MED_CODIGO       AS med_codigo,
            m.MED_CODIFICACION AS codificacion,
            m.MED_COMERCIAL    AS nombre
        FROM dbo.fa_medicamento m
        WHERE
              m.MED_COMERCIAL    LIKE CONCAT('%', %s, '%')
           OR m.MED_CODIFICACION LIKE CONCAT('%', %s, '%')
           OR CAST(m.MED_CODIGO AS varchar(20)) = %s
        ORDER BY
            CASE
              WHEN m.MED_COMERCIAL LIKE CONCAT(%s, '%') THEN 0
              ELSE 1
            END,
            m.MED_COMERCIAL
    """
    params = [q, q, q, q]
    rows = query_bdfarmacia(sql, params)

    results = [
        {
            "id": r["med_codigo"],
            "label": f'{r["med_codigo"]} / {r["codificacion"]} / {r["nombre"]}'
        }
        for r in rows
    ]
    return JsonResponse({"results": results})
