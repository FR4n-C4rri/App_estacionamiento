"""Tests del modo en que el servidor va a buscar la foto a la cámara."""

import base64
import http.server
import os
import sys
import threading
import time
import types
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
import servidores_falsos as falsos  # noqa: E402

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


def test_video_de_archivo_lee_bien_en_cualquier_momento_del_loop(video, monkeypatch):
    """Antes, caer en la última fracción del archivo (aquí los últimos 50 ms de
    2000) dejaba el cursor pasado el último cuadro y la captura fallaba con
    'no llegó ninguna imagen'. Se recorre todo el loop, con la hora cada 20 ms."""
    ahora = {"ms": 0.0}
    monkeypatch.setattr(captor, "time", types.SimpleNamespace(time=lambda: ahora["ms"] / 1000,
                                                              monotonic=time.monotonic))
    fallas = []
    for ms in range(0, 4000, 20):
        ahora["ms"] = float(ms)
        try:
            captor.capturar({"tipo": "video", "url": str(video), "intervalo": 10})
        except captor.ErrorCaptura:
            fallas.append(ms)
    assert fallas == []


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


# --- Lo que usan las cámaras IP de verdad -------------------------------------
# Cámaras de mentira (tests/servidores_falsos.py) que hablan el mismo protocolo:
# snapshot con Digest (Hikvision/Dahua), stream MJPEG (IP Webcam) y RTSP sobre TCP.

necesita_ffmpeg = pytest.mark.skipif(not falsos.hay_ffmpeg(), reason="hace falta ffmpeg para simular una cámara RTSP")


def esperar(condicion, segundos=10):
    limite = time.time() + segundos
    while not condicion() and time.time() < limite:
        time.sleep(0.1)
    return condicion()


def test_snapshot_con_autenticacion_digest():
    with falsos.servidor_snapshot("admin", "clave123", auth="digest") as srv:
        contenido = captor.capturar({"tipo": "foto", "url": f"http://admin:clave123@{srv.host}/snapshot.jpg"})
        assert gc.decodificar_imagen(contenido)[1:3] == (320, 240)
        with pytest.raises(captor.ErrorCaptura):
            captor.capturar({"tipo": "foto", "url": f"http://admin:mala@{srv.host}/snapshot.jpg"})


def test_snapshot_sin_clave_en_una_camara_que_la_pide():
    with falsos.servidor_snapshot("admin", "clave123") as srv:
        with pytest.raises(captor.ErrorCaptura, match="No pude bajar la foto"):
            captor.capturar({"tipo": "foto", "url": f"http://{srv.host}/snapshot.jpg"})


def test_snapshot_que_devuelve_algo_que_no_es_una_foto():
    with falsos.servidor_snapshot(contenido=b"<html>login</html>", tipo_contenido="text/html") as srv:
        with pytest.raises(captor.ErrorCaptura, match="no es una foto"):
            captor.capturar({"tipo": "foto", "url": f"http://{srv.host}/snapshot.jpg"})


def test_snapshot_de_una_camara_que_no_responde():
    with pytest.raises(captor.ErrorCaptura, match="No pude bajar la foto"):
        captor.capturar({"tipo": "foto", "url": "http://127.0.0.1:1/snapshot.jpg"})


def test_video_http_en_vivo_tipo_ip_webcam():
    with falsos.servidor_mjpeg() as srv:
        contenido = captor.capturar({"tipo": "video", "url": f"http://{srv.host}/video", "intervalo": 10})
    assert gc.decodificar_imagen(contenido)[1:3] == (320, 240)


@necesita_ffmpeg
def test_video_rtsp_sin_clave():
    with falsos.ServidorRTSP() as srv:
        contenido = captor.capturar({"tipo": "video", "url": f"rtsp://127.0.0.1:{srv.puerto}/live", "intervalo": 10})
        assert srv.sesiones == 1
    assert gc.decodificar_imagen(contenido)[1:3] == (320, 240)


