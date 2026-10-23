"""
Manejo de las carpetas de cámaras. Cada cámara es una carpeta dentro de
camaras/ con esta forma:

    camaras/<id>/
        camara.json     datos de la cámara (nombre, ubicación, cuadra, api_key...)
        espacios.json   polígonos de los lugares (formato de calibrar_espacios.py)
        referencia.jpg  foto sobre la que se delimitaron los lugares
        fotos/          carpeta que revisa el detector (fotos nuevas)
        procesadas/     fotos ya analizadas
        preview.jpg     última foto analizada con todo dibujado

La carpeta es la fuente de verdad de la configuración; la base de datos
tiene un índice que se sincroniza con sincronizar_db().
"""

import json
import re
import secrets
import shutil
from datetime import datetime

import cv2
import numpy as np

import config
from base_de_datos import db

ID_VALIDO = re.compile(r"^[a-z0-9_]{1,40}$")
TIPOS_ESPACIO = {"valido", "prohibido"}


class ErrorCamara(ValueError):
    pass


# --- Rutas -----------------------------------------------------------------

def carpeta(camara_id):
    if not ID_VALIDO.match(camara_id or ""):
        raise ErrorCamara("ID de cámara inválido: usá minúsculas, números y _ (ej. camara_2)")
    return config.CARPETA_CAMARAS / camara_id


def ruta_fotos(camara_id):
    return carpeta(camara_id) / "fotos"


def ruta_procesadas(camara_id):
    return carpeta(camara_id) / "procesadas"


def ruta_referencia(camara_id):
    return carpeta(camara_id) / "referencia.jpg"


def ruta_preview(camara_id):
    return carpeta(camara_id) / "preview.jpg"


def ruta_espacios(camara_id):
    return carpeta(camara_id) / "espacios.json"


def existe(camara_id):
    return (carpeta(camara_id) / "camara.json").exists()


def listar_ids():
    if not config.CARPETA_CAMARAS.exists():
        return []
    return sorted(
        c.name for c in config.CARPETA_CAMARAS.iterdir()
        if c.is_dir() and ID_VALIDO.match(c.name) and (c / "camara.json").exists()
    )


def siguiente_id():
    usados = set(listar_ids())
    n = 1
    while f"camara_{n}" in usados:
        n += 1
    return f"camara_{n}"


# --- Lectura / escritura ---------------------------------------------------

def _leer_json(ruta, default):
    if not ruta.exists():
        return default
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _escribir_json(ruta, data):
    tmp = ruta.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(ruta)


def leer_camara(camara_id):
    cam = _leer_json(carpeta(camara_id) / "camara.json", None)
    if cam is None:
        raise ErrorCamara(f"No existe la cámara {camara_id}")
    return cam


def leer_espacios(camara_id):
    espacios = _leer_json(ruta_espacios(camara_id), [])
    for e in espacios:
        e.setdefault("tipo", "valido")  # compatibilidad con calibraciones viejas
    return espacios


def total_lugares(espacios):
    return sum(1 for e in espacios if e["tipo"] == "valido")


def generar_api_key():
    return secrets.token_urlsafe(18)


# --- Validaciones ----------------------------------------------------------

def validar_datos(datos):
    """Normaliza y valida los datos editables de una cámara."""
    nombre = str(datos.get("nombre", "")).strip()
    if not nombre:
        raise ErrorCamara("Falta el nombre de la cámara / cuadra")
    try:
        lat, lng = float(datos["lat"]), float(datos["lng"])
    except (KeyError, TypeError, ValueError):
        raise ErrorCamara("Falta la ubicación de la cámara (marcala en el mapa)")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ErrorCamara("Ubicación fuera de rango")

    cuadra = datos.get("cuadra")
    if cuadra:
        try:
            cuadra = [[float(p[0]), float(p[1])] for p in cuadra]
        except (TypeError, ValueError, IndexError):
            raise ErrorCamara("Los extremos de la cuadra no son válidos")
        if len(cuadra) != 2:
            raise ErrorCamara("La cuadra se marca con 2 puntos: inicio y fin")
    else:
        cuadra = None

    return {
        "nombre": nombre,
        "direccion": str(datos.get("direccion", "")).strip(),
        "lat": lat,
        "lng": lng,
        "cuadra": cuadra,
        "activa": bool(datos.get("activa", True)),
    }


