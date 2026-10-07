"""
Acceso a la base SQLite: conexión y todas las consultas que usan el
servidor y el detector. SQLite es un archivo, así que el detector puede
escribir mientras el servidor lee (se activa el modo WAL para eso).
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config


def ahora_iso():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def conectar(ruta=None):
    ruta = ruta or config.RUTA_DB
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def crear_tablas():
    with conectar() as conn:
        conn.executescript(config.RUTA_ESQUEMA.read_text(encoding="utf-8"))


# --- Cámaras ---------------------------------------------------------------

def guardar_camara(conn, cam, total_lugares):
    """Inserta o actualiza el índice de una cámara a partir de su camara.json."""
    cuadra = cam.get("cuadra") or [[None, None], [None, None]]
    conn.execute(
        """INSERT INTO camaras (id, nombre, direccion, lat, lng,
                               cuadra_inicio_lat, cuadra_inicio_lng, cuadra_fin_lat, cuadra_fin_lng,
                               total_lugares, api_key, activa, creada_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               nombre=excluded.nombre, direccion=excluded.direccion,
               lat=excluded.lat, lng=excluded.lng,
               cuadra_inicio_lat=excluded.cuadra_inicio_lat, cuadra_inicio_lng=excluded.cuadra_inicio_lng,
               cuadra_fin_lat=excluded.cuadra_fin_lat, cuadra_fin_lng=excluded.cuadra_fin_lng,
               total_lugares=excluded.total_lugares, api_key=excluded.api_key,
               activa=excluded.activa""",
        (cam["id"], cam["nombre"], cam.get("direccion", ""), cam["lat"], cam["lng"],
         cuadra[0][0], cuadra[0][1], cuadra[1][0], cuadra[1][1],
         total_lugares, cam["api_key"], 1 if cam.get("activa", True) else 0,
         cam.get("creada_en") or ahora_iso()),
    )


def borrar_camara(conn, camara_id):
    conn.execute("DELETE FROM camaras WHERE id = ?", (camara_id,))
    borrar_estado(conn, camara_id)
    conn.execute("DELETE FROM historial WHERE camara = ?", (camara_id,))


def ids_camaras(conn):
    return [fila["id"] for fila in conn.execute("SELECT id FROM camaras")]


def camaras_con_estado(conn, solo_activas=False):
    """Todas las cámaras unidas con su último estado (None si nunca se procesó)."""
    sql = """SELECT c.*, e.ocupados, e.total, e.porcentaje, e.estado, e.actualizado_en,
                    (SELECT COUNT(*) FROM espacios_estado x
                      WHERE x.camara = c.id AND x.tipo = 'prohibido' AND x.ocupado = 1) AS prohibidos_bloqueados
             FROM camaras c LEFT JOIN camaras_estado e ON e.camara = c.id"""
    if solo_activas:
        sql += " WHERE c.activa = 1"
    return [dict(fila) for fila in conn.execute(sql + " ORDER BY c.id")]


def espacios_de(conn, camara_id):
    filas = conn.execute(
        "SELECT espacio_id, tipo, ocupado, actualizado_en FROM espacios_estado WHERE camara = ? ORDER BY espacio_id",
        (camara_id,),
    )
    return [dict(f) for f in filas]


# --- Estado (lo escribe el detector) ----------------------------------------

def guardar_estado(conn, camara_id, espacios, ocupado_por_id, bloqueado_por_id,
                   ocupados, total, porcentaje, estado_txt):
    """Mismo guardado que hacía estado_vehiculos.py, más una fila de historial."""
    momento = ahora_iso()
    filas = []
    for esp in espacios:
        if esp["tipo"] == "prohibido":
            ocupado = 1 if esp["id"] in bloqueado_por_id else 0
        else:
            ocupado = 1 if esp["id"] in ocupado_por_id else 0
        filas.append((camara_id, esp["id"], esp["tipo"], ocupado, momento))

    conn.executemany(
        """INSERT OR REPLACE INTO espacios_estado
           (camara, espacio_id, tipo, ocupado, actualizado_en) VALUES (?, ?, ?, ?, ?)""",
        filas,
    )
    conn.execute(
        """INSERT OR REPLACE INTO camaras_estado
           (camara, ocupados, total, porcentaje, estado, actualizado_en)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (camara_id, ocupados, total, porcentaje, estado_txt, momento),
    )
    conn.execute(
        "INSERT INTO historial (camara, ocupados, total, registrado_en) VALUES (?, ?, ?, ?)",
        (camara_id, ocupados, total, momento),
    )


def borrar_estado(conn, camara_id):
    """Se usa cuando cambian los espacios de una cámara: el estado viejo ya no aplica."""
    conn.execute("DELETE FROM camaras_estado WHERE camara = ?", (camara_id,))
    conn.execute("DELETE FROM espacios_estado WHERE camara = ?", (camara_id,))
