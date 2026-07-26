"""
==============================================================================
OpoCoach
Archivo: contexto.py
==============================================================================

Descripción:
    Contexto de trabajo de la convocatoria activa.

==============================================================================
"""

from lib.repositorio import obtener_resumen_convocatoria
from lib.sesion import obtener_convocatoria_id


def obtener_contexto():
    convocatoria_id = obtener_convocatoria_id()

    if convocatoria_id is None:
        return None

    return obtener_resumen_convocatoria(convocatoria_id)