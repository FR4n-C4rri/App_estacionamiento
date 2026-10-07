"""
Herramienta de calibración de espacios de estacionamiento.

Permite marcar con el mouse el polígono de cada espacio sobre una
imagen de referencia (una foto, o el primer frame de la cámara) y
guarda las coordenadas en camaras/<id>/espacios.json para usarlas
después en la detección con YOLO.

Es la alternativa por consola a la pantalla "Agregar cámara" del modo
admin (que hace lo mismo desde el navegador). La cámara tiene que estar
creada (carpeta camaras/<id>/ con camara.json).

Cada polígono tiene un "tipo":
  - "valido"    -> un lugar real donde un auto puede estacionar. Cuenta
                   para el total de lugares de esa cámara.
  - "prohibido" -> una zona donde NO se puede estacionar (bajada de
                   garage, cochera, hidrante, etc.). No cuenta para el
                   total de lugares, pero si algo la ocupa se puede
                   avisar aparte (está bloqueando un acceso).

Uso (desde la raíz del proyecto):
    py -m deteccion.calibrar_espacios --camara camara_1
    py -m deteccion.calibrar_espacios --camara camara_1 --imagen otra_foto.jpg

Controles:
    click izquierdo -> agrega un punto al polígono actual
    'n'              -> cierra el polígono actual como espacio VÁLIDO
    'p'              -> cierra el polígono actual como zona PROHIBIDA (garage, bajada)
    'z'              -> deshace: quita el último punto, o el último espacio ya cerrado
    's'              -> guarda el progreso en el archivo JSON
    'q'              -> guarda y sale
"""

import argparse

import cv2
import numpy as np

import gestor_camaras as gc

COLOR_VALIDO = (0, 200, 0)
COLOR_PROHIBIDO = (0, 140, 255)
COLOR_EN_CURSO = (0, 0, 255)


def main():
    parser = argparse.ArgumentParser(description="Calibración de espacios de estacionamiento")
    parser.add_argument("--camara", required=True, help="ID de la cámara, ej: camara_1")
    parser.add_argument("--imagen", help="Imagen de referencia (default: camaras/<id>/referencia.jpg). "
                                         "Si pasás otra, reemplaza la referencia de la cámara.")
    args = parser.parse_args()

    if not gc.existe(args.camara):
        raise SystemExit(f"No existe la cámara {args.camara}: creala primero desde el modo admin")
    args.salida = str(gc.ruta_espacios(args.camara))

    ruta_img = args.imagen or str(gc.ruta_referencia(args.camara))
    img = cv2.imread(ruta_img)
    if img is None:
        raise SystemExit(f"No se pudo abrir la imagen: {ruta_img}")
    if args.imagen:
        with open(args.imagen, "rb") as f:
            gc.actualizar_referencia(args.camara, f.read())

    espacios = gc.leer_espacios(args.camara)
    print(f"Cargados {len(espacios)} espacios existentes para '{args.camara}'")

    puntos_actuales = []

    def click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            puntos_actuales.append([x, y])

    cv2.namedWindow("Calibracion", cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
    alto, ancho = img.shape[:2]
    escala = min(1200 / ancho, 800 / alto, 1.0)
    cv2.resizeWindow("Calibracion", int(ancho * escala), int(alto * escala))
    cv2.setMouseCallback("Calibracion", click)

    print("Click para agregar puntos.")
    print("'n' = cerrar como espacio VÁLIDO   |   'p' = cerrar como zona PROHIBIDA (garage/bajada)")
    print("'z' = deshacer   |   's' = guardar   |   'q' = guardar y salir")

    def siguiente_id(tipo):
        prefijo = "espacio" if tipo == "valido" else "prohibido"
        existentes = [e for e in espacios if e["tipo"] == tipo]
        return f"{prefijo}_{len(existentes) + 1}"

    def cerrar_poligono(tipo):
        nonlocal puntos_actuales
        if len(puntos_actuales) < 3:
            print("Necesitás al menos 3 puntos para cerrar un polígono")
            return
        esp_id = siguiente_id(tipo)
        espacios.append({"id": esp_id, "puntos": puntos_actuales, "tipo": tipo})
        etiqueta = "espacio válido" if tipo == "valido" else "zona PROHIBIDA"
        print(f"Guardado {esp_id} ({etiqueta}) con {len(puntos_actuales)} puntos")
        puntos_actuales = []

    while True:
        vista = img.copy()

        for esp in espacios:
            pts = np.array(esp["puntos"], dtype=np.int32)
            color = COLOR_VALIDO if esp["tipo"] == "valido" else COLOR_PROHIBIDO
            cv2.polylines(vista, [pts], True, color, 2)
            cx, cy = pts[:, 0].mean().astype(int), pts[:, 1].mean().astype(int)
            cv2.putText(vista, esp["id"], (cx - 10, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        for p in puntos_actuales:
            cv2.circle(vista, tuple(p), 4, COLOR_EN_CURSO, -1)
        if len(puntos_actuales) > 1:
            cv2.polylines(vista, [np.array(puntos_actuales, dtype=np.int32)], False, COLOR_EN_CURSO, 2)

        cv2.imshow("Calibracion", vista)
        key = cv2.waitKey(20) & 0xFF

        if key == ord("n"):
            cerrar_poligono("valido")

        elif key == ord("p"):
            cerrar_poligono("prohibido")

        elif key == ord("z"):
            if puntos_actuales:
                puntos_actuales.pop()
            elif espacios:
                eliminado = espacios.pop()
                print(f"Eliminado {eliminado['id']}")

        elif key == ord("s"):
            guardar(args.salida, args.camara, espacios)
            print(f"Guardado en {args.salida}")

        elif key == ord("q"):
            break

    guardar(args.salida, args.camara, espacios)
    validos = sum(1 for e in espacios if e["tipo"] == "valido")
    prohibidos = len(espacios) - validos
    print(f"Guardado final en {args.salida}: {validos} espacios válidos, {prohibidos} zonas prohibidas")
    cv2.destroyAllWindows()


def guardar(ruta, camara, espacios):
    if not any(e["tipo"] == "valido" for e in espacios):
        print("Todavía no hay ningún lugar válido: no guardo")
        return
    gc.actualizar_espacios(camara, espacios)


if __name__ == "__main__":
    main()
