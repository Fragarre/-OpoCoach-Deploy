from __future__ import annotations

import re
from typing import Any

from lib.database import conectar


def _dicts(filas) -> list[dict[str, Any]]:
    return [dict(fila) for fila in filas]


def _clave_articulo(valor: str | None) -> tuple:
    """
    Orden natural para artículos: 1, 2, 2 bis, 3, 10...
    Los identificadores no numéricos quedan detrás conservando orden estable.
    """
    texto = str(valor or "").strip()
    m = re.match(r"^\s*(\d+)\s*(.*)$", texto, flags=re.IGNORECASE)
    if not m:
        return (1, 10**9, texto.casefold())
    return (0, int(m.group(1)), m.group(2).strip().casefold())


def obtener_convocatoria_materiales(convocatoria_id: int) -> dict[str, Any] | None:
    with conectar() as con:
        fila = con.execute(
            """
            SELECT id, codigo, puesto, activa
            FROM convocatorias
            WHERE id = ?
            """,
            (convocatoria_id,),
        ).fetchone()
    return dict(fila) if fila else None


def _fuente_principal(con, norma_id: int) -> dict[str, Any] | None:
    """
    Selecciona la fuente con mayor número de bloques/artículos almacenados.
    En empate prioriza la fuente que ya está enlazada por más referencias
    de temario. No modifica datos.
    """
    fila = con.execute(
        """
        WITH recuento_fuente AS (
            SELECT
                nf.id_fuente,
                nf.titulo_fuente,
                COUNT(DISTINCT af.id) AS articulos_corpus
            FROM norma_fuentes nf
            LEFT JOIN articulos_fuente af
                ON af.id_boe = nf.id_fuente
            WHERE nf.norma_id = ?
            GROUP BY nf.id_fuente, nf.titulo_fuente
        ),
        uso_temario AS (
            SELECT
                af.id_boe AS id_fuente,
                COUNT(DISTINCT tr.id) AS referencias_uso
            FROM temario_referencias tr
            JOIN articulos_fuente af
                ON af.id = tr.articulo_fuente_id
            WHERE tr.norma_id = ?
            GROUP BY af.id_boe
        )
        SELECT
            rf.id_fuente,
            rf.titulo_fuente,
            rf.articulos_corpus,
            COALESCE(ut.referencias_uso, 0) AS referencias_uso
        FROM recuento_fuente rf
        LEFT JOIN uso_temario ut
            ON ut.id_fuente = rf.id_fuente
        WHERE rf.articulos_corpus > 0
        ORDER BY
            rf.articulos_corpus DESC,
            referencias_uso DESC,
            rf.id_fuente
        LIMIT 1
        """,
        (norma_id, norma_id),
    ).fetchone()
    return dict(fila) if fila else None


def listar_normas_materiales(convocatoria_id: int) -> list[dict[str, Any]]:
    """
    Normas realmente presentes en el temario de la convocatoria.
    Añade la fuente principal y el número de artículos/bloques disponibles.
    """
    with conectar() as con:
        filas = con.execute(
            """
            SELECT
                n.id AS norma_id,
                n.nombre_canonico,
                COUNT(DISTINCT tr.id) AS referencias_temario
            FROM temarios t
            JOIN temario_temas tt
                ON tt.temario_id = t.id
            JOIN temario_referencias tr
                ON tr.tema_id = tt.id
            JOIN normas n
                ON n.id = tr.norma_id
            WHERE t.convocatoria_id = ?
              AND tr.norma_id IS NOT NULL
            GROUP BY n.id, n.nombre_canonico
            ORDER BY UPPER(n.nombre_canonico), n.id
            """,
            (convocatoria_id,),
        ).fetchall()

        resultado: list[dict[str, Any]] = []
        for fila in filas:
            item = dict(fila)
            fuente = _fuente_principal(con, int(item["norma_id"]))
            if fuente is None:
                continue
            item.update(fuente)
            resultado.append(item)

    return resultado


def obtener_temas_norma(
    convocatoria_id: int,
    norma_id: int,
) -> list[dict[str, Any]]:
    with conectar() as con:
        filas = con.execute(
            """
            SELECT DISTINCT
                tt.id,
                tt.parte,
                tt.numero_tema,
                tt.titulo
            FROM temarios t
            JOIN temario_temas tt
                ON tt.temario_id = t.id
            JOIN temario_referencias tr
                ON tr.tema_id = tt.id
            WHERE t.convocatoria_id = ?
              AND tr.norma_id = ?
            ORDER BY tt.parte, tt.numero_tema, tt.titulo
            """,
            (convocatoria_id, norma_id),
        ).fetchall()
    return _dicts(filas)


def obtener_articulos_texto_completo(norma_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with conectar() as con:
        norma = con.execute(
            """
            SELECT id, nombre_canonico
            FROM normas
            WHERE id = ?
            """,
            (norma_id,),
        ).fetchone()
        if norma is None:
            raise ValueError("La norma seleccionada no existe.")

        fuente = _fuente_principal(con, norma_id)
        if fuente is None:
            raise ValueError("La norma no tiene texto disponible en el corpus.")

        filas = con.execute(
            """
            SELECT
                id,
                id_boe,
                id_bloque,
                articulo_boe,
                titulo_bloque,
                texto
            FROM articulos_fuente
            WHERE id_boe = ?
              AND TRIM(COALESCE(texto, '')) <> ''
            """,
            (fuente["id_fuente"],),
        ).fetchall()

    articulos = _dicts(filas)
    articulos.sort(
        key=lambda x: (
            _clave_articulo(x.get("articulo_boe")),
            str(x.get("id_bloque") or "").casefold(),
            int(x["id"]),
        )
    )

    meta = dict(norma)
    meta.update(fuente)
    return meta, articulos


def obtener_articulos_extracto(
    convocatoria_id: int,
    norma_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Devuelve los artículos de la norma efectivamente enlazados al temario
    de la convocatoria. Se deduplican artículos repetidos en varios temas.
    """
    with conectar() as con:
        norma = con.execute(
            """
            SELECT id, nombre_canonico
            FROM normas
            WHERE id = ?
            """,
            (norma_id,),
        ).fetchone()
        if norma is None:
            raise ValueError("La norma seleccionada no existe.")

        filas = con.execute(
            """
            SELECT DISTINCT
                af.id,
                af.id_boe,
                af.id_bloque,
                af.articulo_boe,
                af.titulo_bloque,
                af.texto
            FROM temarios t
            JOIN temario_temas tt
                ON tt.temario_id = t.id
            JOIN temario_referencias tr
                ON tr.tema_id = tt.id
            JOIN articulos_fuente af
                ON af.id = tr.articulo_fuente_id
            WHERE t.convocatoria_id = ?
              AND tr.norma_id = ?
              AND TRIM(COALESCE(af.texto, '')) <> ''
            """,
            (convocatoria_id, norma_id),
        ).fetchall()

        fuente = _fuente_principal(con, norma_id)

    articulos = _dicts(filas)
    articulos.sort(
        key=lambda x: (
            _clave_articulo(x.get("articulo_boe")),
            str(x.get("id_bloque") or "").casefold(),
            int(x["id"]),
        )
    )

    meta = dict(norma)
    if fuente:
        meta.update(fuente)
    return meta, articulos
