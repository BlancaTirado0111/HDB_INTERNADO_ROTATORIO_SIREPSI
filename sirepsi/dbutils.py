# sirepsi/dbutils.py
from django.db import connections

def query_bdfarmacia(sql: str, params=None):
    """
    Ejecuta SELECTs en la conexión 'BDFarmacia' y devuelve lista de dicts (keys en minúsculas).
    Usa %s como placeholder. Si params es falsy, ejecuta sin segundo argumento.
    """
    rows = []
    with connections["BDFarmacia"].cursor() as cur:
        if params:
            cur.execute(sql, tuple(params))
        else:
            cur.execute(sql)
        cols = [c[0].lower() for c in cur.description] if cur.description else []
        for r in cur.fetchall():
            rows.append({cols[i]: r[i] for i in range(len(cols))})
    return rows


# ========= Helpers para búsqueda de medicamento =========

def get_med_by_codificacion_or_codigo(term: str):
    """
    Busca por: MED_CODIGO exacto (si es numérico), MED_CODIFICACION exacta,
    o coincidencia parcial en MED_COMERCIAL.
    """
    if term is None or str(term).strip() == "":
        return None

    sql = """
        SELECT TOP(1)
            m.MED_CODIGO        AS med_codigo,
            m.MED_CODIFICACION  AS codificacion,
            m.MED_COMERCIAL     AS nombre,
            m.med_generico      AS dci,
            m.med_concentracion AS concentracion,
            m.med_unidad        AS presentacion
        FROM dbo.fa_medicamento m
        WHERE
            (ISNUMERIC(%s) = 1 AND m.MED_CODIGO = TRY_CONVERT(int, %s))
         OR (m.MED_CODIFICACION = %s)
         OR (m.MED_COMERCIAL LIKE CONCAT('%', %s, '%'));
    """
    params = [term, term, term, term]
    res = query_bdfarmacia(sql, params)
    return res[0] if res else None


def kardex_encabezado(med_codigo: int):
    """
    Encabezado a mostrar encima del Kardex (nombre, DCI, concentración, presentación, laboratorio).
    """
    sql = """
        SELECT
          m.MED_COMERCIAL      AS nombre_del_producto,
          m.med_generico       AS dci,
          m.med_concentracion  AS concentracion,
          m.med_unidad         AS presentacion,
          p.PRO_NOMBRE         AS laboratorio,
          NULL                 AS origen  -- cambia a p.PRO_PAIS si existiera
        FROM dbo.fa_medicamento m
        LEFT JOIN dbo.fa_proveedor p ON p.Emp_Codigo = m.emp_codigo
        WHERE m.MED_CODIGO = %s;
    """
    rows = query_bdfarmacia(sql, [med_codigo])
    return rows[0] if rows else None


