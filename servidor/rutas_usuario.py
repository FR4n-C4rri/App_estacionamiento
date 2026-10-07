"""Endpoints del modo usuario: buscar lugares cerca y ver la foto de una cuadra."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

import config
import gestor_camaras as gc
from base_de_datos import db
from servidor.geo import distancia_m

router = APIRouter(prefix="/api")


def resumen_camara(fila, conn=None, con_espacios=False):
    """Arma lo que ve el mapa de una cámara a partir de una fila de
    db.camaras_con_estado(). Si el último dato es viejo -> 'SIN DATOS'."""
    cuadra = None
    if fila["cuadra_inicio_lat"] is not None and fila["cuadra_fin_lat"] is not None:
        cuadra = [[fila["cuadra_inicio_lat"], fila["cuadra_inicio_lng"]],
                  [fila["cuadra_fin_lat"], fila["cuadra_fin_lng"]]]

    estado = "SIN DATOS"
    minutos = None
    if fila["actualizado_en"]:
        actualizado = datetime.fromisoformat(fila["actualizado_en"])
        minutos = (datetime.now(timezone.utc) - actualizado).total_seconds() / 60
        if minutos <= config.MINUTOS_SIN_DATOS:
            estado = fila["estado"]

    total = fila["total"] if fila["total"] is not None else fila["total_lugares"]
    ocupados = fila["ocupados"]
    datos = {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "direccion": fila["direccion"],
        "lat": fila["lat"],
        "lng": fila["lng"],
        "cuadra": cuadra,
        "activa": bool(fila["activa"]),
        "total": total,
        "ocupados": ocupados,
        "libres": max(total - ocupados, 0) if ocupados is not None else None,
        "porcentaje": fila["porcentaje"],
        "estado": estado,
        "actualizado_en": fila["actualizado_en"],
        "minutos_desde_actualizacion": round(minutos, 1) if minutos is not None else None,
        "prohibidos_bloqueados": fila["prohibidos_bloqueados"] or 0,
        "tiene_preview": gc.ruta_preview(fila["id"]).exists(),
    }
    if con_espacios and conn is not None:
        datos["espacios"] = db.espacios_de(conn, fila["id"])
    return datos


@router.get("/cerca")
def lugares_cerca(lat: float = Query(..., ge=-90, le=90),
                  lng: float = Query(..., ge=-180, le=180),
                  radio: float = Query(config.RADIO_DEFAULT_M, gt=0, le=20000)):
    """Cuadras con cámara dentro de `radio` metros, de la más cercana a la más lejana."""
    resultado = []
    with db.conectar() as conn:
        for fila in db.camaras_con_estado(conn, solo_activas=True):
            d = distancia_m(lat, lng, fila["lat"], fila["lng"])
            if d <= radio:
                item = resumen_camara(fila, conn, con_espacios=True)
                item["distancia_m"] = round(d)
                resultado.append(item)
    resultado.sort(key=lambda c: c["distancia_m"])
    return {"lat": lat, "lng": lng, "radio": radio, "cuadras": resultado}


@router.get("/camaras/{camara_id}/preview.jpg")
def preview(camara_id: str):
    try:
        ruta = gc.ruta_preview(camara_id)
    except gc.ErrorCamara:
        raise HTTPException(404)
    if not ruta.exists():
        raise HTTPException(404, "Esta cámara todavía no procesó ninguna foto")
    return FileResponse(ruta, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})
