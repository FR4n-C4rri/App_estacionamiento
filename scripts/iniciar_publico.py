"""
Levanta la app y la publica en internet con un túnel de Cloudflare
(gratis, sin cuenta). Lo usa iniciar_publico.bat (doble clic).

    py -m scripts.iniciar_publico
    py -m scripts.iniciar_publico --puerto 8001   (si el 8000 está ocupado)

Pasos:
  1. Busca cloudflared (se instala con: winget install Cloudflare.cloudflared).
  2. Si la contraseña de admin sigue siendo la de fábrica ("admin"), pide
     una nueva y la guarda en .env: con el túnel el panel queda en internet.
  3. Arranca el servidor (localhost:8000) y el túnel.
  4. Muestra el link público, lo copia al portapapeles y lo guarda en
     link_publico.txt.

Ctrl+C (o cerrar la ventana) apaga todo. El link cambia cada vez que se
arranca: las cámaras que mandan fotos tienen que actualizar "servidor"
en su camara.ini.
"""

import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import config

PUERTO = 8000
URL_LOCAL = f"http://localhost:{PUERTO}"


def _leer_puerto():
    global PUERTO, URL_LOCAL
    if "--puerto" in sys.argv:
        PUERTO = int(sys.argv[sys.argv.index("--puerto") + 1])
        URL_LOCAL = f"http://localhost:{PUERTO}"
PATRON_LINK = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
RUTAS_CLOUDFLARED = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "cloudflared" / "cloudflared.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "cloudflared" / "cloudflared.exe",
]


def buscar_cloudflared():
    encontrado = shutil.which("cloudflared")
    if encontrado:
        return encontrado
    for ruta in RUTAS_CLOUDFLARED:
        if ruta.exists():
            return str(ruta)
    raise SystemExit("No encontré cloudflared. Instalalo una vez con:\n\n"
                     "    winget install --id Cloudflare.cloudflared\n\n"
                     "y volvé a abrir este programa.")


def asegurar_contrasena():
    if config.ADMIN_PASSWORD != "admin":
        return
    print("La contraseña del modo admin sigue siendo 'admin'. Con el túnel el panel")
    print("queda en internet, así que elegí una nueva (se guarda en el archivo .env).\n")
    while True:
        nueva = getpass.getpass("Nueva contraseña de admin (no se ve al escribir): ").strip()
        if len(nueva) < 6:
            print("Tiene que tener al menos 6 caracteres.")
            continue
        if getpass.getpass("Repetila: ").strip() != nueva:
            print("No coinciden, de nuevo.")
            continue
        break
    ruta_env = config.RAIZ / ".env"
    lineas = ruta_env.read_text(encoding="utf-8").splitlines() if ruta_env.exists() else []
    lineas = [l for l in lineas if not l.strip().startswith("ADMIN_PASSWORD=")]
    lineas.append(f"ADMIN_PASSWORD={nueva}")
    ruta_env.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("Contraseña guardada en .env\n")


def puerto_ocupado():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PUERTO)) == 0


def responde(url, timeout=5):
    try:
        with urllib.request.urlopen(f"{url}/api/cerca?lat=0&lng=0&radio=1", timeout=timeout) as r:
            return "cuadras" in json.loads(r.read())
    except Exception:
        return False


def esperar(condicion, segundos, proceso=None):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return True
        if proceso is not None and proceso.poll() is not None:
            return False
        time.sleep(1)
    return False


def copiar_al_portapapeles(texto):
    try:
        subprocess.run("clip", input=texto, text=True, check=True, shell=True)
        return True
    except Exception:
        return False


def main():
    _leer_puerto()
    cloudflared = buscar_cloudflared()
    asegurar_contrasena()

    if puerto_ocupado():
        raise SystemExit(f"Ya hay algo usando el puerto {PUERTO} (¿el servidor abierto en otra ventana?).\n"
                         f"Cerralo y volvé a abrir este programa, así arranca con la configuración nueva.")

    procesos = []
    try:
        print("Arrancando el servidor...")
        servidor = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "servidor.main:app", "--host", "127.0.0.1", "--port", str(PUERTO)],
            cwd=config.RAIZ,
        )
        procesos.append(servidor)
        if not esperar(lambda: responde(URL_LOCAL), 90, servidor):
            raise SystemExit("El servidor no arrancó. Mirá los mensajes de arriba.")

        print("Abriendo el túnel de Cloudflare...")
        tunel = subprocess.Popen(
            [cloudflared, "tunnel", "--no-autoupdate", "--url", URL_LOCAL],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
        procesos.append(tunel)

        link = {}

        def leer_salida():
            for linea in tunel.stdout:
                if "url" not in link:
                    m = PATRON_LINK.search(linea)
                    if m:
                        link["url"] = m.group(0)
                if " ERR " in linea:
                    print(f"[tunel] {linea.strip()}")

        threading.Thread(target=leer_salida, daemon=True).start()
        if not esperar(lambda: "url" in link, 60, tunel):
            raise SystemExit("No se pudo abrir el túnel (¿hay internet?).")
        url = link["url"]

        print("Esperando que el link responda desde internet...")
        accesible = esperar(lambda: responde(url, timeout=8), 90, tunel)

        (config.RAIZ / "link_publico.txt").write_text(url + "\n", encoding="utf-8")
        copiado = copiar_al_portapapeles(url)
        linea = "=" * 64
        print(f"\n{linea}")
        print("  LA APP ESTÁ PUBLICADA" if accesible else "  TÚNEL ABIERTO (todavía no respondió: probá en un minuto)")
        print(f"\n  Mapa:   {url}/")
        print(f"  Admin:  {url}/admin")
        print(f"\n  {'(link copiado al portapapeles y ' if copiado else '('}guardado en link_publico.txt)")
        print("  Las cámaras que mandan fotos tienen que tener este link en")
        print("  la línea 'servidor' de su camara.ini.")
        print(f"\n  Dejá esta ventana abierta. Ctrl+C para apagar todo.")
        print(f"{linea}\n")

        while all(p.poll() is None for p in procesos):
            time.sleep(1)
        print("Se cerró el servidor o el túnel; apago todo.")
    except KeyboardInterrupt:
        print("\nApagando...")
    finally:
        for p in reversed(procesos):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()


if __name__ == "__main__":
    main()
