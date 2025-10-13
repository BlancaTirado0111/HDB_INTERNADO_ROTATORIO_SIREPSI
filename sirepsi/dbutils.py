# sirepsi/dbutils.py
from django.db import connections

def query_bdfarmacia(sql: str, params=None):
    """
    Ejecuta SELECTs en la BD 'BDFarmacia' y devuelve lista de dicts.
    - Si NO hay params, llama a execute(sql) SIN segundo argumento.
    - Si hay params, siempre los convierte a TUPLA.
    """
    rows = []
    with connections["BDFarmacia"].cursor() as cur:
        if params is None or params == [] or params == ():
            # <-- importante: NO pasar un segundo argumento vacío
            cur.execute(sql)
        else:
            cur.execute(sql, tuple(params))

        cols = [c[0].lower() for c in cur.description] if cur.description else []
        for r in cur.fetchall():
            rows.append({cols[i]: r[i] for i in range(len(cols))})
    return rows
