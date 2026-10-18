"""
Lógica de ocupación de espacios (versión refactorizada del
estado_vehiculos.py original, para poder usarla con muchas cámaras desde
deteccion/detector.py).

Cómo decide si un espacio está ocupado:
  - Se detectan "car" y "volquete" con el best.pt fine-tuneado.
  - Cada detección se reparte en el espacio donde más encaja. Encaja si la
    parte baja de su caja (la "huella" que apoya en el suelo) cubre al menos
    MIN_SOLAPE del polígono -o del vehículo, lo que sea más chico- o si su
    punto de apoyo (centro inferior de la caja) cae adentro. Antes alcanzaba
    con que ese único punto quedara unos píxeles afuera para que un auto
    claramente estacionado no se contara, y los polígonos finos o chicos
    lo sufrían más.
  - Un espacio está ocupado si hay algo en él de forma CONTINUA durante
    SEGUNDOS_PARA_CONFIRMAR (45 s autos, 5 s volquetes). Una foto suelta en
    la que el modelo no ve el auto no corta la racha (GRACIA_S); si el
    espacio sigue vacío más que eso, la racha se corta.
  - Las zonas "prohibido" (bajadas de garage) no cuentan para el total;
    si algo las ocupa se avisa como bloqueada.
  - Semáforo: >= 80 % LLENO, >= 50 % CASI LLENO, si no HAY LUGAR.

También: escalar_espacios(), por si una cámara manda fotos con otra
resolución que la foto de referencia sobre la que se delimitó, y
GeometriaEspacios, que deja los polígonos listos una sola vez en lugar de
reconstruirlos por cada detección de cada foto.
"""

import math
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

# Qué parte de la caja (contando desde abajo) se toma como lo que el vehículo
# apoya en el suelo. Los espacios se dibujan sobre esa franja, no sobre el techo.
HUELLA_FRAC = float(os.environ.get("HUELLA_FRAC", "0.5"))
# Cuánto tiene que quedar cubierto (0 a 1) para que una detección cuente en un
# espacio, medido contra lo más chico entre el polígono y la huella.
MIN_SOLAPE = float(os.environ.get("MIN_SOLAPE", "0.25"))
# Segundos que un espacio puede figurar vacío (el modelo no ve el auto en una o
# dos fotos) sin que se corte la racha. Con fotos cada 10 s tolera 2 seguidas.
GRACIA_S = float(os.environ.get("GRACIA_S", "25"))
# Tamaño de entrada del modelo. 0 = el que trae el modelo (640). Subirlo
# (960, 1280) ayuda con autos lejanos, a costa de más CPU.
IMGSZ = int(os.environ.get("IMGSZ", "0"))

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


def huella(xyxy):
    """Franja de la caja que el vehículo apoya en el suelo: su parte baja."""
    x1, y1, x2, y2 = xyxy
    return x1, y2 - (y2 - y1) * HUELLA_FRAC, x2, y2


