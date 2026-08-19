
from __future__ import annotations

from datetime import datetime

from lib.database import conectar_usuario


TABLA = "simulacro_preguntas"
TABLA_NUEVA = "simulacro_preguntas_nueva_seguridad"


def obtener_valores(con, tabla: str) -> dict[str | None, int]:
    filas = con.execute(
        f"""
        SELECT seguridad_usuario, COUNT(*) AS cantidad
        FROM {tabla}
        GROUP BY seguridad_usuario
        ORDER BY seguridad_usuario
        """
    ).fetchall()

    resultado: dict[str | None, int] = {}

    for fila in filas:
        resultado[fila[0]] = int(fila[1])

    return resultado


def mostrar_valores(titulo: str, valores: dict[str | None, int]) -> None:
    print()
    print(titulo)
    print("-" * len(titulo))

    for valor, cantidad in valores.items():
        etiqueta = "NULL" if valor is None else valor
        print(f"{etiqueta:20} {cantidad:6}")


def main() -> int:
    print("=" * 78)
    print("MIGRACIÓN TURSO: NORMALIZAR SEGURIDAD")
    print("=" * 78)

    with conectar_usuario() as con:
        fila_sql = con.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (TABLA,),
        ).fetchone()

        if fila_sql is None:
            raise RuntimeError(
                "No existe la tabla simulacro_preguntas."
            )

        sql_actual = str(fila_sql[0] or "")

        valores_antes = obtener_valores(con, TABLA)
        mostrar_valores("Valores antes de migrar", valores_antes)

        permitidos_antes = {
            None,
            "MUY_SEGURO",
            "BASTANTE_SEGURO",
            "POCO_SEGURO",
            "SEGURO",
            "MENOS_SEGURO",
        }

        inesperados = set(valores_antes) - permitidos_antes

        if inesperados:
            raise RuntimeError(
                "Existen valores de seguridad no previstos: "
                + ", ".join(repr(x) for x in inesperados)
            )

        if (
            "'SEGURO'" in sql_actual
            and "'MENOS_SEGURO'" in sql_actual
            and "'MUY_SEGURO'" not in sql_actual
            and "'BASTANTE_SEGURO'" not in sql_actual
            and "'POCO_SEGURO'" not in sql_actual
        ):
            print()
            print(
                "La estructura ya admite únicamente SEGURO y MENOS_SEGURO."
            )
            print("No es necesario reconstruir la tabla.")
            return 0

        total_antes = int(
            con.execute(
                f"SELECT COUNT(*) FROM {TABLA}"
            ).fetchone()[0]
        )

        total_snapshot = int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM simulacro_snapshot
                """
            ).fetchone()[0]
        )

        huerfanos_antes = int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM simulacro_snapshot ss
                LEFT JOIN simulacro_preguntas sp
                    ON sp.id = ss.simulacro_pregunta_id
                WHERE sp.id IS NULL
                """
            ).fetchone()[0]
        )

        if huerfanos_antes != 0:
            raise RuntimeError(
                "Ya existen snapshots huérfanos antes de la migración. "
                "No se modifica nada."
            )

        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        tabla_backup = f"simulacro_preguntas_backup_{marca}"

        print()
        print(f"Filas en simulacro_preguntas: {total_antes}")
        print(f"Filas en simulacro_snapshot:  {total_snapshot}")
        print(f"Snapshots huérfanos:          {huerfanos_antes}")
        print()
        print("Conversión:")
        print("  MUY_SEGURO       -> SEGURO")
        print("  BASTANTE_SEGURO  -> MENOS_SEGURO")
        print("  POCO_SEGURO      -> MENOS_SEGURO")
        print()
        print(
            "Se creará además una tabla de respaldo en Turso: "
            f"{tabla_backup}"
        )

        confirmacion = input(
            "Escribe MIGRAR para continuar: "
        ).strip()

        if confirmacion != "MIGRAR":
            print("Operación cancelada.")
            return 1

        # La tabla de respaldo se crea antes de tocar la original.
        con.execute(
            f"""
            CREATE TABLE {tabla_backup} AS
            SELECT *
            FROM {TABLA}
            """
        )

        respaldo = int(
            con.execute(
                f"SELECT COUNT(*) FROM {tabla_backup}"
            ).fetchone()[0]
        )

        if respaldo != total_antes:
            raise RuntimeError(
                "La copia de respaldo no contiene el mismo número de filas. "
                "No se continúa."
            )

        # La capa Turso de OpoCoach trabaja con cada sentencia confirmada
        # individualmente. Se desactiva temporalmente la comprobación de FK
        # para poder reconstruir la tabla conservando exactamente los IDs.
        con.execute("PRAGMA foreign_keys = OFF")

        # Si quedó una tabla temporal de un intento anterior, no se reutiliza.
        con.execute(
            f"DROP TABLE IF EXISTS {TABLA_NUEVA}"
        )

        con.execute(
            f"""
            CREATE TABLE {TABLA_NUEVA} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                simulacro_id INTEGER NOT NULL,
                orden INTEGER NOT NULL,

                pregunta_id INTEGER,
                banco_pregunta_id INTEGER,
                parte_id INTEGER,

                parte_nombre TEXT,
                parte_orden INTEGER,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                respuesta_usuario TEXT
                    CHECK (
                        respuesta_usuario IS NULL
                        OR respuesta_usuario IN ('A', 'B', 'C', 'D')
                    ),

                seguridad_usuario TEXT
                    CHECK (
                        seguridad_usuario IS NULL
                        OR seguridad_usuario IN (
                            'SEGURO',
                            'MENOS_SEGURO'
                        )
                    ),

                FOREIGN KEY (simulacro_id)
                    REFERENCES simulacros(id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE,

                UNIQUE (simulacro_id, orden),
                UNIQUE (simulacro_id, pregunta_id)
            )
            """
        )

        con.execute(
            f"""
            INSERT INTO {TABLA_NUEVA} (
                id,
                simulacro_id,
                orden,
                pregunta_id,
                banco_pregunta_id,
                parte_id,
                parte_nombre,
                parte_orden,
                created_at,
                respuesta_usuario,
                seguridad_usuario
            )
            SELECT
                id,
                simulacro_id,
                orden,
                pregunta_id,
                banco_pregunta_id,
                parte_id,
                parte_nombre,
                parte_orden,
                created_at,
                respuesta_usuario,
                CASE seguridad_usuario
                    WHEN 'MUY_SEGURO'
                        THEN 'SEGURO'
                    WHEN 'BASTANTE_SEGURO'
                        THEN 'MENOS_SEGURO'
                    WHEN 'POCO_SEGURO'
                        THEN 'MENOS_SEGURO'
                    ELSE seguridad_usuario
                END
            FROM {TABLA}
            ORDER BY id
            """
        )

        total_nueva = int(
            con.execute(
                f"SELECT COUNT(*) FROM {TABLA_NUEVA}"
            ).fetchone()[0]
        )

        if total_nueva != total_antes:
            raise RuntimeError(
                "La tabla nueva no contiene el mismo número de filas. "
                f"Original={total_antes}, nueva={total_nueva}. "
                f"El respaldo permanece en {tabla_backup}."
            )

        valores_nueva = obtener_valores(con, TABLA_NUEVA)

        if set(valores_nueva) - {None, "SEGURO", "MENOS_SEGURO"}:
            raise RuntimeError(
                "La tabla nueva contiene valores de seguridad no normalizados. "
                f"El respaldo permanece en {tabla_backup}."
            )

        # Verifica que se conservaron exactamente los mismos IDs.
        ids_distintos = int(
            con.execute(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT id FROM {TABLA}
                    EXCEPT
                    SELECT id FROM {TABLA_NUEVA}

                    UNION ALL

                    SELECT id FROM {TABLA_NUEVA}
                    EXCEPT
                    SELECT id FROM {TABLA}
                )
                """
            ).fetchone()[0]
        )

        if ids_distintos != 0:
            raise RuntimeError(
                "Los IDs de la tabla nueva no coinciden con los originales. "
                f"El respaldo permanece en {tabla_backup}."
            )

        con.execute(
            f"DROP TABLE {TABLA}"
        )

        con.execute(
            f"""
            ALTER TABLE {TABLA_NUEVA}
            RENAME TO {TABLA}
            """
        )

        # Índices explícitos que existían en el diseño original.
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_simulacro_preguntas_pregunta
            ON simulacro_preguntas(pregunta_id)
            """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_simulacro_preguntas_simulacro
            ON simulacro_preguntas(simulacro_id)
            """
        )

        con.execute("PRAGMA foreign_keys = ON")

        total_despues = int(
            con.execute(
                f"SELECT COUNT(*) FROM {TABLA}"
            ).fetchone()[0]
        )

        valores_despues = obtener_valores(con, TABLA)

        huerfanos_despues = int(
            con.execute(
                """
                SELECT COUNT(*)
                FROM simulacro_snapshot ss
                LEFT JOIN simulacro_preguntas sp
                    ON sp.id = ss.simulacro_pregunta_id
                WHERE sp.id IS NULL
                """
            ).fetchone()[0]
        )

        mostrar_valores(
            "Valores después de migrar",
            valores_despues,
        )

        if total_despues != total_antes:
            raise RuntimeError(
                "El total final de filas no coincide con el inicial."
            )

        if huerfanos_despues != 0:
            raise RuntimeError(
                "Se han detectado snapshots huérfanos después de la migración."
            )

        antiguos = {
            "MUY_SEGURO",
            "BASTANTE_SEGURO",
            "POCO_SEGURO",
        } & set(valores_despues)

        if antiguos:
            raise RuntimeError(
                "Todavía existen valores históricos después de la migración."
            )

        print()
        print("=" * 78)
        print("MIGRACIÓN COMPLETADA Y VERIFICADA")
        print("=" * 78)
        print(f"Filas antes:             {total_antes}")
        print(f"Filas después:           {total_despues}")
        print(f"Snapshots huérfanos:     {huerfanos_despues}")
        print(f"Tabla de respaldo Turso: {tabla_backup}")
        print()
        print(
            "La tabla simulacro_preguntas admite ahora únicamente "
            "NULL, SEGURO y MENOS_SEGURO."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
