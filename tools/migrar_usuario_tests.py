from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
DB_DEFECTO = RAIZ / "db" / "usuario.sqlite3"


def columnas(con: sqlite3.Connection, tabla: str) -> set[str]:
    return {
        str(fila[1])
        for fila in con.execute(f"PRAGMA table_info({tabla})")
    }


def crear_backup(db: Path) -> Path:
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db.with_name(
        f"{db.stem}_antes_tests_{marca}{db.suffix}"
    )
    shutil.copy2(db, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_DEFECTO)
    args = parser.parse_args()

    db = args.db.resolve()

    if not db.is_file():
        raise FileNotFoundError(f"No existe la base: {db}")

    backup = crear_backup(db)

    with sqlite3.connect(db) as con:
        con.execute("PRAGMA foreign_keys = ON")

        tablas = {
            fila[0]
            for fila in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        if "simulacros" not in tablas:
            raise RuntimeError("No existe la tabla simulacros.")

        if "tipo_prueba" not in columnas(con, "simulacros"):
            con.execute(
                """
                ALTER TABLE simulacros
                ADD COLUMN tipo_prueba TEXT NOT NULL
                    DEFAULT 'SIMULACRO'
                    CHECK (tipo_prueba IN ('SIMULACRO', 'TEST'))
                """
            )

        con.execute(
            """
            UPDATE simulacros
            SET tipo_prueba = 'SIMULACRO'
            WHERE tipo_prueba IS NULL
               OR TRIM(tipo_prueba) = ''
            """
        )

        errores_fk = con.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if errores_fk:
            raise RuntimeError(
                f"Errores de claves externas: {errores_fk}"
            )

        integridad = con.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integridad != "ok":
            raise RuntimeError(
                f"integrity_check devolvió: {integridad}"
            )

    print(f"Base migrada: {db}")
    print(f"Copia de seguridad: {backup}")
    print("Columna disponible: simulacros.tipo_prueba")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            f"ERROR: {error.__class__.__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