class GeometriaEspacios:
    """Los polígonos de una cámara, listos para consultar. Se arma UNA vez por
    cámara y resolución (no por cada detección de cada foto)."""

    def __init__(self, espacios):
        self.espacios = espacios
        self.ids = [e["id"] for e in espacios]
        self.pts = []     # vértices de cada polígono
        self.cajas = []   # (x1, y1, x2, y2) del rectángulo que encierra a cada uno
        self.areas = []   # píxeles que cubre cada polígono
        for esp in espacios:
            pts = np.array(esp["puntos"], dtype=np.int32)
            x, y, w, h = cv2.boundingRect(pts)
            mascara = np.zeros((h, w), np.uint8)
            cv2.fillPoly(mascara, [(pts - (x, y)).astype(np.int32)], 1)
            self.pts.append(pts)
            self.cajas.append((x, y, x + w, y + h))
            self.areas.append(max(1, cv2.countNonZero(mascara)))

    def cobertura(self, i, zona):
        """Cuánto de lo más chico entre el polígono `i` y la `zona` (x1, y1, x2, y2)
        queda tapado por el otro, de 0 a 1. Solo rasteriza la parte en común."""
        hx1, hy1, hx2, hy2 = zona
        bx1, by1, bx2, by2 = self.cajas[i]
        x1, y1 = max(bx1, math.floor(hx1)), max(by1, math.floor(hy1))
        x2, y2 = min(bx2, math.ceil(hx2)), min(by2, math.ceil(hy2))
        if x2 <= x1 or y2 <= y1:
            return 0.0
        mascara = np.zeros((y2 - y1, x2 - x1), np.uint8)
        cv2.fillPoly(mascara, [(self.pts[i] - (x1, y1)).astype(np.int32)], 1)
        area_zona = max(1.0, (hx2 - hx1) * (hy2 - hy1))
        return min(1.0, cv2.countNonZero(mascara) / min(self.areas[i], area_zona))

    def punto_dentro(self, i, punto):
        x1, y1, x2, y2 = self.cajas[i]
        if not (x1 <= punto[0] < x2 and y1 <= punto[1] < y2):
            return False
        return cv2.pointPolygonTest(self.pts[i], (float(punto[0]), float(punto[1])), False) >= 0

    def asignar(self, cajas, nombres):
        """Reparte cada detección en el espacio donde más encaja. Devuelve
        {id_espacio: (nombre_clase, cobertura)}; si varias detecciones caen en el
        mismo espacio queda la que más lo cubre. Una detección cuenta para UN solo
        espacio: un auto entre dos lugares no marca los dos."""
        asignadas = {}
        for caja, nombre in zip(cajas, nombres):
            punto = punto_de_apoyo(caja)
            zona = huella(caja)
            mejor = None
            for i in range(len(self.ids)):
                cob = self.cobertura(i, zona)
                if cob < MIN_SOLAPE and not self.punto_dentro(i, punto):
                    continue
                if mejor is None or cob > mejor[1]:
                    mejor = (i, cob)
            if mejor is None:
                continue
            esp_id = self.ids[mejor[0]]
            previa = asignadas.get(esp_id)
            if previa is None or mejor[1] > previa[1]:
                asignadas[esp_id] = (nombre, mejor[1])
        return asignadas


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
    continua — sin importar si es el mismo auto o uno distinto.

    `gracia_s`: segundos que el espacio puede figurar vacío sin cortar la racha
    (por defecto 0: un solo hueco la corta, como antes)."""

    def __init__(self, gracia_s=0.0):
        self.gracia_s = gracia_s
        self.racha = {}  # esp_id -> (inicio de la racha, nombre_clase, último momento visto)

    def actualizar(self, esp_id, nombre_clase, ahora):
        """Hay algo en el espacio. Devuelve cuántos segundos lleva ahí."""
        entrada = self.racha.get(esp_id)
        if entrada is None or entrada[1] != nombre_clase:
            self.racha[esp_id] = (ahora, nombre_clase, ahora)
            return 0.0
        self.racha[esp_id] = (entrada[0], nombre_clase, ahora)
        return ahora - entrada[0]

    def ausente(self, esp_id, ahora):
        """El espacio figura vacío en esta foto. Si la racha todavía está dentro
        de la gracia la conserva y devuelve (segundos que llevaba, clase); si
        no, la corta y devuelve None."""
        entrada = self.racha.get(esp_id)
        if entrada is None:
            return None
        inicio, nombre_clase, visto = entrada
        if not self.gracia_s or ahora - visto > self.gracia_s:
            del self.racha[esp_id]
            return None
        return visto - inicio, nombre_clase

    def liberar(self, esp_id):
        """Corta la racha ya, sin gracia."""
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


def analizar_foto(frame, ahora, model, clases, id_a_nombre, espacios, ocupacion, geometria=None):
    """Corre la detección sobre UNA foto (ya leída) y actualiza la ocupación
    de cada espacio. Dibuja todo sobre `frame`. Devuelve un dict con el
    resultado para guardarlo en la base.

    `geometria`: GeometriaEspacios ya armada para estos `espacios` (el detector
    la reutiliza foto tras foto); si no se pasa, se arma acá."""
    parametros = {"classes": list(clases.values()), "conf": CONF_MIN, "verbose": False}
    if IMGSZ:
        parametros["imgsz"] = IMGSZ
    resultados = model(frame, **parametros)[0]
    cajas = resultados.boxes.xyxy.tolist()
    nombres = [id_a_nombre[int(c)] for c in resultados.boxes.cls.tolist()]

    asignadas = (geometria or GeometriaEspacios(espacios)).asignar(cajas, nombres)

    grosor = max(2, frame.shape[1] // 800)
    escala_texto = max(0.45, frame.shape[1] / 2000)
    for (x1, y1, x2, y2), nombre_clase in zip(cajas, nombres):
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), COLOR_DETECCION, grosor)
        cv2.putText(frame, nombre_clase, (int(x1), int(y1) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, escala_texto, COLOR_DETECCION, grosor)

    ocupado_por_id = set()
    bloqueado_por_id = set()
    en_gracia = []
    for esp in espacios:
        asignada = asignadas.get(esp["id"])
        if asignada is not None:
            nombre_clase = asignada[0]
            tiempo = ocupacion.actualizar(esp["id"], nombre_clase, ahora)
        else:
            previa = ocupacion.ausente(esp["id"], ahora)
            if previa is None:
                continue
            tiempo, nombre_clase = previa  # sigue contando: no se la vio un momento
            en_gracia.append(esp["id"])
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
        "detecciones": nombres,
        "en_racha": sorted(asignadas),
        "en_gracia": sorted(en_gracia),
    }
