"""
Cámaras IP de mentira para probar el captor sin hardware: se levantan en
127.0.0.1 con un puerto libre y hablan el mismo protocolo que una cámara real.

  - servidor_snapshot(...)   foto por URL, con usuario/clave Basic o Digest
                             (Digest es lo que usan Hikvision y Dahua)
  - servidor_mjpeg(...)      stream HTTP/MJPEG en vivo (IP Webcam: /video)
  - ServidorRTSP(...)        RTSP sobre TCP, con o sin usuario/clave. Necesita
                             ffmpeg instalado para generar el video.
"""

import base64
import hashlib
import http.server
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time

import cv2
import numpy as np


def foto_jpg(ancho=320, alto=240, gris=120):
    return cv2.imencode(".jpg", np.full((alto, ancho, 3), gris, np.uint8))[1].tobytes()


def puerto_libre(tipo=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, tipo) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _md5(texto):
    return hashlib.md5(texto.encode()).hexdigest()


def _campos_digest(cabecera):
    campos = {}
    for clave, entre_comillas, suelto in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', cabecera):
        campos[clave] = entre_comillas or suelto
    return campos


class ServidorHTTP:
    """Servidor HTTP en un hilo. Se usa con `with`; `.host` es 127.0.0.1:puerto."""

    def __init__(self, manejador):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manejador)
        self.srv.daemon_threads = True
        self.host = f"127.0.0.1:{self.srv.server_port}"

    def __enter__(self):
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.srv.shutdown()
        self.srv.server_close()


def servidor_snapshot(usuario=None, clave=None, auth="basic", contenido=None, tipo_contenido="image/jpeg"):
    """Una URL que devuelve una foto por pedido. Con `usuario` pide autenticación
    `auth` ("basic" o "digest"). `.pedidos` cuenta los GET recibidos."""
    contenido = foto_jpg() if contenido is None else contenido
    nonce, realm = "n0nc3-de-prueba", "camara"
    estado = {"pedidos": 0}

    class Manejador(http.server.BaseHTTPRequestHandler):
        def _autorizado(self):
            if usuario is None:
                return True
            cabecera = self.headers.get("Authorization", "")
            if auth == "basic":
                return cabecera == "Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()
            if not cabecera.startswith("Digest "):
                return False
            c = _campos_digest(cabecera[7:])
            ha1, ha2 = _md5(f"{usuario}:{realm}:{clave}"), _md5(f"GET:{c.get('uri')}")
            if c.get("qop") == "auth":
                esperado = _md5(f"{ha1}:{nonce}:{c.get('nc')}:{c.get('cnonce')}:auth:{ha2}")
            else:
                esperado = _md5(f"{ha1}:{nonce}:{ha2}")
            return c.get("username") == usuario and c.get("nonce") == nonce and c.get("response") == esperado

        def do_GET(self):
            estado["pedidos"] += 1
            if not self._autorizado():
                self.send_response(401)
                if auth == "basic":
                    self.send_header("WWW-Authenticate", f'Basic realm="{realm}"')
                else:
                    self.send_header("WWW-Authenticate",
                                     f'Digest realm="{realm}", nonce="{nonce}", qop="auth", algorithm=MD5')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", tipo_contenido)
            self.send_header("Content-Length", str(len(contenido)))
            self.end_headers()
            self.wfile.write(contenido)

        def log_message(self, *args):
            pass

    servidor = ServidorHTTP(Manejador)
    servidor.estado = estado
    return servidor


def servidor_mjpeg(cuadros_por_segundo=20):
    """Stream HTTP multipart/x-mixed-replace que no termina, como /video de IP Webcam."""
    jpg = foto_jpg()

    class Manejador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            parte = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg) + jpg + b"\r\n"
            try:
                while True:
                    self.wfile.write(parte)
                    time.sleep(1 / cuadros_por_segundo)
            except OSError:
                pass  # el captor cortó la conexión

        def log_message(self, *args):
            pass

    return ServidorHTTP(Manejador)


