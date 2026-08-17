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
from datetime import datetime, timedelta

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
    fuentes_seleccionadas: list[str] | None = None,
) -> list[sqlite3.Row]:
    """
    Cuenta las preguntas disponibles por cada parte configurada
    de la convocatoria para los orígenes seleccionados.

    La pertenencia a una parte se obtiene exclusivamente de
    banco_preguntas.convocatoria_parte_id.
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

    fuentes = {str(x).strip().upper() for x in (fuentes_seleccionadas or ["REAL", "IA"]) if str(x).strip()}
    if not fuentes or fuentes - {"REAL", "IA"}:
        raise ValueError("Debe seleccionar al menos una fuente válida: REAL y/o IA.")
    condicion_fuente = (
        "LOWER(TRIM(lp.tipo_fuente)) = 'ia_generada'"
        if fuentes == {"IA"}
        else "LOWER(TRIM(lp.tipo_fuente)) <> 'ia_generada'"
        if fuentes == {"REAL"}
        else "1 = 1"
    )

    with conectar() as con:
        return con.execute(
            f"""
            SELECT
                cp.id AS parte_id,
                cp.nombre AS parte,
                cp.orden AS parte_orden,
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
                    OR UPPER(TRIM(lp.origen_oposicion))
                        IN ({marcadores_origen})
               )
               AND ({condicion_fuente})

            WHERE cp.convocatoria_id = ?

            GROUP BY
                cp.id,
                cp.nombre,
                cp.orden

            ORDER BY cp.orden
            """,
            (
                *origenes,
                convocatoria_id,
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



DIAS_SIN_REPETICION = 3


def _convertir_fecha_turso(
    valor,
) -> datetime | None:
    """Convierte la fecha textual guardada en Turso a datetime."""

    if valor is None:
        return None

    texto = str(valor).strip()

    if not texto:
        return None

    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"

    try:
        fecha = datetime.fromisoformat(texto)
    except ValueError:
        return None

    if fecha.tzinfo is not None:
        fecha = fecha.astimezone().replace(tzinfo=None)

    return fecha


def _obtener_ultima_aparicion_preguntas(
    convocatoria_id: int,
) -> dict[int, datetime]:
    """
    Obtiene desde Turso la última fecha en que apareció cada pregunta
    en cualquier simulacro o test conservado de la convocatoria.
    """

    with conectar_usuario() as con:
        filas = con.execute(
            """
            SELECT
                sp.pregunta_id,
                MAX(s.fecha_generacion) AS ultima_fecha
            FROM simulacros s
            JOIN simulacro_preguntas sp
                ON sp.simulacro_id = s.id
            WHERE s.convocatoria_id = ?
              AND sp.pregunta_id IS NOT NULL
            GROUP BY sp.pregunta_id
            """,
            (convocatoria_id,),
        ).fetchall()

    resultado: dict[int, datetime] = {}

    for fila in filas:
        fecha = _convertir_fecha_turso(
            fila["ultima_fecha"]
        )

        if fecha is not None:
            resultado[int(fila["pregunta_id"])] = fecha

    return resultado


def _es_pregunta_reciente(
    pregunta_id: int,
    ultima_aparicion: dict[int, datetime],
    fecha_limite: datetime,
) -> bool:
    """Indica si la pregunta apareció dentro del periodo protegido."""

    fecha = ultima_aparicion.get(
        int(pregunta_id)
    )

    return (
        fecha is not None
        and fecha > fecha_limite
    )


def _seleccionar_sin_repeticion_reciente(
    candidatas: list,
    cantidad: int,
    ultima_aparicion: dict[int, datetime],
) -> tuple[list, int]:
    """
    Selecciona primero preguntas no usadas en los últimos tres días.

    Si no bastan, completa con preguntas recientes empezando por las que
    llevan más tiempo sin aparecer.

    Devuelve:
        - preguntas elegidas;
        - número de preguntas recientes reutilizadas.
    """

    if cantidad <= 0:
        return [], 0

    fecha_limite = (
        datetime.now()
        - timedelta(days=DIAS_SIN_REPETICION)
    )

    no_recientes = []
    recientes = []

    for pregunta in candidatas:
        pregunta_id = int(
            pregunta["pregunta_id"]
        )
        fecha = ultima_aparicion.get(
            pregunta_id
        )

        if (
            fecha is None
            or fecha <= fecha_limite
        ):
            no_recientes.append(pregunta)
        else:
            recientes.append(pregunta)

    if len(no_recientes) >= cantidad:
        return (
            random.sample(
                no_recientes,
                cantidad,
            ),
            0,
        )

    random.shuffle(no_recientes)
    elegidas = list(no_recientes)

    # El shuffle previo evita un sesgo fijo entre preguntas con la misma fecha.
    random.shuffle(recientes)
    recientes.sort(
        key=lambda pregunta: ultima_aparicion[
            int(pregunta["pregunta_id"])
        ]
    )

    faltan = cantidad - len(elegidas)
    reutilizadas = recientes[:faltan]
    elegidas.extend(reutilizadas)

    return elegidas, len(reutilizadas)



# =============================================================================
# MODELO DE EXAMEN CONFIGURADO EN BASE DE DATOS
# =============================================================================

MAX_PREGUNTAS_LIBRES_POR_NORMA = 2


def _tabla_modelo_examen_existe(con: sqlite3.Connection) -> bool:
    """Comprueba que la base maestra contiene la tabla del modelo de examen."""

    return con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'convocatoria_modelo_bloques'
        """
    ).fetchone() is not None


