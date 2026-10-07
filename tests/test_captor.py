"""Tests del modo en que el servidor va a buscar la foto a la cámara."""

import base64
import http.server
import os
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["DETECTOR"] = "off"
os.environ["CAPTOR"] = "off"

import config  # noqa: E402
import gestor_camaras as gc  # noqa: E402
from base_de_datos import db  # noqa: E402
from deteccion import captor  # noqa: E402

ESPACIOS = [{"tipo": "valido", "puntos": [[10, 10], [100, 10], [100, 60]]}]


def foto_jpg():
    img = np.full((240, 320, 3), 120, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


@pytest.fixture(autouse=True)
def entorno_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CARPETA_CAMARAS", tmp_path / "camaras")
    monkeypatch.setattr(config, "RUTA_DB", tmp_path / "test.db")
    db.crear_tablas()


@pytest.fixture
def video(tmp_path):
    ruta = tmp_path / "cuadra.avi"
    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    for i in range(20):
        escritor.write(np.full((240, 320, 3), i * 10, np.uint8))
    escritor.release()
    return ruta


@pytest.fixture
def servidor_snapshot():
    """Servidor HTTP que imita el snapshot de una cámara IP con usuario/clave (Basic)."""
    contenido = foto_jpg()
    esperado = "Basic " + base64.b64encode(b"admin:clave123").decode()

    class Manejador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") != esperado:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="camara"')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(contenido)))
            self.end_headers()
            self.wfile.write(contenido)

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{srv.server_port}"
    srv.shutdown()


# --- Validación ---

def test_validar_fuente():
    assert gc.validar_fuente(None) == {"tipo": "envio"}
    assert gc.validar_fuente({"tipo": "video", "url": "rtsp://ip/x"}) == {"tipo": "video", "url": "rtsp://ip/x", "intervalo": 10.0}
    assert gc.validar_fuente({"tipo": "video", "url": "0", "intervalo": "5"})["intervalo"] == 5.0
    for mala in ({"tipo": "foto", "url": "rtsp://ip/x"},           # foto tiene que ser http
                 {"tipo": "video", "url": "no-existe.mp4"},       # archivo inexistente
                 {"tipo": "video", "url": ""},
                 {"tipo": "video", "url": "rtsp://ip", "intervalo": 1},
                 {"tipo": "otra"}):
        with pytest.raises(gc.ErrorCamara):
            gc.validar_fuente(mala)


def test_editar_sin_fuente_no_la_pisa():
    gc.crear("camara_1", {"nombre": "x", "lat": 0, "lng": 0,
                          "fuente": {"tipo": "foto", "url": "http://ip/shot.jpg"}}, ESPACIOS, foto_jpg())
    gc.actualizar_datos("camara_1", {"nombre": "y", "lat": 0, "lng": 0, "activa": False})
    assert gc.leer_camara("camara_1")["fuente"]["tipo"] == "foto"


def test_url_para_mostrar_oculta_la_clave():
    assert captor.url_para_mostrar("rtsp://admin:secreta@1.2.3.4:554/a") == "rtsp://admin:***@1.2.3.4:554/a"
    assert captor.url_para_mostrar("http://1.2.3.4/a") == "http://1.2.3.4/a"


# --- Captura ---

def test_captura_de_archivo_de_video(video):
    contenido = captor.capturar({"tipo": "video", "url": str(video), "intervalo": 10})
    _, ancho, alto, _ = gc.decodificar_imagen(contenido)
    assert (ancho, alto) == (320, 240)


def test_captura_http_con_usuario_y_clave(servidor_snapshot):
    contenido = captor.capturar({"tipo": "foto", "url": f"http://admin:clave123@{servidor_snapshot}/shot.jpg"})
    assert gc.decodificar_imagen(contenido)[1:3] == (320, 240)
    with pytest.raises(captor.ErrorCaptura):
        captor.capturar({"tipo": "foto", "url": f"http://admin:mala@{servidor_snapshot}/shot.jpg"})


def test_video_inexistente_da_error_claro():
    with pytest.raises(captor.ErrorCaptura):
        captor.capturar({"tipo": "video", "url": "rtsp://127.0.0.1:1/nada", "intervalo": 10})


def test_captor_deja_fotos_en_la_carpeta(video, monkeypatch):
    monkeypatch.setattr(config, "MAX_PENDIENTES", 2)
    gc.crear("camara_1", {"nombre": "x", "lat": 0, "lng": 0,
                          "fuente": {"tipo": "video", "url": str(video), "intervalo": 2}}, ESPACIOS, foto_jpg())
    gc.crear("camara_2", {"nombre": "y", "lat": 0, "lng": 0}, ESPACIOS, foto_jpg())  # tipo envio: no se toca

    c = captor.Captor(log=lambda *_: None)
    c.sincronizar()
    try:
        assert set(c.hilos) == {"camara_1"}
        limite = time.time() + 10
        while gc.fotos_pendientes("camara_1") < 2 and time.time() < limite:
            time.sleep(0.2)
        assert gc.fotos_pendientes("camara_1") == 2          # no pasa de MAX_PENDIENTES
        assert gc.fotos_pendientes("camara_2") == 0
        assert captor.ESTADO["camara_1"]["error"] is None

        # Al desactivar la cámara, el captor la deja de seguir.
        gc.actualizar_datos("camara_1", {"nombre": "x", "lat": 0, "lng": 0, "activa": False})
        c.sincronizar()
        assert c.hilos == {}
    finally:
        c.detener()
