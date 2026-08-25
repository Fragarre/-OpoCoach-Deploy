from __future__ import annotations

import hashlib
import json
import random
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
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

ORIGENES_VALIDOS = {"A1", "A2", "C1", "C2"}
FUENTES_VALIDAS = {"REAL", "IA"}
RESPUESTAS_VALIDAS = {"A", "B", "C", "D"}
SEGURIDADES_VALIDAS = {"SEGURO", "MENOS_SEGURO"}
DIAS_SIN_REPETICION = 3


_TABLAS_CONTENIDOS = (
    "convocatorias",
    "convocatoria_partes",
    "convocatoria_modelo_bloques",
    "banco_preguntas",
    "lote_preguntas",
    "normas",
    "banco_preguntas_temas",
    "temario_temas",
)


def _sql_postgres(sqlite_sql: str) -> str:
    """Adapta a PostgreSQL el subconjunto SQL de contenidos de este módulo."""
    if "FROM sqlite_master" in sqlite_sql:
        return """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'contenidos'
              AND table_name = 'convocatoria_modelo_bloques'
        """

    consulta = sqlite_sql
    for tabla in sorted(_TABLAS_CONTENIDOS, key=len, reverse=True):
        consulta = re.sub(
            rf"(?<![.\w]){re.escape(tabla)}\b",
            f"contenidos.{tabla}",
            consulta,
        )
    consulta = consulta.replace("?", "%s")
    consulta = consulta.replace("bpt.es_principal = 1", "bpt.es_principal = TRUE")
    return consulta


class _ConexionContenidosDual:
    def __init__(self, con, postgres: bool):
        self._con = con
        self._postgres = postgres

    def execute(self, sql: str, params=()):
        consulta = _sql_postgres(sql) if self._postgres else sql
        return self._con.execute(consulta, params)


@contextmanager
def _conectar_contenidos_dual():
    postgres = obtener_origen_contenidos() == ORIGEN_CONTENIDOS_POSTGRES
    fabrica = conectar_contenidos_postgres if postgres else conectar_contenidos_sqlite
    with fabrica() as con:
        yield _ConexionContenidosDual(con, postgres)


def _normalizar_origenes(origenes: list[str]) -> list[str]:
    resultado = sorted({str(x).strip().upper() for x in origenes if str(x).strip()})
    if not resultado:
        raise ValueError("Debe seleccionar al menos un origen de preguntas.")
    if set(resultado) - ORIGENES_VALIDOS:
        raise ValueError("Existe algún origen de preguntas no válido.")
    return resultado


def _normalizar_fuentes(fuentes: list[str] | None) -> set[str]:
    resultado = {
        str(x).strip().upper()
        for x in (fuentes or ["REAL", "IA"])
        if str(x).strip()
    }
    if not resultado or resultado - FUENTES_VALIDAS:
        raise ValueError("Debe seleccionar al menos una fuente válida: REAL y/o IA.")
    return resultado


def _condicion_fuente(fuentes: set[str]) -> str:
    if fuentes == {"IA"}:
        return "LOWER(TRIM(lp.tipo_fuente)) = 'ia_generada'"
    if fuentes == {"REAL"}:
        return "LOWER(TRIM(lp.tipo_fuente)) <> 'ia_generada'"
    return "1 = 1"


def _serializar_fila(fila) -> dict:
    resultado = dict(fila)
    for clave, valor in list(resultado.items()):
        if isinstance(valor, datetime):
            resultado[clave] = valor.isoformat()
        elif isinstance(valor, UUID):
            resultado[clave] = str(valor)
    return resultado


def obtener_disponibilidad(
    convocatoria_id: int,
    origenes: list[str],
    fuentes: list[str] | None,
) -> list[dict]:
    if not convocatoria_esta_activa(convocatoria_id):
        raise ValueError("La convocatoria no está activa.")

    origenes_n = _normalizar_origenes(origenes)
    fuentes_n = _normalizar_fuentes(fuentes)
    marcas = ", ".join("?" for _ in origenes_n)
    condicion = _condicion_fuente(fuentes_n)

    with _conectar_contenidos_dual() as con:
        filas = con.execute(
            f"""
            SELECT cp.id AS parte_id, cp.nombre AS parte, cp.orden AS parte_orden,
                   cp.numero_preguntas AS necesarias,
                   COUNT(DISTINCT CASE WHEN lp.id IS NOT NULL THEN bp.id END) AS disponibles
            FROM convocatoria_partes cp
            LEFT JOIN banco_preguntas bp
              ON bp.convocatoria_parte_id = cp.id
             AND bp.convocatoria_id = cp.convocatoria_id
             AND bp.estado = 'INCLUIDA'
            LEFT JOIN lote_preguntas lp
              ON lp.id = bp.pregunta_id
             AND (
                    lp.origen_oposicion IS NULL
                    OR TRIM(lp.origen_oposicion) = ''
                    OR UPPER(TRIM(lp.origen_oposicion)) IN ({marcas})
                 )
             AND ({condicion})
            WHERE cp.convocatoria_id = ?
            GROUP BY cp.id, cp.nombre, cp.orden, cp.numero_preguntas
            ORDER BY cp.orden
            """,
            (*origenes_n, convocatoria_id),
        ).fetchall()

    return [dict(x) for x in filas]


def _ultima_aparicion(
    convocatoria_id: int,
    user_id: UUID,
) -> dict[int, datetime]:
    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT sp.pregunta_id, MAX(s.fecha_generacion) AS ultima_fecha
                FROM public.simulacros s
                JOIN public.simulacro_preguntas sp ON sp.simulacro_id = s.id
                WHERE s.user_id = %s
                  AND s.convocatoria_id = %s
                  AND s.estado <> 'ANULADO'
                  AND sp.pregunta_id IS NOT NULL
                GROUP BY sp.pregunta_id
                """,
                (user_id, convocatoria_id),
            )
            filas = cur.fetchall()

    return {
        int(fila["pregunta_id"]): fila["ultima_fecha"]
        for fila in filas
        if fila["ultima_fecha"] is not None
    }


def _seleccionar(
    candidatas: list,
    cantidad: int,
    ultima: dict[int, datetime],
) -> list:
    limite = datetime.now().astimezone() - timedelta(days=DIAS_SIN_REPETICION)
    no_recientes, recientes = [], []

    for pregunta in candidatas:
        fecha = ultima.get(int(pregunta["pregunta_id"]))
        if fecha is not None and fecha.tzinfo is None:
            fecha = fecha.astimezone()
        (
            no_recientes
            if fecha is None or fecha <= limite
            else recientes
        ).append(pregunta)

    if len(no_recientes) >= cantidad:
        return random.sample(no_recientes, cantidad)

    random.shuffle(no_recientes)
    random.shuffle(recientes)
    recientes.sort(key=lambda p: ultima[int(p["pregunta_id"])])
    return no_recientes + recientes[: cantidad - len(no_recientes)]


MAX_PREGUNTAS_LIBRES_POR_NORMA = 2


def _tabla_modelo_examen_existe(con) -> bool:
    return con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'convocatoria_modelo_bloques'
        """
    ).fetchone() is not None


