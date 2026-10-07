"""
Pasa la cámara que ya estaba calibrada en la carpeta original
(Ciudades/espacios.json + la foto de prueba) a la nueva estructura
camaras/<id>/.

La ubicación es de ejemplo: después se corrige desde el modo admin
(Editar -> ubicación).

Uso (desde la raíz del proyecto):
    py -m scripts.migrar_camara_existente
    py -m scripts.migrar_camara_existente --origen ../Ciudades --camara camara_1 --lat -34.6 --lng -58.44
"""

import argparse
import json
from pathlib import Path

import config
import gestor_camaras as gc
from base_de_datos import db


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--origen", default=str(config.RAIZ.parent / "Ciudades"),
                   help="carpeta del proyecto original (con espacios.json)")
    p.add_argument("--camara", default="camara_1")
    p.add_argument("--foto", help="foto de referencia (default: <origen>/carpeta_prueba/foto_prueba_ok.jpg)")
    p.add_argument("--nombre", default="Cuadra de prueba (cámara 1)")
    p.add_argument("--direccion", default="Ubicación de ejemplo — editar desde el modo admin")
    p.add_argument("--lat", type=float, default=-34.59950)
    p.add_argument("--lng", type=float, default=-58.44050)
    args = p.parse_args()

    origen = Path(args.origen)
    with open(origen / "espacios.json", encoding="utf-8") as f:
        espacios = json.load(f)[args.camara]
    foto = Path(args.foto) if args.foto else origen / "carpeta_prueba" / "foto_prueba_ok.jpg"

    db.crear_tablas()
    if gc.existe(args.camara):
        raise SystemExit(f"{args.camara} ya existe en {gc.carpeta(args.camara)} — no la piso")

    datos = {
        "nombre": args.nombre,
        "direccion": args.direccion,
        "lat": args.lat,
        "lng": args.lng,
        # cuadra de ~90 m centrada en la cámara
        "cuadra": [[args.lat, args.lng - 0.0005], [args.lat, args.lng + 0.0005]],
    }
    cam = gc.crear(args.camara, datos, espacios, foto.read_bytes())
    print(f"Creada {cam['id']} en {gc.carpeta(cam['id'])}")
    print(f"  lugares válidos: {gc.total_lugares(gc.leer_espacios(cam['id']))}")
    print(f"  api_key: {cam['api_key']}")


if __name__ == "__main__":
    main()
