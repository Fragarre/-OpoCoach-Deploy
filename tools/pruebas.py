from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from lib.database import conectar


TABLAS = [
    "convocatorias",
    "lote_preguntas",
    "banco_preguntas",
    "convocatoria_partes",
]

with conectar() as con:
    for tabla in TABLAS:
        print(f"\n--- {tabla} ---")
        for fila in con.execute(f"PRAGMA table_info({tabla})"):
            print(f"{fila['name']:<30} {fila['type']}")