def _cargar_bloques_modelo_parte(con, convocatoria_parte_id: int) -> list:
    return con.execute(
        """
        SELECT
            cmb.id,
            cmb.convocatoria_parte_id,
            cmb.orden,
            cmb.tipo_bloque,
            cmb.norma_id,
            cmb.cantidad,
            n.nombre_canonico AS norma
        FROM convocatoria_modelo_bloques cmb
        LEFT JOIN normas n
          ON n.id = cmb.norma_id
        WHERE cmb.convocatoria_parte_id = ?
        ORDER BY cmb.orden, cmb.id
        """,
        (convocatoria_parte_id,),
    ).fetchall()


def _es_juridica_teorica(pregunta) -> bool:
    return (
        str(pregunta["tipo_clasificacion"] or "").strip().upper() == "JURIDICA"
        and str(pregunta["teorica_practica"] or "").strip().upper() == "TEORICA"
    )


def _seleccionar_preguntas_norma_modelo(
    candidatas_parte: list,
    norma_id: int,
    cantidad: int,
    preguntas_usadas: set[int],
    ultima_aparicion: dict[int, datetime],
    parte_nombre: str,
    norma_nombre: str,
) -> list:
    candidatas = [
        pregunta
        for pregunta in candidatas_parte
        if int(pregunta["pregunta_id"]) not in preguntas_usadas
        and _es_juridica_teorica(pregunta)
        and pregunta["norma_id_normalizada"] is not None
        and int(pregunta["norma_id_normalizada"]) == int(norma_id)
    ]

    if len(candidatas) < cantidad:
        raise ValueError(
            f"No hay suficientes preguntas para {parte_nombre} — {norma_nombre}. "
            f"Se necesitan {cantidad} y solo hay {len(candidatas)}."
        )

    return _seleccionar(candidatas, cantidad, ultima_aparicion)


def _seleccionar_preguntas_libres_modelo(
    candidatas_parte: list,
    cantidad_total: int,
    normas_preasignadas: set[int],
    preguntas_usadas: set[int],
    ultima_aparicion: dict[int, datetime],
    parte_nombre: str,
) -> list:
    if cantidad_total <= 0:
        return []

    por_norma: dict[int, list] = {}
    for pregunta in candidatas_parte:
        pregunta_id = int(pregunta["pregunta_id"])
        norma_id = pregunta["norma_id_normalizada"]
        if pregunta_id in preguntas_usadas:
            continue
        if not _es_juridica_teorica(pregunta):
            continue
        if norma_id is None:
            continue
        norma_id = int(norma_id)
        if norma_id in normas_preasignadas:
            continue
        por_norma.setdefault(norma_id, []).append(pregunta)

    capacidad = sum(
        min(MAX_PREGUNTAS_LIBRES_POR_NORMA, len(preguntas))
        for preguntas in por_norma.values()
    )
    if capacidad < cantidad_total:
        raise ValueError(
            f"No hay suficientes preguntas para los bloques LIBRE de "
            f"{parte_nombre}. Se necesitan {cantidad_total} y la capacidad "
            f"disponible, con máximo {MAX_PREGUNTAS_LIBRES_POR_NORMA} por "
            f"norma y excluyendo las normas preasignadas, es {capacidad}."
        )

    elegidas: list = []
    seleccionadas_por_norma = {norma_id: 0 for norma_id in por_norma}
    normas = list(por_norma)

    for _vuelta in range(MAX_PREGUNTAS_LIBRES_POR_NORMA):
        random.shuffle(normas)
        for norma_id in normas:
            if len(elegidas) >= cantidad_total:
                break
            if seleccionadas_por_norma[norma_id] >= MAX_PREGUNTAS_LIBRES_POR_NORMA:
                continue
            ya_elegidas = {int(p["pregunta_id"]) for p in elegidas}
            disponibles_norma = [
                p for p in por_norma[norma_id]
                if int(p["pregunta_id"]) not in ya_elegidas
            ]
            if not disponibles_norma:
                continue
            seleccion = _seleccionar(disponibles_norma, 1, ultima_aparicion)
            elegidas.extend(seleccion)
            seleccionadas_por_norma[norma_id] += 1
        if len(elegidas) >= cantidad_total:
            break

    if len(elegidas) != cantidad_total:
        raise RuntimeError(
            f"No se ha podido completar la selección LIBRE de {parte_nombre}."
        )

    random.shuffle(elegidas)
    return elegidas