def hay_ffmpeg():
    return shutil.which("ffmpeg") is not None


class ServidorRTSP:
    """RTSP mínimo sobre TCP (RTP intercalado, lo que usan las cámaras IP).
    ffmpeg genera un video de prueba como MJPEG/RTP y este servidor reenvía los
    paquetes al cliente. Con `usuario` pide autenticación Basic.

        with ServidorRTSP() as srv:
            url = f"rtsp://127.0.0.1:{srv.puerto}/live"
    """

    def __init__(self, usuario=None, clave=None, ancho=320, alto=240, sin_video=False):
        """`sin_video`: atiende el protocolo completo pero nunca manda imágenes
        (una cámara ocupada o con el perfil equivocado)."""
        self.usuario, self.clave, self.sin_video = usuario, clave, sin_video
        self.ancho, self.alto = ancho, alto
        self.puerto = puerto_libre()
        self.sesiones = 0
        self._parar = threading.Event()
        self._carpeta = tempfile.mkdtemp(prefix="rtsp_falso_")

    def __enter__(self):
        rtp_puerto = puerto_libre(socket.SOCK_DGRAM)
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.bind(("127.0.0.1", rtp_puerto))
        self._udp.settimeout(0.5)
        sdp_ruta = os.path.join(self._carpeta, "video.sdp")
        self._log_ffmpeg = os.path.join(self._carpeta, "ffmpeg.log")
        with open(self._log_ffmpeg, "wb") as log:
            # skip_rtcp: sin RTCP no hay que dejar un segundo puerto escuchando
            # (si no, ffmpeg recibe "connection refused" y se corta).
            self._ffmpeg = subprocess.Popen(
                ["ffmpeg", "-nostdin", "-loglevel", "error", "-re", "-f", "lavfi",
                 "-i", f"testsrc=size={self.ancho}x{self.alto}:rate=10",
                 "-c:v", "mjpeg", "-huffman", "default", "-pix_fmt", "yuvj420p", "-sdp_file", sdp_ruta,
                 "-rtpflags", "skip_rtcp", "-f", "rtp", f"rtp://127.0.0.1:{rtp_puerto}"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
        limite = time.time() + 10
        while not os.path.exists(sdp_ruta) and time.time() < limite:
            time.sleep(0.05)
        if not os.path.exists(sdp_ruta):
            raise RuntimeError("ffmpeg no generó el video de prueba: " + open(self._log_ffmpeg).read())
        with open(sdp_ruta, encoding="utf-8") as f:
            sdp = f.read().replace("\r\n", "\n").rstrip("\n")
        # `a=control` le dice al cliente a qué URL hacer el SETUP de este video.
        self._sdp = (sdp + "\na=control:trackID=0\n").replace("\n", "\r\n")

        self._tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp.bind(("127.0.0.1", self.puerto))
        self._tcp.listen(5)
        self._tcp.settimeout(0.5)
        threading.Thread(target=self._aceptar, daemon=True).start()
        return self

    def __exit__(self, *_):
        self._parar.set()
        self._ffmpeg.terminate()
        try:
            self._ffmpeg.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._ffmpeg.kill()
        for s in (self._tcp, self._udp):
            s.close()
        shutil.rmtree(self._carpeta, ignore_errors=True)

    # --- Protocolo ---

    def _aceptar(self):
        while not self._parar.is_set():
            try:
                conn, _ = self._tcp.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._atender, args=(conn,), daemon=True).start()

    def _autorizado(self, cabeceras):
        if self.usuario is None:
            return True
        esperado = "Basic " + base64.b64encode(f"{self.usuario}:{self.clave}".encode()).decode()
        return cabeceras.get("authorization") == esperado

    @staticmethod
    def _respuesta(cseq, estado="200 OK", extra=(), cuerpo=b""):
        lineas = [f"RTSP/1.0 {estado}", f"CSeq: {cseq}", *extra]
        if cuerpo:
            lineas.append(f"Content-Length: {len(cuerpo)}")
        return ("\r\n".join(lineas) + "\r\n\r\n").encode() + cuerpo

    def _atender(self, conn):
        conn.settimeout(0.5)
        buf = b""
        reenviando = threading.Event()
        try:
            while not self._parar.is_set():
                try:
                    datos = conn.recv(4096)
                except socket.timeout:
                    continue
                if not datos:
                    return
                buf += datos
                while buf:
                    if buf[:1] == b"$":  # RTCP del cliente (canal intercalado): se ignora
                        if len(buf) < 4:
                            break
                        largo = struct.unpack(">H", buf[2:4])[0]
                        if len(buf) < 4 + largo:
                            break
                        buf = buf[4 + largo:]
                        continue
                    fin = buf.find(b"\r\n\r\n")
                    if fin < 0:
                        break
                    pedido, buf = buf[:fin].decode(errors="replace"), buf[fin + 4:]
                    if not self._responder(conn, pedido, reenviando):
                        return
        except OSError:
            pass
        finally:
            reenviando.clear()
            conn.close()

    def _responder(self, conn, pedido, reenviando):
        lineas = pedido.split("\r\n")
        metodo, url = lineas[0].split(" ")[:2]
        cabeceras = {l.split(":", 1)[0].strip().lower(): l.split(":", 1)[1].strip() for l in lineas[1:] if ":" in l}
        cseq = cabeceras.get("cseq", "0")
        sesion = ["Session: 12345678"]

        if metodo == "OPTIONS":
            conn.sendall(self._respuesta(cseq, extra=["Public: OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER"]))
        elif not self._autorizado(cabeceras):
            conn.sendall(self._respuesta(cseq, "401 Unauthorized", ['WWW-Authenticate: Basic realm="camara"']))
        elif metodo == "DESCRIBE":
            conn.sendall(self._respuesta(cseq, extra=[f"Content-Base: {url.rstrip('/')}/", "Content-Type: application/sdp"],
                                         cuerpo=self._sdp.encode()))
        elif metodo == "SETUP":
            self.sesiones += 1
            canales = re.search(r"interleaved=(\d+)-(\d+)", cabeceras.get("transport", ""))
            if not canales:
                conn.sendall(self._respuesta(cseq, "461 Unsupported Transport"))
                return True
            conn.sendall(self._respuesta(cseq, extra=[
                f"Transport: RTP/AVP/TCP;unicast;interleaved={canales.group(1)}-{canales.group(2)}",
                "Session: 12345678;timeout=60"]))
            self._canal = int(canales.group(1))
        elif metodo == "PLAY":
            conn.sendall(self._respuesta(cseq, extra=sesion + ["Range: npt=0.000-"]))
            if not self.sin_video:
                reenviando.set()
                threading.Thread(target=self._reenviar, args=(conn, reenviando), daemon=True).start()
        elif metodo == "TEARDOWN":
            conn.sendall(self._respuesta(cseq, extra=sesion))
            return False
        else:  # GET_PARAMETER y demás keep-alive
            conn.sendall(self._respuesta(cseq, extra=sesion))
        return True

    def _reenviar(self, conn, reenviando):
        # Lo que ffmpeg mandó mientras nadie miraba es viejo: se descarta.
        self._udp.settimeout(0.01)
        try:
            while True:
                self._udp.recvfrom(65535)
        except socket.timeout:
            pass
        self._udp.settimeout(0.5)
        while reenviando.is_set() and not self._parar.is_set():
            try:
                paquete, _ = self._udp.recvfrom(65535)
                conn.sendall(b"$" + bytes([self._canal]) + struct.pack(">H", len(paquete)) + paquete)
            except socket.timeout:
                continue
            except OSError:
                return