@necesita_ffmpeg
def test_video_rtsp_con_usuario_y_clave():
    with falsos.ServidorRTSP("admin", "clave123") as srv:
        url = f"rtsp://admin:clave123@127.0.0.1:{srv.puerto}/live"
        assert gc.decodificar_imagen(captor.capturar({"tipo": "video", "url": url, "intervalo": 10}))[1:3] == (320, 240)
        with pytest.raises(captor.ErrorCaptura, match="usuario/clave"):
            captor.capturar({"tipo": "video", "url": url.replace("clave123", "mala"), "intervalo": 10})


@necesita_ffmpeg
def test_video_rtsp_que_abre_pero_no_manda_imagenes_no_se_cuelga(monkeypatch):
    """Una cámara ocupada o con el perfil equivocado abre la conexión y no manda
    nada. Antes la captura esperaba cada cuadro hasta 15 s (más de un minuto)."""
    monkeypatch.setattr(captor, "TIMEOUT_S", 3)
    monkeypatch.setattr(captor, "TIMEOUT_LECTURA_S", 2)
    monkeypatch.setattr(captor, "PRESUPUESTO_VIDEO_S", 6)
    with falsos.ServidorRTSP(sin_video=True) as srv:
        inicio = time.monotonic()
        with pytest.raises(captor.ErrorCaptura, match="ninguna imagen|No pude abrir"):
            captor.capturar({"tipo": "video", "url": f"rtsp://127.0.0.1:{srv.puerto}/live", "intervalo": 10})
    assert time.monotonic() - inicio < 12


def test_captor_con_url_de_foto_deja_fotos_y_avisa_si_la_camara_se_cae():
    with falsos.servidor_snapshot() as srv:
        gc.crear("camara_1", {"nombre": "x", "lat": 0, "lng": 0,
                              "fuente": {"tipo": "foto", "url": f"http://{srv.host}/s.jpg", "intervalo": 2}},
                 ESPACIOS, foto_jpg())
        c = captor.Captor(log=lambda *_: None)
        c.sincronizar()
        try:
            # Se espera el estado y no el archivo: el hilo lo anota un instante después de guardar la foto.
            assert esperar(lambda: captor.ESTADO["camara_1"]["ultima_captura"])
            assert captor.ESTADO["camara_1"]["error"] is None and gc.fotos_pendientes("camara_1") >= 1
            srv.srv.shutdown()                  # la cámara deja de contestar
            srv.srv.server_close()
            assert esperar(lambda: captor.ESTADO["camara_1"]["error"], segundos=15)
        finally:
            c.detener()


# --- Panel admin ----------------------------------------------------------------

@pytest.fixture
def cliente():
    from fastapi.testclient import TestClient
    from servidor.main import app

    with TestClient(app) as c:
        yield c


def encabezado_admin(cliente):
    token = cliente.post("/api/admin/login", json={"password": config.ADMIN_PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_el_admin_prueba_la_conexion_y_recibe_la_foto(cliente):
    h = encabezado_admin(cliente)
    with falsos.servidor_snapshot("admin", "clave123", auth="digest") as srv:
        r = cliente.post("/api/admin/probar_fuente", headers=h,
                         json={"tipo": "foto", "url": f"http://admin:clave123@{srv.host}/s.jpg"})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert gc.decodificar_imagen(r.content)[1:3] == (320, 240)
        mala = cliente.post("/api/admin/probar_fuente", headers=h,
                            json={"tipo": "foto", "url": f"http://admin:mala@{srv.host}/s.jpg"})
        assert mala.status_code == 400
    assert cliente.post("/api/admin/probar_fuente", headers=h, json={"tipo": "foto", "url": "rtsp://x"}).status_code == 400
    assert cliente.post("/api/admin/probar_fuente", json={"tipo": "foto", "url": "http://x"}).status_code == 401


def test_el_admin_no_muestra_la_clave_de_la_camara_en_la_lista(cliente):
    gc.crear("camara_1", {"nombre": "x", "lat": 0, "lng": 0,
                          "fuente": {"tipo": "video", "url": "rtsp://admin:secreta@10.0.0.5/stream"}},
             ESPACIOS, foto_jpg())
    lista = cliente.get("/api/admin/camaras", headers=encabezado_admin(cliente)).json()
    assert lista[0]["fuente"]["url"] == "rtsp://admin:***@10.0.0.5/stream"
    assert "secreta" not in str(lista)
