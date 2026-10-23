"""
Tests de la lógica de ocupación y del detector. No usan el modelo YOLO: se
reemplaza por uno de mentira que devuelve las cajas que cada test quiere.
Correr desde la raíz:

    python -m pytest tests/test_deteccion.py
"""

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["DETECTOR"] = "off"

import config  # noqa: E402
import gestor_camaras as gc  # noqa: E402
from base_de_datos import db  # noqa: E402
from deteccion import estado_vehiculos as ev  # noqa: E402
from deteccion.detector import Detector  # noqa: E402


def foto_jpg(ancho=320, alto=240, gris=120):
    return cv2.imencode(".jpg", np.full((alto, ancho, 3), gris, np.uint8))[1].tobytes()

CLASES = {"car": 0, "volquete": 1}
ID_A_NOMBRE = {0: "car", 1: "volquete"}


def rect(esp_id, x1, y1, x2, y2, tipo="valido"):
    return {"id": esp_id, "tipo": tipo, "puntos": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]}


# --- Caso real de la cámara de prueba (foto de 4032x3024) ---------------------
# Polígonos de espacio_3 y espacio_4, y la caja que el modelo dibujó sobre el
# auto negro estacionado en el espacio_4 (medida sobre el preview.jpg). El punto
# de apoyo de esa caja cae 7 px FUERA del polígono: con la regla anterior, ese
# auto estacionado nunca se contaba como ocupado.
ESPACIO_3 = {"id": "espacio_3", "tipo": "valido",
             "puntos": [[1176, 1724], [1154, 1814], [1823, 1799], [1853, 1724], [1173, 1724]]}
ESPACIO_4 = {"id": "espacio_4", "tipo": "valido",
             "puntos": [[1014, 1746], [859, 1837], [276, 1822], [325, 1739], [1010, 1731]]}
CAJA_AUTO_NEGRO = [312, 1542, 1043, 1840]

# --- Escena sintética para los tests de tiempo (foto de 800x600) ---------------
ESPACIOS_SIM = [
    rect("espacio_1", 100, 300, 300, 360),
    rect("espacio_2", 320, 300, 520, 360),
    rect("prohibido_1", 560, 300, 700, 360, "prohibido"),
]
AUTO = ([95, 230, 305, 355], 0)                  # un auto sobre espacio_1
VOLQUETE = ([95, 230, 305, 355], 1)              # un volquete sobre espacio_1
AUTO_EN_PROHIBIDO = ([555, 230, 705, 355], 0)


class _Lista(list):
    def tolist(self):
        return list(self)


class ModeloFalso:
    """Imita lo mínimo de ultralytics: model(frame, **kw)[0].boxes.xyxy / .cls.
    `detecciones`: función (n.º de foto) -> [(caja, id_clase), ...]."""

    def __init__(self, detecciones):
        self.detecciones = detecciones
        self.llamadas = []

    def __call__(self, frame, **kwargs):
        d = self.detecciones(len(self.llamadas))
        self.llamadas.append(kwargs)
        boxes = SimpleNamespace(xyxy=_Lista(c for c, _ in d), cls=_Lista(k for _, k in d))
        return [SimpleNamespace(boxes=boxes)]


def correr(modelo, espacios, tiempos, ocupacion=None):
    """Analiza una foto por cada instante de `tiempos` y devuelve los resultados."""
    ocupacion = ocupacion or ev.OcupacionEspacios(gracia_s=ev.GRACIA_S)
    geometria = ev.GeometriaEspacios(espacios)
    return [ev.analizar_foto(np.zeros((600, 800, 3), np.uint8), t, modelo, CLASES, ID_A_NOMBRE,
                             espacios, ocupacion, geometria) for t in tiempos]


def ocupados(resultados):
    return [r["ocupados"] for r in resultados]


@pytest.fixture(autouse=True)
def entorno_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CARPETA_CAMARAS", tmp_path / "camaras")
    monkeypatch.setattr(config, "RUTA_DB", tmp_path / "test.db")
    # Los tests no dependen de lo que haya en el .env de quien los corre.
    monkeypatch.setattr(ev, "HUELLA_FRAC", 0.5)
    monkeypatch.setattr(ev, "MIN_SOLAPE", 0.25)
    monkeypatch.setattr(ev, "GRACIA_S", 25.0)
    monkeypatch.setattr(ev, "IMGSZ", 0)
    db.crear_tablas()


# --- Reparto de detecciones en espacios (el problema de los espacios chicos) ----