def _planificar_cantidades_modelo(
    bloques: list,
    candidatas_parte: list,
    parte_nombre: str,
) -> dict[int, int]:
    cantidades = {int(b["id"]): int(b["cantidad"]) for b in bloques}
    bloques_norma_por_norma: dict[int, list] = {}
    disponibles_por_norma: dict[int, int] = {}

    for bloque in bloques:
        if str(bloque["tipo_bloque"]) != "NORMA":
            continue
        if bloque["norma_id"] is None:
            raise ValueError(
                f"El bloque {bloque['orden']} de {parte_nombre} es NORMA "
                "pero no tiene norma_id."
            )
        norma_id = int(bloque["norma_id"])
        bloques_norma_por_norma.setdefault(norma_id, []).append(bloque)

    for norma_id in bloques_norma_por_norma:
        disponibles_por_norma[norma_id] = sum(
            1
            for pregunta in candidatas_parte
            if _es_juridica_teorica(pregunta)
            and pregunta["norma_id_normalizada"] is not None
            and int(pregunta["norma_id_normalizada"]) == norma_id
        )

    deficit_total = 0
    for norma_id, bloques_norma in bloques_norma_por_norma.items():
        objetivo = sum(int(b["cantidad"]) for b in bloques_norma)
        disponibles = disponibles_por_norma[norma_id]
        if disponibles >= objetivo:
            continue
        deficit = objetivo - disponibles
        reducibles = [
            b for b in reversed(bloques_norma) if int(b["cantidad"]) > 1
        ]
        if deficit > len(reducibles):
            norma_nombre = str(bloques_norma[0]["norma"] or f"norma_id {norma_id}")
            minimo = objetivo - len(reducibles)
            raise ValueError(
                f"No hay suficientes preguntas para {parte_nombre} — "
                f"{norma_nombre}. El modelo prevé {objetivo}, el mínimo "
                f"admisible es {minimo} y solo hay {disponibles}."
            )
        for bloque in reducibles[:deficit]:
            cantidades[int(bloque["id"])] -= 1
            deficit_total += 1

    if deficit_total == 0:
        return cantidades

    bloques_libres = [b for b in bloques if str(b["tipo_bloque"]) == "LIBRE"]
    normas_preasignadas = set(bloques_norma_por_norma)
    por_norma_libre: dict[int, int] = {}
    for pregunta in candidatas_parte:
        if not _es_juridica_teorica(pregunta):
            continue
        norma_id = pregunta["norma_id_normalizada"]
        if norma_id is None:
            continue
        norma_id = int(norma_id)
        if norma_id in normas_preasignadas:
            continue
        por_norma_libre[norma_id] = por_norma_libre.get(norma_id, 0) + 1

    capacidad_libre = sum(
        min(MAX_PREGUNTAS_LIBRES_POR_NORMA, cantidad)
        for cantidad in por_norma_libre.values()
    )
    objetivo_libre = sum(cantidades[int(b["id"])] for b in bloques_libres)
    extra_libre_disponible = max(0, capacidad_libre - objetivo_libre)

    for bloque in bloques_libres:
        if deficit_total <= 0 or extra_libre_disponible <= 0:
            break
        cantidades[int(bloque["id"])] += 1
        deficit_total -= 1
        extra_libre_disponible -= 1

    if deficit_total <= 0:
        return cantidades

    usados_por_norma = {
        norma_id: sum(cantidades[int(b["id"])] for b in bloques_norma)
        for norma_id, bloques_norma in bloques_norma_por_norma.items()
    }
    receptores = [
        b for b in bloques
        if str(b["tipo_bloque"]) == "NORMA" and b["norma_id"] is not None
    ]
    random.shuffle(receptores)

    for bloque in receptores:
        if deficit_total <= 0:
            break
        norma_id = int(bloque["norma_id"])
        if usados_por_norma[norma_id] >= disponibles_por_norma[norma_id]:
            continue
        bloque_id = int(bloque["id"])
        if cantidades[bloque_id] >= int(bloque["cantidad"]) + 1:
            continue
        cantidades[bloque_id] += 1
        usados_por_norma[norma_id] += 1
        deficit_total -= 1

    if deficit_total > 0:
        raise ValueError(
            f"No se puede mantener el total de {parte_nombre} respetando "
            "el margen máximo de una pregunta por bloque del modelo."
        )
    return cantidades


def _seleccionar_parte_segun_modelo(
    parte,
    bloques: list,
    candidatas_parte: list,
    ultima_aparicion: dict[int, datetime],
    preguntas_usadas: set[int],
) -> list:
    nombre_parte = str(parte["nombre"])
    total_parte = int(parte["numero_preguntas"])

    suma_bloques = sum(int(b["cantidad"]) for b in bloques)
    if suma_bloques != total_parte:
        raise ValueError(
            f"El modelo de {nombre_parte} suma {suma_bloques} preguntas, "
            f"pero la parte tiene configuradas {total_parte}."
        )
    ordenes = [int(b["orden"]) for b in bloques]
    if ordenes != list(range(1, len(ordenes) + 1)):
        raise ValueError(
            f"El modelo de {nombre_parte} no tiene un orden consecutivo válido."
        )
    tipos_invalidos = [
        str(b["tipo_bloque"])
        for b in bloques
        if str(b["tipo_bloque"]) not in {"NORMA", "LIBRE"}
    ]
    if tipos_invalidos:
        raise ValueError(
            f"El modelo de {nombre_parte} contiene tipos de bloque no válidos."
        )

    cantidades = _planificar_cantidades_modelo(bloques, candidatas_parte, nombre_parte)
    normas_preasignadas = {
        int(b["norma_id"])
        for b in bloques
        if str(b["tipo_bloque"]) == "NORMA" and b["norma_id"] is not None
    }
    cantidad_libre = sum(
        cantidades[int(b["id"])]
        for b in bloques
        if str(b["tipo_bloque"]) == "LIBRE"
    )
    libres = _seleccionar_preguntas_libres_modelo(
        candidatas_parte,
        cantidad_libre,
        normas_preasignadas,
        preguntas_usadas,
        ultima_aparicion,
        nombre_parte,
    )
    indice_libre = 0
    resultado = []

    for bloque in bloques:
        tipo_bloque = str(bloque["tipo_bloque"])
        cantidad = cantidades[int(bloque["id"])]
        if tipo_bloque == "NORMA":
            norma_id = int(bloque["norma_id"])
            norma_nombre = str(bloque["norma"] or f"norma_id {norma_id}")
            elegidas = _seleccionar_preguntas_norma_modelo(
                candidatas_parte,
                norma_id,
                cantidad,
                preguntas_usadas,
                ultima_aparicion,
                nombre_parte,
                norma_nombre,
            )
        else:
            fin = indice_libre + cantidad
            elegidas = libres[indice_libre:fin]
            indice_libre = fin
            if len(elegidas) != cantidad:
                raise RuntimeError(
                    f"El bloque LIBRE {bloque['orden']} de {nombre_parte} "
                    "no ha podido completarse."
                )

        for pregunta in elegidas:
            pregunta_id = int(pregunta["pregunta_id"])
            if pregunta_id in preguntas_usadas:
                raise RuntimeError(
                    f"La pregunta {pregunta_id} se ha seleccionado dos veces "
                    "en el mismo simulacro."
                )
            preguntas_usadas.add(pregunta_id)
            resultado.append((parte, pregunta))

    if indice_libre != len(libres):
        raise RuntimeError(
            f"La distribución de bloques LIBRE de {nombre_parte} es incoherente."
        )
    if len(resultado) != total_parte:
        raise RuntimeError(
            f"El modelo de {nombre_parte} ha generado {len(resultado)} "
            f"preguntas en lugar de {total_parte}."
        )
    return resultado


