# Estacionamiento por cuadra — app con mapa

Cámaras que sacan fotos de una cuadra → YOLO (`best.pt`) detecta autos y
volquetes → se calcula cuántos de los lugares delimitados están ocupados →
un mapa muestra, cerca del usuario, cuántos lugares libres hay en cada cuadra.

Un lugar se considera ocupado cuando un auto (o volquete) está dentro de su
polígono de forma continua durante 45 s (5 s volquetes), para no contar
autos que solo pasan o esperan el semáforo.

## Inicio rápido (si lo acabás de descargar)

1. **Instalá Python 3.11 o más nuevo** desde https://www.python.org/downloads/
   (en Windows, tildá **"Add python.exe to PATH"** durante la instalación).
2. **Bajá el proyecto**: botón verde *Code* → *Download ZIP* y descomprimilo,
   o `git clone https://github.com/FR4n-C4rri/App_estacionamiento.git`.
3. **Abrí una terminal en la carpeta del proyecto** (en el Explorador:
   clic derecho en la carpeta → *Abrir en Terminal*) e instalá lo necesario
   (una sola vez; tarda unos minutos porque baja PyTorch):
   ```
   py -m pip install -r requirements.txt
   ```
   En Mac/Linux usá `python3` en vez de `py` en todos los comandos.
4. **Arrancá la app**:
   ```
   py -m uvicorn servidor.main:app --port 8000
   ```
   y entrá a http://localhost:8000/ (mapa) o http://localhost:8000/admin
   (contraseña inicial: `admin`; cambiala creando un archivo `.env` con
   `ADMIN_PASSWORD=tu-clave`, ver `.env.example`).
5. **La app arranca sin cámaras.** Cargá la primera desde el admin con
   **"+ Agregar cámara"** (ubicación en el mapa, una foto de la cuadra y los
   lugares marcados sobre la foto). Para probar sin cámara real, en la
   tarjeta de la cámara usá **"Mandar foto de prueba"** dos veces, con 45 s
   de diferencia.

Para publicarla en internet o conectar cámaras de otras casas, ver más abajo.

## Organización

```
estacionamiento_app/
├── base_de_datos/      estacionamiento.db, esquema.sql (tablas), db.py (consultas)
├── camaras/
│   └── camara_1/       una carpeta por cámara:
│       ├── camara.json     nombre, ubicación, extremos de la cuadra, api_key
│       ├── espacios.json   lugares delimitados (polígonos)
│       ├── referencia.jpg  foto sobre la que se delimitó
│       ├── fotos/          ← acá entran las fotos nuevas (las revisa el detector)
│       ├── procesadas/     última foto analizada (las anteriores se borran solas)
│       └── preview.jpg     última foto con todo dibujado
├── deteccion/          best.pt, estado_vehiculos.py (lógica), detector.py (todas las cámaras), calibrar_espacios.py
├── servidor/           API FastAPI (main.py, rutas_usuario.py, rutas_admin.py, rutas_camaras.py)
├── web/                usuario/ (mapa) y admin/ (panel)
├── scripts/            iniciar_publico.py (servidor + túnel), simular_camaras.py, migrar_camara_existente.py
├── cliente_camara/     lo que se le pasa a quien tiene una cámara en otra casa (cliente + camara.ini)
├── muestras/           fotos de prueba por cámara (para el simulador)
├── iniciar_publico.bat doble clic: levanta la app y la publica en internet
├── config.py           rutas y parámetros (se pueden pisar con .env)
└── gestor_camaras.py   alta / edición / baja de carpetas de cámaras
```

La **carpeta de cada cámara es la fuente de verdad** de su configuración. La
tabla `camaras` es un índice que se sincroniza solo al arrancar (y en cada
alta/edición), para buscar cámaras por cercanía rápido. Las tablas
`camaras_estado` y `espacios_estado` son las mismas que antes; se agregó
`historial` (una fila por foto procesada).

## Instalar (una vez)

```
py -m pip install -r requirements.txt
```

Opcional: copiar `.env.example` como `.env` y **cambiar `ADMIN_PASSWORD`**
(por defecto es `admin`).

## Correr

Desde esta carpeta:

```
py -m uvicorn servidor.main:app --port 8000
```

- Modo usuario: http://localhost:8000/
- Modo admin: http://localhost:8000/admin

El servidor también corre el detector en segundo plano: cada 5 s mira
`camaras/*/fotos/`, procesa lo nuevo y actualiza la base. Las cámaras
nuevas se detectan solas, sin reiniciar.

## Publicarla en internet (para que la vea cualquiera)

Doble clic en **`iniciar_publico.bat`** (o `py -m scripts.iniciar_publico`).
Levanta el servidor y un túnel de Cloudflare (gratis, sin cuenta) y muestra
un link `https://….trycloudflare.com` que funciona desde cualquier celular
o compu, con HTTPS (así anda "Buscar lugares cerca mío"). El link se copia
al portapapeles y queda en `link_publico.txt`.

- Hace falta `cloudflared` una vez: `winget install --id Cloudflare.cloudflared`.
- Si la contraseña de admin sigue siendo `admin`, te pide una nueva y la
  guarda en `.env` (el panel admin también queda en internet).
