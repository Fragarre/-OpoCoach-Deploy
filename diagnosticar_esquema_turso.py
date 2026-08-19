
from __future__ import annotations

from lib.database import conectar_usuario


def main() -> int:
    print("=" * 78)
    print("DIAGNÓSTICO ESQUEMA TURSO")
    print("=" * 78)
    print("Modo: SOLO LECTURA")
    print()

    with conectar_usuario() as con:
        fila = con.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = ?
              AND name = ?
            """,
            ("table", "simulacro_preguntas"),
        ).fetchone()

        if fila is None:
            print("ERROR: no existe la tabla simulacro_preguntas en Turso.")
            return 1

        print("Definición de simulacro_preguntas:")
        print("-" * 78)
        print(fila[0])
        print("-" * 78)

        print()
        print("Valores actuales de seguridad_usuario:")
        print("-" * 78)

        filas = con.execute(
            """
            SELECT
                seguridad_usuario,
                COUNT(*) AS cantidad
            FROM simulacro_preguntas
            GROUP BY seguridad_usuario
            ORDER BY seguridad_usuario
            """
        ).fetchall()

        for valor, cantidad in filas:
            etiqueta = "NULL" if valor is None else repr(valor)
            print(f"{etiqueta:25} {cantidad}")

    print()
    print("Diagnóstico terminado. No se ha modificado Turso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
