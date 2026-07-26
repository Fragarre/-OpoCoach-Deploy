"""
==============================================================================
OpoCoach
Archivo: formato.py
==============================================================================

Descripción:
    Funciones de formato para la interfaz.

==============================================================================
"""

def entero(valor: int) -> str:
    """
    Formatea enteros con separador de miles español.
    """
    return f"{valor:,}".replace(",", ".")