def validar_espacios(espacios, ancho, alto):
    """Revisa los polígonos y les asigna IDs ordenados (espacio_N / prohibido_N),
    igual que calibrar_espacios.py."""
    if not isinstance(espacios, list):
        raise ErrorCamara("Los espacios tienen que ser una lista de polígonos")
    contador = {"valido": 0, "prohibido": 0}
    limpios = []
    for esp in espacios:
        tipo = esp.get("tipo", "valido")
        if tipo not in TIPOS_ESPACIO:
            raise ErrorCamara(f"Tipo de espacio inválido: {tipo}")
        try:
            puntos = [[int(round(float(x))), int(round(float(y)))] for x, y in esp["puntos"]]
        except (KeyError, TypeError, ValueError):
            raise ErrorCamara("Hay un polígono con puntos inválidos")
        if len(puntos) < 3:
            raise ErrorCamara("Cada polígono necesita al menos 3 puntos")
        if ancho and alto:
            puntos = [[min(max(x, 0), ancho - 1), min(max(y, 0), alto - 1)] for x, y in puntos]
        contador[tipo] += 1
        prefijo = "espacio" if tipo == "valido" else "prohibido"
        limpios.append({"id": f"{prefijo}_{contador[tipo]}", "puntos": puntos, "tipo": tipo})
    if contador["valido"] == 0:
        raise ErrorCamara("Delimitá al menos un lugar válido")
    return limpios


def decodificar_imagen(contenido):
    """Devuelve (extension, ancho, alto) si los bytes son un JPG/PNG legible."""
    if contenido[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif contenido[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    else:
        raise ErrorCamara("La imagen tiene que ser JPG o PNG (si es de iPhone, puede ser HEIC: convertila)")
    img = cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ErrorCamara("No se pudo leer la imagen (¿archivo corrupto?)")
    alto, ancho = img.shape[:2]
    return ext, ancho, alto, img


# --- Alta / edición / baja -------------------------------------------------

def crear(camara_id, datos, espacios, referencia_bytes):
    carp = carpeta(camara_id)
    if existe(camara_id):
        raise ErrorCamara(f"Ya existe una cámara con ID {camara_id}")
    datos = validar_datos(datos)
    _, ancho, alto, img = decodificar_imagen(referencia_bytes)
    espacios = validar_espacios(espacios, ancho, alto)

    (carp / "fotos").mkdir(parents=True, exist_ok=True)
    (carp / "procesadas").mkdir(exist_ok=True)
    cv2.imwrite(str(ruta_referencia(camara_id)), img)
    _escribir_json(ruta_espacios(camara_id), espacios)
    cam = {
        "id": camara_id,
        **datos,
        "api_key": generar_api_key(),
        "referencia": {"ancho": ancho, "alto": alto},
        "creada_en": db.ahora_iso(),
    }
    _escribir_json(carp / "camara.json", cam)
    sincronizar_una(camara_id)
    return cam


def actualizar_datos(camara_id, datos):
    cam = leer_camara(camara_id)
    cam.update(validar_datos(datos))
    _escribir_json(carpeta(camara_id) / "camara.json", cam)
    sincronizar_una(camara_id)
    return cam


def actualizar_referencia(camara_id, contenido):
    """Reemplaza la foto de referencia. Devuelve (ancho, alto)."""
    cam = leer_camara(camara_id)
    _, ancho, alto, img = decodificar_imagen(contenido)
    cv2.imwrite(str(ruta_referencia(camara_id)), img)
    cam["referencia"] = {"ancho": ancho, "alto": alto}
    _escribir_json(carpeta(camara_id) / "camara.json", cam)
    return ancho, alto


def fotos_pendientes(camara_id):
    carp = ruta_fotos(camara_id)
    if not carp.exists():
        return 0
    return sum(1 for p in carp.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})


def recortar_pendientes(camara_id, maximo=None):
    """Si hay más de `maximo` fotos esperando al detector (default
    config.MAX_FOTOS_EN_COLA), borra las más viejas. Devuelve cuántas borró."""
    maximo = config.MAX_FOTOS_EN_COLA if maximo is None else maximo
    carp = ruta_fotos(camara_id)
    if maximo <= 0 or not carp.exists():
        return 0
    fotos = sorted((p for p in carp.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}),
                   key=lambda p: p.stat().st_mtime)
    borradas = 0
    for vieja in fotos[:max(0, len(fotos) - maximo)]:
        try:
            vieja.unlink()
            borradas += 1
        except OSError:
            pass  # el detector la estaba moviendo justo ahora
    return borradas


