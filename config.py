"""
Configuración central de la app: rutas de carpetas y parámetros.

Los valores se pueden cambiar con variables de entorno o con un archivo
.env en la raíz del proyecto (formato CLAVE=valor, ver .env.example).
"""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def _cargar_env(ruta):
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


_cargar_env(RAIZ / ".env")

# --- Carpetas ---
CARPETA_CAMARAS = Path(os.environ.get("CARPETA_CAMARAS", RAIZ / "camaras"))
CARPETA_WEB = RAIZ / "web"
RUTA_DB = Path(os.environ.get("RUTA_DB", RAIZ / "base_de_datos" / "estacionamiento.db"))
RUTA_ESQUEMA = RAIZ / "base_de_datos" / "esquema.sql"
RUTA_MODELO = Path(os.environ.get("RUTA_MODELO", RAIZ / "deteccion" / "best.pt"))

# --- Admin ---
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

# --- Detector ---
# "on" = el servidor corre el detector en segundo plano. "off" = no (por
# ejemplo si lo corrés aparte con `py -m deteccion.detector`).
DETECTOR = os.environ.get("DETECTOR", "on").lower()
INTERVALO_POLL = float(os.environ.get("INTERVALO_POLL", "5"))
MAX_PROCESADAS = int(os.environ.get("MAX_PROCESADAS", "1"))
ANCHO_PREVIEW = int(os.environ.get("ANCHO_PREVIEW", "1600"))

# --- Mapa / usuario ---
# Si la última actualización de una cámara es más vieja que esto, se
# muestra como "SIN DATOS" en vez de mostrar un estado viejo.
MINUTOS_SIN_DATOS = float(os.environ.get("MINUTOS_SIN_DATOS", "10"))
RADIO_DEFAULT_M = float(os.environ.get("RADIO_DEFAULT_M", "500"))

# --- Recepción de fotos ---
MAX_BYTES_FOTO = int(os.environ.get("MAX_BYTES_FOTO", str(20 * 1024 * 1024)))
# Si el detector no da abasto (o está apagado), cada cámara guarda como máximo
# estas fotos esperando: al llegar una nueva se borran las más viejas. Sin tope,
# la carpeta fotos/ crece sin parar. 0 = sin tope.
MAX_FOTOS_EN_COLA = int(os.environ.get("MAX_FOTOS_EN_COLA", "30"))

# --- Base de datos ---
# El historial guarda una fila por foto procesada de cada cámara. Se borran las
# de más de estos días (0 = guardar todo).
HISTORIAL_DIAS = int(os.environ.get("HISTORIAL_DIAS", "30"))
