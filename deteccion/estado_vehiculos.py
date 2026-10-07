"""
Lógica de ocupación de espacios (versión refactorizada del
estado_vehiculos.py original, para poder usarla con muchas cámaras desde
deteccion/detector.py).

La lógica NO cambió respecto del script original:
  - Se detectan "car" y "volquete" con el best.pt fine-tuneado.
  - Un espacio está ocupado si el punto de apoyo (centro inferior de la
    caja) de alguna detección cae dentro de su polígono de forma CONTINUA
    durante SEGUNDOS_PARA_CONFIRMAR (45 s autos, 5 s volquetes). Si en
    alguna foto queda vacío, la racha se corta.
  - Las zonas "prohibido" (bajadas de garage) no cuentan para el total;
    si algo las ocupa se avisa como bloqueada.
  - Semáforo: >= 80 % LLENO, >= 50 % CASI LLENO, si no HAY LUGAR.

Lo único nuevo: escalar_espacios(), por si una cámara manda fotos con
otra resolución que la foto de referencia sobre la que se delimitó.
"""

import os
import time

import cv2
import numpy as np

CLASES = ["car", "volquete"]

# Segundos de presencia CONTINUA en el mismo espacio para confirmar que
# lo está ocupando de verdad (no de paso).
SEGUNDOS_PARA_CONFIRMAR = {
    "car": 45,
    "volquete": 5,
}

CONF_MIN = float(os.environ.get("CONF_MIN", "0.35"))
EXTENSIONES_VALIDAS = {".jpg", ".jpeg", ".png"}
SEGUNDOS_ANTIGUEDAD_MINIMA = 1.0  # evita leer un archivo a medio escribir

UMBRAL_ROJO = 80
UMBRAL_AMARILLO = 50

COLOR_ROJO = (0, 0, 255)
COLOR_AMARILLO = (0, 210, 255)
COLOR_VERDE = (0, 200, 0)
COLOR_DETECCION = (255, 200, 0)
COLOR_PROHIBIDO_OK = (0, 140, 255)


def punto_de_apoyo(xyxy):
    x1, y1, x2, y2 = xyxy
    return ((x1 + x2) / 2, y2)


def punto_dentro(punto, poligono_pts):
    poly = np.array(poligono_pts, dtype=np.int32)
    return cv2.pointPolygonTest(poly, punto, False) >= 0


def escalar_espacios(espacios, tam_referencia, tam_foto):
    """Ajusta los polígonos si la foto no tiene la misma resolución que la
    referencia. tam_* = (ancho, alto)."""
    if not tam_referencia or tuple(tam_referencia) == tuple(tam_foto):
        return espacios
    fx = tam_foto[0] / tam_referencia[0]
    fy = tam_foto[1] / tam_referencia[1]
    return [
        {**e, "puntos": [[int(round(x * fx)), int(round(y * fy))] for x, y in e["puntos"]]}
        for e in espacios
    ]


def mapa_de_clases(model):
    mapa = {nombre: idx for idx, nombre in model.names.items() if nombre in CLASES}
    faltantes = [c for c in CLASES if c not in mapa]
    if faltantes:
        raise SystemExit(
            f"El modelo no tiene estas clases: {faltantes}. "
            f"Clases disponibles: {list(model.names.values())}. "
            f"¿Le pasaste el best.pt fine-tuneado (no un yolov8*.pt genérico)?"
        )
    return mapa


class OcupacionEspacios:
    """Por cada espacio, mide desde cuándo hay ALGO ocupándolo de forma
    continua — sin importar si es el mismo auto o uno distinto."""

    def __init__(self):
        self.racha = {}  # esp_id -> (timestamp de inicio de la racha, nombre_clase)

    def actualizar(self, esp_id, nombre_clase, ahora):
        entrada = self.racha.get(esp_id)
        if entrada is None or entrada[1] != nombre_clase:
            self.racha[esp_id] = (ahora, nombre_clase)
            return 0.0
        return ahora - entrada[0]

    def liberar(self, esp_id):
        self.racha.pop(esp_id, None)


def estado_semaforo(porcentaje):
    if porcentaje >= UMBRAL_ROJO:
        return "LLENO", COLOR_ROJO
    if porcentaje >= UMBRAL_AMARILLO:
        return "CASI LLENO", COLOR_AMARILLO
    return "HAY LUGAR", COLOR_VERDE