def guardar_foto(camara_id, contenido):
    """Deja una foto nueva en camaras/<id>/fotos/ para que la procese el
    detector. Se escribe con otro nombre y después se renombra, para que el
    detector nunca lea un archivo a medio escribir. Si ya se acumulan más de
    config.MAX_FOTOS_EN_COLA se descartan las más viejas. Devuelve el nombre."""
    if len(contenido) > config.MAX_BYTES_FOTO:
        raise ErrorCamara("La foto es demasiado grande")
    ext, _, _, _ = decodificar_imagen(contenido)
    carp = ruta_fotos(camara_id)
    carp.mkdir(parents=True, exist_ok=True)
    nombre = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ext
    tmp = carp / (nombre + ".subiendo")
    tmp.write_bytes(contenido)
    tmp.replace(carp / nombre)
    recortar_pendientes(camara_id)
    return nombre


def ultima_foto_recibida(camara_id):
    candidatas = []
    for sub in (ruta_fotos(camara_id), ruta_procesadas(camara_id)):
        if sub.exists():
            candidatas += [p for p in sub.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    return max(candidatas, key=lambda p: p.stat().st_mtime) if candidatas else None


def actualizar_espacios(camara_id, espacios):
    cam = leer_camara(camara_id)
    ref = cam.get("referencia") or {}
    espacios = validar_espacios(espacios, ref.get("ancho"), ref.get("alto"))
    _escribir_json(ruta_espacios(camara_id), espacios)
    with db.conectar() as conn:
        db.borrar_estado(conn, camara_id)  # el estado anterior era de otros polígonos
    sincronizar_una(camara_id)
    return espacios


def regenerar_api_key(camara_id):
    cam = leer_camara(camara_id)
    cam["api_key"] = generar_api_key()
    _escribir_json(carpeta(camara_id) / "camara.json", cam)
    sincronizar_una(camara_id)
    return cam["api_key"]


def eliminar(camara_id):
    carp = carpeta(camara_id)
    if not existe(camara_id):
        raise ErrorCamara(f"No existe la cámara {camara_id}")
    shutil.rmtree(carp)
    with db.conectar() as conn:
        db.borrar_camara(conn, camara_id)


# --- Sincronización carpetas -> base de datos ------------------------------

def sincronizar_una(camara_id):
    cam = leer_camara(camara_id)
    with db.conectar() as conn:
        db.guardar_camara(conn, cam, total_lugares(leer_espacios(camara_id)))


def sincronizar_db():
    """Carga en la tabla `camaras` todas las carpetas, y saca de la base
    las cámaras cuya carpeta ya no existe."""
    ids = listar_ids()
    with db.conectar() as conn:
        for camara_id in ids:
            db.guardar_camara(conn, leer_camara(camara_id), total_lugares(leer_espacios(camara_id)))
        for viejo in set(db.ids_camaras(conn)) - set(ids):
            db.borrar_camara(conn, viejo)
    return ids
