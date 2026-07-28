"""
==============================================================================
OpoCoach
Archivo: repositorio.py
==============================================================================

Descripción:
    Funciones de acceso a las bases de datos.

    oposiciones.sqlite3:
        Datos maestros mantenidos desde OpoCoach-Mantenimiento.

    usuario.sqlite3:
        Simulacros y datos generados por el usuario.

==============================================================================
"""

import hashlib
import json
import random
import sqlite3

from lib.database import conectar, conectar_usuario


def total_preguntas() -> int:
    with conectar() as con:
        return con.execute(
            """
            SELECT COUNT(*)
            FROM lote_preguntas
            """
        ).fetchone()[0]


def obtener_convocatorias() -> list[sqlite3.Row]:
    with conectar() as con:
        return con.execute(
            """
            SELECT
                id,
                puesto,
                numero,
                anio,
                codigo
            FROM convocatorias
            ORDER BY anio DESC, numero, puesto
            """
        ).fetchall()


def obtener_convocatoria(
    convocatoria_id: int,
) -> sqlite3.Row | None:
    with conectar() as con:
        return con.execute(
            """
            SELECT
                id,
                puesto,
                numero,
                anio,
                codigo,
                numero_preguntas,
                tiene_partes
            FROM convocatorias
            WHERE id = ?
            """,
            (convocatoria_id,),
        ).fetchone()