def crear_simulacro(
    convocatoria_id: int,
    origenes: list[str],
    fuentes: list[str] | None,
    user_id: UUID,
) -> int:
    if not convocatoria_esta_activa(convocatoria_id):
        raise ValueError("La convocatoria no está activa.")

    origenes_n = _normalizar_origenes(origenes)
    fuentes_n = _normalizar_fuentes(fuentes)
    marcas = ", ".join("?" for _ in origenes_n)
    condicion = _condicion_fuente(fuentes_n)

    with _conectar_contenidos_dual() as con:
        convocatoria = con.execute(
            """
            SELECT id, puesto, numero, anio, codigo, numero_preguntas,
                   valoracion_test_acierto, valoracion_test_fallo,
                   valoracion_test_no_contesta, formula_nota, factor_escala_nota
            FROM convocatorias
            WHERE id = ?
            """,
            (convocatoria_id,),
        ).fetchone()

        if convocatoria is None:
            raise ValueError("La convocatoria no existe.")

        partes = con.execute(
            """
            SELECT id, nombre, numero_preguntas, orden
            FROM convocatoria_partes
            WHERE convocatoria_id = ?
            ORDER BY orden
            """,
            (convocatoria_id,),
        ).fetchall()

        if not partes:
            raise ValueError("La convocatoria no tiene partes configuradas.")

        if sum(p["numero_preguntas"] for p in partes) != convocatoria["numero_preguntas"]:
            raise ValueError(
                "La suma de preguntas de las partes no coincide con el total configurado."
            )

        if not _tabla_modelo_examen_existe(con):
            raise RuntimeError(
                "La base no contiene convocatoria_modelo_bloques. "
                "Configure el modelo de examen desde OpoCoach-Mantenimiento."
            )

        bloques_por_parte = {
            int(parte["id"]): _cargar_bloques_modelo_parte(
                con, int(parte["id"])
            )
            for parte in partes
        }

        candidatas = con.execute(
            f"""
            SELECT DISTINCT
                bp.id AS banco_pregunta_id,
                bp.pregunta_id,
                bp.convocatoria_parte_id,
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
                tt.tipo_contenido AS tema_tipo_contenido
            FROM banco_preguntas bp
            JOIN convocatoria_partes cp
              ON cp.id = bp.convocatoria_parte_id
             AND cp.convocatoria_id = bp.convocatoria_id
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
              AND (
                    lp.origen_oposicion IS NULL
                    OR TRIM(lp.origen_oposicion) = ''
                    OR UPPER(TRIM(lp.origen_oposicion)) IN ({marcas})
                  )
              AND ({condicion})
            """,
            (convocatoria_id, *origenes_n),
        ).fetchall()

    ultima = _ultima_aparicion(convocatoria_id, user_id)
    seleccionadas = []
    usadas: set[int] = set()

    for parte in partes:
        parte_id = int(parte["id"])
        disponibles = [
            pregunta
            for pregunta in candidatas
            if int(pregunta["convocatoria_parte_id"]) == parte_id
            and int(pregunta["pregunta_id"]) not in usadas
        ]
        cantidad = int(parte["numero_preguntas"])

        if len(disponibles) < cantidad:
            raise ValueError(
                f'No hay suficientes preguntas para {parte["nombre"]}. '
                f"Se necesitan {cantidad} y solo hay {len(disponibles)}."
            )

        bloques = bloques_por_parte[parte_id]
        if bloques:
            seleccionadas.extend(
                _seleccionar_parte_segun_modelo(
                    parte=parte,
                    bloques=bloques,
                    candidatas_parte=disponibles,
                    ultima_aparicion=ultima,
                    preguntas_usadas=usadas,
                )
            )
            continue

        for pregunta in _seleccionar(disponibles, cantidad, ultima):
            pregunta_id = int(pregunta["pregunta_id"])
            if pregunta_id in usadas:
                raise RuntimeError(
                    f"La pregunta {pregunta_id} se ha seleccionado dos veces "
                    "en el mismo simulacro."
                )
            usadas.add(pregunta_id)
            seleccionadas.append((parte, pregunta))

    if len(seleccionadas) != int(convocatoria["numero_preguntas"]):
        raise RuntimeError(
            "El número de preguntas seleccionadas no coincide con el total "
            "configurado en la convocatoria."
        )

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT COALESCE(MAX(numero), 0) + 1 AS siguiente
                FROM public.simulacros
                WHERE user_id = %s
                  AND convocatoria_id = %s
                  AND tipo_prueba = 'SIMULACRO'
                """,
                (user_id, convocatoria_id),
            )
            numero = int(cur.fetchone()["siguiente"])

            cur.execute(
                """
                INSERT INTO public.simulacros (
                    user_id,
                    convocatoria_id,
                    numero,
                    total_preguntas,
                    tipo_prueba,
                    es_prueba_gratuita,
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
                    %s, %s, %s, %s, 'SIMULACRO',
                    FALSE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    user_id,
                    convocatoria_id,
                    numero,
                    convocatoria["numero_preguntas"],
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
            simulacro_id = int(cur.fetchone()["id"])

            for orden, (parte, pregunta) in enumerate(seleccionadas, 1):
                cur.execute(
                    """
                    INSERT INTO public.simulacro_preguntas (
                        simulacro_id,
                        orden,
                        pregunta_id,
                        banco_pregunta_id,
                        parte_id,
                        parte_nombre,
                        parte_orden
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        simulacro_id,
                        orden,
                        pregunta["pregunta_id"],
                        pregunta["banco_pregunta_id"],
                        parte["id"],
                        parte["nombre"],
                        parte["orden"],
                    ),
                )
                simulacro_pregunta_id = int(cur.fetchone()["id"])

                tema = {
                    "tema_id_original": pregunta["tema_id"],
                    "parte": pregunta["tema_parte"],
                    "numero_tema": pregunta["numero_tema"],
                    "titulo": pregunta["tema_titulo"],
                    "tipo_contenido": pregunta["tema_tipo_contenido"],
                    "es_principal": 1,
                }

                cur.execute(
                    """
                    INSERT INTO public.simulacro_snapshot (
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
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, NULL
                    )
                    """,
                    (
                        simulacro_pregunta_id,
                        pregunta["enunciado"],
                        pregunta["opcion_a"],
                        pregunta["opcion_b"],
                        pregunta["opcion_c"],
                        pregunta["opcion_d"],
                        pregunta["respuesta_correcta"],
                        pregunta["tipo_clasificacion"],
                        pregunta["tipo_norma"],
                        pregunta["nombre_norma"],
                        pregunta["articulo"],
                        pregunta["tema_no_juridico"],
                        pregunta["origen_oposicion"],
                        pregunta["tipo_fuente"],
                        pregunta["importacion_fichero_id"],
                        pregunta["pagina_origen"],
                        pregunta["norma_id_normalizada"],
                        pregunta["articulo_normalizado"],
                        pregunta["teorica_practica"],
                        pregunta["tipo_norma_normalizado"],
                        pregunta["nombre_norma_normalizado"],
                        pregunta["tipo_vinculacion"],
                        pregunta["banco_estado"],
                        pregunta["metodo_vinculacion"],
                        pregunta["motivo_revision"],
                        Jsonb(tema),
                    ),
                )

        con.commit()

    return simulacro_id


def obtener_simulacro(simulacro_id: int, user_id: UUID) -> dict | None:

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    convocatoria_id,
                    numero,
                    fecha_generacion,
                    total_preguntas,
                    estado,
                    tipo_prueba,
                    es_prueba_gratuita,
                    convocatoria_codigo,
                    convocatoria_puesto,
                    convocatoria_numero,
                    convocatoria_anio
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )
            fila = cur.fetchone()

    return _serializar_fila(fila) if fila else None


def obtener_preguntas_para_realizar(
    simulacro_id: int,
    user_id: UUID,
) -> list[dict]:
    """No expone respuesta_correcta: endpoint apto para el futuro frontend."""

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    sp.id AS simulacro_pregunta_id,
                    sp.orden,
                    sp.parte_nombre,
                    sp.respuesta_usuario,
                    sp.seguridad_usuario,
                    ss.enunciado,
                    ss.opcion_a,
                    ss.opcion_b,
                    ss.opcion_c,
                    ss.opcion_d
                FROM public.simulacro_preguntas sp
                JOIN public.simulacro_snapshot ss
                  ON ss.simulacro_pregunta_id = sp.id
                JOIN public.simulacros s
                  ON s.id = sp.simulacro_id
                WHERE sp.simulacro_id = %s
                  AND s.user_id = %s
                ORDER BY sp.orden
                """,
                (simulacro_id, user_id),
            )
            filas = cur.fetchall()

    return [_serializar_fila(fila) for fila in filas]


def guardar_respuestas(
    simulacro_id: int,
    respuestas: list[dict],
    user_id: UUID,
) -> None:

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, estado
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                FOR UPDATE
                """,
                (simulacro_id, user_id),
            )
            simulacro = cur.fetchone()

            if simulacro is None:
                raise ValueError("El simulacro no existe.")

            cur.execute(
                """
                SELECT id
                FROM public.simulacro_preguntas
                WHERE simulacro_id = %s
                """,
                (simulacro_id,),
            )
            ids_validos = {int(fila["id"]) for fila in cur.fetchall()}

            vistos: set[int] = set()

            for item in respuestas:
                simulacro_pregunta_id = int(item["simulacro_pregunta_id"])

                if simulacro_pregunta_id in vistos:
                    raise ValueError(
                        f"La pregunta {simulacro_pregunta_id} aparece repetida en el envío."
                    )
                vistos.add(simulacro_pregunta_id)

                if simulacro_pregunta_id not in ids_validos:
                    raise ValueError(
                        f"La pregunta {simulacro_pregunta_id} no pertenece al simulacro."
                    )

                respuesta = item.get("respuesta")
                if respuesta is not None:
                    respuesta = str(respuesta).strip().upper() or None

                if respuesta is not None and respuesta not in RESPUESTAS_VALIDAS:
                    raise ValueError("La respuesta debe ser A, B, C, D o null.")

                seguridad = item.get("seguridad")
                if seguridad is not None:
                    seguridad = (
                        str(seguridad).strip().upper().replace(" ", "_") or None
                    )

                if seguridad is not None and seguridad not in SEGURIDADES_VALIDAS:
                    raise ValueError("Seguridad no válida.")

                if respuesta is None:
                    seguridad = None

                cur.execute(
                    """
                    UPDATE public.simulacro_preguntas
                    SET respuesta_usuario = %s,
                        seguridad_usuario = %s,
                        updated_at = now()
                    WHERE id = %s
                      AND simulacro_id = %s
                    """,
                    (
                        respuesta,
                        seguridad,
                        simulacro_pregunta_id,
                        simulacro_id,
                    ),
                )

            cur.execute(
                """
                UPDATE public.simulacros
                SET updated_at = now()
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )

        con.commit()



