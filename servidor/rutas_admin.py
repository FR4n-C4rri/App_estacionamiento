"""
Endpoints del modo admin. Todos (menos el login) piden el header
`Authorization: Bearer <token>` que devuelve POST /api/admin/login.
"""

import hmac
import json
import secrets

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import gestor_camaras as gc
from base_de_datos import db
from servidor.rutas_camaras import guardar_foto_entrante
from servidor.rutas_usuario import resumen_camara

router = APIRouter(prefix="/api/admin")

_tokens = set()  # sesiones abiertas (se pierden al reiniciar el servidor)


class Login(BaseModel):
    password: str


def requiere_admin(authorization: str = Header("")):
    token = authorization.removeprefix("Bearer ").strip()
    if token not in _tokens:
        raise HTTPException(401, "Sesión de admin inválida o vencida")


def _error(e):
    return HTTPException(400, str(e))


def _camara_existente(camara_id):
    try:
        if not gc.existe(camara_id):
            raise HTTPException(404, f"No existe la cámara {camara_id}")
    except gc.ErrorCamara as e:
        raise _error(e)


@router.post("/login")
def login(datos: Login):
    if not hmac.compare_digest(datos.password.encode(), config.ADMIN_PASSWORD.encode()):
        raise HTTPException(401, "Contraseña incorrecta")
    token = secrets.token_urlsafe(24)
    _tokens.add(token)
    return {"token": token}


@router.get("/camaras", dependencies=[Depends(requiere_admin)])
def listar():
    with db.conectar() as conn:
        return [resumen_camara(f, conn, con_espacios=True) for f in db.camaras_con_estado(conn)]


@router.get("/siguiente_id", dependencies=[Depends(requiere_admin)])
def siguiente_id():
    return {"id": gc.siguiente_id()}


@router.get("/camaras/{camara_id}", dependencies=[Depends(requiere_admin)])
def detalle(camara_id: str):
    _camara_existente(camara_id)
    cam = gc.leer_camara(camara_id)
    return {
        **cam,
        "espacios": gc.leer_espacios(camara_id),
        "fotos_pendientes": len(list(gc.ruta_fotos(camara_id).glob("*.*"))) if gc.ruta_fotos(camara_id).exists() else 0,
        "endpoint_fotos": f"/api/camaras/{camara_id}/fotos",
    }


@router.post("/camaras", dependencies=[Depends(requiere_admin)])
async def crear(id: str = Form(...), datos: str = Form(...), espacios: str = Form(...),
                referencia: UploadFile = File(...)):
    """Alta completa de una cámara (último paso del asistente)."""
    try:
        cam = gc.crear(id.strip(), json.loads(datos), json.loads(espacios), await referencia.read())
    except (gc.ErrorCamara, json.JSONDecodeError) as e:
        raise _error(e)
    return {**cam, "endpoint_fotos": f"/api/camaras/{cam['id']}/fotos"}


@router.put("/camaras/{camara_id}", dependencies=[Depends(requiere_admin)])
def editar(camara_id: str, datos: dict = Body(...)):
    _camara_existente(camara_id)
    try:
        return gc.actualizar_datos(camara_id, datos)
    except gc.ErrorCamara as e:
        raise _error(e)


@router.put("/camaras/{camara_id}/espacios", dependencies=[Depends(requiere_admin)])
def editar_espacios(camara_id: str, espacios: list = Body(...)):
    _camara_existente(camara_id)
    try:
        return gc.actualizar_espacios(camara_id, espacios)
    except gc.ErrorCamara as e:
        raise _error(e)


@router.get("/camaras/{camara_id}/referencia.jpg", dependencies=[Depends(requiere_admin)])
def referencia(camara_id: str):
    _camara_existente(camara_id)
    return FileResponse(gc.ruta_referencia(camara_id), media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


@router.post("/camaras/{camara_id}/referencia", dependencies=[Depends(requiere_admin)])
async def cambiar_referencia(camara_id: str, referencia: UploadFile = File(...)):
    """Nueva foto de referencia. Después hay que volver a guardar los espacios."""
    _camara_existente(camara_id)
    try:
        ancho, alto = gc.actualizar_referencia(camara_id, await referencia.read())
    except gc.ErrorCamara as e:
        raise _error(e)
    return {"ancho": ancho, "alto": alto}


@router.get("/camaras/{camara_id}/ultima_foto", dependencies=[Depends(requiere_admin)])
def ultima_foto(camara_id: str):
    """Última foto (sin dibujar) que mandó la cámara, para usarla de referencia."""
    _camara_existente(camara_id)
    ultima = gc.ultima_foto_recibida(camara_id)
    if ultima is None:
        raise HTTPException(404, "Esta cámara todavía no mandó fotos")
    tipo = "image/png" if ultima.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(ultima, media_type=tipo, headers={"Cache-Control": "no-cache"})


@router.post("/camaras/{camara_id}/fotos", dependencies=[Depends(requiere_admin)])
async def subir_foto_prueba(camara_id: str, foto: UploadFile = File(...)):
    """Mandar una foto como si fuera la cámara (para probar sin cámara real)."""
    _camara_existente(camara_id)
    return {"archivo": guardar_foto_entrante(camara_id, await foto.read())}


@router.post("/camaras/{camara_id}/regenerar_key", dependencies=[Depends(requiere_admin)])
def regenerar_key(camara_id: str):
    _camara_existente(camara_id)
    return {"api_key": gc.regenerar_api_key(camara_id)}


@router.delete("/camaras/{camara_id}", dependencies=[Depends(requiere_admin)])
def eliminar(camara_id: str):
    _camara_existente(camara_id)
    gc.eliminar(camara_id)
    return {"ok": True}