def kardex_detalle(med_codigo: int, almacen: int, fecha_desde, fecha_hasta):
    """
    Devuelve filas del Kardex con Paciente/Médico + saldo anterior y saldo acumulado.
    Columnas devueltas (keys):
      fecha(dd/mm/aaaa), cantidad_ingreso, nombre_paciente, nombre_medico,
      no_receta, cantidad_egreso, saldo_anterior, saldo_actual, observaciones
    """
    sql = """
    WITH mov_raw AS (
      SELECT
          n.NOT_FECHA_MOV,
          n.NOT_CODIGO,
          n.NOT_SEC_CLASE,
          n.CLA_CODIGO,
          n.NOT_OBSERVACIONES,
          n.USU_CODIGO,
          n.PER_CODIGO,
          m.MOV_CODIGO,
          m.MED_CODIGO,
          m.MOV_CANTIDAD,
          cl.DOC_CODIGO
      FROM dbo.fa_nota n
      JOIN dbo.fa_movimiento m  ON m.NOT_CODIGO = n.NOT_CODIGO
      LEFT JOIN dbo.fa_clase_nota cl
             ON cl.CLA_CODIGO = n.CLA_CODIGO
            AND cl.CLA_TIPO   = n.CLA_TIPO
      WHERE n.NOT_ESTADO = 'V'
        AND n.ALM_CODIGO = %s
        AND m.MED_CODIGO = %s
    ),
    saldo_anterior AS (
      SELECT ISNULL(SUM(
        CASE 
          WHEN r.CLA_CODIGO = 1 AND ISNULL(r.DOC_CODIGO,0) <> 2 THEN  r.MOV_CANTIDAD
          WHEN r.CLA_CODIGO = 2 AND ISNULL(r.DOC_CODIGO,0) <> 2 THEN -r.MOV_CANTIDAD
          WHEN r.CLA_CODIGO = 1 AND ISNULL(r.DOC_CODIGO,0)  = 2 THEN  r.MOV_CANTIDAD   -- ajustes +
          WHEN r.CLA_CODIGO = 2 AND ISNULL(r.DOC_CODIGO,0)  = 2 THEN -r.MOV_CANTIDAD  -- ajustes -
          ELSE 0
        END
      ),0) AS saldo_ant
      FROM mov_raw r
      WHERE r.NOT_FECHA_MOV < %s
    ),
    rango AS (
      SELECT *
      FROM mov_raw
      WHERE NOT_FECHA_MOV >= %s
        AND NOT_FECHA_MOV <  DATEADD(day, 1, %s)
    ),
    qty AS (
      SELECT r.*,
             CASE 
               WHEN r.CLA_CODIGO = 1 AND ISNULL(r.DOC_CODIGO,0) <> 2 THEN  r.MOV_CANTIDAD
               WHEN r.CLA_CODIGO = 2 AND ISNULL(r.DOC_CODIGO,0) <> 2 THEN -r.MOV_CANTIDAD
               WHEN r.CLA_CODIGO = 1 AND ISNULL(r.DOC_CODIGO,0)  = 2 THEN  r.MOV_CANTIDAD
               WHEN r.CLA_CODIGO = 2 AND ISNULL(r.DOC_CODIGO,0)  = 2 THEN -r.MOV_CANTIDAD
               ELSE 0
             END AS qty_signed
      FROM rango r
    ),
    -- Enlace a Recibos/Recetarios (normalizado a texto)
    rr AS (
      SELECT q.*,
             rrp.vclihiccli,
             rrp.medico AS per_medico
      FROM qty q
      LEFT JOIN dbo.RecibosRecetariosPorMedico rrp
             ON rrp.vrectipdoc = q.CLA_CODIGO
            AND CONVERT(VARCHAR(25), rrp.vrecnumero) = CONVERT(VARCHAR(25), q.NOT_SEC_CLASE)
    ),
    nombres AS (
      SELECT rr.*,
             LTRIM(RTRIM(CONCAT(h.hcl_appat,' ',h.hcl_apmat,', ',h.hcl_nombre))) AS paciente_rr,
             med.per_Nombre  AS medico_rr,
             pac.per_Nombre  AS paciente_per,
             usr.Usu_NombreUsuario AS medico_usr
      FROM rr
      LEFT JOIN bdestadistica..se_hc  h   ON h.hcl_codigo   = rr.vclihiccli
      LEFT JOIN dbo.rh_Personal       med ON med.per_Codigo = rr.per_medico
      LEFT JOIN dbo.rh_Personal       pac ON pac.per_Codigo = rr.PER_CODIGO
      LEFT JOIN dbo.Usuarios          usr ON usr.USU_CODIGO = rr.USU_CODIGO
    ),
    calc AS (
      SELECT
          n.NOT_FECHA_MOV AS fecha_dt,
          n.NOT_SEC_CLASE AS no_receta,
          CASE WHEN n.qty_signed > 0 THEN n.qty_signed ELSE 0 END  AS cantidad_ingreso,
          CASE WHEN n.qty_signed < 0 THEN -n.qty_signed ELSE 0 END AS cantidad_egreso,
          COALESCE(NULLIF(n.paciente_rr,''), NULLIF(n.paciente_per,'')) AS nombre_paciente,
          COALESCE(NULLIF(n.medico_rr,''),  NULLIF(n.medico_usr,''), CAST(n.USU_CODIGO AS varchar(20))) AS nombre_medico,
          NULLIF(LTRIM(RTRIM(n.NOT_OBSERVACIONES)), '') AS observaciones,
          n.qty_signed
      FROM nombres n
    )
    SELECT
      CONVERT(VARCHAR(10), c.fecha_dt, 103) AS fecha,    -- dd/mm/aaaa
      c.cantidad_ingreso,
      c.nombre_paciente,
      c.nombre_medico,
      c.no_receta,
      c.cantidad_egreso,
      (SELECT saldo_ant FROM saldo_anterior) AS saldo_anterior,
      (SELECT saldo_ant FROM saldo_anterior)
        + SUM(c.qty_signed) OVER (
            ORDER BY c.fecha_dt, c.no_receta
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          ) AS saldo_actual,
      c.observaciones
    FROM calc c
    ORDER BY c.fecha_dt, c.no_receta;
    """
    params = [almacen, med_codigo, fecha_desde, fecha_desde, fecha_hasta]
    return query_bdfarmacia(sql, params)