- Tu compu tiene que quedar prendida con esa ventana abierta.
- **El link cambia cada vez que lo arrancás**: las cámaras en otras casas
  tienen que actualizar la línea `servidor` de su `camara.ini`.
- Si el puerto 8000 está ocupado: `py -m scripts.iniciar_publico --puerto 8001`.

Solo para la misma red (sin túnel): `--host 0.0.0.0` y usar la IP de la
PC. Ojo: el navegador solo da la ubicación del usuario en `localhost` o
con HTTPS.

## Modo usuario

Mapa a pantalla completa con el botón **"Buscar lugares cerca mío"**:
pide la ubicación, busca cámaras en el radio elegido (300 m – 2 km) y
pinta cada cuadra (verde hay lugar / amarillo casi lleno / rojo lleno /
gris sin datos recientes) con la cantidad de lugares libres. Tocando una
cuadra se ve el detalle y la última foto. Se actualiza solo cada 30 s.
Si el usuario no da permiso de ubicación, puede tocar el mapa.

## Modo admin

- Lista de cámaras con su estado, última foto, y acciones: editar,
  mandar foto de prueba, activar/desactivar, eliminar.
- **Agregar cámara** (asistente):
  1. Datos (ID, nombre de la cuadra, dirección).
  2. Ubicación: en el mapa se marca la cámara y el inicio/fin de la cuadra.
  3. Foto de referencia.
  4. Delimitar lugares sobre la foto (como `calibrar_espacios.py`: clicks,
     **N** válido, **P** prohibido, **Z** deshacer).
  5. Confirmar → crea `camaras/<id>/` y muestra la **API key** y la URL
     a la que la cámara tiene que mandar las fotos.

## Probar con fotos (fase 1)

```
py -m scripts.simular_camaras --intervalo 10
```

Toma las fotos de `muestras/<id_camara>/` y las va dejando en
`camaras/<id_camara>/fotos/` cada 10 s. Viene una foto de ejemplo en
`muestras/camara_1/`: para usarla, primero creá en el admin una cámara con
ID `camara_1` usando esa misma foto como referencia. Con `--http http://localhost:8000`
las manda por HTTP como una cámara real. También se puede copiar fotos a
mano a `camaras/<id>/fotos/` o usar "Mandar foto de prueba" en el admin.

Recordá: un lugar recién figura **ocupado** después de 45 s seguidos con
un auto encima, así que con la primera foto siempre da "HAY LUGAR".

## Cámaras reales (fase 2)

Cada cámara tiene un **origen de las fotos**, que se elige en el paso 1
de "Agregar cámara" (o en Editar):

**1. La cámara las manda** (default). Un dispositivo hace un
`POST /api/camaras/<id>/fotos` con la foto (campo `foto`) y el header
`X-Camera-Key: <api_key>`. Es la opción para **cámaras en otra casa / otra
red**: la conexión sale de esa casa hacia el servidor, así que el router no
la bloquea (al revés, desde acá no se puede llegar a una IP privada de otra
casa). Pasos:

1. Publicá la app con `iniciar_publico.bat` y entrá al admin **desde el
   link público**.
2. En la cámara (Editar → Confirmar) tocá **"Descargar camara.ini"**: sale
   con el link, el ID y la key ya completos.
3. Pasale a la otra persona la carpeta `cliente_camara/` con ese
   `camara.ini` adentro. Ella elige la `fuente` (webcam `0`, IP Webcam
   `http://IP-del-celu:8080/video` o RTSP) y hace doble clic en
   `iniciar_camara.bat` (instala OpenCV la primera vez). Ver `cliente_camara/LEEME.txt`.

**2. El servidor las busca** (`deteccion/captor.py`). Pensado para
cámaras de seguridad IP, que no pueden correr programas. Cada N segundos
el servidor saca una foto y la deja en `camaras/<id>/fotos/`:

- **Video**: `rtsp://usuario:clave@192.168.0.50:554/Streaming/Channels/101`,
  un stream HTTP (`http://192.168.0.20:8080/video` de IP Webcam), un
  número de webcam (`0`) o un archivo de video (para simular una cámara).
- **URL de foto**: una dirección que devuelve un JPG por pedido, como el
  snapshot ONVIF de las cámaras IP o `http://192.168.0.20:8080/shot.jpg`
  de IP Webcam. Acepta usuario y clave en la URL (Basic y Digest).

El botón **"Probar conexión"** del asistente saca una foto en el momento,
y en el paso 3 **"Tomar foto desde la cámara"** la usa como referencia.
La lista de cámaras muestra la última captura o el error de conexión. La
condición es que el servidor llegue a la cámara (misma red o accesible
desde internet). El usuario y la clave quedan guardados en
`camaras/<id>/camara.json`, así que no compartas esa carpeta.

En los dos casos, si las fotos tienen otra resolución que la de
referencia, los polígonos se escalan solos.

## Tests

```
py -m pytest
```

## Limitación conocida del modelo

En la foto de prueba, el auto negro de `espacio_3` (tapado por el árbol)
**no se detecta** ni bajando la confianza a 0.05 ni subiendo la resolución
de entrada, así que ese lugar figura siempre libre. Se arregla
reentrenando `best.pt` con más fotos de autos parcialmente tapados.
