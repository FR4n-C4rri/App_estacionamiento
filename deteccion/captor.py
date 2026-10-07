"""
Captor: el modo en que el SERVIDOR va a buscar la imagen a la cámara (en
vez de que la cámara la mande). Pensado para cámaras de seguridad IP, que
no pueden correr programas pero sí exponen su imagen por la red.

Cada cámara dice de dónde salen sus fotos en camara.json -> "fuente":

  {"tipo": "envio"}
      La cámara manda las fotos con un POST y su API key. El captor no hace nada.

  {"tipo": "video", "url": "rtsp://usuario:clave@192.168.0.50:554/Streaming/Channels/101", "intervalo": 10}
      Cualquier cosa que abra OpenCV: RTSP, stream HTTP/MJPEG (ej. IP Webcam
      http://ip:8080/video), un número de webcam ("0") o un archivo de video
      (útil para simular una cámara: se lee como si fuera en vivo, en loop).

  {"tipo": "foto", "url": "http://usuario:clave@192.168.0.50/ISAPI/Streaming/channels/101/picture", "intervalo": 10}
      Una URL que devuelve una foto JPG por pedido (snapshot ONVIF, o
      http://ip:8080/shot.jpg en IP Webcam). Soporta usuario/clave en la URL
      (autenticación Basic y Digest, la que usan Hikvision/Dahua).

Por cada cámara de tipo video/foto corre un hilo que cada `intervalo`
segundos saca una foto y la deja en camaras/<id>/fotos/. De ahí en
adelante es igual que una foto enviada: la procesa deteccion/detector.py.
Si el detector viene atrasado (ya hay varias fotos esperando), el captor
saltea esa captura para no acumular.
"""

import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import cv2

import config
import gestor_camaras as gc
from base_de_datos import db

# RTSP por TCP: más estable que UDP a través de routers y redes con pérdida.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

TIMEOUT_S = 15
CALIDAD_JPG = 90

# Estado de captura por cámara, para mostrarlo en el admin:
# id -> {"tipo", "ultima_captura" (iso), "error" (str o None), "salteadas"}
ESTADO = {}


class ErrorCaptura(Exception):
    pass


# --- Captura de una foto -----------------------------------------------------

def _sin_credenciales(url):
    """Separa usuario y clave de la URL: http://user:pass@host/x -> (http://host/x, user, pass)."""
    partes = urllib.parse.urlsplit(url)
    if not partes.username:
        return url, None, None
    host = partes.hostname + (f":{partes.port}" if partes.port else "")
    limpia = urllib.parse.urlunsplit((partes.scheme, host, partes.path, partes.query, partes.fragment))
    return limpia, urllib.parse.unquote(partes.username), urllib.parse.unquote(partes.password or "")


def url_para_mostrar(url):
    """La URL sin la contraseña, para logs y pantallas."""
    partes = urllib.parse.urlsplit(url)
    if not partes.password:
        return url
    host = f"{partes.username}:***@{partes.hostname}" + (f":{partes.port}" if partes.port else "")
    return urllib.parse.urlunsplit((partes.scheme, host, partes.path, partes.query, partes.fragment))


def capturar_foto_http(url):
    limpia, usuario, clave = _sin_credenciales(url)
    manejadores = []
    if usuario is not None:
        claves = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        claves.add_password(None, limpia, usuario, clave)
        manejadores = [urllib.request.HTTPDigestAuthHandler(claves), urllib.request.HTTPBasicAuthHandler(claves)]
    abridor = urllib.request.build_opener(*manejadores)
    try:
        with abridor.open(limpia, timeout=TIMEOUT_S) as resp:
            contenido = resp.read(config.MAX_BYTES_FOTO + 1)
    except Exception as e:
        raise ErrorCaptura(f"No pude bajar la foto: {e}") from None
    return contenido


def _abrir_video(url):
    if url.isdigit():
        return cv2.VideoCapture(int(url))
    parametros = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_S * 1000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_S * 1000]
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, parametros)


