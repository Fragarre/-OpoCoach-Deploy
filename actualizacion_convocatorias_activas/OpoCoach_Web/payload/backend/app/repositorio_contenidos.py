from __future__ import annotations

from app.database import (
    ORIGEN_CONTENIDOS_POSTGRES,
    conectar_contenidos_postgres,
    conectar_contenidos_sqlite,
    obtener_origen_contenidos,
)

def _sqlite_tiene_columna_activa(con) -> bool:
    return "activa" in {
        str(fila["name"])
        for fila in con.execute("PRAGMA table_info(convocatorias)").fetchall()
    }


def _postgres_tiene_columna_activa(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'contenidos'
          AND table_name = 'convocatorias'
          AND column_name = 'activa'
        """
    )
    return cur.fetchone() is not None


def convocatoria_esta_activa(convocatoria_id: int) -> bool:
    """
    Indica si la convocatoria admite operaciones nuevas.

    Durante una transición de esquema, si ``activa`` aún no existe, mantiene
    el comportamiento histórico: toda convocatoria existente se considera activa.
    """
    origen = obtener_origen_contenidos()

    if origen == ORIGEN_CONTENIDOS_POSTGRES:
        with conectar_contenidos_postgres() as con:
            with con.cursor() as cur:
                if _postgres_tiene_columna_activa(cur):
                    cur.execute(
                        """
                        SELECT activa
                        FROM contenidos.convocatorias
                        WHERE id = %s
                        """,
                        (convocatoria_id,),
                    )
                    fila = cur.fetchone()
                    return fila is not None and bool(fila["activa"])

                cur.execute(
                    "SELECT 1 AS existe FROM contenidos.convocatorias WHERE id = %s",
                    (convocatoria_id,),
                )
                return cur.fetchone() is not None

    with conectar_contenidos_sqlite() as con:
        if _sqlite_tiene_columna_activa(con):
            fila = con.execute(
                "SELECT activa FROM convocatorias WHERE id = ?",
                (convocatoria_id,),
            ).fetchone()
            return fila is not None and int(fila["activa"] or 0) == 1

        fila = con.execute(
            "SELECT 1 FROM convocatorias WHERE id = ?",
            (convocatoria_id,),
        ).fetchone()
        return fila is not None


def obtener_convocatorias() -> list[dict]:
    """Devuelve únicamente convocatorias disponibles para trabajo actual."""
    origen = obtener_origen_contenidos()

    if origen == ORIGEN_CONTENIDOS_POSTGRES:
        with conectar_contenidos_postgres() as con:
            with con.cursor() as cur:
                filtro = (
                    "WHERE COALESCE(activa, TRUE) = TRUE"
                    if _postgres_tiene_columna_activa(cur)
                    else ""
                )
                cur.execute(
                    f"""
                    SELECT id, puesto, numero, anio, codigo
                    FROM contenidos.convocatorias
                    {filtro}
                    ORDER BY anio DESC, numero, puesto
                    """
                )
                return [dict(fila) for fila in cur.fetchall()]

    with conectar_contenidos_sqlite() as con:
        filtro = (
            "WHERE COALESCE(activa, 1) = 1"
            if _sqlite_tiene_columna_activa(con)
            else ""
        )
        filas = con.execute(
            f"""
            SELECT id, puesto, numero, anio, codigo
            FROM convocatorias
            {filtro}
            ORDER BY anio DESC, numero, puesto
            """
        ).fetchall()
    return [dict(fila) for fila in filas]


def obtener_resumen_convocatoria(convocatoria_id: int) -> dict | None:
    origen = obtener_origen_contenidos()

    if origen == ORIGEN_CONTENIDOS_POSTGRES:
        with conectar_contenidos_postgres() as con:
            with con.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.id,
                        c.codigo,
                        c.puesto,
                        c.numero,
                        c.anio,
                        c.numero_preguntas,
                        t.id AS temario_id,
                        t.nombre AS temario_nombre,
                        (
                            SELECT COUNT(*)
                            FROM contenidos.temario_temas tt
                            WHERE tt.temario_id = t.id
                        ) AS total_temas,
                        (
                            SELECT COUNT(*)
                            FROM contenidos.banco_preguntas bp
                            JOIN contenidos.lote_preguntas lp
                              ON lp.id = bp.pregunta_id
                            WHERE bp.convocatoria_id = c.id
                              AND bp.estado = 'INCLUIDA'
                        ) AS total_banco
                    FROM contenidos.convocatorias c
                    LEFT JOIN contenidos.temarios t
                      ON t.convocatoria_id = c.id
                    WHERE c.id = %s
                    """,
                    (convocatoria_id,),
                )
                fila = cur.fetchone()
                return dict(fila) if fila is not None else None

    with conectar_contenidos_sqlite() as con:
        fila = con.execute(
            """
            SELECT
                c.id,
                c.codigo,
                c.puesto,
                c.numero,
                c.anio,
                c.numero_preguntas,
                t.id AS temario_id,
                t.nombre AS temario_nombre,
                (
                    SELECT COUNT(*)
                    FROM temario_temas tt
                    WHERE tt.temario_id = t.id
                ) AS total_temas,
                (
                    SELECT COUNT(*)
                    FROM banco_preguntas bp
                    JOIN lote_preguntas lp ON lp.id = bp.pregunta_id
                    WHERE bp.convocatoria_id = c.id
                      AND bp.estado = 'INCLUIDA'
                ) AS total_banco
            FROM convocatorias c
            LEFT JOIN temarios t ON t.convocatoria_id = c.id
            WHERE c.id = ?
            """,
            (convocatoria_id,),
        ).fetchone()
    return dict(fila) if fila is not None else None


def comprobar_base() -> dict:
    origen = obtener_origen_contenidos()

    if origen == ORIGEN_CONTENIDOS_POSTGRES:
        with conectar_contenidos_postgres() as con:
            with con.cursor() as cur:
                # PostgreSQL no dispone de un equivalente directo a
                # PRAGMA integrity_check. Aquí "ok" significa que la conexión
                # funciona y que las tablas esenciales de contenidos pueden
                # consultarse correctamente.
                cur.execute(
                    "SELECT COUNT(*) AS total FROM contenidos.convocatorias"
                )
                total_convocatorias = int(cur.fetchone()["total"])

                cur.execute(
                    "SELECT COUNT(*) AS total FROM contenidos.lote_preguntas"
                )
                total_preguntas = int(cur.fetchone()["total"])

        return {
            "integridad": "ok",
            "convocatorias": total_convocatorias,
            "preguntas": total_preguntas,
        }

    with conectar_contenidos_sqlite() as con:
        integridad = con.execute("PRAGMA integrity_check").fetchone()[0]
        total_convocatorias = con.execute(
            "SELECT COUNT(*) FROM convocatorias"
        ).fetchone()[0]
        total_preguntas = con.execute(
            "SELECT COUNT(*) FROM lote_preguntas"
        ).fetchone()[0]

    return {
        "integridad": integridad,
        "convocatorias": total_convocatorias,
        "preguntas": total_preguntas,
    }
