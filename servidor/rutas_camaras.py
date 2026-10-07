"""
Recepción de fotos que mandan las cámaras (fase "tiempo real").

La cámara hace:
    POST /api/camaras/<id>/fotos
    header  X-Camera-Key: <api_key de camaras/<id>/camara.json>
    form    foto=<archivo jpg/png>

La foto se guarda en camaras/<id>/fotos/ y el detector la procesa en su
próxima pasada, igual que una foto de prueba copiada a mano.
"""

import hmac

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

import config
import gestor_camaras as gc

router = APIRouter(prefix="/api/camaras")


def guardar_foto_entrante(camara_id, contenido):
    """Valida la imagen y la deja en la carpeta fotos/ de la cámara."""
    if len(contenido) > config.MAX_BYTES_FOTO:
        raise HTTPException(413, "La foto es demasiado grande")
    try:
        return gc.guardar_foto(camara_id, contenido)
    except gc.ErrorCamara as e:
        raise HTTPException(415, str(e))


@router.post("/{camara_id}/fotos")
async def recibir_foto(camara_id: str, foto: UploadFile = File(...),
                       x_camera_key: str = Header(..., alias="X-Camera-Key")):
    try:
        cam = gc.leer_camara(camara_id)
    except gc.ErrorCamara:
        raise HTTPException(404, "Cámara inexistente")
    if not hmac.compare_digest(x_camera_key, cam["api_key"]):
        raise HTTPException(401, "API key incorrecta")
    if not cam.get("activa", True):
        raise HTTPException(409, "La cámara está desactivada")
    nombre = guardar_foto_entrante(camara_id, await foto.read())
    return {"ok": True, "camara": camara_id, "archivo": nombre}
