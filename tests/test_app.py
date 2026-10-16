"""
Tests sin modelo YOLO (el detector se desactiva). Correr desde la raíz:

    py -m pytest
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["DETECTOR"] = "off"
os.environ["ADMIN_PASSWORD"] = "clave-test"

import config  # noqa: E402
import gestor_camaras as gc  # noqa: E402
from base_de_datos import db  # noqa: E402
from deteccion import estado_vehiculos as ev  # noqa: E402
from servidor.geo import distancia_m  # noqa: E402

ESPACIOS = [
    {"tipo": "valido", "puntos": [[10, 10], [100, 10], [100, 60], [10, 60]]},
    {"tipo": "valido", "puntos": [[120, 10], [200, 10], [200, 60], [120, 60]]},
    {"tipo": "prohibido", "puntos": [[10, 80], [100, 80], [100, 120]]},
]


def foto_jpg(ancho=320, alto=240):
    ok, buf = cv2.imencode(".jpg", np.zeros((alto, ancho, 3), np.uint8))
    return buf.tobytes()


@pytest.fixture(autouse=True)
def entorno_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CARPETA_CAMARAS", tmp_path / "camaras")
    monkeypatch.setattr(config, "RUTA_DB", tmp_path / "test.db")
    db.crear_tablas()


def crear_camara(camara_id="camara_1", lat=-34.6, lng=-58.44):
    return gc.crear(camara_id, {"nombre": f"Cuadra {camara_id}", "lat": lat, "lng": lng,
                                "cuadra": [[lat, lng - 0.0005], [lat, lng + 0.0005]]},
                    ESPACIOS, foto_jpg())


# --- Lógica pura ---

def test_distancia_haversine():
    # 0.001° de latitud ~ 111 m
    assert distancia_m(-34.6, -58.44, -34.601, -58.44) == pytest.approx(111.2, abs=0.5)
    assert distancia_m(-34.6, -58.44, -34.6, -58.44) == 0


def test_estado_semaforo():
    assert ev.estado_semaforo(0)[0] == "HAY LUGAR"
    assert ev.estado_semaforo(50)[0] == "CASI LLENO"
    assert ev.estado_semaforo(80)[0] == "LLENO"


def test_escalar_espacios():
    esc = ev.escalar_espacios(ESPACIOS, (320, 240), (640, 480))
    assert esc[0]["puntos"][1] == [200, 20]
    assert ev.escalar_espacios(ESPACIOS, (320, 240), (320, 240)) is ESPACIOS


def test_racha_de_ocupacion():
    oc = ev.OcupacionEspacios()
    assert oc.actualizar("e1", "car", 0) == 0
    assert oc.actualizar("e1", "car", 50) == 50
    oc.liberar("e1")  # un hueco corta la racha
    assert oc.actualizar("e1", "car", 60) == 0


# --- Carpetas de cámaras + base ---

def test_crear_camara_arma_carpeta_y_db():
    cam = crear_camara()
    carpeta = config.CARPETA_CAMARAS / "camara_1"
    for nombre in ("camara.json", "espacios.json", "referencia.jpg", "fotos", "procesadas"):
        assert (carpeta / nombre).exists()
    espacios = json.loads((carpeta / "espacios.json").read_text(encoding="utf-8"))
    assert [e["id"] for e in espacios] == ["espacio_1", "espacio_2", "prohibido_1"]
    assert cam["referencia"] == {"ancho": 320, "alto": 240}
    with db.conectar() as conn:
        fila = conn.execute("SELECT total_lugares FROM camaras WHERE id='camara_1'").fetchone()
    assert fila["total_lugares"] == 2


def test_validaciones():
    with pytest.raises(gc.ErrorCamara):
        gc.crear("Camara Mal", {"nombre": "x", "lat": 0, "lng": 0}, ESPACIOS, foto_jpg())
    with pytest.raises(gc.ErrorCamara):
        gc.crear("camara_9", {"nombre": "x", "lat": 0, "lng": 0}, [ESPACIOS[2]], foto_jpg())
    with pytest.raises(gc.ErrorCamara):
        gc.crear("camara_9", {"nombre": "x", "lat": 0, "lng": 0}, ESPACIOS, b"no es imagen")
    crear_camara()
    with pytest.raises(gc.ErrorCamara):
        crear_camara()


def test_sincronizar_borra_camaras_sin_carpeta():
    crear_camara("camara_1")
    crear_camara("camara_2")
    import shutil
    shutil.rmtree(config.CARPETA_CAMARAS / "camara_2")
    assert gc.sincronizar_db() == ["camara_1"]
    with db.conectar() as conn:
        assert db.ids_camaras(conn) == ["camara_1"]


# --- API ---

@pytest.fixture
def cliente():
    from fastapi.testclient import TestClient
    from servidor.main import app

    with TestClient(app) as c:
        yield c


def test_cerca_filtra_por_radio_y_calcula_libres(cliente):
    crear_camara("camara_1", -34.6, -58.44)
    crear_camara("camara_2", -34.7, -58.44)  # ~11 km
    with db.conectar() as conn:
        db.guardar_estado(conn, "camara_1", gc.leer_espacios("camara_1"), {"espacio_1"}, {"prohibido_1"},
                          1, 2, 50.0, "CASI LLENO")
    r = cliente.get("/api/cerca", params={"lat": -34.601, "lng": -58.44, "radio": 500}).json()
    assert [c["id"] for c in r["cuadras"]] == ["camara_1"]
    c = r["cuadras"][0]
    assert (c["libres"], c["total"], c["estado"], c["prohibidos_bloqueados"]) == (1, 2, "CASI LLENO", 1)
    assert c["distancia_m"] == pytest.approx(111, abs=2)


def test_sin_datos_si_nunca_se_proceso(cliente):
    crear_camara()
    c = cliente.get("/api/cerca", params={"lat": -34.6, "lng": -58.44}).json()["cuadras"][0]
    assert c["estado"] == "SIN DATOS" and c["libres"] is None


def test_subida_de_foto_con_api_key(cliente):
    cam = crear_camara()
    url = "/api/camaras/camara_1/fotos"
    archivos = {"foto": ("f.jpg", foto_jpg(), "image/jpeg")}
    assert cliente.post(url, files=archivos, headers={"X-Camera-Key": "mala"}).status_code == 401
    r = cliente.post(url, files=archivos, headers={"X-Camera-Key": cam["api_key"]})
    assert r.status_code == 200
    assert len(list((config.CARPETA_CAMARAS / "camara_1" / "fotos").glob("*.jpg"))) == 1


def test_admin_alta_completa(cliente):
    assert cliente.post("/api/admin/login", json={"password": "mala"}).status_code == 401
    assert cliente.get("/api/admin/camaras").status_code == 401
    token = cliente.post("/api/admin/login", json={"password": "clave-test"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    assert cliente.get("/api/admin/siguiente_id", headers=h).json()["id"] == "camara_1"
    r = cliente.post("/api/admin/camaras", headers=h, data={
        "id": "camara_1",
        "datos": json.dumps({"nombre": "Nueva", "lat": -34.6, "lng": -58.44}),
        "espacios": json.dumps(ESPACIOS),
    }, files={"referencia": ("r.jpg", foto_jpg(), "image/jpeg")})
    assert r.status_code == 200, r.text
    assert r.json()["api_key"]

    nuevos = ESPACIOS[:1]
    assert cliente.put("/api/admin/camaras/camara_1/espacios", headers=h, json=nuevos).status_code == 200
    assert cliente.get("/api/admin/camaras", headers=h).json()[0]["total"] == 1

    assert cliente.delete("/api/admin/camaras/camara_1", headers=h).status_code == 200
    assert not (config.CARPETA_CAMARAS / "camara_1").exists()
