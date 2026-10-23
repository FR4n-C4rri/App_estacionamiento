# Estacionamiento por cuadra — app con mapa

Cámaras que sacan fotos de una cuadra → YOLO (`best.pt`) detecta autos y
volquetes → se calcula cuántos de los lugares delimitados están ocupados →
un mapa muestra, cerca del usuario, cuántos lugares libres hay en cada cuadra.

Un lugar se considera ocupado cuando un auto (o volquete) está sobre su
polígono de forma continua durante 45 s (5 s volquetes), para no contar
autos que solo pasan o esperan el semáforo. Para saber si un auto está en un
lugar se mira la parte baja de su caja (lo que apoya en el suelo), no un solo
punto, así que los polígonos chicos o finos también funcionan; y si el modelo
no ve el auto en una foto suelta, no se reinicia la cuenta de los 45 s.
Ver [Ajustar la detección](#ajustar-la-detección).

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
   **En Linux o Mac** se usa un entorno virtual (en Ubuntu/Debian, instalar
   directo da el error *"externally-managed-environment"*). Ver
   [Instalar en Linux / Mac](#instalar-en-linux--mac).
4. **Arrancá la app**:
   ```
   py -m uvicorn servidor.main:app --port 8000
   ```
   (en Linux/Mac: `python -m uvicorn servidor.main:app --port 8000` con el
   entorno virtual activado) y entrá a http://localhost:8000/ (mapa) o http://localhost:8000/admin
   (contraseña inicial: `admin`; cambiala creando un archivo `.env` con
   `ADMIN_PASSWORD=tu-clave`, ver `.env.example`).
5. **La app arranca sin cámaras.** Cargá la primera desde el admin con
   **"+ Agregar cámara"** (ubicación en el mapa, una foto de la cuadra y los
   lugares marcados sobre la foto). Para probar sin cámara real, en la
   tarjeta de la cámara usá **"Mandar foto de prueba"** dos veces, con 45 s
   de diferencia.

Para publicarla en internet o conectar cámaras de otras casas, ver más abajo.

## Instalar en Linux / Mac

Ubuntu, Debian y derivados no dejan instalar paquetes de Python en el
sistema (error *"This environment is externally managed"*). Se usa un
entorno virtual: una carpeta `.venv` dentro del proyecto con sus paquetes.
No uses `--break-system-packages`: puede romper programas del sistema.

Una sola vez, desde la carpeta del proyecto:

```
sudo apt install python3-venv python3-full    # solo Ubuntu/Debian
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Cada vez que abras una terminal nueva para usar la app, primero activá el
entorno (al principio de la línea aparece `(.venv)`) y después arrancala:

```
source .venv/bin/activate
python -m uvicorn servidor.main:app --port 8000
```

Con el entorno activado, todos los comandos de este README funcionan
cambiando `py` por `python` (por ejemplo `python -m scripts.simular_camaras`).
Los `.bat` son solo para Windows: en Linux/Mac el equivalente de
`iniciar_publico.bat` es `python -m scripts.iniciar_publico` (instalando
antes `cloudflared` desde https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/),
y el de `iniciar_camara.bat` es `python cliente_camara.py` dentro de
`cliente_camara/` (con `pip install opencv-python`).

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
├── tests/              pytest (lógica de detección, detector y API)
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

Las cámaras **mandan sus fotos al servidor**: un dispositivo (la compu
con la webcam, o una compu que lee un celular con IP Webcam o una cámara
IP de su red) hace un `POST /api/camaras/<id>/fotos` con la foto (campo
`foto`) y el header `X-Camera-Key: <api_key>`. Como la conexión sale de la
casa de la cámara hacia el servidor, el router no la bloquea y funciona
desde cualquier red. Pasos para una cámara en otra casa:

1. Publicá la app con `iniciar_publico.bat` y entrá al admin **desde el
   link público**.
2. En la cámara (Editar → Confirmar) tocá **"Descargar camara.ini"**: sale
   con el link, el ID y la key ya completos.
3. Pasale a la otra persona la carpeta `cliente_camara/` con ese
   `camara.ini` adentro. Ella elige la `fuente` (webcam `0`, IP Webcam
   `http://IP-del-celu:8080/video` o RTSP) y hace doble clic en
   `iniciar_camara.bat` (instala OpenCV la primera vez). Ver `cliente_camara/LEEME.txt`.

Si las fotos tienen otra resolución que la de referencia, los polígonos se
escalan solos.

## Ajustar la detección

Todo se cambia en `.env` (ver `.env.example`):

| Variable | Qué hace | Cuándo tocarla |
|---|---|---|
| `MIN_SOLAPE` (0.25) | Cuánto de la parte baja de la caja del auto tiene que tapar al lugar para contarlo | Bajala si marcaste lugares muy chicos y el auto figura afuera; subila si un auto marca también el lugar vecino |
| `HUELLA_FRAC` (0.5) | Qué parte de la caja, desde abajo, se toma como lo que apoya en el suelo | Orientativo: cámaras que miran muy de arriba, subila (0.7); muy de costado, bajala (0.35) |
| `GRACIA_S` (25) | Segundos que un lugar puede figurar vacío (el modelo no ve el auto en una o dos fotos) sin reiniciar la cuenta | Pensada para fotos cada ~10 s (tolera 2 seguidas sin ver el auto). Subila si el modelo parpadea mucho o si sacás las fotos más espaciadas; `0` = como antes (un solo hueco reinicia) |
| `CONF_MIN` (0.35) | Confianza mínima de YOLO | Bajala con autos lejanos o tapados (más falsos positivos) |
| `IMGSZ` (0 = el del modelo, 640) | Tamaño de entrada de YOLO | `960` o `1280` ayudan con autos lejanos en fotos grandes; usan bastante más CPU |
| `MAX_FOTOS_EN_COLA` (30) | Fotos esperando por cámara; al pasarse se borran las más viejas | Evita que `fotos/` crezca sin parar si el detector está apagado o atrasado |
| `HISTORIAL_DIAS` (30) | Días que se guarda el historial (una fila por foto) | `0` = guardar todo |

En el log del detector, `sin verse un momento: [...]` indica lugares que
siguen contando aunque en esa foto el modelo no viera el auto.

## Tests

```
py -m pytest
```

Cubren la lógica de detección (con un modelo de mentira, sin YOLO), el
detector contra una carpeta de fotos y la base, y la API.

## Limitación conocida del modelo

En la foto de prueba, el auto negro de `espacio_3` (tapado por el árbol)
**no se detecta** ni bajando la confianza a 0.05 ni subiendo la resolución
de entrada, así que ese lugar figura siempre libre. Se arregla
reentrenando `best.pt` con más fotos de autos parcialmente tapados.