def obtener_tiempo_correccion(
    simulacro_id: int,
    user_id: UUID,
) -> int:
    """Devuelve el tiempo acumulado de corrección, en segundos."""
    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT COALESCE(tiempo_correccion_segundos, 0)
                    AS tiempo_correccion_segundos
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )
            fila = cur.fetchone()

    if fila is None:
        raise ValueError("El simulacro no existe.")

    return max(0, int(fila["tiempo_correccion_segundos"] or 0))


def finalizar_simulacro(
    simulacro_id: int,
    user_id: UUID,
    segundos_adicionales: int = 0,
) -> dict:
    """Cierra y califica usando la configuración congelada del simulacro."""

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    estado,
                    tipo_prueba,
                    total_preguntas,
                    convocatoria_numero_preguntas,
                    valoracion_test_acierto,
                    valoracion_test_fallo,
                    valoracion_test_no_contesta,
                    factor_escala_nota,
                    COALESCE(tiempo_correccion_segundos, 0)
                        AS tiempo_correccion_segundos
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                FOR UPDATE
                """,
                (simulacro_id, user_id),
            )
            simulacro = cur.fetchone()

            if simulacro is None:
                raise ValueError("El simulacro no existe.")

            cur.execute(
                """
                SELECT sp.respuesta_usuario, ss.respuesta_correcta
                FROM public.simulacro_preguntas sp
                JOIN public.simulacro_snapshot ss
                  ON ss.simulacro_pregunta_id = sp.id
                WHERE sp.simulacro_id = %s
                """,
                (simulacro_id,),
            )
            filas = cur.fetchall()

            if not filas:
                raise ValueError("El simulacro no contiene preguntas.")

            aciertos = 0
            fallos = 0
            no_contestadas = 0

            for fila in filas:
                respuesta = (fila["respuesta_usuario"] or "").strip().upper()
                correcta = (fila["respuesta_correcta"] or "").strip().upper()

                if not respuesta:
                    no_contestadas += 1
                elif respuesta == correcta:
                    aciertos += 1
                else:
                    fallos += 1

            valor_acierto = float(
                simulacro["valoracion_test_acierto"]
                if simulacro["valoracion_test_acierto"] is not None
                else 1.0
            )
            valor_fallo = float(
                simulacro["valoracion_test_fallo"]
                if simulacro["valoracion_test_fallo"] is not None
                else 0.0
            )
            valor_no_contesta = float(
                simulacro["valoracion_test_no_contesta"]
                if simulacro["valoracion_test_no_contesta"] is not None
                else 0.0
            )
            escala = float(
                simulacro["factor_escala_nota"]
                if simulacro["factor_escala_nota"] is not None
                else 10.0
            )
            denominador = int(
                simulacro["total_preguntas"]
                if simulacro["tipo_prueba"] == "TEST"
                else (
                    simulacro["convocatoria_numero_preguntas"]
                    or simulacro["total_preguntas"]
                    or len(filas)
                )
            )

            puntos = (
                aciertos * valor_acierto
                + fallos * valor_fallo
                + no_contestadas * valor_no_contesta
            )
            nota = (puntos / denominador) * escala if denominador else 0.0

            segundos = max(0, int(segundos_adicionales))
            tiempo_total = max(
                0,
                int(simulacro["tiempo_correccion_segundos"] or 0),
            ) + segundos

            cur.execute(
                """
                UPDATE public.simulacros
                SET estado = 'FINALIZADO',
                    finalizado_at = COALESCE(finalizado_at, now()),
                    tiempo_correccion_segundos = %s,
                    updated_at = now()
                WHERE id = %s
                  AND user_id = %s
                """,
                (tiempo_total, simulacro_id, user_id),
            )

        con.commit()

    return {
        "simulacro_id": simulacro_id,
        "total": len(filas),
        "contestadas": aciertos + fallos,
        "aciertos": aciertos,
        "fallos": fallos,
        "no_contestadas": no_contestadas,
        "puntos": round(puntos, 4),
        "nota": round(nota, 2),
        "tiempo_correccion_segundos": tiempo_total,
    }


def obtener_correccion(simulacro_id: int, user_id: UUID) -> list[dict]:
    """Expone la solución solo si el simulacro del usuario está finalizado."""

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, estado
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )
            simulacro = cur.fetchone()

            if simulacro is None:
                raise ValueError("El simulacro no existe.")

            if simulacro["estado"] != "FINALIZADO":
                raise ValueError(
                    "Debe finalizar el simulacro antes de consultar la corrección."
                )

            cur.execute(
                """
                SELECT
                    sp.id AS simulacro_pregunta_id,
                    sp.orden,
                    sp.parte_nombre,
                    sp.respuesta_usuario,
                    sp.seguridad_usuario,
                    ss.enunciado,
                    ss.opcion_a,
                    ss.opcion_b,
                    ss.opcion_c,
                    ss.opcion_d,
                    ss.respuesta_correcta,
                    CASE
                        WHEN sp.respuesta_usuario IS NULL
                             OR btrim(sp.respuesta_usuario) = ''
                            THEN 'NO_CONTESTADA'
                        WHEN upper(btrim(sp.respuesta_usuario))
                             = upper(btrim(ss.respuesta_correcta))
                            THEN 'ACIERTO'
                        ELSE 'FALLO'
                    END AS resultado
                FROM public.simulacro_preguntas sp
                JOIN public.simulacro_snapshot ss
                  ON ss.simulacro_pregunta_id = sp.id
                JOIN public.simulacros s
                  ON s.id = sp.simulacro_id
                WHERE sp.simulacro_id = %s
                  AND s.user_id = %s
                ORDER BY sp.orden
                """,
                (simulacro_id, user_id),
            )
            filas = cur.fetchall()

    return [_serializar_fila(fila) for fila in filas]



def listar_simulacros(
    user_id: UUID,
    convocatoria_id: int | None = None,
    tipo_prueba: str = "SIMULACRO",
) -> list[dict]:
    tipo = str(tipo_prueba).strip().upper()
    if tipo not in {"SIMULACRO", "TEST"}:
        raise ValueError("tipo_prueba debe ser SIMULACRO o TEST.")

    parametros: list[object] = [user_id, tipo]
    filtro_convocatoria = ""

    if convocatoria_id is not None:
        filtro_convocatoria = "AND s.convocatoria_id = %s"
        parametros.append(convocatoria_id)

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT
                    s.id,
                    s.convocatoria_id,
                    s.numero,
                    s.fecha_generacion,
                    s.total_preguntas,
                    s.estado,
                    s.tipo_prueba,
                    s.es_prueba_gratuita,
                    s.convocatoria_codigo,
                    COUNT(sp.id) FILTER (
                        WHERE sp.respuesta_usuario IS NOT NULL
                    )::int AS contestadas
                FROM public.simulacros s
                LEFT JOIN public.simulacro_preguntas sp
                  ON sp.simulacro_id = s.id
                WHERE s.user_id = %s
                  AND s.tipo_prueba = %s
                  AND s.estado <> 'ANULADO'
                  {filtro_convocatoria}
                GROUP BY s.id
                ORDER BY s.fecha_generacion DESC, s.id DESC
                """,
                tuple(parametros),
            )
            filas = cur.fetchall()

    return [_serializar_fila(fila) for fila in filas]


