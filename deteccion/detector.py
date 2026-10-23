"""
Detector multi-cámara: un solo proceso, el modelo se carga UNA vez, y
cada pocos segundos recorre camaras/<id>/fotos/ de TODAS las cámaras.
Por cada foto nueva aplica la lógica de estado_vehiculos.py, guarda el
resultado en la base, deja el preview en camaras/<id>/preview.jpg y
mueve la foto a camaras/<id>/procesadas/.

Las cámaras nuevas que se den de alta desde el modo admin se detectan
solas, sin reiniciar. Si se editan los espacios de una cámara, se
reinicia su racha de ocupación.

Normalmente lo arranca el servidor (servidor/main.py) en segundo plano.
También se puede correr aparte:

    py -m deteccion.detector
"""

import os
import shutil
import threading
import time
from datetime import datetime

import cv2

import config
import gestor_camaras as gc
from base_de_datos import db
from deteccion import estado_vehiculos as ev


class Detector:
    def __init__(self, ruta_modelo=None, intervalo=None, log=print):
        self.ruta_modelo = ruta_modelo or config.RUTA_MODELO
        self.intervalo = intervalo or config.INTERVALO_POLL
        self.log = log
        self.model = None
        self.clases = None
        self.id_a_nombre = None
        self.por_camara = {}  # id -> {"ocupacion", "firma_espacios", "fallidas"}
        self._parar = threading.Event()
        self._hilo = None
        self._ultima_poda = 0.0

    # --- Modelo ---

    def cargar_modelo(self):
        if self.model is not None:
            return
        from ultralytics import YOLO  # import pesado: solo cuando hace falta

        self.log(f"[detector] Cargando modelo {self.ruta_modelo} ...")
        self.model = YOLO(str(self.ruta_modelo))
        self.clases = ev.mapa_de_clases(self.model)
        self.id_a_nombre = {idx: nombre for nombre, idx in self.clases.items()}
        self.log(f"[detector] Modelo listo. Clases: {list(self.clases)}")

    # --- Estado por cámara ---

    def _estado(self, camara_id):
        ruta = gc.ruta_espacios(camara_id)
        firma = ruta.stat().st_mtime if ruta.exists() else None
        est = self.por_camara.get(camara_id)
        if est is None or est["firma_espacios"] != firma:
            if est is not None:
                self.log(f"[detector] {camara_id}: cambiaron los espacios, reinicio la racha")
            est = {"ocupacion": ev.OcupacionEspacios(gracia_s=ev.GRACIA_S), "firma_espacios": firma,
                   "fallidas": set(), "clave_geometria": None}
            self.por_camara[camara_id] = est
        return est

    # --- Procesamiento ---

    def ciclo(self):
        """Una pasada por todas las cámaras. Devuelve cuántas fotos procesó."""
        procesadas = 0
        ids = gc.listar_ids()
        for viejo in set(self.por_camara) - set(ids):
            del self.por_camara[viejo]

        for camara_id in ids:
            try:
                cam = gc.leer_camara(camara_id)
            except Exception as e:  # camara.json a medio escribir, etc.
                self.log(f"[detector] {camara_id}: no pude leer camara.json ({e})")
                continue
            if not cam.get("activa", True):
                continue
            est = self._estado(camara_id)
            fotos = ev.fotos_nuevas(str(gc.ruta_fotos(camara_id)), est["fallidas"])
            if not fotos:
                continue  # nada nuevo: no hace falta ni leer los espacios
            espacios = gc.leer_espacios(camara_id)
            if gc.total_lugares(espacios) == 0:
                continue
            for mtime, ruta in fotos:
                self.cargar_modelo()
                if self.procesar(camara_id, cam, espacios, est, ruta, mtime):
                    procesadas += 1
        return procesadas

    def procesar(self, camara_id, cam, espacios, est, ruta, mtime):
        frame = cv2.imread(ruta)
        if frame is None:
            self.log(f"[detector] {camara_id}: no pude leer {os.path.basename(ruta)}, la salteo")
            est["fallidas"].add(ruta)
            return False

        ref = cam.get("referencia") or {}
        tam_ref = (ref["ancho"], ref["alto"]) if ref.get("ancho") else None
        tam_foto = (frame.shape[1], frame.shape[0])
        if est["clave_geometria"] != (tam_ref, tam_foto):
            # Se rehace solo si cambia la resolución de la foto o de la referencia
            # (si se editan los espacios, `est` entero se reinicia en _estado).
            espacios_foto = ev.escalar_espacios(espacios, tam_ref, tam_foto)
            est["espacios_foto"] = espacios_foto
            est["geometria"] = ev.GeometriaEspacios(espacios_foto)
            est["clave_geometria"] = (tam_ref, tam_foto)
        espacios_foto = est["espacios_foto"]

        r = ev.analizar_foto(frame, mtime, self.model, self.clases, self.id_a_nombre,
                             espacios_foto, est["ocupacion"], est["geometria"])

        with db.conectar() as conn:
            if not conn.execute("SELECT 1 FROM camaras WHERE id = ?", (camara_id,)).fetchone():
                gc.sincronizar_una(camara_id)
            db.guardar_estado(conn, camara_id, espacios_foto, r["ocupado_por_id"], r["bloqueado_por_id"],
                              r["ocupados"], r["total"], r["porcentaje"], r["estado"])

        self._guardar_preview(camara_id, frame)
        self._archivar(camara_id, ruta, est)

        marca = datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
        gracia = f", sin verse un momento: {r['en_gracia']}" if r["en_gracia"] else ""
        self.log(f"[detector] [{marca}] {camara_id} {os.path.basename(ruta)} -> "
                 f"{r['ocupados']}/{r['total']} ({r['porcentaje']:.0f}%) {r['estado']} "
                 f"| detecciones: {len(r['detecciones'])}, en racha: {r['en_racha']}{gracia}")
        return True

    def _guardar_preview(self, camara_id, frame):
        alto, ancho = frame.shape[:2]
        if ancho > config.ANCHO_PREVIEW:
            factor = config.ANCHO_PREVIEW / ancho
            frame = cv2.resize(frame, (config.ANCHO_PREVIEW, int(alto * factor)), interpolation=cv2.INTER_AREA)
        destino = gc.ruta_preview(camara_id)
        tmp = destino.with_name("preview.tmp.jpg")
        cv2.imwrite(str(tmp), frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        os.replace(tmp, destino)

    def _archivar(self, camara_id, ruta, est):
        carpeta = gc.ruta_procesadas(camara_id)
        carpeta.mkdir(exist_ok=True)
        try:
            shutil.move(ruta, carpeta / os.path.basename(ruta))
        except OSError as e:
            self.log(f"[detector] {camara_id}: no pude mover {ruta} ({e}); no la vuelvo a procesar")
            est["fallidas"].add(ruta)
            return
        guardadas = sorted(carpeta.iterdir(), key=lambda p: p.stat().st_mtime)
        sobrantes = max(0, len(guardadas) - config.MAX_PROCESADAS)
        for p in guardadas[:sobrantes]:
            try:
                p.unlink()
            except OSError:
                pass

    # --- Bucle ---

    def podar_historial(self):
        """Borra del historial lo más viejo que config.HISTORIAL_DIAS (una fila
        por foto por cámara: sin esto la tabla crece para siempre)."""
        self._ultima_poda = time.time()
        with db.conectar() as conn:
            borradas = db.podar_historial(conn, config.HISTORIAL_DIAS)
        if borradas:
            self.log(f"[detector] Historial: borré {borradas} filas de más de {config.HISTORIAL_DIAS} días")
        return borradas

    def correr(self):
        self.log(f"[detector] Mirando {config.CARPETA_CAMARAS}/*/fotos cada {self.intervalo}s")
        while not self._parar.is_set():
            try:
                if time.time() - self._ultima_poda >= 3600:
                    self.podar_historial()
                self.ciclo()
            except Exception as e:  # que un error puntual no mate el detector
                self.log(f"[detector] Error en el ciclo: {e!r}")
            self._parar.wait(self.intervalo)

    def iniciar_en_segundo_plano(self):
        self._hilo = threading.Thread(target=self.correr, name="detector", daemon=True)
        self._hilo.start()

    def detener(self):
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=5)


if __name__ == "__main__":
    db.crear_tablas()
    gc.sincronizar_db()
    det = Detector()
    det.cargar_modelo()
    try:
        det.correr()
    except KeyboardInterrupt:
        print("Listo, corté acá.")
