"""
Servidor de la app. Desde la raíz del proyecto:

    py -m uvicorn servidor.main:app --port 8000

    http://localhost:8000/        -> modo usuario (mapa)
    http://localhost:8000/admin   -> modo admin

Al arrancar crea las tablas, sincroniza las carpetas de camaras/ con la
base y corre en segundo plano el detector (DETECTOR=on) y el captor que
va a buscar las fotos a las cámaras de tipo video/foto (CAPTOR=on).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
import gestor_camaras as gc
from base_de_datos import db
from servidor import rutas_admin, rutas_camaras, rutas_usuario


@asynccontextmanager
async def ciclo_de_vida(app):
    db.crear_tablas()
    ids = gc.sincronizar_db()
    print(f"[servidor] {len(ids)} cámara(s): {', '.join(ids) or '-'}")
    detector = captor = None
    if config.DETECTOR == "on":
        from deteccion.detector import Detector

        detector = Detector()
        detector.iniciar_en_segundo_plano()
    if config.CAPTOR == "on":
        from deteccion.captor import Captor

        captor = Captor()
        captor.iniciar_en_segundo_plano()
    yield
    if captor:
        captor.detener()
    if detector:
        detector.detener()


app = FastAPI(title="Estacionamiento por cuadra", lifespan=ciclo_de_vida)
app.include_router(rutas_usuario.router)
app.include_router(rutas_admin.router)
app.include_router(rutas_camaras.router)
app.mount("/static", StaticFiles(directory=config.CARPETA_WEB), name="static")


@app.middleware("http")
async def sin_cache_en_web(request, call_next):
    # Que el navegador revalide HTML/JS/CSS siempre (si no, tras editar el
    # frontend se sigue viendo la versión vieja).
    respuesta = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", "/admin"):
        respuesta.headers["Cache-Control"] = "no-cache"
    return respuesta


@app.get("/", include_in_schema=False)
def modo_usuario():
    return FileResponse(config.CARPETA_WEB / "usuario" / "index.html")


@app.get("/admin", include_in_schema=False)
def modo_admin():
    return FileResponse(config.CARPETA_WEB / "admin" / "index.html")