def obtener_resumen_convocatoria(
    convocatoria_id: int,
) -> sqlite3.Row | None:
    with conectar() as con:
        return con.execute(
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
                    JOIN lote_preguntas lp
                        ON lp.id = bp.pregunta_id
                    WHERE bp.convocatoria_id = c.id
                      AND bp.estado = 'INCLUIDA'
                ) AS total_banco
            FROM convocatorias c
            LEFT JOIN temarios t
                ON t.convocatoria_id = c.id
            WHERE c.id = ?
            """,
            (convocatoria_id,),
        ).fetchone()

def obtener_simulacros(
    convocatoria_id: int,
) -> list[sqlite3.Row]:
    """
    Obtiene los simulacros guardados en usuario.sqlite3.
    """

    with conectar_usuario() as con:
        return con.execute(
            """
            SELECT
                s.id,
                s.numero,
                s.fecha_generacion,
                s.total_preguntas,
                s.estado,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM simulacro_preguntas sp
                        WHERE sp.simulacro_id = s.id
                          AND (
                              sp.respuesta_usuario IS NOT NULL
                              OR sp.seguridad_usuario IS NOT NULL
                          )
                    )
                    THEN 1
                    ELSE 0
                END AS corregido
            FROM simulacros s
            WHERE s.convocatoria_id = ?
              AND s.tipo_prueba = 'SIMULACRO'
            ORDER BY s.numero DESC
            """,
            (convocatoria_id,),
        ).fetchall()


def obtener_disponibilidad_simulacro(
    convocatoria_id: int,
    origenes_seleccionados: list[str],
) -> list[sqlite3.Row]:
    """
    Cuenta las preguntas disponibles por cada parte del simulacro
    para los orígenes seleccionados.

    Las preguntas sin origen asignado se incluyen siempre.
    """

    origenes_validos = {"A1", "A2", "C1", "C2"}
    origenes = sorted(
        {
            str(origen).strip().upper()
            for origen in origenes_seleccionados
            if str(origen).strip()
        }
    )

    if not origenes:
        return []

    if set(origenes) - origenes_validos:
        raise ValueError(
            "Existe algún origen de preguntas no válido."
        )

    marcadores_origen = ", ".join("?" for _ in origenes)

    with conectar() as con:
        return con.execute(
            f"""
            WITH preguntas_clasificadas AS (
                SELECT DISTINCT
                    bp.id AS banco_pregunta_id,

                    CASE
                        WHEN tt.parte = 'GENERAL'
                            THEN 'general'

                        WHEN tt.parte = 'ESPECIAL'
                             AND lp.tipo_clasificacion = 'INFORMATICA'
                            THEN 'especial_informatica'

                        WHEN tt.parte = 'ESPECIAL'
                             AND lp.teorica_practica = 'PRACTICA'
                            THEN 'especial_practica'

                        WHEN tt.parte = 'ESPECIAL'
                             AND lp.teorica_practica = 'TEORICA'
                            THEN 'especial_teoria'
                    END AS nombre_parte

                FROM banco_preguntas bp

                JOIN lote_preguntas lp
                    ON lp.id = bp.pregunta_id

                JOIN banco_preguntas_temas bpt
                    ON bpt.banco_pregunta_id = bp.id
                   AND bpt.es_principal = 1

                JOIN temario_temas tt
                    ON tt.id = bpt.tema_id

                WHERE bp.convocatoria_id = ?
                  AND bp.estado = 'INCLUIDA'
                  AND (
                        lp.origen_oposicion IS NULL
                        OR TRIM(lp.origen_oposicion) = ''
                        OR UPPER(TRIM(lp.origen_oposicion))
                            IN ({marcadores_origen})
                  )
            )

            SELECT
                nombre_parte AS parte,
                COUNT(*) AS disponibles

            FROM preguntas_clasificadas

            WHERE nombre_parte IS NOT NULL

            GROUP BY nombre_parte

            ORDER BY nombre_parte
            """,
            (
                convocatoria_id,
                *origenes,
            ),
        ).fetchall()

TAMANO_LOTE_ESCRITURA = 25


def _dividir_en_lotes(elementos: list[dict], tamano: int):
    """Divide una lista en lotes consecutivos."""

    for inicio in range(0, len(elementos), tamano):
        yield elementos[inicio:inicio + tamano]


def _guardar_preguntas_prueba_en_lotes(
    con_usuario,
    prueba_id: int,
    preguntas: list[dict],
    tamano_lote: int = TAMANO_LOTE_ESCRITURA,
) -> None:
    """
    Guarda preguntas y snapshots mediante INSERT múltiples.

    Cada lote requiere únicamente dos peticiones a Turso:
        1. simulacro_preguntas
        2. simulacro_snapshot
    """

    if tamano_lote <= 0:
        raise ValueError("tamano_lote debe ser mayor que cero.")

    for lote in _dividir_en_lotes(preguntas, tamano_lote):
        marcadores_preguntas = ", ".join(
            "(?, ?, ?, ?, ?, ?, ?)" for _ in lote
        )
        parametros_preguntas: list = []

        for item in lote:
            parametros_preguntas.extend(
                (
                    prueba_id,
                    item["orden"],
                    item["pregunta_id"],
                    item["banco_pregunta_id"],
                    item["parte_id"],
                    item["parte_nombre"],
                    item["parte_orden"],
                )
            )

        cursor = con_usuario.execute(
            f"""
            INSERT INTO simulacro_preguntas
            (
                simulacro_id,
                orden,
                pregunta_id,
                banco_pregunta_id,
                parte_id,
                parte_nombre,
                parte_orden
            )
            VALUES {marcadores_preguntas}
            """,
            parametros_preguntas,
        )

        if cursor.rowcount not in (-1, len(lote)):
            raise RuntimeError(
                "No se han podido guardar todas las preguntas "
                "de la prueba."
            )

        marcadores_snapshot = ", ".join(
            "(" + ", ".join("?" for _ in range(27)) + ")"
            for _ in lote
        )
        parametros_snapshot: list = []

        for item in lote:
            parametros_snapshot.extend(
                (
                    item["orden"],
                    item["enunciado"],
                    item["opcion_a"],
                    item["opcion_b"],
                    item["opcion_c"],
                    item["opcion_d"],
                    item["respuesta_correcta"],
                    item["tipo_clasificacion"],
                    item["tipo_norma"],
                    item["nombre_norma"],
                    item["articulo"],
                    item["tema_no_juridico"],
                    item["origen_oposicion"],
                    item["tipo_fuente"],
                    item["importacion_fichero_id"],
                    item["pagina_origen"],
                    item["norma_id_normalizada"],
                    item["articulo_normalizado"],
                    item["teorica_practica"],
                    item["tipo_norma_normalizado"],
                    item["nombre_norma_normalizado"],
                    item["banco_tipo_vinculacion"],
                    item["banco_estado"],
                    item["banco_metodo_vinculacion"],
                    item["banco_motivo_revision"],
                    item["temas_json"],
                    None,
                )
            )

        cursor = con_usuario.execute(
            f"""
            WITH datos_snapshot
            (
                orden,
                enunciado,
                opcion_a,
                opcion_b,
                opcion_c,
                opcion_d,
                respuesta_correcta,
                tipo_clasificacion,
                tipo_norma,
                nombre_norma,
                articulo,
                tema_no_juridico,
                origen_oposicion,
                tipo_fuente,
                importacion_fichero_id,
                pagina_origen,
                norma_id_normalizada,
                articulo_normalizado,
                teorica_practica,
                tipo_norma_normalizado,
                nombre_norma_normalizado,
                banco_tipo_vinculacion,
                banco_estado,
                banco_metodo_vinculacion,
                banco_motivo_revision,
                temas_json,
                comentario_solucion
            ) AS (
                VALUES {marcadores_snapshot}
            )
            INSERT INTO simulacro_snapshot
            (
                simulacro_pregunta_id,
                enunciado,
                opcion_a,
                opcion_b,
                opcion_c,
                opcion_d,
                respuesta_correcta,
                tipo_clasificacion,
                tipo_norma,
                nombre_norma,
                articulo,
                tema_no_juridico,
                origen_oposicion,
                tipo_fuente,
                importacion_fichero_id,
                pagina_origen,
                norma_id_normalizada,
                articulo_normalizado,
                teorica_practica,
                tipo_norma_normalizado,
                nombre_norma_normalizado,
                banco_tipo_vinculacion,
                banco_estado,
                banco_metodo_vinculacion,
                banco_motivo_revision,
                temas_json,
                comentario_solucion
            )
            SELECT
                sp.id,
                ds.enunciado,
                ds.opcion_a,
                ds.opcion_b,
                ds.opcion_c,
                ds.opcion_d,
                ds.respuesta_correcta,
                ds.tipo_clasificacion,
                ds.tipo_norma,
                ds.nombre_norma,
                ds.articulo,
                ds.tema_no_juridico,
                ds.origen_oposicion,
                ds.tipo_fuente,
                ds.importacion_fichero_id,
                ds.pagina_origen,
                ds.norma_id_normalizada,
                ds.articulo_normalizado,
                ds.teorica_practica,
                ds.tipo_norma_normalizado,
                ds.nombre_norma_normalizado,
                ds.banco_tipo_vinculacion,
                ds.banco_estado,
                ds.banco_metodo_vinculacion,
                ds.banco_motivo_revision,
                ds.temas_json,
                ds.comentario_solucion
            FROM datos_snapshot ds
            JOIN simulacro_preguntas sp
                ON sp.simulacro_id = ?
               AND sp.orden = ds.orden
            """,
            (*parametros_snapshot, prueba_id),
        )

        if cursor.rowcount not in (-1, len(lote)):
            raise RuntimeError(
                "No se han podido guardar todos los snapshots "
                "de la prueba."
            )


def crear_simulacro(
    convocatoria_id: int,
    origenes_seleccionados: list[str],
) -> int:
    """
    Genera un simulacro completo.

    Lee las preguntas desde oposiciones.sqlite3 y guarda el simulacro
    inmutable en usuario.sqlite3.
    """

    origenes_validos = {"A1", "A2", "C1", "C2"}
    origenes = sorted(
        {
            str(origen).strip().upper()
            for origen in origenes_seleccionados
            if str(origen).strip()
        }
    )

    if not origenes:
        raise ValueError(
            "Debe seleccionar al menos un origen de preguntas."
        )

    origenes_no_validos = set(origenes) - origenes_validos

    if origenes_no_validos:
        raise ValueError(
            "Existe algún origen de preguntas no válido."
        )

    marcadores_origen = ", ".join("?" for _ in origenes)

    # -------------------------------------------------------------------------
    # 1. Lectura de los datos maestros
    # -------------------------------------------------------------------------

    with conectar() as con_catalogo:

        convocatoria = con_catalogo.execute(
            """
            SELECT
                id,
                puesto,
                numero,
                anio,
                codigo,
                numero_preguntas,
                valoracion_test_acierto,
                valoracion_test_fallo,
                valoracion_test_no_contesta,
                formula_nota,
                factor_escala_nota
            FROM convocatorias
            WHERE id = ?
            """,
            (convocatoria_id,),
        ).fetchone()

        if convocatoria is None:
            raise ValueError("La convocatoria no existe.")

        partes = con_catalogo.execute(
            """
            SELECT
                id,
                nombre,
                numero_preguntas,
                orden
            FROM convocatoria_partes
            WHERE convocatoria_id = ?
            ORDER BY orden
            """,
            (convocatoria_id,),
        ).fetchall()

        if not partes:
            raise ValueError(
                "La convocatoria no tiene partes configuradas."
            )

        total_partes = sum(
            parte["numero_preguntas"]
            for parte in partes
        )

        if total_partes != convocatoria["numero_preguntas"]:
            raise ValueError(
                "La suma de preguntas de las partes no coincide "
                "con el total configurado en la convocatoria."
            )

        candidatas = con_catalogo.execute(
            f"""
            WITH preguntas_clasificadas AS (
                SELECT DISTINCT
                    bp.id AS banco_pregunta_id,
                    bp.pregunta_id,

                    lp.enunciado,
                    lp.opcion_a,
                    lp.opcion_b,
                    lp.opcion_c,
                    lp.opcion_d,
                    lp.respuesta_correcta,

                    lp.tipo_clasificacion,
                    lp.tipo_norma,
                    lp.nombre_norma,
                    lp.articulo,
                    lp.tema_no_juridico,

                    lp.origen_oposicion,
                    lp.tipo_fuente,
                    lp.importacion_fichero_id,
                    lp.pagina_origen,

                    lp.norma_id_normalizada,
                    lp.articulo_normalizado,
                    lp.teorica_practica,
                    lp.tipo_norma_normalizado,
                    lp.nombre_norma_normalizado,

                    bp.tipo_vinculacion,
                    bp.estado AS banco_estado,
                    bp.metodo_vinculacion,
                    bp.motivo_revision,

                    tt.id AS tema_id,
                    tt.parte AS tema_parte,
                    tt.numero_tema,
                    tt.titulo AS tema_titulo,
                    tt.tipo_contenido AS tema_tipo_contenido,

                    CASE
                        WHEN tt.parte = 'GENERAL'
                            THEN 'general'

                        WHEN tt.parte = 'ESPECIAL'
                             AND lp.tipo_clasificacion = 'INFORMATICA'
                            THEN 'especial_informatica'

                        WHEN tt.parte = 'ESPECIAL'
                             AND lp.teorica_practica = 'PRACTICA'
                            THEN 'especial_practica'

                        WHEN tt.parte = 'ESPECIAL'
                             AND lp.teorica_practica = 'TEORICA'
                            THEN 'especial_teoria'
                    END AS nombre_parte

                FROM banco_preguntas bp

                JOIN lote_preguntas lp
                    ON lp.id = bp.pregunta_id

                JOIN banco_preguntas_temas bpt
                    ON bpt.banco_pregunta_id = bp.id
                   AND bpt.es_principal = 1

                JOIN temario_temas tt
                    ON tt.id = bpt.tema_id

                WHERE bp.convocatoria_id = ?
                  AND bp.estado = 'INCLUIDA'
                  AND (
                        lp.origen_oposicion IS NULL
                        OR TRIM(lp.origen_oposicion) = ''
                        OR UPPER(TRIM(lp.origen_oposicion))
                            IN ({marcadores_origen})
                  )
            )

            SELECT *
            FROM preguntas_clasificadas
            WHERE nombre_parte IS NOT NULL
            """,
            (
                convocatoria_id,
                *origenes,
            ),
        ).fetchall()

    # -------------------------------------------------------------------------
    # 2. Selección aleatoria de preguntas
    # -------------------------------------------------------------------------

    preguntas_seleccionadas: list[
        tuple[sqlite3.Row, sqlite3.Row]
    ] = []

    preguntas_usadas: set[int] = set()

    for parte in partes:

        candidatas_parte = [
            pregunta
            for pregunta in candidatas
            if pregunta["nombre_parte"] == parte["nombre"]
            and pregunta["pregunta_id"] not in preguntas_usadas
        ]

        cantidad = parte["numero_preguntas"]

        if len(candidatas_parte) < cantidad:
            raise ValueError(
                f'No hay suficientes preguntas para '
                f'{parte["nombre"]}. '
                f'Se necesitan {cantidad} y solo hay '
                f'{len(candidatas_parte)}.'
            )

        elegidas = random.sample(
            candidatas_parte,
            cantidad,
        )

        for pregunta in elegidas:
            preguntas_usadas.add(
                pregunta["pregunta_id"]
            )

            preguntas_seleccionadas.append(
                (parte, pregunta)
            )

    if (
        len(preguntas_seleccionadas)
        != convocatoria["numero_preguntas"]
    ):
        raise ValueError(
            "El número de preguntas seleccionadas no coincide "
            "con el total de la convocatoria."
        )

    # -------------------------------------------------------------------------
    # 3. Escritura completa en usuario.sqlite3
    # -------------------------------------------------------------------------

    with conectar_usuario() as con_usuario:

        con_usuario.execute("BEGIN IMMEDIATE")

        numero = con_usuario.execute(
            """
            SELECT COALESCE(MAX(numero), 0) + 1
            FROM simulacros
            WHERE convocatoria_id = ?
            """,
            (convocatoria_id,),
        ).fetchone()[0]

        cursor_simulacro = con_usuario.execute(
            """
            INSERT INTO simulacros
            (
                convocatoria_id,
                numero,
                total_preguntas,
                tipo_prueba,

                convocatoria_codigo,
                convocatoria_puesto,
                convocatoria_numero,
                convocatoria_anio,
                convocatoria_numero_preguntas,

                valoracion_test_acierto,
                valoracion_test_fallo,
                valoracion_test_no_contesta,
                formula_nota,
                factor_escala_nota
            )
            VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                convocatoria_id,
                numero,
                convocatoria["numero_preguntas"],
                "SIMULACRO",

                convocatoria["codigo"],
                convocatoria["puesto"],
                convocatoria["numero"],
                convocatoria["anio"],
                convocatoria["numero_preguntas"],

                convocatoria["valoracion_test_acierto"],
                convocatoria["valoracion_test_fallo"],
                convocatoria["valoracion_test_no_contesta"],
                convocatoria["formula_nota"],
                convocatoria["factor_escala_nota"],
            ),
        )

        simulacro_id = cursor_simulacro.lastrowid

        if simulacro_id is None:
            raise RuntimeError(
                "No se ha podido crear el simulacro."
            )

        preguntas_para_guardar: list[dict] = []

        for orden, datos in enumerate(
            preguntas_seleccionadas,
            start=1,
        ):
            parte, pregunta = datos

            preguntas_para_guardar.append(
                {
                    "orden": orden,
                    "pregunta_id": pregunta["pregunta_id"],
                    "banco_pregunta_id": pregunta["banco_pregunta_id"],
                    "parte_id": parte["id"],
                    "parte_nombre": parte["nombre"],
                    "parte_orden": parte["orden"],
                    "enunciado": pregunta["enunciado"],
                    "opcion_a": pregunta["opcion_a"],
                    "opcion_b": pregunta["opcion_b"],
                    "opcion_c": pregunta["opcion_c"],
                    "opcion_d": pregunta["opcion_d"],
                    "respuesta_correcta": pregunta["respuesta_correcta"],
                    "tipo_clasificacion": pregunta["tipo_clasificacion"],
                    "tipo_norma": pregunta["tipo_norma"],
                    "nombre_norma": pregunta["nombre_norma"],
                    "articulo": pregunta["articulo"],
                    "tema_no_juridico": pregunta["tema_no_juridico"],
                    "origen_oposicion": pregunta["origen_oposicion"],
                    "tipo_fuente": pregunta["tipo_fuente"],
                    "importacion_fichero_id": pregunta["importacion_fichero_id"],
                    "pagina_origen": pregunta["pagina_origen"],
                    "norma_id_normalizada": pregunta["norma_id_normalizada"],
                    "articulo_normalizado": pregunta["articulo_normalizado"],
                    "teorica_practica": pregunta["teorica_practica"],
                    "tipo_norma_normalizado": pregunta["tipo_norma_normalizado"],
                    "nombre_norma_normalizado": pregunta["nombre_norma_normalizado"],
                    "banco_tipo_vinculacion": pregunta["tipo_vinculacion"],
                    "banco_estado": pregunta["banco_estado"],
                    "banco_metodo_vinculacion": pregunta["metodo_vinculacion"],
                    "banco_motivo_revision": pregunta["motivo_revision"],
                    "temas_json": json.dumps(
                        {
                            "tema_id_original": pregunta["tema_id"],
                            "parte": pregunta["tema_parte"],
                            "numero_tema": pregunta["numero_tema"],
                            "titulo": pregunta["tema_titulo"],
                            "tipo_contenido": pregunta["tema_tipo_contenido"],
                            "es_principal": 1,
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        _guardar_preguntas_prueba_en_lotes(
            con_usuario,
            int(simulacro_id),
            preguntas_para_guardar,
        )

        return int(simulacro_id)

def obtener_simulacro(
    simulacro_id: int,
    ) -> sqlite3.Row | None:
    """
    Obtiene la cabecera de un simulacro guardado en usuario.sqlite3.
    """

    with conectar_usuario() as con:
        return con.execute(
            """
            SELECT
                id,
                convocatoria_id,
                numero,
                fecha_generacion,
                total_preguntas,
                estado,
                tipo_prueba,

                convocatoria_codigo,
                convocatoria_puesto,
                convocatoria_numero,
                convocatoria_anio,
                convocatoria_numero_preguntas,

                valoracion_test_acierto,
                valoracion_test_fallo,
                valoracion_test_no_contesta,
                formula_nota,
                factor_escala_nota
            FROM simulacros
            WHERE id = ?
            """,
            (simulacro_id,),
        ).fetchone()


def obtener_preguntas_simulacro(
    simulacro_id: int,
) -> list[sqlite3.Row]:
    """
    Obtiene las preguntas y el snapshot inmutable de un simulacro.
    """

    with conectar_usuario() as con:
        return con.execute(
            """
            SELECT
                sp.id AS simulacro_pregunta_id,
                sp.orden,
                sp.pregunta_id,
                sp.banco_pregunta_id,
                sp.parte_id,
                sp.parte_nombre,
                sp.parte_orden,
                sp.respuesta_usuario,
                sp.seguridad_usuario,

                ss.enunciado,
                ss.opcion_a,
                ss.opcion_b,
                ss.opcion_c,
                ss.opcion_d,
                ss.respuesta_correcta,

                ss.tipo_clasificacion,
                ss.tipo_norma,
                ss.nombre_norma,
                ss.articulo,
                ss.tema_no_juridico,

                ss.teorica_practica,
                ss.temas_json,
                ss.comentario_solucion

            FROM simulacro_preguntas sp

            JOIN simulacro_snapshot ss
                ON ss.simulacro_pregunta_id = sp.id

            WHERE sp.simulacro_id = ?

            ORDER BY sp.orden
            """,
            (simulacro_id,),
        ).fetchall()

def guardar_respuesta_simulacro(
    simulacro_pregunta_id: int,
    respuesta_usuario: str | None,
    seguridad_usuario: str | None,
) -> bool:
    """
    Guarda la respuesta elegida y el nivel de seguridad
    de una pregunta concreta del simulacro.
    """

    respuestas_validas = {
        None,
        "A",
        "B",
        "C",
        "D",
    }

    seguridades_validas = {
        None,
        "MUY_SEGURO",
        "BASTANTE_SEGURO",
        "POCO_SEGURO",
    }

    if respuesta_usuario not in respuestas_validas:
        raise ValueError(
            "La respuesta del usuario no es válida."
        )

    if seguridad_usuario not in seguridades_validas:
        raise ValueError(
            "El nivel de seguridad no es válido."
        )

    with conectar_usuario() as con:
        cursor = con.execute(
            """
            UPDATE simulacro_preguntas
            SET
                respuesta_usuario = ?,
                seguridad_usuario = ?
            WHERE id = ?
            """,
            (
                respuesta_usuario,
                seguridad_usuario,
                simulacro_pregunta_id,
            ),
        )

    return cursor.rowcount == 1


def obtener_resultado_simulacro(
    simulacro_id: int,
) -> dict:
    """
    Calcula el resultado usando exclusivamente usuario.sqlite3.
    """

    with conectar_usuario() as con_usuario:
        simulacro = con_usuario.execute(
            """
            SELECT
                id,
                convocatoria_id,
                numero,
                total_preguntas,
                tipo_prueba,
                convocatoria_codigo,
                convocatoria_numero_preguntas,
                valoracion_test_acierto,
                valoracion_test_fallo,
                valoracion_test_no_contesta,
                factor_escala_nota
            FROM simulacros
            WHERE id = ?
            """,
            (simulacro_id,),
        ).fetchone()

        if simulacro is None:
            raise ValueError("El simulacro no existe.")

        preguntas = con_usuario.execute(
            """
            SELECT
                sp.orden,
                sp.respuesta_usuario,
                sp.seguridad_usuario,
                ss.respuesta_correcta,
                ss.temas_json
            FROM simulacro_preguntas sp
            JOIN simulacro_snapshot ss
                ON ss.simulacro_pregunta_id = sp.id
            WHERE sp.simulacro_id = ?
            ORDER BY sp.orden
            """,
            (simulacro_id,),
        ).fetchall()

    total = len(preguntas)

    if total != simulacro["total_preguntas"]:
        raise ValueError(
            "El número de preguntas guardadas no coincide con "
            "el total del simulacro."
        )

    respuestas_validas = {"A", "B", "C", "D"}

    etiquetas_seguridad = {
        "MUY_SEGURO": "Muy seguro",
        "BASTANTE_SEGURO": "Bastante seguro",
        "POCO_SEGURO": "Poco seguro",
    }

    aciertos = 0
    fallos = 0
    no_contestadas = 0
    estadisticas_temas: dict[str, dict] = {}

    estadisticas_seguridad = {
        codigo: {
            "codigo": codigo,
            "seguridad": etiqueta,
            "contestadas": 0,
            "aciertos": 0,
            "fallos": 0,
        }
        for codigo, etiqueta in etiquetas_seguridad.items()
    }

    for pregunta in preguntas:
        respuesta_correcta = pregunta["respuesta_correcta"]
        respuesta_usuario = pregunta["respuesta_usuario"]
        seguridad_usuario = pregunta["seguridad_usuario"]

        if respuesta_correcta not in respuestas_validas:
            raise ValueError(
                "El simulacro contiene alguna pregunta sin una "
                "respuesta correcta válida."
            )

        if not pregunta["temas_json"]:
            raise ValueError(
                "El simulacro contiene una pregunta sin tema "
                f'congelado: pregunta {pregunta["orden"]}.'
            )

        try:
            tema = json.loads(pregunta["temas_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "El simulacro contiene un tema congelado no válido "
                f'en la pregunta {pregunta["orden"]}.'
            ) from exc

        parte = tema.get("parte")
        numero_tema = tema.get("numero_tema")
        titulo = tema.get("titulo")

        if parte is None or numero_tema is None or not titulo:
            raise ValueError(
                "El tema congelado está incompleto "
                f'en la pregunta {pregunta["orden"]}.'
            )

        clave_tema = f"{parte}|{numero_tema}|{titulo}"

        if clave_tema not in estadisticas_temas:
            estadisticas_temas[clave_tema] = {
                "tema_id": tema.get("tema_id_original"),
                "parte": parte,
                "numero_tema": numero_tema,
                "titulo": titulo,
                "preguntas": 0,
                "contestadas": 0,
                "no_contestadas": 0,
                "aciertos": 0,
                "fallos": 0,
            }

        estadistica_tema = estadisticas_temas[clave_tema]
        estadistica_tema["preguntas"] += 1

        if respuesta_usuario is None:
            no_contestadas += 1
            estadistica_tema["no_contestadas"] += 1
            continue

        if respuesta_usuario not in respuestas_validas:
            raise ValueError(
                "Existe alguna respuesta del usuario no válida."
            )

        if seguridad_usuario not in estadisticas_seguridad:
            raise ValueError(
                "Existe alguna pregunta contestada sin un nivel "
                "de seguridad válido."
            )

        estadistica_tema["contestadas"] += 1
        estadistica_seguridad = estadisticas_seguridad[seguridad_usuario]
        estadistica_seguridad["contestadas"] += 1

        if respuesta_usuario == respuesta_correcta:
            aciertos += 1
            estadistica_tema["aciertos"] += 1
            estadistica_seguridad["aciertos"] += 1
        else:
            fallos += 1
            estadistica_tema["fallos"] += 1
            estadistica_seguridad["fallos"] += 1

    contestadas = aciertos + fallos

    valor_acierto = simulacro["valoracion_test_acierto"]
    valor_fallo = simulacro["valoracion_test_fallo"]
    valor_no_contesta = simulacro["valoracion_test_no_contesta"]
    factor_escala = simulacro["factor_escala_nota"]

    if any(
        valor is None
        for valor in (
            valor_acierto,
            valor_fallo,
            valor_no_contesta,
            factor_escala,
        )
    ):
        raise ValueError(
            "El simulacro no tiene congelada toda la configuración "
            "de corrección."
        )

    puntuacion_bruta = (
        aciertos * valor_acierto
        + fallos * valor_fallo
        + no_contestadas * valor_no_contesta
    )

    if simulacro["tipo_prueba"] == "TEST":
        divisor_nota = simulacro["total_preguntas"]
    else:
        divisor_nota = simulacro[
            "convocatoria_numero_preguntas"
        ]

    if divisor_nota is None or divisor_nota <= 0:
        raise ValueError(
            "La prueba no tiene congelado un número de "
            "preguntas válido."
        )

    nota = (
        puntuacion_bruta
        / divisor_nota
        * factor_escala
    )

    resultado_temas = []

    for estadistica in estadisticas_temas.values():
        preguntas_tema = estadistica["preguntas"]

        estadistica["porcentaje_simulacro"] = (
            preguntas_tema / total * 100 if total else 0.0
        )
        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / preguntas_tema * 100
            if preguntas_tema
            else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / preguntas_tema * 100
            if preguntas_tema
            else 0.0
        )

        resultado_temas.append(estadistica)

    resultado_temas.sort(
        key=lambda item: (
            item["parte"],
            item["numero_tema"],
            item["titulo"],
        )
    )

    resultado_seguridad = []

    for estadistica in estadisticas_seguridad.values():
        contestadas_seguridad = estadistica["contestadas"]

        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / contestadas_seguridad * 100
            if contestadas_seguridad
            else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / contestadas_seguridad * 100
            if contestadas_seguridad
            else 0.0
        )

        resultado_seguridad.append(estadistica)

    return {
        "simulacro_id": simulacro_id,
        "simulacro_numero": simulacro["numero"],
        "convocatoria_id": simulacro["convocatoria_id"],
        "convocatoria_codigo": simulacro["convocatoria_codigo"],
        "tipo_prueba": simulacro["tipo_prueba"],
        "total": total,
        "contestadas": contestadas,
        "no_contestadas": no_contestadas,
        "aciertos": aciertos,
        "fallos": fallos,
        "valor_acierto": valor_acierto,
        "valor_fallo": valor_fallo,
        "valor_no_contesta": valor_no_contesta,
        "puntuacion_bruta": puntuacion_bruta,
        "factor_escala_nota": factor_escala,
        "nota": nota,
        "temas": resultado_temas,
        "seguridad": resultado_seguridad,
    }

def eliminar_simulacro(
    simulacro_id: int,
    convocatoria_id: int,
    ) -> bool:
    """
    Elimina un simulacro de usuario.sqlite3.

    También se eliminan automáticamente sus registros de
    simulacro_preguntas y simulacro_snapshot mediante ON DELETE CASCADE.
    """

    with conectar_usuario() as con:
        cursor = con.execute(
            """
            DELETE FROM simulacros
            WHERE id = ?
              AND convocatoria_id = ?
            """,
            (
                simulacro_id,
                convocatoria_id,
            ),
        )

    return cursor.rowcount == 1


def obtener_puntos_temario_test(
    convocatoria_id: int,
) -> list[sqlite3.Row]:
    """Obtiene los puntos del temario y su disponibilidad para tests."""

    with conectar() as con:
        return con.execute(
            """
            SELECT
                tt.id,
                tt.parte,
                tt.numero_tema,
                tt.titulo,
                tt.tipo_contenido,
                COUNT(DISTINCT bp.pregunta_id) AS disponibles

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

            WHERE t.convocatoria_id = ?

            GROUP BY
                tt.id,
                tt.parte,
                tt.numero_tema,
                tt.titulo,
                tt.tipo_contenido

            ORDER BY
                CASE tt.parte
                    WHEN 'GENERAL' THEN 1
                    WHEN 'ESPECIAL' THEN 2
                    ELSE 3
                END,
                tt.numero_tema,
                tt.titulo
            """,
            (
                convocatoria_id,
                convocatoria_id,
            ),
        ).fetchall()


def obtener_tests(
    convocatoria_id: int,
) -> list[sqlite3.Row]:
    """Obtiene los tests guardados en usuario.sqlite3."""

    with conectar_usuario() as con:
        return con.execute(
            """
            SELECT
                s.id,
                s.numero,
                s.fecha_generacion,
                s.total_preguntas,
                s.estado,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM simulacro_preguntas sp
                        WHERE sp.simulacro_id = s.id
                          AND (
                              sp.respuesta_usuario IS NOT NULL
                              OR sp.seguridad_usuario IS NOT NULL
                          )
                    )
                    THEN 1
                    ELSE 0
                END AS corregido
            FROM simulacros s
            WHERE s.convocatoria_id = ?
              AND s.tipo_prueba = 'TEST'
            ORDER BY s.numero DESC
            """,
            (convocatoria_id,),
        ).fetchall()


def _repartir_proporcionalmente(
    disponibilidades: dict[int, int],
    total_solicitado: int,
) -> dict[int, int]:
    """Reparte el total por disponibilidad mediante restos mayores."""

    total_disponible = sum(disponibilidades.values())

    if total_disponible <= 0:
        return {tema_id: 0 for tema_id in disponibilidades}

    total_generar = min(total_solicitado, total_disponible)
    cuotas_exactas = {
        tema_id: total_generar * disponibles / total_disponible
        for tema_id, disponibles in disponibilidades.items()
    }
    reparto = {
        tema_id: min(int(cuota), disponibilidades[tema_id])
        for tema_id, cuota in cuotas_exactas.items()
    }

    pendientes = total_generar - sum(reparto.values())

    orden_resto = sorted(
        disponibilidades,
        key=lambda tema_id: (
            cuotas_exactas[tema_id] - int(cuotas_exactas[tema_id]),
            disponibilidades[tema_id],
            -tema_id,
        ),
        reverse=True,
    )

    while pendientes > 0:
        asignada = False

        for tema_id in orden_resto:
            if reparto[tema_id] < disponibilidades[tema_id]:
                reparto[tema_id] += 1
                pendientes -= 1
                asignada = True

                if pendientes == 0:
                    break

        if not asignada:
            break

    return reparto


def crear_test(
    convocatoria_id: int,
    numero_preguntas: int,
    temas_seleccionados: list[int],
) -> dict:
    """
    Crea un test proporcional entre los puntos del temario seleccionados.

    El test queda congelado en usuario.sqlite3 con la misma estructura
    autónoma utilizada por los simulacros.
    """

    if numero_preguntas <= 0:
        raise ValueError(
            "El número de preguntas debe ser mayor que cero."
        )

    temas_ids = sorted({int(tema_id) for tema_id in temas_seleccionados})

    if not temas_ids:
        raise ValueError(
            "Debe seleccionar al menos un punto del temario."
        )

    marcadores = ", ".join("?" for _ in temas_ids)

    with conectar() as con_catalogo:
        convocatoria = con_catalogo.execute(
            """
            SELECT
                id,
                puesto,
                numero,
                anio,
                codigo,
                numero_preguntas,
                valoracion_test_acierto,
                valoracion_test_fallo,
                valoracion_test_no_contesta,
                formula_nota,
                factor_escala_nota
            FROM convocatorias
            WHERE id = ?
            """,
            (convocatoria_id,),
        ).fetchone()

        if convocatoria is None:
            raise ValueError("La convocatoria no existe.")

        temas = con_catalogo.execute(
            f"""
            SELECT
                tt.id,
                tt.parte,
                tt.numero_tema,
                tt.titulo,
                tt.tipo_contenido
            FROM temario_temas tt
            JOIN temarios t
                ON t.id = tt.temario_id
            WHERE t.convocatoria_id = ?
              AND tt.id IN ({marcadores})
            ORDER BY tt.parte, tt.numero_tema, tt.titulo
            """,
            (convocatoria_id, *temas_ids),
        ).fetchall()

        if len(temas) != len(temas_ids):
            raise ValueError(
                "Alguno de los puntos seleccionados no pertenece "
                "a la convocatoria."
            )

        candidatas = con_catalogo.execute(
            f"""
            SELECT DISTINCT
                bp.id AS banco_pregunta_id,
                bp.pregunta_id,

                lp.enunciado,
                lp.opcion_a,
                lp.opcion_b,
                lp.opcion_c,
                lp.opcion_d,
                lp.respuesta_correcta,

                lp.tipo_clasificacion,
                lp.tipo_norma,
                lp.nombre_norma,
                lp.articulo,
                lp.tema_no_juridico,

                lp.origen_oposicion,
                lp.tipo_fuente,
                lp.importacion_fichero_id,
                lp.pagina_origen,

                lp.norma_id_normalizada,
                lp.articulo_normalizado,
                lp.teorica_practica,
                lp.tipo_norma_normalizado,
                lp.nombre_norma_normalizado,

                bp.tipo_vinculacion,
                bp.estado AS banco_estado,
                bp.metodo_vinculacion,
                bp.motivo_revision,

                tt.id AS tema_id,
                tt.parte AS tema_parte,
                tt.numero_tema,
                tt.titulo AS tema_titulo,
                tt.tipo_contenido AS tema_tipo_contenido

            FROM banco_preguntas bp

            JOIN lote_preguntas lp
                ON lp.id = bp.pregunta_id

            JOIN banco_preguntas_temas bpt
                ON bpt.banco_pregunta_id = bp.id
               AND bpt.es_principal = 1

            JOIN temario_temas tt
                ON tt.id = bpt.tema_id

            WHERE bp.convocatoria_id = ?
              AND bp.estado = 'INCLUIDA'
              AND tt.id IN ({marcadores})
            """,
            (
                convocatoria_id,
                *temas_ids,
            ),
        ).fetchall()

    candidatas_por_tema: dict[int, list[sqlite3.Row]] = {
        tema_id: [] for tema_id in temas_ids
    }

    for pregunta in candidatas:
        candidatas_por_tema[int(pregunta["tema_id"])].append(
            pregunta
        )

    disponibilidades = {
        tema_id: len(preguntas)
        for tema_id, preguntas in candidatas_por_tema.items()
    }
    total_disponible = sum(disponibilidades.values())

    if total_disponible == 0:
        raise ValueError(
            "No hay preguntas disponibles para los puntos "
            "seleccionados."
        )

    reparto = _repartir_proporcionalmente(
        disponibilidades,
        numero_preguntas,
    )

    preguntas_seleccionadas: list[sqlite3.Row] = []
    preguntas_usadas: set[int] = set()

    for tema in temas:
        tema_id = int(tema["id"])
        cantidad = reparto[tema_id]
        disponibles_tema = [
            pregunta
            for pregunta in candidatas_por_tema[tema_id]
            if int(pregunta["pregunta_id"]) not in preguntas_usadas
        ]

        elegidas = random.sample(
            disponibles_tema,
            cantidad,
        )

        for pregunta in elegidas:
            preguntas_usadas.add(int(pregunta["pregunta_id"]))
            preguntas_seleccionadas.append(pregunta)

    random.shuffle(preguntas_seleccionadas)
    total_generado = len(preguntas_seleccionadas)

    if total_generado == 0:
        raise ValueError("No se ha podido generar el test.")

    avisos: list[str] = []

    if total_generado < numero_preguntas:
        avisos.append(
            f"Se solicitaron {numero_preguntas} preguntas, pero "
            f"solo hay {total_generado} disponibles en los puntos "
            "seleccionados. El test se ha creado con el máximo "
            "disponible."
        )

    with conectar_usuario() as con_usuario:
        con_usuario.execute("BEGIN IMMEDIATE")

        numero = con_usuario.execute(
            """
            SELECT COALESCE(MAX(numero), 0) + 1
            FROM simulacros
            WHERE convocatoria_id = ?
            """,
            (convocatoria_id,),
        ).fetchone()[0]

        cursor_test = con_usuario.execute(
            """
            INSERT INTO simulacros
            (
                convocatoria_id,
                numero,
                total_preguntas,
                tipo_prueba,

                convocatoria_codigo,
                convocatoria_puesto,
                convocatoria_numero,
                convocatoria_anio,
                convocatoria_numero_preguntas,

                valoracion_test_acierto,
                valoracion_test_fallo,
                valoracion_test_no_contesta,
                formula_nota,
                factor_escala_nota
            )
            VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                convocatoria_id,
                numero,
                total_generado,
                "TEST",

                convocatoria["codigo"],
                convocatoria["puesto"],
                convocatoria["numero"],
                convocatoria["anio"],
                convocatoria["numero_preguntas"],

                convocatoria["valoracion_test_acierto"],
                convocatoria["valoracion_test_fallo"],
                convocatoria["valoracion_test_no_contesta"],
                convocatoria["formula_nota"],
                convocatoria["factor_escala_nota"],
            ),
        )

        test_id = cursor_test.lastrowid

        if test_id is None:
            raise RuntimeError("No se ha podido crear el test.")

        preguntas_para_guardar: list[dict] = []

        for orden, pregunta in enumerate(
            preguntas_seleccionadas,
            start=1,
        ):
            preguntas_para_guardar.append(
                {
                    "orden": orden,
                    "pregunta_id": pregunta["pregunta_id"],
                    "banco_pregunta_id": pregunta["banco_pregunta_id"],
                    "parte_id": None,
                    "parte_nombre": pregunta["tema_parte"],
                    "parte_orden": pregunta["numero_tema"],
                    "enunciado": pregunta["enunciado"],
                    "opcion_a": pregunta["opcion_a"],
                    "opcion_b": pregunta["opcion_b"],
                    "opcion_c": pregunta["opcion_c"],
                    "opcion_d": pregunta["opcion_d"],
                    "respuesta_correcta": pregunta["respuesta_correcta"],
                    "tipo_clasificacion": pregunta["tipo_clasificacion"],
                    "tipo_norma": pregunta["tipo_norma"],
                    "nombre_norma": pregunta["nombre_norma"],
                    "articulo": pregunta["articulo"],
                    "tema_no_juridico": pregunta["tema_no_juridico"],
                    "origen_oposicion": pregunta["origen_oposicion"],
                    "tipo_fuente": pregunta["tipo_fuente"],
                    "importacion_fichero_id": pregunta["importacion_fichero_id"],
                    "pagina_origen": pregunta["pagina_origen"],
                    "norma_id_normalizada": pregunta["norma_id_normalizada"],
                    "articulo_normalizado": pregunta["articulo_normalizado"],
                    "teorica_practica": pregunta["teorica_practica"],
                    "tipo_norma_normalizado": pregunta["tipo_norma_normalizado"],
                    "nombre_norma_normalizado": pregunta["nombre_norma_normalizado"],
                    "banco_tipo_vinculacion": pregunta["tipo_vinculacion"],
                    "banco_estado": pregunta["banco_estado"],
                    "banco_metodo_vinculacion": pregunta["metodo_vinculacion"],
                    "banco_motivo_revision": pregunta["motivo_revision"],
                    "temas_json": json.dumps(
                        {
                            "tema_id_original": pregunta["tema_id"],
                            "parte": pregunta["tema_parte"],
                            "numero_tema": pregunta["numero_tema"],
                            "titulo": pregunta["tema_titulo"],
                            "tipo_contenido": pregunta["tema_tipo_contenido"],
                            "es_principal": 1,
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        _guardar_preguntas_prueba_en_lotes(
            con_usuario,
            int(test_id),
            preguntas_para_guardar,
        )


    return {
        "test_id": int(test_id),
        "numero": int(numero),
        "total_solicitado": numero_preguntas,
        "total_generado": total_generado,
        "reparto": reparto,
        "avisos": avisos,
    }


def eliminar_test(
    test_id: int,
    convocatoria_id: int,
) -> bool:
    """Elimina un test de usuario.sqlite3."""

    with conectar_usuario() as con:
        cursor = con.execute(
            """
            DELETE FROM simulacros
            WHERE id = ?
              AND convocatoria_id = ?
              AND tipo_prueba = 'TEST'
            """,
            (
                test_id,
                convocatoria_id,
            ),
        )

    return cursor.rowcount == 1


def obtener_resultado_acumulado_convocatoria(
    convocatoria_id: int,
) -> dict:
    """
    Calcula el rendimiento acumulado de los simulacros corregidos que
    siguen existiendo para una convocatoria.

    Solo incluye pruebas de tipo SIMULACRO. Un simulacro se considera
    corregido cuando alguna de sus preguntas tiene respuesta o nivel de
    seguridad guardado. El resultado se recalcula siempre desde
    usuario.sqlite3, por lo que una eliminación queda reflejada de forma
    automática.
    """

    respuestas_validas = {"A", "B", "C", "D"}
    etiquetas_seguridad = {
        "MUY_SEGURO": "Muy seguro",
        "BASTANTE_SEGURO": "Bastante seguro",
        "POCO_SEGURO": "Poco seguro",
    }

    with conectar_usuario() as con:
        simulacros = con.execute(
            """
            SELECT
                s.id,
                s.numero,
                s.fecha_generacion,
                s.valoracion_test_acierto,
                s.valoracion_test_fallo,
                s.valoracion_test_no_contesta
            FROM simulacros s
            WHERE s.convocatoria_id = ?
              AND s.tipo_prueba = 'SIMULACRO'
              AND EXISTS (
                    SELECT 1
                    FROM simulacro_preguntas sp
                    WHERE sp.simulacro_id = s.id
                      AND (
                          sp.respuesta_usuario IS NOT NULL
                          OR sp.seguridad_usuario IS NOT NULL
                      )
              )
            ORDER BY s.id
            """,
            (convocatoria_id,),
        ).fetchall()

        if not simulacros:
            return {
                "convocatoria_id": convocatoria_id,
                "simulacros": 0,
                "simulacros_ids": [],
                "preguntas": 0,
                "contestadas": 0,
                "no_contestadas": 0,
                "aciertos": 0,
                "fallos": 0,
                "temas": [],
                "seguridad": [],
                "firma_datos": hashlib.sha256(b"").hexdigest(),
            }

        simulacros_ids = [int(fila["id"]) for fila in simulacros]
        marcadores = ", ".join("?" for _ in simulacros_ids)

        preguntas = con.execute(
            f"""
            SELECT
                s.id AS simulacro_id,
                s.numero AS simulacro_numero,
                sp.orden,
                sp.respuesta_usuario,
                sp.seguridad_usuario,
                ss.respuesta_correcta,
                ss.temas_json
            FROM simulacros s
            JOIN simulacro_preguntas sp
                ON sp.simulacro_id = s.id
            JOIN simulacro_snapshot ss
                ON ss.simulacro_pregunta_id = sp.id
            WHERE s.id IN ({marcadores})
            ORDER BY s.id, sp.orden
            """,
            simulacros_ids,
        ).fetchall()

    total = len(preguntas)
    aciertos = 0
    fallos = 0
    no_contestadas = 0
    estadisticas_temas: dict[str, dict] = {}

    estadisticas_seguridad = {
        codigo: {
            "codigo": codigo,
            "seguridad": etiqueta,
            "contestadas": 0,
            "aciertos": 0,
            "fallos": 0,
        }
        for codigo, etiqueta in etiquetas_seguridad.items()
    }

    firma_partes: list[str] = []

    for simulacro in simulacros:
        firma_partes.append(
            "|".join(
                [
                    str(simulacro["id"]),
                    str(simulacro["numero"]),
                    str(simulacro["fecha_generacion"]),
                    str(simulacro["valoracion_test_acierto"]),
                    str(simulacro["valoracion_test_fallo"]),
                    str(simulacro["valoracion_test_no_contesta"]),
                ]
            )
        )

    for pregunta in preguntas:
        respuesta_correcta = pregunta["respuesta_correcta"]
        respuesta_usuario = pregunta["respuesta_usuario"]
        seguridad_usuario = pregunta["seguridad_usuario"]

        if respuesta_correcta not in respuestas_validas:
            raise ValueError(
                "Los simulacros acumulados contienen alguna pregunta "
                "sin una respuesta correcta válida."
            )

        if not pregunta["temas_json"]:
            raise ValueError(
                "Los simulacros acumulados contienen alguna pregunta "
                "sin tema congelado."
            )

        try:
            tema = json.loads(pregunta["temas_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Los simulacros acumulados contienen un tema congelado "
                "no válido."
            ) from exc

        parte = tema.get("parte")
        numero_tema = tema.get("numero_tema")
        titulo = tema.get("titulo")

        if parte is None or numero_tema is None or not titulo:
            raise ValueError(
                "Los simulacros acumulados contienen un tema congelado "
                "incompleto."
            )

        clave_tema = f"{parte}|{numero_tema}|{titulo}"

        if clave_tema not in estadisticas_temas:
            estadisticas_temas[clave_tema] = {
                "tema_id": tema.get("tema_id_original"),
                "parte": parte,
                "numero_tema": numero_tema,
                "titulo": titulo,
                "preguntas": 0,
                "contestadas": 0,
                "no_contestadas": 0,
                "aciertos": 0,
                "fallos": 0,
                "fallos_muy_seguro": 0,
            }

        estadistica_tema = estadisticas_temas[clave_tema]
        estadistica_tema["preguntas"] += 1

        firma_partes.append(
            "|".join(
                [
                    str(pregunta["simulacro_id"]),
                    str(pregunta["orden"]),
                    str(respuesta_usuario),
                    str(seguridad_usuario),
                    str(respuesta_correcta),
                    clave_tema,
                ]
            )
        )

        if respuesta_usuario is None:
            no_contestadas += 1
            estadistica_tema["no_contestadas"] += 1
            continue

        if respuesta_usuario not in respuestas_validas:
            raise ValueError(
                "Existe alguna respuesta acumulada del usuario no válida."
            )

        if seguridad_usuario not in estadisticas_seguridad:
            raise ValueError(
                "Existe alguna pregunta acumulada contestada sin un "
                "nivel de seguridad válido."
            )

        estadistica_tema["contestadas"] += 1
        estadistica_seguridad = estadisticas_seguridad[seguridad_usuario]
        estadistica_seguridad["contestadas"] += 1

        if respuesta_usuario == respuesta_correcta:
            aciertos += 1
            estadistica_tema["aciertos"] += 1
            estadistica_seguridad["aciertos"] += 1
        else:
            fallos += 1
            estadistica_tema["fallos"] += 1
            estadistica_seguridad["fallos"] += 1

            if seguridad_usuario == "MUY_SEGURO":
                estadistica_tema["fallos_muy_seguro"] += 1

    contestadas = aciertos + fallos
    resultado_temas = []

    for estadistica in estadisticas_temas.values():
        preguntas_tema = estadistica["preguntas"]
        contestadas_tema = estadistica["contestadas"]

        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / preguntas_tema * 100
            if preguntas_tema
            else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / preguntas_tema * 100
            if preguntas_tema
            else 0.0
        )
        estadistica["porcentaje_no_contestadas"] = (
            estadistica["no_contestadas"] / preguntas_tema * 100
            if preguntas_tema
            else 0.0
        )
        estadistica["porcentaje_aciertos_contestadas"] = (
            estadistica["aciertos"] / contestadas_tema * 100
            if contestadas_tema
            else 0.0
        )

        resultado_temas.append(estadistica)

    resultado_temas.sort(
        key=lambda item: (
            item["parte"],
            item["numero_tema"],
            item["titulo"],
        )
    )

    resultado_seguridad = []

    for estadistica in estadisticas_seguridad.values():
        contestadas_seguridad = estadistica["contestadas"]
        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / contestadas_seguridad * 100
            if contestadas_seguridad
            else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / contestadas_seguridad * 100
            if contestadas_seguridad
            else 0.0
        )
        resultado_seguridad.append(estadistica)

    firma_datos = hashlib.sha256(
        "\n".join(firma_partes).encode("utf-8")
    ).hexdigest()

    return {
        "convocatoria_id": convocatoria_id,
        "simulacros": len(simulacros),
        "simulacros_ids": simulacros_ids,
        "preguntas": total,
        "contestadas": contestadas,
        "no_contestadas": no_contestadas,
        "aciertos": aciertos,
        "fallos": fallos,
        "temas": resultado_temas,
        "seguridad": resultado_seguridad,
        "firma_datos": firma_datos,
    }