def test_caso_real_el_auto_del_espacio_4_se_cuenta():
    # Con la regla anterior (solo el punto de apoyo) este auto quedaba afuera...
    assert not ev.punto_dentro(ev.punto_de_apoyo(CAJA_AUTO_NEGRO), ESPACIO_4["puntos"])
    # ...con la nueva, queda en su espacio, y no en el vecino.
    asignadas = ev.GeometriaEspacios([ESPACIO_3, ESPACIO_4]).asignar([CAJA_AUTO_NEGRO], ["car"])
    assert list(asignadas) == ["espacio_4"]
    nombre, cobertura = asignadas["espacio_4"]
    assert nombre == "car" and cobertura > 0.9


@pytest.mark.parametrize("dx", [-30, 0, 30])
@pytest.mark.parametrize("dy", range(-40, 41, 10))
def test_aguanta_el_vaiven_de_la_caja(dx, dy):
    """La caja del modelo se mueve unos píxeles de foto a foto: no puede decidir si el lugar está ocupado."""
    x1, y1, x2, y2 = CAJA_AUTO_NEGRO
    caja = [x1 + dx, y1, x2 + dx, y2 + dy]
    asignadas = ev.GeometriaEspacios([ESPACIO_3, ESPACIO_4]).asignar([caja], ["car"])
    assert list(asignadas) == ["espacio_4"]


def test_el_mismo_auto_corrido_al_lugar_vecino_cuenta_para_el_vecino():
    x1, y1, x2, y2 = CAJA_AUTO_NEGRO
    caja = [x1 + 800, y1, x2 + 800, y2]
    asignadas = ev.GeometriaEspacios([ESPACIO_3, ESPACIO_4]).asignar([caja], ["car"])
    assert list(asignadas) == ["espacio_3"]


def test_poligono_chico_dentro_de_un_auto_grande():
    chico = rect("espacio_1", 40, 190, 80, 215)   # 40x25 px, apenas un parche bajo el auto
    asignadas = ev.GeometriaEspacios([chico]).asignar([[0, 100, 200, 220]], ["car"])
    assert asignadas["espacio_1"][1] == pytest.approx(1.0)


def test_auto_chico_dentro_de_un_espacio_grande():
    grande = rect("espacio_1", 0, 0, 400, 200)
    asignadas = ev.GeometriaEspacios([grande]).asignar([[100, 50, 200, 150]], ["car"])
    assert asignadas["espacio_1"][1] == pytest.approx(1.0)


def test_un_auto_en_el_espacio_de_al_lado_no_cuenta():
    a, b = rect("espacio_1", 0, 100, 100, 160), rect("espacio_2", 110, 100, 210, 160)
    asignadas = ev.GeometriaEspacios([a, b]).asignar([[0, 40, 100, 150]], ["car"])
    assert list(asignadas) == ["espacio_1"]


def test_un_auto_entre_dos_espacios_cuenta_para_uno_solo():
    a, b = rect("espacio_1", 0, 100, 100, 160), rect("espacio_2", 100, 100, 200, 160)
    # 70 px sobre el primero y 30 px sobre el segundo
    asignadas = ev.GeometriaEspacios([a, b]).asignar([[30, 40, 130, 160]], ["car"])
    assert list(asignadas) == ["espacio_1"]


def test_si_hay_varias_detecciones_en_un_espacio_gana_la_que_mas_lo_cubre():
    espacio = rect("espacio_1", 0, 100, 100, 160)
    completa, parcial = [0, 40, 100, 160], [60, 40, 180, 160]
    asignadas = ev.GeometriaEspacios([espacio]).asignar([parcial, completa], ["car", "volquete"])
    assert asignadas["espacio_1"][0] == "volquete"


def test_sin_detecciones_no_asigna_nada():
    assert ev.GeometriaEspacios(ESPACIOS_SIM).asignar([], []) == {}


def test_el_solape_minimo_se_puede_ajustar(monkeypatch):
    espacio = rect("espacio_1", 0, 100, 100, 160)
    # La caja se pasa 80 px del espacio: su punto de apoyo (x=120) cae afuera y
    # cubre 1/3 de lo más chico entre el espacio y su huella.
    caja = [60, 100, 180, 160]
    geometria = ev.GeometriaEspacios([espacio])
    assert geometria.asignar([caja], ["car"])["espacio_1"][1] == pytest.approx(1 / 3, abs=0.02)
    monkeypatch.setattr(ev, "MIN_SOLAPE", 0.5)
    assert geometria.asignar([caja], ["car"]) == {}


