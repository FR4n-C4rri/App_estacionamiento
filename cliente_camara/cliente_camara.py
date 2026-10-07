"""
Cliente de cámara: corre en una compu que tiene acceso a la cámara (la
webcam, un celular con IP Webcam o una cámara IP de SU red), saca una foto
cada N segundos y la manda al servidor de estacionamiento.

Es lo que hay que usar cuando la cámara está en otra casa / otra red: la
conexión sale desde acá hacia el servidor, así que el router no la bloquea.

Configuración: archivo camara.ini en esta misma carpeta (se descarga desde
el modo admin, "Descargar camara.ini"):

    [camara]
    servidor  = https://xxxx.trycloudflare.com
    id        = camara_3
    key       = ...
    fuente    = 0
    intervalo = 10

`fuente` puede ser:
    0, 1, ...                            webcam de esta compu
    http://192.168.0.20:8080/video       celular con la app "IP Webcam"
    rtsp://usuario:clave@192.168.0.50/…  cámara de seguridad IP

Uso:
    py cliente_camara.py                       (lee camara.ini)
    py cliente_camara.py --config otra.ini
    py cliente_camara.py --servidor https://otro-link...   (pisa lo del .ini)

Necesita Python y opencv-python (iniciar_camara.bat lo instala solo).
"""

import argparse
import configparser
import time
from datetime import datetime
from pathlib import Path

import cv2

try:
    from envio_http import enviar_foto
except ImportError:  # importado como paquete desde la raíz del proyecto
    from cliente_camara.envio_http import enviar_foto

CARPETA = Path(__file__).resolve().parent
CAMPOS = ("servidor", "id", "key", "fuente", "intervalo", "calidad")
DEFAULTS = {"fuente": "0", "intervalo": "10", "calidad": "85"}


def leer_config():
    p = argparse.ArgumentParser(description="Manda fotos de una cámara al servidor de estacionamiento")
    p.add_argument("--config", default=str(CARPETA / "camara.ini"), help="archivo de configuración (default: camara.ini)")
    p.add_argument("--servidor")
    p.add_argument("--id", "--camara", dest="id")
    p.add_argument("--key")
    p.add_argument("--fuente")
    p.add_argument("--intervalo")
    p.add_argument("--calidad", help="calidad JPG (0-100)")
    args = p.parse_args()

    valores = dict(DEFAULTS)
    ruta = Path(args.config)
    if ruta.exists():
        ini = configparser.ConfigParser(interpolation=None)
        ini.read(ruta, encoding="utf-8")
        if ini.has_section("camara"):
            valores.update({k: v.strip() for k, v in ini["camara"].items() if k in CAMPOS and v.strip()})
        print(f"Configuración leída de {ruta}")
    elif not (args.servidor and args.id and args.key):
        raise SystemExit(f"No encontré {ruta}. Descargalo desde el modo admin (\"Descargar camara.ini\") "
                         f"y guardalo en esta carpeta.")
    for campo in CAMPOS:
        if getattr(args, campo) is not None:
            valores[campo] = getattr(args, campo)

    faltan = [c for c in ("servidor", "id", "key") if not valores.get(c)]
    if faltan:
        raise SystemExit(f"Faltan datos en la configuración: {', '.join(faltan)}")
    try:
        valores["intervalo"] = float(valores["intervalo"])
        valores["calidad"] = int(valores["calidad"])
    except ValueError:
        raise SystemExit("intervalo y calidad tienen que ser números")
    return valores


def abrir(fuente):
    cap = cv2.VideoCapture(int(fuente) if fuente.isdigit() else fuente)
    if not cap.isOpened():
        raise SystemExit(f"No pude abrir la cámara: {fuente}\n"
                         f"Revisá la dirección (probala en VLC) y que la cámara esté en la misma red que esta compu.")
    return cap


def main():
    cfg = leer_config()
    cap = abrir(cfg["fuente"])
    print(f"Mandando una foto cada {cfg['intervalo']:g}s a {cfg['servidor']} como {cfg['id']}. Ctrl+C para cortar.")
    errores_seguidos = 0
    try:
        while True:
            inicio = time.time()
            # Los streams van acumulando cuadros: se descartan algunos para mandar uno actual.
            for _ in range(5):
                cap.grab()
            ok, frame = cap.read()
            marca = datetime.now().strftime("%H:%M:%S")
            if not ok:
                print(f"[{marca}] No pude leer la cámara, la reabro...")
                cap.release()
                time.sleep(2)
                cap = abrir(cfg["fuente"])
                continue
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, cfg["calidad"]])
            try:
                r = enviar_foto(cfg["servidor"], cfg["id"], cfg["key"], jpg.tobytes())
                print(f"[{marca}] enviada ({r['archivo']})")
                errores_seguidos = 0
            except Exception as e:
                errores_seguidos += 1
                print(f"[{marca}] Error enviando: {e}")
                if "401" in str(e):
                    print("         -> La key no coincide: descargá de nuevo camara.ini desde el admin.")
                elif errores_seguidos == 3:
                    print("         -> ¿Cambió el link del servidor? Si se reinició el túnel, actualizá 'servidor' en camara.ini.")
            time.sleep(max(0, cfg["intervalo"] - (time.time() - inicio)))
    except KeyboardInterrupt:
        print("Listo, corté acá.")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
