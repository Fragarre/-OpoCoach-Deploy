"""
==============================================================================
OpoCoach
Archivo: database.py
==============================================================================

Descripción:
    Gestión de las conexiones con SQLite.

==============================================================================
"""

from pathlib import Path
import sqlite3


BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "db"

DB_PATH = DB_DIR / "oposiciones.sqlite3"
USUARIO_DB_PATH = DB_DIR / "usuario.sqlite3"


def conectar():
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def conectar_usuario():
    conexion = sqlite3.connect(USUARIO_DB_PATH)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion