from __future__ import annotations

import random
import re
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database import (
    ORIGEN_CONTENIDOS_POSTGRES,
    conectar_contenidos_postgres,
    conectar_contenidos_sqlite,
    obtener_origen_contenidos,
)
from app.postgres import conectar_postgres
from app.repositorio_contenidos import convocatoria_esta_activa
from app.simulacros import (
    _condicion_fuente,
    _normalizar_fuentes,
    _seleccionar,
    _ultima_aparicion,
)


_TABLAS_CONTENIDOS = (
    "convocatorias",
    "temarios",
    "temario_temas",
    "banco_preguntas_temas",
    "banco_preguntas",
    "lote_preguntas",
    "normas",
)


def _sql_postgres(sqlite_sql: str) -> str:
    """
    Adapta únicamente el subconjunto SQL de contenidos usado en este módulo.
    No se utiliza para consultas de public.* ni para escrituras.
    """
    consulta = sqlite_sql

    # En PostgreSQL es obligatorio referenciar el esquema de contenidos.
    for tabla in sorted(_TABLAS_CONTENIDOS, key=len, reverse=True):
        consulta = re.sub(
            rf"(?<![.\w]){re.escape(tabla)}\b",
            f"contenidos.{tabla}",
            consulta,
        )

    # Los placeholders de SQLite y psycopg son distintos.
    consulta = consulta.replace("?", "%s")

    # es_principal es INTEGER 0/1 en SQLite y boolean en PostgreSQL.
    consulta = consulta.replace("bpt.es_principal = 1", "bpt.es_principal = TRUE")

    return consulta


def _consultar_contenidos(
    sqlite_sql: str,
    params: tuple = (),
    *,
    uno: bool = False,
):
    origen = obtener_origen_contenidos()

    if origen == ORIGEN_CONTENIDOS_POSTGRES:
        with conectar_contenidos_postgres() as con:
            with con.cursor() as cur:
                cur.execute(_sql_postgres(sqlite_sql), params)
                fila_o_filas = cur.fetchone() if uno else cur.fetchall()
    else:
        with conectar_contenidos_sqlite() as con:
            cursor = con.execute(sqlite_sql, params)
            fila_o_filas = cursor.fetchone() if uno else cursor.fetchall()

    if uno:
        return dict(fila_o_filas) if fila_o_filas is not None else None
    return [dict(fila) for fila in fila_o_filas]


def obtener_puntos_temario_test(
    convocatoria_id: int,
    fuentes: list[str] | None,
) -> list[dict]:
    if not convocatoria_esta_activa(convocatoria_id):
        raise ValueError("La convocatoria no está activa.")

    fuentes_n = _normalizar_fuentes(fuentes)
    condicion = _condicion_fuente(fuentes_n)

    return _consultar_contenidos(
        f"""
        SELECT
            tt.id,
            tt.parte,
            tt.numero_tema,
            tt.titulo,
            tt.tipo_contenido,
            COUNT(DISTINCT CASE WHEN lp.id IS NOT NULL
                                THEN bp.pregunta_id END) AS disponibles
        FROM temarios t
        JOIN temario_temas tt
          ON tt.temario_id = t.id
        LEFT JOIN banco_preguntas_temas bpt
          ON bpt.tema_id = tt.id
         AND bpt.es_principal = 1
        LEFT JOIN banco_preguntas bp
          ON bp.id = bpt.banco_pregunta_id
         AND bp.convocatoria_id = ?
         AND bp.estado = 'INCLUIDA'
        LEFT JOIN lote_preguntas lp
          ON lp.id = bp.pregunta_id
         AND ({condicion})
        WHERE t.convocatoria_id = ?
        GROUP BY
            tt.id, tt.parte, tt.numero_tema,
            tt.titulo, tt.tipo_contenido
        HAVING COUNT(DISTINCT CASE WHEN lp.id IS NOT NULL
                                   THEN bp.pregunta_id END) > 0
        ORDER BY
            CASE tt.parte
                WHEN 'GENERAL' THEN 1
                WHEN 'ESPECIAL' THEN 2
                ELSE 3
            END,
            tt.numero_tema,
            tt.titulo
        """,
        (convocatoria_id, convocatoria_id),
    )


def obtener_normas_test(
    convocatoria_id: int,
    fuentes: list[str] | None,
) -> list[dict]:
    if not convocatoria_esta_activa(convocatoria_id):
        raise ValueError("La convocatoria no está activa.")

    fuentes_n = _normalizar_fuentes(fuentes)
    condicion = _condicion_fuente(fuentes_n)

    return _consultar_contenidos(
        f"""
        SELECT
            CASE
                WHEN lp.norma_id_normalizada IS NOT NULL
                    THEN 'ID:' || CAST(lp.norma_id_normalizada AS TEXT)
                ELSE 'NOMBRE:' || LOWER(
                    TRIM(
                        COALESCE(
                            NULLIF(TRIM(lp.nombre_norma_normalizado), ''),
                            NULLIF(TRIM(lp.nombre_norma), '')
                        )
                    )
                )
            END AS norma_clave,
            COALESCE(
                MAX(n.nombre_canonico),
                MIN(
                    COALESCE(
                        NULLIF(TRIM(lp.nombre_norma_normalizado), ''),
                        NULLIF(TRIM(lp.nombre_norma), '')
                    )
                )
            ) AS norma_nombre,
            COUNT(DISTINCT bp.pregunta_id) AS disponibles
        FROM banco_preguntas bp
        JOIN lote_preguntas lp
          ON lp.id = bp.pregunta_id
        LEFT JOIN normas n
          ON n.id = lp.norma_id_normalizada
        WHERE bp.convocatoria_id = ?
          AND bp.estado = 'INCLUIDA'
          AND ({condicion})
          AND UPPER(TRIM(COALESCE(lp.tipo_clasificacion, '')))
                <> 'INFORMATICA'
          AND (
                lp.norma_id_normalizada IS NOT NULL
                OR COALESCE(
                    NULLIF(TRIM(lp.nombre_norma_normalizado), ''),
                    NULLIF(TRIM(lp.nombre_norma), '')
                ) IS NOT NULL
          )
        GROUP BY norma_clave
        ORDER BY norma_nombre
        """,
        (convocatoria_id,),
    )


def _repartir_proporcionalmente(
    disponibilidades: dict[str, int],
    total_solicitado: int,
) -> dict[str, int]:
    total_disponible = sum(disponibilidades.values())
    if total_disponible <= 0:
        return {clave: 0 for clave in disponibilidades}

    total_generar = min(total_solicitado, total_disponible)
    cuotas = {
        clave: total_generar * disponibles / total_disponible
        for clave, disponibles in disponibilidades.items()
    }
    reparto = {
        clave: min(int(cuota), disponibilidades[clave])
        for clave, cuota in cuotas.items()
    }

    pendientes = total_generar - sum(reparto.values())
    orden = sorted(
        disponibilidades,
        key=lambda clave: (
            cuotas[clave] - int(cuotas[clave]),
            disponibilidades[clave],
            str(clave),
        ),
        reverse=True,
    )

    while pendientes > 0:
        asignada = False
        for clave in orden:
            if reparto[clave] < disponibilidades[clave]:
                reparto[clave] += 1
                pendientes -= 1
                asignada = True
                if pendientes == 0:
                    break
        if not asignada:
            break

    return reparto


def _cargar_datos_creacion_test(
    convocatoria_id: int,
    temas_ids: list[int],
    normas_claves: list[str],
    modo: str,
    condicion: str,
) -> tuple[dict, list[dict], list[dict], list[str]]:
    convocatoria = _consultar_contenidos(
        """
        SELECT
            id, puesto, numero, anio, codigo, numero_preguntas,
            valoracion_test_acierto, valoracion_test_fallo,
            valoracion_test_no_contesta, formula_nota,
            factor_escala_nota
        FROM convocatorias
        WHERE id = ?
        """,
        (convocatoria_id,),
        uno=True,
    )

    if convocatoria is None:
        raise ValueError("La convocatoria no existe.")

    if modo == "TEMA":
        marcadores = ", ".join("?" for _ in temas_ids)

        elementos = _consultar_contenidos(
            f"""
            SELECT
                tt.id AS elemento_id,
                tt.numero_tema || '. ' || tt.parte || ' — ' ||
                tt.titulo AS elemento_nombre
            FROM temario_temas tt
            JOIN temarios t ON t.id = tt.temario_id
            WHERE t.convocatoria_id = ?
              AND tt.id IN ({marcadores})
            ORDER BY tt.parte, tt.numero_tema, tt.titulo
            """,
            (convocatoria_id, *temas_ids),
        )

        if len(elementos) != len(temas_ids):
            raise ValueError(
                "Alguno de los puntos seleccionados no pertenece "
                "a la convocatoria."
            )

        candidatas = _consultar_contenidos(
            f"""
            SELECT DISTINCT
                bp.id AS banco_pregunta_id,
                bp.pregunta_id,
                lp.enunciado, lp.opcion_a, lp.opcion_b,
                lp.opcion_c, lp.opcion_d, lp.respuesta_correcta,
                lp.tipo_clasificacion, lp.tipo_norma,
                lp.nombre_norma, lp.articulo, lp.tema_no_juridico,
                lp.origen_oposicion, lp.tipo_fuente,
                lp.importacion_fichero_id, lp.pagina_origen,
                lp.norma_id_normalizada, lp.articulo_normalizado,
                lp.teorica_practica, lp.tipo_norma_normalizado,
                COALESCE(
                    n.nombre_canonico,
                    lp.nombre_norma_normalizado
                ) AS nombre_norma_normalizado,
                bp.tipo_vinculacion,
                bp.estado AS banco_estado,
                bp.metodo_vinculacion,
                bp.motivo_revision,
                tt.id AS tema_id,
                tt.parte AS tema_parte,
                tt.numero_tema,
                tt.titulo AS tema_titulo,
                tt.tipo_contenido AS tema_tipo_contenido,
                CAST(tt.id AS TEXT) AS elemento_id
            FROM banco_preguntas bp
            JOIN lote_preguntas lp
              ON lp.id = bp.pregunta_id
            LEFT JOIN normas n
              ON n.id = lp.norma_id_normalizada
            JOIN banco_preguntas_temas bpt
              ON bpt.banco_pregunta_id = bp.id
             AND bpt.es_principal = 1
            JOIN temario_temas tt
              ON tt.id = bpt.tema_id
            WHERE bp.convocatoria_id = ?
              AND bp.estado = 'INCLUIDA'
              AND ({condicion})
              AND tt.id IN ({marcadores})
            """,
            (convocatoria_id, *temas_ids),
        )
        claves_elementos = [str(x) for x in temas_ids]

    else:
        marcadores = ", ".join("?" for _ in normas_claves)
        expresion = """
            CASE
                WHEN lp.norma_id_normalizada IS NOT NULL
                    THEN 'ID:' || CAST(lp.norma_id_normalizada AS TEXT)
                ELSE 'NOMBRE:' || LOWER(
                    TRIM(
                        COALESCE(
                            NULLIF(TRIM(lp.nombre_norma_normalizado), ''),
                            NULLIF(TRIM(lp.nombre_norma), '')
                        )
                    )
                )
            END
        """

        elementos = _consultar_contenidos(
            f"""
            SELECT
                {expresion} AS elemento_id,
                COALESCE(
                    MAX(n.nombre_canonico),
                    MIN(
                        COALESCE(
                            NULLIF(TRIM(lp.nombre_norma_normalizado), ''),
                            NULLIF(TRIM(lp.nombre_norma), '')
                        )
                    )
                ) AS elemento_nombre
            FROM banco_preguntas bp
            JOIN lote_preguntas lp
              ON lp.id = bp.pregunta_id
            LEFT JOIN normas n
              ON n.id = lp.norma_id_normalizada
            WHERE bp.convocatoria_id = ?
              AND bp.estado = 'INCLUIDA'
              AND ({condicion})
              AND UPPER(TRIM(COALESCE(lp.tipo_clasificacion, '')))
                    <> 'INFORMATICA'
              AND {expresion} IN ({marcadores})
            GROUP BY elemento_id
            ORDER BY elemento_nombre
            """,
            (convocatoria_id, *normas_claves),
        )

        if len(elementos) != len(normas_claves):
            raise ValueError(
                "Alguna de las normas seleccionadas no pertenece "
                "al banco de la convocatoria."
            )

        candidatas = _consultar_contenidos(
            f"""
            SELECT DISTINCT
                bp.id AS banco_pregunta_id,
                bp.pregunta_id,
                lp.enunciado, lp.opcion_a, lp.opcion_b,
                lp.opcion_c, lp.opcion_d, lp.respuesta_correcta,
                lp.tipo_clasificacion, lp.tipo_norma,
                lp.nombre_norma, lp.articulo, lp.tema_no_juridico,
                lp.origen_oposicion, lp.tipo_fuente,
                lp.importacion_fichero_id, lp.pagina_origen,
                lp.norma_id_normalizada, lp.articulo_normalizado,
                lp.teorica_practica, lp.tipo_norma_normalizado,
                COALESCE(
                    n.nombre_canonico,
                    lp.nombre_norma_normalizado
                ) AS nombre_norma_normalizado,
                bp.tipo_vinculacion,
                bp.estado AS banco_estado,
                bp.metodo_vinculacion,
                bp.motivo_revision,
                tt.id AS tema_id,
                tt.parte AS tema_parte,
                tt.numero_tema,
                tt.titulo AS tema_titulo,
                tt.tipo_contenido AS tema_tipo_contenido,
                {expresion} AS elemento_id
            FROM banco_preguntas bp
            JOIN lote_preguntas lp
              ON lp.id = bp.pregunta_id
            LEFT JOIN normas n
              ON n.id = lp.norma_id_normalizada
            JOIN banco_preguntas_temas bpt
              ON bpt.banco_pregunta_id = bp.id
             AND bpt.es_principal = 1
            JOIN temario_temas tt
              ON tt.id = bpt.tema_id
            WHERE bp.convocatoria_id = ?
              AND bp.estado = 'INCLUIDA'
              AND ({condicion})
              AND UPPER(TRIM(COALESCE(lp.tipo_clasificacion, '')))
                    <> 'INFORMATICA'
              AND {expresion} IN ({marcadores})
            """,
            (convocatoria_id, *normas_claves),
        )
        claves_elementos = normas_claves

    return convocatoria, elementos, candidatas, claves_elementos



def crear_test(
    convocatoria_id: int,
    numero_preguntas: int,
    temas_seleccionados: list[int] | None,
    normas_seleccionadas: list[str] | None,
    modo_seleccion: str,
    fuentes: list[str] | None,
    user_id: UUID,
    es_prueba_gratuita: bool = False,
) -> dict:
    if not convocatoria_esta_activa(convocatoria_id):
        raise ValueError("La convocatoria no está activa.")

    if numero_preguntas <= 0:
        raise ValueError("El número de preguntas debe ser mayor que cero.")

    if es_prueba_gratuita and numero_preguntas > 10:
        raise ValueError(
            "La prueba gratuita permite un máximo de 10 preguntas."
        )

    modo = str(modo_seleccion).strip().upper()
    if modo not in {"TEMA", "NORMA"}:
        raise ValueError("El modo de selección del test no es válido.")

    fuentes_n = _normalizar_fuentes(fuentes)
    condicion = _condicion_fuente(fuentes_n)

    temas_ids = sorted({int(x) for x in (temas_seleccionados or [])})
    normas_claves = sorted({
        str(x).strip()
        for x in (normas_seleccionadas or [])
        if str(x).strip()
    })

    if modo == "TEMA" and not temas_ids:
        raise ValueError("Debe seleccionar al menos un punto del temario.")
    if modo == "NORMA" and not normas_claves:
        raise ValueError("Debe seleccionar al menos una ley o norma.")

    convocatoria, elementos, candidatas, claves_elementos = (
        _cargar_datos_creacion_test(
            convocatoria_id=convocatoria_id,
            temas_ids=temas_ids,
            normas_claves=normas_claves,
            modo=modo,
            condicion=condicion,
        )
    )

    por_elemento = {clave: [] for clave in claves_elementos}
    for pregunta in candidatas:
        clave = str(pregunta["elemento_id"])
        if clave in por_elemento:
            por_elemento[clave].append(pregunta)

    disponibilidades = {
        clave: len(preguntas)
        for clave, preguntas in por_elemento.items()
    }
    total_disponible = sum(disponibilidades.values())

    if total_disponible == 0:
        raise ValueError(
            "No hay preguntas disponibles para la selección realizada."
        )

    reparto = _repartir_proporcionalmente(
        disponibilidades,
        numero_preguntas,
    )

    ultima = _ultima_aparicion(convocatoria_id, user_id)
    elegidas_total = []
    usadas: set[int] = set()

    for elemento in elementos:
        clave = str(elemento["elemento_id"])
        cantidad = reparto.get(clave, 0)
        disponibles = [
            p for p in por_elemento[clave]
            if int(p["pregunta_id"]) not in usadas
        ]
        elegidas = _seleccionar(
            disponibles,
            min(cantidad, len(disponibles)),
            ultima,
        )
        for p in elegidas:
            usadas.add(int(p["pregunta_id"]))
            elegidas_total.append(p)

    objetivo = min(numero_preguntas, total_disponible)
    if len(elegidas_total) < objetivo:
        restantes = [
            p
            for lista in por_elemento.values()
            for p in lista
            if int(p["pregunta_id"]) not in usadas
        ]
        adicionales = _seleccionar(
            restantes,
            min(objetivo - len(elegidas_total), len(restantes)),
            ultima,
        )
        for p in adicionales:
            usadas.add(int(p["pregunta_id"]))
            elegidas_total.append(p)

    random.shuffle(elegidas_total)
    total_generado = len(elegidas_total)
    if total_generado == 0:
        raise ValueError("No se ha podido generar el test.")

    avisos = []
    if total_generado < numero_preguntas:
        avisos.append(
            f"Se solicitaron {numero_preguntas} preguntas, pero solo hay "
            f"{total_generado} preguntas distintas disponibles. "
            "El test se ha creado con el máximo disponible."
        )

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            if es_prueba_gratuita:
                cur.execute(
                    """
                    SELECT prueba_gratuita_consumida_at
                    FROM public.profiles
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (user_id,),
                )
                perfil = cur.fetchone()
                if perfil is None:
                    raise ValueError("El usuario no tiene perfil OpoCoach.")
                if perfil["prueba_gratuita_consumida_at"] is not None:
                    raise ValueError(
                        "La prueba gratuita de esta cuenta ya ha sido utilizada."
                    )

            cur.execute(
                """
                SELECT COALESCE(MAX(numero), 0) + 1 AS siguiente
                FROM public.simulacros
                WHERE user_id = %s
                  AND convocatoria_id = %s
                  AND tipo_prueba = 'TEST'
                """,
                (user_id, convocatoria_id),
            )
            numero = int(cur.fetchone()["siguiente"])

            cur.execute(
                """
                INSERT INTO public.simulacros (
                    user_id, convocatoria_id, numero,
                    total_preguntas, tipo_prueba,
                    convocatoria_codigo, convocatoria_puesto,
                    convocatoria_numero, convocatoria_anio,
                    convocatoria_numero_preguntas,
                    valoracion_test_acierto, valoracion_test_fallo,
                    valoracion_test_no_contesta, formula_nota,
                    factor_escala_nota, es_prueba_gratuita
                )
                VALUES (
                    %s, %s, %s, %s, 'TEST',
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    user_id, convocatoria_id, numero, total_generado,
                    convocatoria["codigo"], convocatoria["puesto"],
                    convocatoria["numero"], convocatoria["anio"],
                    convocatoria["numero_preguntas"],
                    convocatoria["valoracion_test_acierto"],
                    convocatoria["valoracion_test_fallo"],
                    convocatoria["valoracion_test_no_contesta"],
                    convocatoria["formula_nota"],
                    convocatoria["factor_escala_nota"],
                    bool(es_prueba_gratuita),
                ),
            )
            test_id = int(cur.fetchone()["id"])

            for orden, p in enumerate(elegidas_total, 1):
                cur.execute(
                    """
                    INSERT INTO public.simulacro_preguntas (
                        simulacro_id, orden, pregunta_id,
                        banco_pregunta_id, parte_id,
                        parte_nombre, parte_orden
                    )
                    VALUES (%s, %s, %s, %s, NULL, %s, %s)
                    RETURNING id
                    """,
                    (
                        test_id, orden, p["pregunta_id"],
                        p["banco_pregunta_id"],
                        p["tema_parte"], p["numero_tema"],
                    ),
                )
                sp_id = int(cur.fetchone()["id"])

                tema = {
                    "tema_id_original": p["tema_id"],
                    "parte": p["tema_parte"],
                    "numero_tema": p["numero_tema"],
                    "titulo": p["tema_titulo"],
                    "tipo_contenido": p["tema_tipo_contenido"],
                    "es_principal": 1,
                }

                cur.execute(
                    """
                    INSERT INTO public.simulacro_snapshot (
                        simulacro_pregunta_id,
                        enunciado, opcion_a, opcion_b, opcion_c, opcion_d,
                        respuesta_correcta, tipo_clasificacion,
                        tipo_norma, nombre_norma, articulo,
                        tema_no_juridico, origen_oposicion, tipo_fuente,
                        importacion_fichero_id, pagina_origen,
                        norma_id_normalizada, articulo_normalizado,
                        teorica_practica, tipo_norma_normalizado,
                        nombre_norma_normalizado,
                        banco_tipo_vinculacion, banco_estado,
                        banco_metodo_vinculacion, banco_motivo_revision,
                        temas_json, comentario_solucion
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, NULL
                    )
                    """,
                    (
                        sp_id,
                        p["enunciado"], p["opcion_a"], p["opcion_b"],
                        p["opcion_c"], p["opcion_d"],
                        p["respuesta_correcta"], p["tipo_clasificacion"],
                        p["tipo_norma"], p["nombre_norma"], p["articulo"],
                        p["tema_no_juridico"], p["origen_oposicion"],
                        p["tipo_fuente"], p["importacion_fichero_id"],
                        p["pagina_origen"], p["norma_id_normalizada"],
                        p["articulo_normalizado"], p["teorica_practica"],
                        p["tipo_norma_normalizado"],
                        p["nombre_norma_normalizado"],
                        p["tipo_vinculacion"], p["banco_estado"],
                        p["metodo_vinculacion"], p["motivo_revision"],
                        Jsonb(tema),
                    ),
                )

            if es_prueba_gratuita:
                cur.execute(
                    """
                    UPDATE public.profiles
                    SET prueba_gratuita_consumida_at = now(),
                        updated_at = now()
                    WHERE id = %s
                      AND prueba_gratuita_consumida_at IS NULL
                    """,
                    (user_id,),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        "No se ha podido registrar el consumo de la prueba gratuita."
                    )

        con.commit()

    return {
        "id": test_id,
        "numero": numero,
        "total_solicitado": numero_preguntas,
        "total_generado": total_generado,
        "avisos": avisos,
    }