def dibujar_espacios(frame, espacios, ocupado_por_id, bloqueado_por_id):
    grosor = max(2, frame.shape[1] // 800)
    escala_txt = max(0.45, frame.shape[1] / 2000)
    for esp in espacios:
        pts = np.array(esp["puntos"], dtype=np.int32)
        if esp["tipo"] == "prohibido":
            bloqueado = esp["id"] in bloqueado_por_id
            color = COLOR_ROJO if bloqueado else COLOR_PROHIBIDO_OK
            texto = "BLOQUEADO" if bloqueado else "prohibido"
        else:
            ocupado = esp["id"] in ocupado_por_id
            color = COLOR_ROJO if ocupado else COLOR_VERDE
            texto = "ocupado" if ocupado else "libre"
        cv2.polylines(frame, [pts], True, color, grosor)
        cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
        cv2.putText(frame, f"{esp['id']}: {texto}", (cx - int(45 * escala_txt / 0.45), cy),
                    cv2.FONT_HERSHEY_SIMPLEX, escala_txt, color, grosor)


def dibujar_banner(frame, ocupados, total, porcentaje, estado, color):
    alto_banner = max(40, frame.shape[0] // 25)
    escala = alto_banner / 57
    cv2.rectangle(frame, (0, 0), (frame.shape[1], alto_banner), (30, 30, 30), -1)
    texto = f"{ocupados}/{total} ocupados ({porcentaje:.0f}%) - {estado}"
    cv2.putText(frame, texto, (12, int(alto_banner * 0.68)), cv2.FONT_HERSHEY_SIMPLEX,
                escala, color, max(2, int(escala * 2)))


def fotos_nuevas(carpeta, ya_procesadas):
    """Lista archivos de imagen en `carpeta` que todavía no procesamos,
    ordenados por momento de captura (mtime). Descarta los modificados hace
    menos de SEGUNDOS_ANTIGUEDAD_MINIMA, para no leer un archivo a medio escribir."""
    candidatos = []
    ahora = time.time()
    if not os.path.isdir(carpeta):
        return candidatos
    for nombre in os.listdir(carpeta):
        ruta = os.path.join(carpeta, nombre)
        if ruta in ya_procesadas:
            continue
        if os.path.splitext(nombre)[1].lower() not in EXTENSIONES_VALIDAS:
            continue
        if not os.path.isfile(ruta):
            continue
        mtime = os.path.getmtime(ruta)
        if ahora - mtime < SEGUNDOS_ANTIGUEDAD_MINIMA:
            continue
        candidatos.append((mtime, ruta))
    candidatos.sort(key=lambda par: par[0])
    return candidatos


def analizar_foto(frame, ahora, model, clases, id_a_nombre, espacios, ocupacion):
    """Corre la detección sobre UNA foto (ya leída) y actualiza la ocupación
    de cada espacio. Dibuja todo sobre `frame`. Devuelve un dict con el
    resultado para guardarlo en la base."""
    resultados = model(frame, classes=list(clases.values()), conf=CONF_MIN, verbose=False)[0]

    clase_en_espacio = {}
    detecciones = []
    for box, cls_id in zip(resultados.boxes.xyxy.tolist(), resultados.boxes.cls.tolist()):
        nombre_clase = id_a_nombre[int(cls_id)]
        detecciones.append(nombre_clase)
        punto = punto_de_apoyo(box)
        for esp in espacios:
            if esp["id"] in clase_en_espacio:
                continue
            if punto_dentro(punto, esp["puntos"]):
                clase_en_espacio[esp["id"]] = nombre_clase

        x1, y1, x2, y2 = box
        grosor = max(2, frame.shape[1] // 800)
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), COLOR_DETECCION, grosor)
        cv2.putText(frame, nombre_clase, (int(x1), int(y1) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.45, frame.shape[1] / 2000), COLOR_DETECCION, grosor)

    ocupado_por_id = set()
    bloqueado_por_id = set()
    for esp in espacios:
        nombre_clase = clase_en_espacio.get(esp["id"])
        if nombre_clase is None:
            ocupacion.liberar(esp["id"])
            continue
        tiempo = ocupacion.actualizar(esp["id"], nombre_clase, ahora)
        if tiempo >= SEGUNDOS_PARA_CONFIRMAR[nombre_clase]:
            destino = ocupado_por_id if esp["tipo"] == "valido" else bloqueado_por_id
            destino.add(esp["id"])

    total_lugares = sum(1 for e in espacios if e["tipo"] == "valido")
    ocupados = len(ocupado_por_id)
    porcentaje = 100 * ocupados / total_lugares if total_lugares else 0.0
    estado_txt, color_estado = estado_semaforo(porcentaje)

    dibujar_espacios(frame, espacios, ocupado_por_id, bloqueado_por_id)
    dibujar_banner(frame, ocupados, total_lugares, porcentaje, estado_txt, color_estado)

    return {
        "ocupado_por_id": ocupado_por_id,
        "bloqueado_por_id": bloqueado_por_id,
        "ocupados": ocupados,
        "total": total_lugares,
        "porcentaje": porcentaje,
        "estado": estado_txt,
        "detecciones": detecciones,
        "en_racha": sorted(clase_en_espacio),
    }