def _cargar_bloques_modelo_parte(
    con: sqlite3.Connection,
    convocatoria_parte_id: int,
) -> list[sqlite3.Row]:
    """Carga, en orden, los bloques configurados para una parte."""

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
    """Identifica una candidata apta para una parte jurídica teórica modelada."""

    return (
        str(pregunta["tipo_clasificacion"] or "").strip().upper()
        == "JURIDICA"
        and str(pregunta["teorica_practica"] or "").strip().upper()
        == "TEORICA"
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
    """Selecciona la cantidad ya ajustada de un bloque NORMA."""

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

    elegidas, _ = _seleccionar_sin_repeticion_reciente(
        candidatas=candidatas,
        cantidad=cantidad,
        ultima_aparicion=ultima_aparicion,
    )
    return elegidas


def _seleccionar_preguntas_libres_modelo(
    candidatas_parte: list,
    cantidad_total: int,
    normas_preasignadas: set[int],
    preguntas_usadas: set[int],
    ultima_aparicion: dict[int, datetime],
    parte_nombre: str,
) -> list:
    """
    Selecciona todas las preguntas LIBRE de una parte en una sola operación.

    Reglas acordadas:
    - solo normas de la misma parte, porque las candidatas ya proceden del banco
      y de convocatoria_parte_id;
    - se excluyen todas las normas que tengan un bloque NORMA en esa parte;
    - máximo dos preguntas por norma sumando todos los bloques LIBRE de la parte.
    """

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
    seleccionadas_por_norma: dict[int, int] = {
        norma_id: 0 for norma_id in por_norma
    }
    normas = list(por_norma)

    # Primera vuelta: como máximo una por norma antes de empezar una segunda.
    # Esto favorece el objetivo de que los bloques libres recorran normas que no
    # forman parte del reparto fijo, sin alterar el límite máximo acordado.
    for _vuelta in range(MAX_PREGUNTAS_LIBRES_POR_NORMA):
        random.shuffle(normas)

        for norma_id in normas:
            if len(elegidas) >= cantidad_total:
                break

            if (
                seleccionadas_por_norma[norma_id]
                >= MAX_PREGUNTAS_LIBRES_POR_NORMA
            ):
                continue

            ya_elegidas = {
                int(pregunta["pregunta_id"])
                for pregunta in elegidas
            }
            disponibles_norma = [
                pregunta
                for pregunta in por_norma[norma_id]
                if int(pregunta["pregunta_id"]) not in ya_elegidas
            ]

            if not disponibles_norma:
                continue

            seleccion, _ = _seleccionar_sin_repeticion_reciente(
                candidatas=disponibles_norma,
                cantidad=1,
                ultima_aparicion=ultima_aparicion,
            )

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
    bloques: list[sqlite3.Row],
    candidatas_parte: list,
    parte_nombre: str,
) -> dict[int, int]:
    """
    Ajusta únicamente lo imprescindible cuando una norma queda una pregunta
    por debajo del modelo. Cada bloque puede desviarse como máximo en una
    pregunta y un bloque NORMA nunca puede quedar a cero.
    """

    cantidades = {
        int(bloque["id"]): int(bloque["cantidad"])
        for bloque in bloques
    }

    bloques_norma_por_norma: dict[int, list[sqlite3.Row]] = {}
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

    # Solo se permite reducir un bloque NORMA en una pregunta. Si el modelo
    # pide una sola pregunta, esa pregunta sigue siendo obligatoria.
    for norma_id, bloques_norma in bloques_norma_por_norma.items():
        objetivo = sum(int(bloque["cantidad"]) for bloque in bloques_norma)
        disponibles = disponibles_por_norma[norma_id]

        if disponibles >= objetivo:
            continue

        deficit = objetivo - disponibles
        reducibles = [
            bloque
            for bloque in reversed(bloques_norma)
            if int(bloque["cantidad"]) > 1
        ]

        if deficit > len(reducibles):
            norma_nombre = str(
                bloques_norma[0]["norma"] or f"norma_id {norma_id}"
            )
            minimo = objetivo - len(reducibles)
            raise ValueError(
                f"No hay suficientes preguntas para {parte_nombre} — "
                f"{norma_nombre}. El modelo prevé {objetivo}, el mínimo "
                f"admisible es {minimo} y solo hay {disponibles}."
            )

        for bloque in reducibles[:deficit]:
            bloque_id = int(bloque["id"])
            cantidades[bloque_id] -= 1
            deficit_total += 1

    if deficit_total == 0:
        return cantidades

    # La compensación mantiene el total de la parte. Se prefieren los bloques
    # LIBRE; cada bloque puede crecer como máximo en una pregunta.
    bloques_libres = [
        bloque
        for bloque in bloques
        if str(bloque["tipo_bloque"]) == "LIBRE"
    ]

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
    objetivo_libre = sum(
        int(cantidades[int(bloque["id"])])
        for bloque in bloques_libres
    )
    extra_libre_disponible = max(0, capacidad_libre - objetivo_libre)

    for bloque in bloques_libres:
        if deficit_total <= 0 or extra_libre_disponible <= 0:
            break
        cantidades[int(bloque["id"])] += 1
        deficit_total -= 1
        extra_libre_disponible -= 1

    if deficit_total <= 0:
        return cantidades

    # Si no basta LIBRE, una norma con disponibilidad puede absorber como
    # máximo una pregunta adicional por bloque, manteniendo el patrón próximo.
    usados_por_norma = {
        norma_id: sum(
            cantidades[int(bloque["id"])]
            for bloque in bloques_norma
        )
        for norma_id, bloques_norma in bloques_norma_por_norma.items()
    }

    receptores = [
        bloque
        for bloque in bloques
        if str(bloque["tipo_bloque"]) == "NORMA"
        and bloque["norma_id"] is not None
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
    bloques: list[sqlite3.Row],
    candidatas_parte: list,
    ultima_aparicion: dict[int, datetime],
    preguntas_usadas: set[int],
) -> list[tuple[sqlite3.Row, sqlite3.Row]]:
    """Construye una parte jurídica teórica siguiendo sus bloques configurados."""

    nombre_parte = str(parte["nombre"])
    total_parte = int(parte["numero_preguntas"])

    suma_bloques = sum(int(bloque["cantidad"]) for bloque in bloques)
    if suma_bloques != total_parte:
        raise ValueError(
            f"El modelo de {nombre_parte} suma {suma_bloques} preguntas, "
            f"pero la parte tiene configuradas {total_parte}."
        )

    ordenes = [int(bloque["orden"]) for bloque in bloques]
    if ordenes != list(range(1, len(ordenes) + 1)):
        raise ValueError(
            f"El modelo de {nombre_parte} no tiene un orden consecutivo válido."
        )

    tipos_invalidos = [
        str(bloque["tipo_bloque"])
        for bloque in bloques
        if str(bloque["tipo_bloque"]) not in {"NORMA", "LIBRE"}
    ]
    if tipos_invalidos:
        raise ValueError(
            f"El modelo de {nombre_parte} contiene tipos de bloque no válidos."
        )

    cantidades = _planificar_cantidades_modelo(
        bloques=bloques,
        candidatas_parte=candidatas_parte,
        parte_nombre=nombre_parte,
    )

    normas_preasignadas = {
        int(bloque["norma_id"])
        for bloque in bloques
        if str(bloque["tipo_bloque"]) == "NORMA"
        and bloque["norma_id"] is not None
    }

    cantidad_libre = sum(
        cantidades[int(bloque["id"])]
        for bloque in bloques
        if str(bloque["tipo_bloque"]) == "LIBRE"
    )

    libres = _seleccionar_preguntas_libres_modelo(
        candidatas_parte=candidatas_parte,
        cantidad_total=cantidad_libre,
        normas_preasignadas=normas_preasignadas,
        preguntas_usadas=preguntas_usadas,
        ultima_aparicion=ultima_aparicion,
        parte_nombre=nombre_parte,
    )
    indice_libre = 0

    resultado: list[tuple[sqlite3.Row, sqlite3.Row]] = []

    for bloque in bloques:
        tipo_bloque = str(bloque["tipo_bloque"])
        cantidad = cantidades[int(bloque["id"])]

        if tipo_bloque == "NORMA":
            norma_id = int(bloque["norma_id"])
            norma_nombre = str(bloque["norma"] or f"norma_id {norma_id}")
            elegidas = _seleccionar_preguntas_norma_modelo(
                candidatas_parte=candidatas_parte,
                norma_id=norma_id,
                cantidad=cantidad,
                preguntas_usadas=preguntas_usadas,
                ultima_aparicion=ultima_aparicion,
                parte_nombre=nombre_parte,
                norma_nombre=norma_nombre,
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
    origenes_seleccionados: list[str],
    fuentes_seleccionadas: list[str] | None = None,
) -> int:
    """
    Genera un simulacro completo a partir del banco de la convocatoria.

    - El número y orden de las partes procede de convocatoria_partes.
    - Las partes que tienen filas en convocatoria_modelo_bloques se construyen
      exactamente según sus bloques NORMA/LIBRE.
    - Las partes sin modelo de bloques se seleccionan aleatoriamente dentro de
      su banco (por ejemplo, prácticas y partes no jurídicas).
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

    if set(origenes) - origenes_validos:
        raise ValueError(
            "Existe algún origen de preguntas no válido."
        )

    marcadores_origen = ", ".join(
        "?" for _ in origenes
    )

    fuentes = {
        str(x).strip().upper()
        for x in (
            fuentes_seleccionadas
            or ["REAL", "IA"]
        )
        if str(x).strip()
    }

    if not fuentes or fuentes - {"REAL", "IA"}:
        raise ValueError(
            "Debe seleccionar al menos una fuente válida: REAL y/o IA."
        )

    condicion_fuente = (
        "LOWER(TRIM(lp.tipo_fuente)) = 'ia_generada'"
        if fuentes == {"IA"}
        else "LOWER(TRIM(lp.tipo_fuente)) <> 'ia_generada'"
        if fuentes == {"REAL"}
        else "1 = 1"
    )

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
            raise ValueError(
                "La convocatoria no existe."
            )

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

        if (
            sum(
                int(parte["numero_preguntas"])
                for parte in partes
            )
            != int(convocatoria["numero_preguntas"])
        ):
            raise ValueError(
                "La suma de preguntas de las partes no coincide "
                "con el total configurado en la convocatoria."
            )

        if not _tabla_modelo_examen_existe(con_catalogo):
            raise RuntimeError(
                "La base no contiene convocatoria_modelo_bloques. "
                "Configure el modelo de examen desde OpoCoach-Mantenimiento."
            )

        bloques_por_parte = {
            int(parte["id"]): _cargar_bloques_modelo_parte(
                con_catalogo,
                int(parte["id"]),
            )
            for parte in partes
        }

        candidatas = con_catalogo.execute(
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

            JOIN convocatoria_partes cp
                ON cp.id = bp.convocatoria_parte_id
               AND cp.convocatoria_id = bp.convocatoria_id

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
              AND ({condicion_fuente})
            """,
            (
                convocatoria_id,
                *origenes,
            ),
        ).fetchall()

    preguntas_seleccionadas: list[
        tuple[sqlite3.Row, sqlite3.Row]
    ] = []
    preguntas_usadas: set[int] = set()

    ultima_aparicion = _obtener_ultima_aparicion_preguntas(
        convocatoria_id
    )

    for parte in partes:
        parte_id = int(parte["id"])
        nombre_parte = str(parte["nombre"])
        cantidad = int(parte["numero_preguntas"])

        candidatas_parte = [
            pregunta
            for pregunta in candidatas
            if int(pregunta["convocatoria_parte_id"]) == parte_id
            and int(pregunta["pregunta_id"]) not in preguntas_usadas
        ]

        if len(candidatas_parte) < cantidad:
            raise ValueError(
                f"No hay suficientes preguntas para {nombre_parte}. "
                f"Se necesitan {cantidad} y solo hay "
                f"{len(candidatas_parte)}."
            )

        bloques = bloques_por_parte[parte_id]

        if bloques:
            elegidas_parte = _seleccionar_parte_segun_modelo(
                parte=parte,
                bloques=bloques,
                candidatas_parte=candidatas_parte,
                ultima_aparicion=ultima_aparicion,
                preguntas_usadas=preguntas_usadas,
            )
            preguntas_seleccionadas.extend(elegidas_parte)
            continue

        # Partes sin modelo: selección aleatoria desde su banco. Aquí quedan,
        # por diseño, las partes prácticas y las no jurídicas.
        elegidas, _ = _seleccionar_sin_repeticion_reciente(
            candidatas=candidatas_parte,
            cantidad=cantidad,
            ultima_aparicion=ultima_aparicion,
        )

        for pregunta in elegidas:
            pregunta_id = int(pregunta["pregunta_id"])
            if pregunta_id in preguntas_usadas:
                raise RuntimeError(
                    f"La pregunta {pregunta_id} se ha seleccionado dos veces "
                    "en el mismo simulacro."
                )
            preguntas_usadas.add(pregunta_id)
            preguntas_seleccionadas.append((parte, pregunta))

    if (
        len(preguntas_seleccionadas)
        != int(convocatoria["numero_preguntas"])
    ):
        raise ValueError(
            "El número de preguntas seleccionadas no coincide "
            "con el total de la convocatoria."
        )

    conteo_partes: dict[int, int] = {}
    for parte, _pregunta in preguntas_seleccionadas:
        parte_id = int(parte["id"])
        conteo_partes[parte_id] = conteo_partes.get(parte_id, 0) + 1

    for parte in partes:
        parte_id = int(parte["id"])
        esperado = int(parte["numero_preguntas"])
        real = conteo_partes.get(parte_id, 0)
        if real != esperado:
            raise RuntimeError(
                f"Validación del simulacro fallida: {parte['nombre']} "
                f"contiene {real} preguntas y debe contener {esperado}."
            )

    with conectar_usuario() as con_usuario:
        con_usuario.execute(
            "BEGIN IMMEDIATE"
        )

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
        "SEGURO",
        "MENOS_SEGURO",
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
        "SEGURO": "Seguro",
        "MENOS_SEGURO": "Menos seguro",
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

        if (
            seguridad_usuario is not None
            and seguridad_usuario not in estadisticas_seguridad
        ):
            raise ValueError(
                "Existe alguna pregunta contestada con un nivel "
                "de seguridad no válido."
            )

        estadistica_tema["contestadas"] += 1

        estadistica_seguridad = (
            estadisticas_seguridad.get(seguridad_usuario)
        )
        if estadistica_seguridad is not None:
            estadistica_seguridad["contestadas"] += 1

        if respuesta_usuario == respuesta_correcta:
            aciertos += 1
            estadistica_tema["aciertos"] += 1
            if estadistica_seguridad is not None:
                estadistica_seguridad["aciertos"] += 1
        else:
            fallos += 1
            estadistica_tema["fallos"] += 1
            if estadistica_seguridad is not None:
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

        if contestadas_seguridad:
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
    fuentes_seleccionadas: list[str] | None = None,
) -> list[sqlite3.Row]:
    """Obtiene los puntos del temario y su disponibilidad para tests."""

    fuentes = {
        str(x).strip().upper()
        for x in (fuentes_seleccionadas or ["REAL", "IA"])
        if str(x).strip()
    }

    if not fuentes or fuentes - {"REAL", "IA"}:
        raise ValueError(
            "Debe seleccionar al menos una fuente válida: REAL y/o IA."
        )

    condicion_fuente = (
        "LOWER(TRIM(lp.tipo_fuente)) = 'ia_generada'"
        if fuentes == {"IA"}
        else "LOWER(TRIM(lp.tipo_fuente)) <> 'ia_generada'"
        if fuentes == {"REAL"}
        else "1 = 1"
    )

    with conectar() as con:
        return con.execute(
            f"""
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
               AND {condicion_fuente}

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



def obtener_normas_test(
    convocatoria_id: int,
    fuentes_seleccionadas: list[str] | None = None,
) -> list[sqlite3.Row]:
    """
    Obtiene las leyes o normas con preguntas disponibles para crear tests.

    La identidad de una norma es inequívoca:
        - norma_id_normalizada, cuando existe.
        - nombre normalizado, solo como respaldo si no existe ID.

    El nombre mostrado se toma de normas.nombre_canonico cuando hay ID.
    """

    fuentes = {
        str(x).strip().upper()
        for x in (fuentes_seleccionadas or ["REAL", "IA"])
        if str(x).strip()
    }

    if not fuentes or fuentes - {"REAL", "IA"}:
        raise ValueError(
            "Debe seleccionar al menos una fuente válida: REAL y/o IA."
        )

    condicion_fuente = (
        "LOWER(TRIM(lp.tipo_fuente)) = 'ia_generada'"
        if fuentes == {"IA"}
        else "LOWER(TRIM(lp.tipo_fuente)) <> 'ia_generada'"
        if fuentes == {"REAL"}
        else "1 = 1"
    )

    with conectar() as con:
        return con.execute(
            f"""
            SELECT
                CASE
                    WHEN lp.norma_id_normalizada IS NOT NULL
                        THEN 'ID:' || CAST(
                            lp.norma_id_normalizada AS TEXT
                        )
                    ELSE 'NOMBRE:' || LOWER(
                        TRIM(
                            COALESCE(
                                NULLIF(
                                    TRIM(lp.nombre_norma_normalizado),
                                    ''
                                ),
                                NULLIF(
                                    TRIM(lp.nombre_norma),
                                    ''
                                )
                            )
                        )
                    )
                END AS norma_clave,

                COALESCE(
                    MAX(n.nombre_canonico),
                    MIN(
                        COALESCE(
                            NULLIF(
                                TRIM(lp.nombre_norma_normalizado),
                                ''
                            ),
                            NULLIF(
                                TRIM(lp.nombre_norma),
                                ''
                            )
                        )
                    )
                ) AS norma_nombre,

                COUNT(
                    DISTINCT bp.pregunta_id
                ) AS disponibles

            FROM banco_preguntas bp

            JOIN lote_preguntas lp
                ON lp.id = bp.pregunta_id

            LEFT JOIN normas n
                ON n.id = lp.norma_id_normalizada

            WHERE bp.convocatoria_id = ?
              AND bp.estado = 'INCLUIDA'
              AND {condicion_fuente}
              AND UPPER(
                    TRIM(
                        COALESCE(
                            lp.tipo_clasificacion,
                            ''
                        )
                    )
                  ) <> 'INFORMATICA'
              AND (
                    lp.norma_id_normalizada IS NOT NULL
                    OR COALESCE(
                        NULLIF(
                            TRIM(lp.nombre_norma_normalizado),
                            ''
                        ),
                        NULLIF(
                            TRIM(lp.nombre_norma),
                            ''
                        )
                    ) IS NOT NULL
                  )

            GROUP BY
                norma_clave

            ORDER BY
                norma_nombre
            """,
            (convocatoria_id,),
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
        key=lambda elemento_id: (
            cuotas_exactas[elemento_id]
            - int(cuotas_exactas[elemento_id]),
            disponibilidades[elemento_id],
            str(elemento_id),
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
    temas_seleccionados: list[int] | None = None,
    normas_seleccionadas: list[str] | None = None,
    modo_seleccion: str = "TEMA",
    fuentes_seleccionadas: list[str] | None = None,
) -> dict:
    """
    Crea un test proporcionalmente entre los elementos seleccionados.

    modo_seleccion:
        - TEMA: puntos del temario.
        - NORMA: leyes o normas.

    Ambos modos congelan las preguntas con la misma estructura utilizada
    por los simulacros y comparten el mismo sistema de corrección.
    """

    if numero_preguntas <= 0:
        raise ValueError(
            "El número de preguntas debe ser mayor que cero."
        )

    modo = str(modo_seleccion).strip().upper()

    if modo not in {"TEMA", "NORMA"}:
        raise ValueError(
            "El modo de selección del test no es válido."
        )

    fuentes = {
        str(x).strip().upper()
        for x in (fuentes_seleccionadas or ["REAL", "IA"])
        if str(x).strip()
    }

    if not fuentes or fuentes - {"REAL", "IA"}:
        raise ValueError(
            "Debe seleccionar al menos una fuente válida: REAL y/o IA."
        )

    condicion_fuente = (
        "LOWER(TRIM(lp.tipo_fuente)) = 'ia_generada'"
        if fuentes == {"IA"}
        else "LOWER(TRIM(lp.tipo_fuente)) <> 'ia_generada'"
        if fuentes == {"REAL"}
        else "1 = 1"
    )

    temas_ids = sorted(
        {
            int(tema_id)
            for tema_id in (temas_seleccionados or [])
        }
    )
    normas_claves = sorted(
        {
            str(clave).strip()
            for clave in (normas_seleccionadas or [])
            if str(clave).strip()
        }
    )

    if modo == "TEMA" and not temas_ids:
        raise ValueError(
            "Debe seleccionar al menos un punto del temario."
        )

    if modo == "NORMA" and not normas_claves:
        raise ValueError(
            "Debe seleccionar al menos una ley o norma."
        )

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

        if modo == "TEMA":
            marcadores = ", ".join(
                "?"
                for _ in temas_ids
            )

            elementos = con_catalogo.execute(
                f"""
                SELECT
                    tt.id AS elemento_id,
                    (
                        tt.numero_tema || '. '
                        || tt.parte || ' — '
                        || tt.titulo
                    ) AS elemento_nombre
                FROM temario_temas tt
                JOIN temarios t
                    ON t.id = tt.temario_id
                WHERE t.convocatoria_id = ?
                  AND tt.id IN ({marcadores})
                ORDER BY
                    tt.parte,
                    tt.numero_tema,
                    tt.titulo
                """,
                (
                    convocatoria_id,
                    *temas_ids,
                ),
            ).fetchall()

            if len(elementos) != len(temas_ids):
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
                    tt.tipo_contenido AS tema_tipo_contenido,

                    CAST(tt.id AS TEXT) AS elemento_id

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
                  AND {condicion_fuente}
                  AND tt.id IN ({marcadores})
                """,
                (
                    convocatoria_id,
                    *temas_ids,
                ),
            ).fetchall()

            claves_elementos = [
                str(tema_id)
                for tema_id in temas_ids
            ]

        else:
            marcadores = ", ".join(
                "?"
                for _ in normas_claves
            )

            expresion_clave_norma = """
                CASE
                    WHEN lp.norma_id_normalizada IS NOT NULL
                        THEN 'ID:' || CAST(
                            lp.norma_id_normalizada AS TEXT
                        )
                    ELSE 'NOMBRE:' || LOWER(
                        TRIM(
                            COALESCE(
                                NULLIF(
                                    TRIM(lp.nombre_norma_normalizado),
                                    ''
                                ),
                                NULLIF(
                                    TRIM(lp.nombre_norma),
                                    ''
                                )
                            )
                        )
                    )
                END
            """

            elementos = con_catalogo.execute(
                f"""
                SELECT
                    {expresion_clave_norma} AS elemento_id,

                    COALESCE(
                        MAX(n.nombre_canonico),
                        MIN(
                            COALESCE(
                                NULLIF(
                                    TRIM(lp.nombre_norma_normalizado),
                                    ''
                                ),
                                NULLIF(
                                    TRIM(lp.nombre_norma),
                                    ''
                                )
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
                  AND {condicion_fuente}
                  AND UPPER(
                        TRIM(
                            COALESCE(
                                lp.tipo_clasificacion,
                                ''
                            )
                        )
                      ) <> 'INFORMATICA'
                  AND {expresion_clave_norma}
                        IN ({marcadores})

                GROUP BY
                    elemento_id

                ORDER BY
                    elemento_nombre
                """,
                (
                    convocatoria_id,
                    *normas_claves,
                ),
            ).fetchall()

            if len(elementos) != len(normas_claves):
                raise ValueError(
                    "Alguna de las normas seleccionadas no pertenece "
                    "al banco de la convocatoria."
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
                    tt.tipo_contenido AS tema_tipo_contenido,

                    {expresion_clave_norma} AS elemento_id

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
                  AND {condicion_fuente}
                  AND UPPER(
                        TRIM(
                            COALESCE(
                                lp.tipo_clasificacion,
                                ''
                            )
                        )
                      ) <> 'INFORMATICA'
                  AND {expresion_clave_norma}
                        IN ({marcadores})
                """,
                (
                    convocatoria_id,
                    *normas_claves,
                ),
            ).fetchall()

            claves_elementos = normas_claves

    candidatas_por_elemento: dict[
        str,
        list[sqlite3.Row],
    ] = {
        clave: []
        for clave in claves_elementos
    }

    for pregunta in candidatas:
        clave = str(pregunta["elemento_id"])

        if clave in candidatas_por_elemento:
            candidatas_por_elemento[clave].append(
                pregunta
            )

    disponibilidades = {
        clave: len(preguntas)
        for clave, preguntas
        in candidatas_por_elemento.items()
    }
    total_disponible = sum(
        disponibilidades.values()
    )

    if total_disponible == 0:
        raise ValueError(
            "No hay preguntas disponibles para la selección realizada."
        )

    reparto = _repartir_proporcionalmente(
        disponibilidades,
        numero_preguntas,
    )

    preguntas_seleccionadas: list[sqlite3.Row] = []
    preguntas_usadas: set[int] = set()
    reutilizadas_recientes = 0

    ultima_aparicion = _obtener_ultima_aparicion_preguntas(
        convocatoria_id
    )

    for elemento in elementos:
        clave = str(elemento["elemento_id"])
        cantidad = reparto[clave]

        disponibles_elemento = [
            pregunta
            for pregunta
            in candidatas_por_elemento[clave]
            if int(pregunta["pregunta_id"])
            not in preguntas_usadas
        ]

        cantidad_real = min(
            cantidad,
            len(disponibles_elemento),
        )

        (
            elegidas,
            reutilizadas_elemento,
        ) = _seleccionar_sin_repeticion_reciente(
            candidatas=disponibles_elemento,
            cantidad=cantidad_real,
            ultima_aparicion=ultima_aparicion,
        )

        reutilizadas_recientes += reutilizadas_elemento

        for pregunta in elegidas:
            preguntas_usadas.add(
                int(pregunta["pregunta_id"])
            )
            preguntas_seleccionadas.append(
                pregunta
            )

    if len(preguntas_seleccionadas) < min(
        numero_preguntas,
        total_disponible,
    ):
        restantes = [
            pregunta
            for preguntas_elemento
            in candidatas_por_elemento.values()
            for pregunta in preguntas_elemento
            if int(pregunta["pregunta_id"])
            not in preguntas_usadas
        ]

        faltan = min(
            numero_preguntas,
            total_disponible,
        ) - len(preguntas_seleccionadas)

        if faltan > 0:
            (
                adicionales,
                reutilizadas_adicionales,
            ) = _seleccionar_sin_repeticion_reciente(
                candidatas=restantes,
                cantidad=min(
                    faltan,
                    len(restantes),
                ),
                ultima_aparicion=ultima_aparicion,
            )

            reutilizadas_recientes += (
                reutilizadas_adicionales
            )

            for pregunta in adicionales:
                preguntas_usadas.add(
                    int(pregunta["pregunta_id"])
                )
                preguntas_seleccionadas.append(
                    pregunta
                )

    random.shuffle(preguntas_seleccionadas)
    total_generado = len(
        preguntas_seleccionadas
    )

    if total_generado == 0:
        raise ValueError(
            "No se ha podido generar el test."
        )

    avisos: list[str] = []

    if total_generado < numero_preguntas:
        avisos.append(
            f"Se solicitaron {numero_preguntas} preguntas, pero "
            f"solo hay {total_generado} preguntas distintas "
            "disponibles para la selección realizada. El test se ha "
            "creado con el máximo disponible."
        )

    if reutilizadas_recientes > 0:
        avisos.append(
            f"No había suficientes preguntas sin utilizar durante "
            f"los últimos {DIAS_SIN_REPETICION} días. Se han "
            f"reutilizado {reutilizadas_recientes}, seleccionando "
            "preferentemente las que llevaban más tiempo sin aparecer."
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
            raise RuntimeError(
                "No se ha podido crear el test."
            )

        preguntas_para_guardar: list[dict] = []

        for orden, pregunta in enumerate(
            preguntas_seleccionadas,
            start=1,
        ):
            preguntas_para_guardar.append(
                {
                    "orden": orden,
                    "pregunta_id": pregunta["pregunta_id"],
                    "banco_pregunta_id": pregunta[
                        "banco_pregunta_id"
                    ],
                    "parte_id": None,
                    "parte_nombre": pregunta["tema_parte"],
                    "parte_orden": pregunta["numero_tema"],
                    "enunciado": pregunta["enunciado"],
                    "opcion_a": pregunta["opcion_a"],
                    "opcion_b": pregunta["opcion_b"],
                    "opcion_c": pregunta["opcion_c"],
                    "opcion_d": pregunta["opcion_d"],
                    "respuesta_correcta": pregunta[
                        "respuesta_correcta"
                    ],
                    "tipo_clasificacion": pregunta[
                        "tipo_clasificacion"
                    ],
                    "tipo_norma": pregunta["tipo_norma"],
                    "nombre_norma": pregunta["nombre_norma"],
                    "articulo": pregunta["articulo"],
                    "tema_no_juridico": pregunta[
                        "tema_no_juridico"
                    ],
                    "origen_oposicion": pregunta[
                        "origen_oposicion"
                    ],
                    "tipo_fuente": pregunta["tipo_fuente"],
                    "importacion_fichero_id": pregunta[
                        "importacion_fichero_id"
                    ],
                    "pagina_origen": pregunta["pagina_origen"],
                    "norma_id_normalizada": pregunta[
                        "norma_id_normalizada"
                    ],
                    "articulo_normalizado": pregunta[
                        "articulo_normalizado"
                    ],
                    "teorica_practica": pregunta[
                        "teorica_practica"
                    ],
                    "tipo_norma_normalizado": pregunta[
                        "tipo_norma_normalizado"
                    ],
                    "nombre_norma_normalizado": pregunta[
                        "nombre_norma_normalizado"
                    ],
                    "banco_tipo_vinculacion": pregunta[
                        "tipo_vinculacion"
                    ],
                    "banco_estado": pregunta["banco_estado"],
                    "banco_metodo_vinculacion": pregunta[
                        "metodo_vinculacion"
                    ],
                    "banco_motivo_revision": pregunta[
                        "motivo_revision"
                    ],
                    "temas_json": json.dumps(
                        {
                            "tema_id_original": pregunta["tema_id"],
                            "parte": pregunta["tema_parte"],
                            "numero_tema": pregunta[
                                "numero_tema"
                            ],
                            "titulo": pregunta["tema_titulo"],
                            "tipo_contenido": pregunta[
                                "tema_tipo_contenido"
                            ],
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
        "modo_seleccion": modo,
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
    tipo_prueba: str = "SIMULACRO",
) -> dict:
    """
    Calcula el rendimiento acumulado de las pruebas corregidas del
    tipo indicado que siguen existiendo para una convocatoria.

    Una prueba se considera corregida cuando alguna de sus preguntas
    tiene respuesta o nivel de seguridad guardado. El resultado se recalcula siempre desde Turso,
    por lo que cualquier modificación o eliminación queda reflejada
    automáticamente.
    """

    tipo = str(tipo_prueba).strip().upper()

    if tipo not in {"SIMULACRO", "TEST"}:
        raise ValueError(
            "El tipo de prueba acumulada no es válido."
        )

    respuestas_validas = {"A", "B", "C", "D"}
    etiquetas_seguridad = {
        "SEGURO": "Seguro",
        "MENOS_SEGURO": "Menos seguro",
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
              AND s.tipo_prueba = ?
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
            (
                convocatoria_id,
                tipo,
            ),
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
                "normas": [],
                "seguridad": [],
                "firma_datos": hashlib.sha256(b"").hexdigest(),
            }

        simulacros_ids = [
            int(fila["id"])
            for fila in simulacros
        ]
        marcadores = ", ".join(
            "?"
            for _ in simulacros_ids
        )

        preguntas = con.execute(
            f"""
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
            tema = json.loads(
                pregunta["temas_json"]
            )
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
                "fallos_seguro": 0,
            }

        estadistica_tema = estadisticas_temas[
            clave_tema
        ]
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

        estadistica_norma = estadisticas_normas[
            clave_norma
        ]
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

        if respuesta_usuario not in respuestas_validas:
            raise ValueError(
                "Existe alguna respuesta acumulada del usuario "
                "no válida."
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

        estadistica_seguridad = (
            estadisticas_seguridad.get(seguridad_usuario)
        )
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
            preguntas_tema / total * 100
            if total
            else 0.0
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
            preguntas_norma / total * 100
            if total
            else 0.0
        )
        estadistica["porcentaje_aciertos"] = (
            estadistica["aciertos"] / preguntas_norma * 100
            if preguntas_norma
            else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"] / preguntas_norma * 100
            if preguntas_norma
            else 0.0
        )
        estadistica["porcentaje_no_contestadas"] = (
            estadistica["no_contestadas"] / preguntas_norma * 100
            if preguntas_norma
            else 0.0
        )
        estadistica["porcentaje_aciertos_contestadas"] = (
            estadistica["aciertos"] / contestadas_norma * 100
            if contestadas_norma
            else 0.0
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
            estadistica["aciertos"]
            / contestadas_seguridad
            * 100
            if contestadas_seguridad
            else 0.0
        )
        estadistica["porcentaje_fallos"] = (
            estadistica["fallos"]
            / contestadas_seguridad
            * 100
            if contestadas_seguridad
            else 0.0
        )

        if contestadas_seguridad:
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
        "normas": resultado_normas,
        "seguridad": resultado_seguridad,
        "firma_datos": firma_datos,
    }