def capturar_video(url):
    cap = _abrir_video(url)
    try:
        if not cap.isOpened():
            raise ErrorCaptura("No pude abrir el video (¿dirección, usuario/clave o red?)")
        if Path(url).is_file():
            # Archivo de video: se simula una cámara en vivo yendo al momento
            # que corresponde a la hora actual (en loop).
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            cuadros = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1
            duracion_ms = max(1.0, cuadros / fps * 1000)
            cap.set(cv2.CAP_PROP_POS_MSEC, (time.time() * 1000) % duracion_ms)
        else:
            # Stream en vivo: se descartan algunos cuadros del buffer para no
            # quedarse con una imagen vieja.
            for _ in range(5):
                cap.grab()
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ErrorCaptura("Se abrió el video pero no llegó ninguna imagen")
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, CALIDAD_JPG])
        if not ok:
            raise ErrorCaptura("No pude convertir la imagen a JPG")
        return jpg.tobytes()
    finally:
        cap.release()


def capturar(fuente):
    """Saca UNA foto de la fuente. Devuelve los bytes (JPG/PNG) o lanza ErrorCaptura."""
    if fuente["tipo"] == "foto":
        contenido = capturar_foto_http(fuente["url"])
    elif fuente["tipo"] == "video":
        contenido = capturar_video(fuente["url"])
    else:
        raise ErrorCaptura("Esta cámara manda sus propias fotos: no hay nada que buscar")
    try:
        gc.decodificar_imagen(contenido)
    except gc.ErrorCamara as e:
        raise ErrorCaptura(f"La cámara respondió algo que no es una foto válida: {e}") from None
    return contenido


# --- Hilos de captura --------------------------------------------------------

class Captor:
    def __init__(self, log=print, intervalo_revision=5):
        self.log = log
        self.intervalo_revision = intervalo_revision
        self.hilos = {}  # id -> {"fuente", "parar": Event, "hilo": Thread}
        self._parar = threading.Event()
        self._hilo = None

    def sincronizar(self):
        """Arranca / frena hilos según lo que diga cada camara.json."""
        deseadas = {}
        for camara_id in gc.listar_ids():
            try:
                cam = gc.leer_camara(camara_id)
            except Exception:
                continue
            fuente = gc.fuente_de(cam)
            if cam.get("activa", True) and fuente["tipo"] in ("video", "foto"):
                deseadas[camara_id] = fuente

        for camara_id in list(self.hilos):
            if self.hilos[camara_id]["fuente"] != deseadas.get(camara_id):
                self._frenar(camara_id)
        for camara_id, fuente in deseadas.items():
            if camara_id not in self.hilos:
                self._arrancar(camara_id, fuente)
        for camara_id in list(ESTADO):
            if camara_id not in deseadas:
                ESTADO.pop(camara_id, None)

    def _arrancar(self, camara_id, fuente):
        parar = threading.Event()
        hilo = threading.Thread(target=self._bucle, args=(camara_id, fuente, parar),
                                name=f"captor-{camara_id}", daemon=True)
        self.hilos[camara_id] = {"fuente": fuente, "parar": parar, "hilo": hilo}
        ESTADO[camara_id] = {"tipo": fuente["tipo"], "ultima_captura": None, "error": None, "salteadas": 0}
        self.log(f"[captor] {camara_id}: tomo una foto cada {fuente['intervalo']:g}s de {url_para_mostrar(fuente['url'])}")
        hilo.start()

    def _frenar(self, camara_id):
        datos = self.hilos.pop(camara_id)
        datos["parar"].set()
        self.log(f"[captor] {camara_id}: dejo de tomar fotos")

    def _bucle(self, camara_id, fuente, parar):
        estado = ESTADO[camara_id]
        while not parar.is_set():
            inicio = time.time()
            try:
                if gc.fotos_pendientes(camara_id) >= config.MAX_PENDIENTES:
                    estado["salteadas"] += 1  # el detector viene atrasado
                else:
                    gc.guardar_foto(camara_id, capturar(fuente))
                    estado["ultima_captura"] = db.ahora_iso()
                    if estado["error"]:
                        self.log(f"[captor] {camara_id}: volvió a andar")
                    estado["error"] = None
            except Exception as e:
                mensaje = str(e) or repr(e)
                if mensaje != estado["error"]:
                    self.log(f"[captor] {camara_id}: {mensaje}")
                estado["error"] = mensaje
            parar.wait(max(1.0, fuente["intervalo"] - (time.time() - inicio)))

    def correr(self):
        while not self._parar.is_set():
            try:
                self.sincronizar()
            except Exception as e:
                self.log(f"[captor] Error revisando cámaras: {e!r}")
            self._parar.wait(self.intervalo_revision)

    def iniciar_en_segundo_plano(self):
        self._hilo = threading.Thread(target=self.correr, name="captor", daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()
        for camara_id in list(self.hilos):
            self._frenar(camara_id)
