"""Envío de una foto al servidor (multipart/form-data) usando solo la librería estándar."""

import json
import secrets
import urllib.error
import urllib.request


def enviar_foto(servidor, camara_id, api_key, contenido, nombre="foto.jpg", tipo="image/jpeg"):
    limite = "----limite" + secrets.token_hex(12)
    cuerpo = (
        f"--{limite}\r\n"
        f'Content-Disposition: form-data; name="foto"; filename="{nombre}"\r\n'
        f"Content-Type: {tipo}\r\n\r\n"
    ).encode() + contenido + f"\r\n--{limite}--\r\n".encode()

    req = urllib.request.Request(
        f"{servidor.rstrip('/')}/api/camaras/{camara_id}/fotos",
        data=cuerpo,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={limite}", "X-Camera-Key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"El servidor respondió {e.code}: {e.read().decode(errors='replace')}") from None
