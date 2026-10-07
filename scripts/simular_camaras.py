"""
Simulador de cámaras (fase 1, fotos de prueba).

Cada N segundos toma la siguiente foto de muestras/<camara_id>/ (en
loop) y la "manda" como si fuera la cámara:
  - por defecto la copia a camaras/<camara_id>/fotos/
  - con --http la envía al servidor por POST, igual que una cámara real

Recordá: un lugar recién se confirma "ocupado" después de 45 s de racha,
así que el intervalo tiene que ser bastante menor (10-15 s está bien).

Uso (desde la raíz del proyecto):
    py -m scripts.simular_camaras                       # todas las cámaras con carpeta en muestras/
    py -m scripts.simular_camaras --camara camara_1 --intervalo 10
    py -m scripts.simular_camaras --http http://localhost:8000
"""

import argparse
import itertools
import time
from datetime import datetime

import config
import gestor_camaras as gc
from cliente_camara.envio_http import enviar_foto

CARPETA_MUESTRAS = config.RAIZ / "muestras"
EXT = {".jpg", ".jpeg", ".png"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--camara", action="append", help="ID de cámara (se puede repetir). Default: todas las de muestras/")
    p.add_argument("--intervalo", type=float, default=10)
    p.add_argument("--http", metavar="URL_SERVIDOR", help="enviar por HTTP en vez de copiar a la carpeta")
    p.add_argument("--veces", type=int, default=0, help="cantidad de rondas (0 = infinito)")
    args = p.parse_args()

    ids = args.camara or sorted(c.name for c in CARPETA_MUESTRAS.iterdir() if c.is_dir())
    fuentes = {}
    for camara_id in ids:
        if not gc.existe(camara_id):
            print(f"Salteo {camara_id}: no existe la cámara (creala en el modo admin)")
            continue
        fotos = sorted(f for f in (CARPETA_MUESTRAS / camara_id).glob("*") if f.suffix.lower() in EXT)
        if not fotos:
            print(f"Salteo {camara_id}: no hay fotos en muestras/{camara_id}/")
            continue
        fuentes[camara_id] = itertools.cycle(fotos)
    if not fuentes:
        raise SystemExit("No hay nada para simular.")

    print(f"Simulando {list(fuentes)} cada {args.intervalo}s ({'HTTP ' + args.http if args.http else 'copiando a la carpeta'}). Ctrl+C para cortar.")
    ronda = 0
    try:
        while args.veces == 0 or ronda < args.veces:
            ronda += 1
            for camara_id, ciclo in fuentes.items():
                foto = next(ciclo)
                contenido = foto.read_bytes()
                marca = datetime.now().strftime("%H:%M:%S")
                if args.http:
                    cam = gc.leer_camara(camara_id)
                    tipo = "image/png" if foto.suffix.lower() == ".png" else "image/jpeg"
                    r = enviar_foto(args.http, camara_id, cam["api_key"], contenido, foto.name, tipo)
                    print(f"[{marca}] {camara_id} <- {foto.name} (enviada: {r['archivo']})")
                else:
                    destino = gc.ruta_fotos(camara_id)
                    destino.mkdir(parents=True, exist_ok=True)
                    nombre = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + foto.suffix.lower()
                    tmp = destino / (nombre + ".subiendo")
                    tmp.write_bytes(contenido)
                    tmp.replace(destino / nombre)
                    print(f"[{marca}] {camara_id} <- {foto.name} (copiada como {nombre})")
            if args.veces == 0 or ronda < args.veces:
                time.sleep(args.intervalo)
    except KeyboardInterrupt:
        print("Listo, corté acá.")


if __name__ == "__main__":
    main()
