"""
==============================================================================
OpoCoach
Archivo: lib/database.py
==============================================================================

Descripción:
    Gestión de las conexiones:

    - oposiciones.sqlite3 permanece en SQLite local.
    - los datos de usuario se almacenan en Turso.
==============================================================================
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from dotenv import load_dotenv
from lib.turso_compat import TursoConnection



BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "db"
load_dotenv(BASE_DIR / ".env")

DB_PATH = DB_DIR / "oposiciones.sqlite3"
os.getenv("TURSO_DATABASE_URL")
os.getenv("TURSO_AUTH_TOKEN")


def _obtener_secreto(nombre: str) -> str:
    """
    Busca primero una variable de entorno y después Streamlit Secrets.
    """
    valor = os.getenv(nombre, "").strip()

    if valor:
        return valor

    try:
        import streamlit as st

        valor_secreto = st.secrets.get(nombre, "")
        return str(valor_secreto).strip()
    except Exception:
        return ""


def _normalizar_url_turso(url: str) -> str:
    """
    libsql-client funciona por HTTP con la base remota utilizada actualmente.
    """
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]

    return url


def conectar():
    """
    Conexión local con la base maestra oposiciones.sqlite3.
    """
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def conectar_usuario() -> TursoConnection:
    """
    Conexión remota con la base de usuario alojada en Turso.
    """
    url = _obtener_secreto("TURSO_DATABASE_URL")
    token = _obtener_secreto("TURSO_AUTH_TOKEN")

    if not url:
        raise RuntimeError(
            "No está configurado TURSO_DATABASE_URL."
        )

    if not token:
        raise RuntimeError(
            "No está configurado TURSO_AUTH_TOKEN."
        )

    return TursoConnection(
        url=_normalizar_url_turso(url),
        auth_token=token,
    )