def prescripciones_detalle(med_codigo: int, almacen: int, fecha_desde, fecha_hasta):
    """
    Devuelve la lista de prescripciones (egresos) para un medicamento y rango de fechas.
    Columnas:
      fecha(dd/mm/aaaa), nombre_paciente, nombre_medico, no_receta, observaciones
    """
    sql = """
    WITH mov_raw AS (
      SELECT
          n.NOT_FECHA_MOV,
          n.NOT_CODIGO,
          n.NOT_SEC_CLASE,
          n.CLA_CODIGO,
          n.NOT_OBSERVACIONES,
          n.USU_CODIGO,
          n.PER_CODIGO,
          m.MOV_CODIGO,
          m.MED_CODIGO,
          m.MOV_CANTIDAD,
          cl.DOC_CODIGO
      FROM dbo.fa_nota n
      JOIN dbo.fa_movimiento m  ON m.NOT_CODIGO = n.NOT_CODIGO
      LEFT JOIN dbo.fa_clase_nota cl
             ON cl.CLA_CODIGO = n.CLA_CODIGO
            AND cl.CLA_TIPO   = n.CLA_TIPO
      WHERE n.NOT_ESTADO = 'V'
        AND n.ALM_CODIGO = %s
        AND m.MED_CODIGO = %s
    ),
    rango AS (
      SELECT *
      FROM mov_raw
      WHERE NOT_FECHA_MOV >= %s
        AND NOT_FECHA_MOV <  DATEADD(day, 1, %s)
    ),
    qty AS (
      SELECT r.*,
             CASE 
               WHEN r.CLA_CODIGO = 1 AND ISNULL(r.DOC_CODIGO,0) <> 2 THEN  r.MOV_CANTIDAD
               WHEN r.CLA_CODIGO = 2 AND ISNULL(r.DOC_CODIGO,0) <> 2 THEN -r.MOV_CANTIDAD
               WHEN r.CLA_CODIGO = 1 AND ISNULL(r.DOC_CODIGO,0)  = 2 THEN  r.MOV_CANTIDAD
               WHEN r.CLA_CODIGO = 2 AND ISNULL(r.DOC_CODIGO,0)  = 2 THEN -r.MOV_CANTIDAD
               ELSE 0
             END AS qty_signed
      FROM rango r
    ),
    rr AS (
      SELECT q.*,
             rrp.vclihiccli,
             rrp.medico AS per_medico
      FROM qty q
      LEFT JOIN dbo.RecibosRecetariosPorMedico rrp
             ON rrp.vrectipdoc = q.CLA_CODIGO
            AND CONVERT(VARCHAR(25), rrp.vrecnumero) = CONVERT(VARCHAR(25), q.NOT_SEC_CLASE)
    ),
    nombres AS (
      SELECT rr.*,
             LTRIM(RTRIM(CONCAT(h.hcl_appat,' ',h.hcl_apmat,', ',h.hcl_nombre))) AS paciente_rr,
             med.per_Nombre  AS medico_rr,
             pac.per_Nombre  AS paciente_per,
             usr.Usu_NombreUsuario AS medico_usr
      FROM rr
      LEFT JOIN bdestadistica..se_hc  h   ON h.hcl_codigo   = rr.vclihiccli
      LEFT JOIN dbo.rh_Personal       med ON med.per_Codigo = rr.per_medico
      LEFT JOIN dbo.rh_Personal       pac ON pac.per_Codigo = rr.PER_CODIGO
      LEFT JOIN dbo.Usuarios          usr ON usr.USU_CODIGO = rr.USU_CODIGO
    )
    SELECT
      CONVERT(VARCHAR(10), n.NOT_FECHA_MOV, 103) AS fecha,    -- dd/mm/aaaa
      COALESCE(NULLIF(n.paciente_rr,''), NULLIF(n.paciente_per,'')) AS nombre_paciente,
      COALESCE(NULLIF(n.medico_rr,''),  NULLIF(n.medico_usr,''), CAST(n.USU_CODIGO AS varchar(20))) AS nombre_medico,
      n.NOT_SEC_CLASE AS no_receta,
      NULLIF(LTRIM(RTRIM(n.NOT_OBSERVACIONES)), '') AS observaciones
    FROM nombres n
    WHERE n.qty_signed < 0   -- solo EGRESOS = prescripciones/dispensaciones
    ORDER BY n.NOT_FECHA_MOV, n.NOT_SEC_CLASE;
    """
    params = [almacen, med_codigo, fecha_desde, fecha_hasta]
    return query_bdfarmacia(sql, params)
