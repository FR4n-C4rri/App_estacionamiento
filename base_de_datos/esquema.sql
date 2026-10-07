-- Esquema de la base de datos de la app de estacionamiento.
--
-- La configuración de cada cámara vive en su carpeta (camaras/<id>/);
-- la tabla `camaras` es un índice de esa información para poder buscar
-- por cercanía rápido. Las tablas de estado las escribe el detector.

CREATE TABLE IF NOT EXISTS camaras (
    id                  TEXT PRIMARY KEY,
    nombre              TEXT NOT NULL,
    direccion           TEXT NOT NULL DEFAULT '',
    lat                 REAL NOT NULL,
    lng                 REAL NOT NULL,
    cuadra_inicio_lat   REAL,
    cuadra_inicio_lng   REAL,
    cuadra_fin_lat      REAL,
    cuadra_fin_lng      REAL,
    total_lugares       INTEGER NOT NULL,
    api_key             TEXT NOT NULL,
    activa              INTEGER NOT NULL DEFAULT 1,
    creada_en           TEXT NOT NULL
);

-- Resumen por cámara (mismo formato que generaba estado_vehiculos.py).
CREATE TABLE IF NOT EXISTS camaras_estado (
    camara          TEXT PRIMARY KEY,
    ocupados        INTEGER NOT NULL,
    total           INTEGER NOT NULL,
    porcentaje      REAL NOT NULL,
    estado          TEXT NOT NULL,   -- 'HAY LUGAR' / 'CASI LLENO' / 'LLENO'
    actualizado_en  TEXT NOT NULL
);

-- Detalle lugar por lugar (mismo formato que generaba estado_vehiculos.py).
CREATE TABLE IF NOT EXISTS espacios_estado (
    camara          TEXT NOT NULL,
    espacio_id      TEXT NOT NULL,
    tipo            TEXT NOT NULL,   -- 'valido' / 'prohibido'
    ocupado         INTEGER NOT NULL,
    actualizado_en  TEXT NOT NULL,
    PRIMARY KEY (camara, espacio_id)
);

-- Una fila por foto procesada, para gráficos o el informe.
CREATE TABLE IF NOT EXISTS historial (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    camara          TEXT NOT NULL,
    ocupados        INTEGER NOT NULL,
    total           INTEGER NOT NULL,
    registrado_en   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_historial_camara ON historial (camara, registrado_en);