def test_el_punto_de_apoyo_adentro_sigue_contando(monkeypatch):
    """Compatibilidad: aunque el solape pedido sea imposible, un auto con el
    punto de apoyo dentro del polígono se sigue contando, como antes."""
    monkeypatch.setattr(ev, "MIN_SOLAPE", 1.01)
    espacio = rect("espacio_1", 0, 0, 1000, 1000)
    geometria = ev.GeometriaEspacios([espacio])
    assert "espacio_1" in geometria.asignar([[900, 900, 1100, 990]], ["car"])      # centro x=1000: borde afuera
    assert "espacio_1" in geometria.asignar([[800, 900, 1000, 990]], ["car"])      # centro x=900: adentro
    assert geometria.asignar([[1200, 900, 1400, 990]], ["car"]) == {}              # todo afuera


def test_la_geometria_se_arma_una_sola_vez_y_da_lo_mismo_que_armarla_cada_vez():
    modelo = ModeloFalso(lambda i: [AUTO])
    con = correr(modelo, ESPACIOS_SIM, range(0, 60, 10))
    sin = [ev.analizar_foto(np.zeros((600, 800, 3), np.uint8), t, modelo, CLASES, ID_A_NOMBRE, ESPACIOS_SIM, oc)
           for t, oc in zip(range(0, 60, 10), [ev.OcupacionEspacios(gracia_s=ev.GRACIA_S)] * 6)]
    assert [(r["ocupados"], r["en_racha"]) for r in con] == [(r["ocupados"], r["en_racha"]) for r in sin]


# --- Racha de ocupación y gracia ------------------------------------------------

def test_racha_sin_gracia_se_corta_con_un_hueco_como_antes():
    oc = ev.OcupacionEspacios()
    assert oc.actualizar("e1", "car", 0) == 0
    assert oc.ausente("e1", 10) is None
    assert oc.actualizar("e1", "car", 20) == 0


def test_racha_con_gracia_aguanta_dos_fotos_seguidas_sin_ver_el_auto():
    oc = ev.OcupacionEspacios(gracia_s=25)
    assert oc.actualizar("e1", "car", 0) == 0
    assert oc.actualizar("e1", "car", 10) == 10
    assert oc.ausente("e1", 20) == (10, "car")
    assert oc.ausente("e1", 30) == (10, "car")
    assert oc.actualizar("e1", "car", 40) == 40      # la racha sigue desde el segundo 0


def test_racha_con_gracia_se_corta_pasado_el_tiempo():
    oc = ev.OcupacionEspacios(gracia_s=25)
    oc.actualizar("e1", "car", 0)
    assert oc.ausente("e1", 10) == (0, "car")
    assert oc.ausente("e1", 20) == (0, "car")
    assert oc.ausente("e1", 30) is None              # 30 s sin verlo: se corta
    assert oc.actualizar("e1", "car", 40) == 0


def test_cambiar_de_clase_reinicia_la_racha():
    oc = ev.OcupacionEspacios(gracia_s=25)
    oc.actualizar("e1", "car", 0)
    assert oc.actualizar("e1", "volquete", 10) == 0


def test_liberar_corta_la_racha_sin_gracia():
    oc = ev.OcupacionEspacios(gracia_s=25)
    oc.actualizar("e1", "car", 0)
    oc.liberar("e1")
    assert oc.ausente("e1", 5) is None


# --- analizar_foto de punta a punta (con modelo de mentira) ----------------------

def test_confirma_ocupado_a_los_45_segundos():
    resultados = correr(ModeloFalso(lambda i: [AUTO]), ESPACIOS_SIM, range(0, 60, 10))
    assert ocupados(resultados) == [0, 0, 0, 0, 0, 1]
    final = resultados[-1]
    assert (final["ocupado_por_id"], final["total"], final["porcentaje"], final["estado"]) == \
           ({"espacio_1"}, 2, 50.0, "CASI LLENO")


def test_el_volquete_se_confirma_a_los_5_segundos():
    assert ocupados(correr(ModeloFalso(lambda i: [VOLQUETE]), ESPACIOS_SIM, [0, 10])) == [0, 1]


def test_una_foto_en_la_que_el_modelo_no_ve_el_auto_no_reinicia_la_racha():
    no_lo_ve_en_la_cuarta = lambda i: [] if i == 3 else [AUTO]
    resultados = correr(ModeloFalso(no_lo_ve_en_la_cuarta), ESPACIOS_SIM, range(0, 60, 10))
    assert resultados[3]["en_gracia"] == ["espacio_1"]
    assert ocupados(resultados) == [0, 0, 0, 0, 0, 1]