def eliminar_simulacro(simulacro_id: int, user_id: UUID) -> bool:
    with conectar_postgres() as con:
        with con.cursor() as cur:
            cur.execute(
                """
                DELETE FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )
            eliminado = cur.rowcount == 1
        con.commit()

    return eliminado


def obtener_resultado_guardado(
    simulacro_id: int,
    user_id: UUID,
) -> dict:
    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    id,
                    estado,
                    tipo_prueba,
                    total_preguntas,
                    convocatoria_numero_preguntas,
                    valoracion_test_acierto,
                    valoracion_test_fallo,
                    valoracion_test_no_contesta,
                    factor_escala_nota,
                    COALESCE(tiempo_correccion_segundos, 0)
                        AS tiempo_correccion_segundos
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )
            simulacro = cur.fetchone()

            if simulacro is None:
                raise ValueError("El simulacro no existe.")

            if simulacro["estado"] != "FINALIZADO":
                raise ValueError("El simulacro todavía no está finalizado.")

            cur.execute(
                """
                SELECT sp.respuesta_usuario, ss.respuesta_correcta
                FROM public.simulacro_preguntas sp
                JOIN public.simulacro_snapshot ss
                  ON ss.simulacro_pregunta_id = sp.id
                WHERE sp.simulacro_id = %s
                """,
                (simulacro_id,),
            )
            filas = cur.fetchall()

    aciertos = 0
    fallos = 0
    no_contestadas = 0

    for fila in filas:
        respuesta = (fila["respuesta_usuario"] or "").strip().upper()
        correcta = (fila["respuesta_correcta"] or "").strip().upper()

        if not respuesta:
            no_contestadas += 1
        elif respuesta == correcta:
            aciertos += 1
        else:
            fallos += 1

    valor_acierto = float(
        simulacro["valoracion_test_acierto"]
        if simulacro["valoracion_test_acierto"] is not None
        else 1.0
    )
    valor_fallo = float(
        simulacro["valoracion_test_fallo"]
        if simulacro["valoracion_test_fallo"] is not None
        else 0.0
    )
    valor_no_contesta = float(
        simulacro["valoracion_test_no_contesta"]
        if simulacro["valoracion_test_no_contesta"] is not None
        else 0.0
    )
    escala = float(
        simulacro["factor_escala_nota"]
        if simulacro["factor_escala_nota"] is not None
        else 10.0
    )
    denominador = int(
        simulacro["total_preguntas"]
        if simulacro["tipo_prueba"] == "TEST"
        else (
            simulacro["convocatoria_numero_preguntas"]
            or simulacro["total_preguntas"]
            or len(filas)
        )
    )

    puntos = (
        aciertos * valor_acierto
        + fallos * valor_fallo
        + no_contestadas * valor_no_contesta
    )
    nota = (puntos / denominador) * escala if denominador else 0.0

    return {
        "simulacro_id": simulacro_id,
        "total": len(filas),
        "contestadas": aciertos + fallos,
        "aciertos": aciertos,
        "fallos": fallos,
        "no_contestadas": no_contestadas,
        "puntos": round(puntos, 4),
        "nota": round(nota, 2),
        "tiempo_correccion_segundos": max(
            0,
            int(simulacro["tiempo_correccion_segundos"] or 0),
        ),
    }


def obtener_resultado_para_analisis(
    simulacro_id: int,
    user_id: UUID,
) -> dict:
    """
    Devuelve el resultado de la prueba abierta junto con los valores de
    puntuación que necesita el análisis IA.

    No modifica datos.
    """
    resultado = obtener_resultado_guardado(simulacro_id, user_id)

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    convocatoria_id,
                    valoracion_test_acierto,
                    valoracion_test_fallo,
                    valoracion_test_no_contesta
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )
            simulacro = cur.fetchone()

    if simulacro is None:
        raise ValueError("El simulacro no existe.")

    resultado["convocatoria_id"] = int(simulacro["convocatoria_id"])
    resultado["valor_acierto"] = float(
        simulacro["valoracion_test_acierto"]
        if simulacro["valoracion_test_acierto"] is not None
        else 1.0
    )
    resultado["valor_fallo"] = float(
        simulacro["valoracion_test_fallo"]
        if simulacro["valoracion_test_fallo"] is not None
        else 0.0
    )
    resultado["valor_no_contesta"] = float(
        simulacro["valoracion_test_no_contesta"]
        if simulacro["valoracion_test_no_contesta"] is not None
        else 0.0
    )

    return resultado

def obtener_resultado_acumulado(
    simulacro_id: int,
    user_id: UUID,
    solo_prueba_gratuita: bool = False,
) -> dict:
    """
    Calcula el rendimiento acumulado de las pruebas del mismo tipo y
    convocatoria que la prueba indicada, usando únicamente datos del usuario
    autenticado almacenados en PostgreSQL.

    Reproduce el criterio de la versión Streamlit: una prueba entra en el
    acumulado cuando conserva al menos una respuesta o un nivel de seguridad.
    """
    etiquetas_seguridad = {
        "SEGURO": "Seguro",
        "MENOS_SEGURO": "Menos seguro",
    }

    with conectar_postgres() as con:
        with con.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT convocatoria_id, tipo_prueba, es_prueba_gratuita
                FROM public.simulacros
                WHERE id = %s
                  AND user_id = %s
                """,
                (simulacro_id, user_id),
            )
            referencia = cur.fetchone()

            if referencia is None:
                raise ValueError("El simulacro no existe.")

            tipo_prueba = str(referencia["tipo_prueba"]).strip().upper()
            if tipo_prueba not in {"SIMULACRO", "TEST"}:
                raise ValueError("El tipo de prueba acumulada no es válido.")

            convocatoria_id = int(referencia["convocatoria_id"])

            if solo_prueba_gratuita and not bool(referencia["es_prueba_gratuita"]):
                raise ValueError(
                    "El histórico de suscripción ya no está disponible."
                )

            filtro_gratuita = (
                "AND s.es_prueba_gratuita = true"
                if solo_prueba_gratuita
                else ""
            )

            cur.execute(
                f"""
                SELECT
                    s.id,
                    s.numero,
                    s.fecha_generacion,
                    s.valoracion_test_acierto,
                    s.valoracion_test_fallo,
                    s.valoracion_test_no_contesta
                FROM public.simulacros s
                WHERE s.user_id = %s
                  AND s.convocatoria_id = %s
                  AND s.tipo_prueba = %s
                  {filtro_gratuita}
                  AND EXISTS (
                        SELECT 1
                        FROM public.simulacro_preguntas sp
                        WHERE sp.simulacro_id = s.id
                          AND (
                              sp.respuesta_usuario IS NOT NULL
                              OR sp.seguridad_usuario IS NOT NULL
                          )
                  )
                ORDER BY s.id
                """,
                (user_id, convocatoria_id, tipo_prueba),
            )
            simulacros = cur.fetchall()

            if not simulacros:
                return {
                    "convocatoria_id": convocatoria_id,
                    "tipo_prueba": tipo_prueba,
                    "simulacros": 0,
                    "simulacros_ids": [],
                    "preguntas": 0,
                    "contestadas": 0,
                    "no_contestadas": 0,
                    "aciertos": 0,
                    "fallos": 0,
                    "temas": [],
                    "normas": [],
                    "seguridad": [],
                    "firma_datos": hashlib.sha256(b"").hexdigest(),
                }

            simulacros_ids = [int(fila["id"]) for fila in simulacros]

            cur.execute(
                """
                SELECT
                    s.id AS simulacro_id,
                    s.numero AS simulacro_numero,
                    sp.orden,
                    sp.respuesta_usuario,
                    sp.seguridad_usuario,
                    ss.respuesta_correcta,
                    ss.tipo_clasificacion,
                    ss.nombre_norma,
                    ss.nombre_norma_normalizado,
                    ss.temas_json
                FROM public.simulacros s
                JOIN public.simulacro_preguntas sp
                  ON sp.simulacro_id = s.id
                JOIN public.simulacro_snapshot ss
                  ON ss.simulacro_pregunta_id = sp.id
                WHERE s.user_id = %s
                  AND s.convocatoria_id = %s
                  AND s.tipo_prueba = %s
                  AND s.id = ANY(%s)
                ORDER BY s.id, sp.orden
                """,
                (user_id, convocatoria_id, tipo_prueba, simulacros_ids),
            )
            preguntas = cur.fetchall()

    total = len(preguntas)
    aciertos = 0
    fallos = 0
    no_contestadas = 0

    estadisticas_temas: dict[str, dict] = {}
    estadisticas_normas: dict[str, dict] = {}
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

        if respuesta_correcta not in RESPUESTAS_VALIDAS:
            raise ValueError(
                "Las pruebas acumuladas contienen alguna pregunta "
                "sin una respuesta correcta válida."
            )

        tema = pregunta["temas_json"]
        if isinstance(tema, str):
            try:
                tema = json.loads(tema)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Las pruebas acumuladas contienen un tema congelado no válido."
                ) from exc

        if not isinstance(tema, dict):
            raise ValueError(
                "Las pruebas acumuladas contienen alguna pregunta sin tema congelado."
            )

        parte = tema.get("parte")
        numero_tema = tema.get("numero_tema")
        titulo = tema.get("titulo")

        if parte is None or numero_tema is None or not titulo:
            raise ValueError(
                "Las pruebas acumuladas contienen un tema congelado incompleto."
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
                "fallos_seguro": 0,
            }

        estadistica_tema = estadisticas_temas[clave_tema]
        estadistica_tema["preguntas"] += 1

        tipo_clasificacion = str(
            pregunta["tipo_clasificacion"] or ""
        ).strip().upper()

        if tipo_clasificacion == "INFORMATICA":
            nombre_norma = "Informática"
        else:
            nombre_norma = str(
                pregunta["nombre_norma_normalizado"]
                or pregunta["nombre_norma"]
                or "Sin norma identificada"
            ).strip()
            if not nombre_norma:
                nombre_norma = "Sin norma identificada"

        clave_norma = nombre_norma.casefold()

        if clave_norma not in estadisticas_normas:
            estadisticas_normas[clave_norma] = {
                "norma": nombre_norma,
                "preguntas": 0,
                "contestadas": 0,
                "no_contestadas": 0,
                "aciertos": 0,
                "fallos": 0,
                "fallos_seguro": 0,
            }

        estadistica_norma = estadisticas_normas[clave_norma]
        estadistica_norma["preguntas"] += 1

        firma_partes.append(
            "|".join(
                [
                    str(pregunta["simulacro_id"]),
                    str(pregunta["orden"]),
                    str(respuesta_usuario),
                    str(seguridad_usuario),
                    str(respuesta_correcta),
                    clave_tema,
                    clave_norma,
                ]
            )
        )

        if respuesta_usuario is None:
            no_contestadas += 1
            estadistica_tema["no_contestadas"] += 1
            estadistica_norma["no_contestadas"] += 1
            continue

        if respuesta_usuario not in RESPUESTAS_VALIDAS:
            raise ValueError(
                "Existe alguna respuesta acumulada del usuario no válida."
            )

        if (
            seguridad_usuario is not None
            and seguridad_usuario not in estadisticas_seguridad
        ):
            raise ValueError(
                "Existe alguna pregunta acumulada con un nivel "
                "de seguridad no válido."
            )

        estadistica_tema["contestadas"] += 1
        estadistica_norma["contestadas"] += 1

        estadistica_seguridad = estadisticas_seguridad.get(seguridad_usuario)
        if estadistica_seguridad is not None:
            estadistica_seguridad["contestadas"] += 1

        if respuesta_usuario == respuesta_correcta:
            aciertos += 1
            estadistica_tema["aciertos"] += 1
            estadistica_norma["aciertos"] += 1
            if estadistica_seguridad is not None:
                estadistica_seguridad["aciertos"] += 1
        else:
            fallos += 1
            estadistica_tema["fallos"] += 1
            estadistica_norma["fallos"] += 1
            if estadistica_seguridad is not None:
                estadistica_seguridad["fallos"] += 1

            if seguridad_usuario == "SEGURO":
                estadistica_tema["fallos_seguro"] += 1
                estadistica_norma["fallos_seguro"] += 1

    contestadas = aciertos + fallos

    resultado_temas = []
    for estadistica in estadisticas_temas.values():
        preguntas_tema = estadistica["preguntas"]
        contestadas_tema = estadistica["contestadas"]
        estadistica["porcentaje_convocatoria"] = (
            preguntas_tema / total * 100 if total else 0.0
        )
        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / preguntas_tema * 100
            if preguntas_tema else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / preguntas_tema * 100
            if preguntas_tema else 0.0
        )
        estadistica["porcentaje_no_contestadas"] = (
            estadistica["no_contestadas"] / preguntas_tema * 100
            if preguntas_tema else 0.0
        )
        estadistica["porcentaje_aciertos_contestadas"] = (
            estadistica["aciertos"] / contestadas_tema * 100
            if contestadas_tema else 0.0
        )
        resultado_temas.append(estadistica)

    resultado_temas.sort(
        key=lambda item: (
            -item["porcentaje_convocatoria"],
            item["parte"],
            item["numero_tema"],
            item["titulo"],
        )
    )

    resultado_normas = []
    for estadistica in estadisticas_normas.values():
        preguntas_norma = estadistica["preguntas"]
        contestadas_norma = estadistica["contestadas"]
        estadistica["porcentaje_convocatoria"] = (
            preguntas_norma / total * 100 if total else 0.0
        )
        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / preguntas_norma * 100
            if preguntas_norma else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / preguntas_norma * 100
            if preguntas_norma else 0.0
        )
        estadistica["porcentaje_no_contestadas"] = (
            estadistica["no_contestadas"] / preguntas_norma * 100
            if preguntas_norma else 0.0
        )
        estadistica["porcentaje_aciertos_contestadas"] = (
            estadistica["aciertos"] / contestadas_norma * 100
            if contestadas_norma else 0.0
        )
        resultado_normas.append(estadistica)

    resultado_normas.sort(
        key=lambda item: (
            -item["porcentaje_convocatoria"],
            item["norma"].casefold(),
        )
    )

    resultado_seguridad = []
    for estadistica in estadisticas_seguridad.values():
        contestadas_seguridad = estadistica["contestadas"]
        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / contestadas_seguridad * 100
            if contestadas_seguridad else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / contestadas_seguridad * 100
            if contestadas_seguridad else 0.0
        )
        if contestadas_seguridad:
            resultado_seguridad.append(estadistica)

    firma_datos = hashlib.sha256(
        "\n".join(firma_partes).encode("utf-8")
    ).hexdigest()

    return {
        "convocatoria_id": convocatoria_id,
        "tipo_prueba": tipo_prueba,
        "simulacros": len(simulacros),
        "simulacros_ids": simulacros_ids,
        "preguntas": total,
        "contestadas": contestadas,
        "no_contestadas": no_contestadas,
        "aciertos": aciertos,
        "fallos": fallos,
        "temas": resultado_temas,
        "normas": resultado_normas,
        "seguridad": resultado_seguridad,
        "firma_datos": firma_datos,
    }