def test_sin_gracia_ese_mismo_caso_no_llegaba_a_confirmarse():
    no_lo_ve_en_la_cuarta = lambda i: [] if i == 3 else [AUTO]
    resultados = correr(ModeloFalso(no_lo_ve_en_la_cuarta), ESPACIOS_SIM, range(0, 60, 10),
                        ocupacion=ev.OcupacionEspacios())
    assert ocupados(resultados) == [0, 0, 0, 0, 0, 0]


def test_un_lugar_confirmado_sigue_ocupado_durante_la_gracia_y_se_libera_despues():
    auto_hasta_los_50_s = lambda i: [AUTO] if i <= 5 else []
    resultados = correr(ModeloFalso(auto_hasta_los_50_s), ESPACIOS_SIM, range(0, 100, 10))
    #                    t=0 ... 40  50  60  70  80  90
    assert ocupados(resultados) == [0, 0, 0, 0, 0, 1, 1, 1, 0, 0]


def test_un_auto_que_se_va_y_otro_que_llega_no_suman_tiempos():
    # Auto de 0 a 20 s; vacío de 30 a 50 s (más que la gracia); otro llega a los 60 s.
    uno_se_va_otro_llega = lambda i: [AUTO] if (i <= 2 or i >= 6) else []
    resultados = correr(ModeloFalso(uno_se_va_otro_llega), ESPACIOS_SIM, range(0, 120, 10))
    # El segundo recién se confirma 45 s después de llegar (t=60 + 50 = 110), no antes.
    assert ocupados(resultados) == [0] * 11 + [1]


def test_una_zona_prohibida_ocupada_figura_bloqueada_y_no_suma_al_total():
    modelo = ModeloFalso(lambda i: [AUTO_EN_PROHIBIDO])
    final = correr(modelo, ESPACIOS_SIM, range(0, 60, 10))[-1]
    assert final["bloqueado_por_id"] == {"prohibido_1"}
    assert (final["ocupados"], final["total"]) == (0, 2)


def test_el_tamano_de_entrada_del_modelo_solo_se_pasa_si_esta_configurado(monkeypatch):
    modelo = ModeloFalso(lambda i: [])
    correr(modelo, ESPACIOS_SIM, [0])
    assert "imgsz" not in modelo.llamadas[0] and modelo.llamadas[0]["classes"] == [0, 1]
    monkeypatch.setattr(ev, "IMGSZ", 960)
    correr(modelo, ESPACIOS_SIM, [10])
    assert modelo.llamadas[1]["imgsz"] == 960


# --- Detector: carpeta de fotos -> modelo -> base de datos -----------------------

def preparar_camara(camara_id="camara_1", ancho=800, alto=600):
    return gc.crear(camara_id, {"nombre": "Cuadra", "lat": -34.6, "lng": -58.44},
                    ESPACIOS_SIM, foto_jpg(ancho, alto))


def dejar_fotos(camara_id, cantidad, desde, paso=10, ancho=800, alto=600):
    """Deja fotos en la carpeta de la cámara como si las hubiera sacado una cámara, `paso` s entre cada una."""
    for i in range(cantidad):
        ruta = gc.ruta_fotos(camara_id) / gc.guardar_foto(camara_id, foto_jpg(ancho, alto))
        os.utime(ruta, (desde + i * paso, desde + i * paso))


def detector_con(modelo):
    det = Detector(log=lambda *_: None)
    det.model, det.clases, det.id_a_nombre = modelo, CLASES, ID_A_NOMBRE
    return det


def test_el_detector_procesa_la_carpeta_y_guarda_el_resultado_en_la_base():
    preparar_camara()
    dejar_fotos("camara_1", 6, time.time() - 200)
    det = detector_con(ModeloFalso(lambda i: [AUTO]))
    assert det.ciclo() == 6

    with db.conectar() as conn:
        estado = dict(conn.execute("SELECT * FROM camaras_estado WHERE camara='camara_1'").fetchone())
        espacios = {f["espacio_id"]: f["ocupado"] for f in conn.execute("SELECT * FROM espacios_estado")}
        historial = conn.execute("SELECT COUNT(*) FROM historial").fetchone()[0]
    assert (estado["ocupados"], estado["total"], estado["estado"]) == (1, 2, "CASI LLENO")
    assert espacios == {"espacio_1": 1, "espacio_2": 0, "prohibido_1": 0}
    assert historial == 6
    assert gc.fotos_pendientes("camara_1") == 0                       # todas procesadas
    assert gc.ruta_preview("camara_1").exists()
    assert det.ciclo() == 0                                           # y no se repiten


def test_el_detector_arma_la_geometria_una_sola_vez(monkeypatch):
    armadas = []

    class GeometriaContada(ev.GeometriaEspacios):
        def __init__(self, espacios):
            armadas.append(1)
            super().__init__(espacios)

    monkeypatch.setattr(ev, "GeometriaEspacios", GeometriaContada)
    preparar_camara()
    dejar_fotos("camara_1", 6, time.time() - 200)
    detector_con(ModeloFalso(lambda i: [AUTO])).ciclo()
    assert len(armadas) == 1


def test_el_detector_no_lee_los_espacios_si_no_hay_fotos_nuevas(monkeypatch):
    preparar_camara()
    lecturas = []
    original = gc.leer_espacios
    monkeypatch.setattr(gc, "leer_espacios", lambda c: lecturas.append(c) or original(c))
    det = detector_con(ModeloFalso(lambda i: []))
    assert det.ciclo() == 0
    assert lecturas == []
    dejar_fotos("camara_1", 1, time.time() - 50)
    assert det.ciclo() == 1
    assert lecturas == ["camara_1"]


def test_el_detector_escala_los_espacios_si_la_foto_tiene_otra_resolucion():
    preparar_camara(ancho=800, alto=600)                       # los espacios se marcaron sobre 800x600
    dejar_fotos("camara_1", 6, time.time() - 200, ancho=1600, alto=1200)
    auto_a_doble_escala = ([190, 460, 610, 710], 0)            # el AUTO, pero en una foto de 1600x1200
    det = detector_con(ModeloFalso(lambda i: [auto_a_doble_escala]))
    assert det.ciclo() == 6
    with db.conectar() as conn:
        ocupado = conn.execute("SELECT ocupado FROM espacios_estado WHERE espacio_id='espacio_1'").fetchone()[0]
    assert ocupado == 1


def test_el_detector_reinicia_la_racha_y_la_geometria_si_se_editan_los_espacios():
    preparar_camara()
    base = time.time() - 300
    dejar_fotos("camara_1", 3, base)
    det = detector_con(ModeloFalso(lambda i: [AUTO]))
    det.ciclo()
    antes = det.por_camara["camara_1"]
    assert antes["ocupacion"].racha                                   # había una racha en marcha

    gc.actualizar_espacios("camara_1", [rect("x", 100, 300, 300, 360), rect("y", 320, 300, 520, 360)])
    ruta = gc.ruta_espacios("camara_1")
    os.utime(ruta, (os.path.getmtime(ruta) + 5, os.path.getmtime(ruta) + 5))   # que la firma sea distinta
    dejar_fotos("camara_1", 1, base + 100)
    det.ciclo()
    despues = det.por_camara["camara_1"]
    assert despues is not antes
    assert despues["geometria"].ids == ["espacio_1", "espacio_2"]
    assert despues["ocupacion"].racha["espacio_1"][0] == pytest.approx(base + 100, abs=1)


# --- Base de datos y carpeta de fotos: que no crezcan para siempre ----------------

def test_podar_historial_borra_solo_lo_viejo():
    ahora = db.ahora_iso()
    viejo = "2020-01-01T00:00:00+00:00"
    with db.conectar() as conn:
        conn.executemany("INSERT INTO historial (camara, ocupados, total, registrado_en) VALUES (?, 1, 2, ?)",
                         [("c", viejo), ("c", viejo), ("c", ahora)])
        assert db.podar_historial(conn, 0) == 0                       # 0 días = guardar todo
        assert db.podar_historial(conn, 30) == 2
        assert conn.execute("SELECT COUNT(*) FROM historial").fetchone()[0] == 1


def test_el_detector_poda_el_historial_con_los_dias_configurados(monkeypatch):
    monkeypatch.setattr(config, "HISTORIAL_DIAS", 7)
    with db.conectar() as conn:
        conn.execute("INSERT INTO historial (camara, ocupados, total, registrado_en) VALUES ('c', 0, 1, '2020-01-01T00:00:00+00:00')")
    assert detector_con(None).podar_historial() == 1


def test_guardar_foto_descarta_las_mas_viejas_si_se_acumulan(monkeypatch):
    monkeypatch.setattr(config, "MAX_FOTOS_EN_COLA", 3)
    preparar_camara()
    nombres = [gc.guardar_foto("camara_1", foto_jpg()) for _ in range(6)]
    quedan = sorted(p.name for p in gc.ruta_fotos("camara_1").iterdir())
    assert quedan == nombres[-3:]


def test_sin_tope_las_fotos_no_se_descartan(monkeypatch):
    monkeypatch.setattr(config, "MAX_FOTOS_EN_COLA", 0)
    preparar_camara()
    for _ in range(5):
        gc.guardar_foto("camara_1", foto_jpg())
    assert gc.fotos_pendientes("camara_1") == 5
