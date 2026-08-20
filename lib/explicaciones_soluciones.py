"""
==============================================================================
OpoCoach
Archivo: lib/explicaciones_soluciones.py
==============================================================================

Genera comentarios explicativos para el PDF de soluciones.

Lee:
    - usuario.sqlite3:
        simulacro_preguntas
        simulacro_snapshot

    - oposiciones.sqlite3:
        temario_referencias
        articulos_fuente

Escribe:
    - usuario.sqlite3:
        simulacro_snapshot.comentario_solucion

La generación es incremental:
    solo procesa preguntas cuyo comentario_solucion está vacío.

==============================================================================
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from lib.database import conectar, conectar_usuario
from tools.openai_api import seleccionar_fragmento_json


TAMANO_LOTE = 16
MAX_TRABAJADORES_IA = 3
MODELO_PREDETERMINADO = "gpt-5.4-nano"
OPERACION_IA = "comentarios_pdf_soluciones"

ROOT = Path(__file__).resolve().parents[1]
CARPETA_LOGS = ROOT / "logs" / "ia" / "soluciones"


INSTRUCCIONES = """
Eres preparador de oposiciones.

La respuesta correcta de cada pregunta ya está determinada. No debes resolver
la pregunta de nuevo ni cuestionar la respuesta indicada.

Recibirás preguntas JURIDICAS y NO JURIDICAS. Las no jurídicas suelen ser
de INFORMATICA. Redacta un comentario claro que explique por qué la opción
indicada es correcta.

REGLAS PARA PREGUNTAS JURIDICAS:
- Utiliza exclusivamente la norma, el artículo y el texto de la fuente aportada.
- Comienza identificando expresamente la norma y el artículo aplicables.
- Usa una fórmula natural, por ejemplo:
  "Según el artículo 96 de la Ley 39/2015, ..."
- Explica la regla concreta del precepto que permite reconocer la respuesta.
- Señala el elemento decisivo: plazo, órgano competente, requisito, excepción,
  efecto jurídico, definición o procedimiento.
- Cuando aporte valor, indica brevemente por qué las restantes opciones no
  encajan con la regla del artículo, sin analizarlas una por una.
- No uses conocimiento jurídico externo ni completes información ausente.

REGLAS PARA PREGUNTAS NO JURIDICAS, INCLUIDAS LAS INFORMATICAS:
- Utiliza el enunciado, las opciones y la respuesta correcta proporcionada.
- Explica el concepto, función, comando, herramienta o comportamiento técnico
  que hace correcta esa opción.
- Puedes usar conocimiento técnico general y estable de informática, sistemas
  operativos, seguridad, redes y aplicaciones ofimáticas.
- No inventes versiones, rutas, nombres de menús o detalles que no sean seguros.
- Cuando una respuesta dependa de una versión concreta y esta no figure en la
  pregunta, limita la explicación al principio técnico que pueda afirmarse con
  seguridad.
- Cuando aporte valor, señala brevemente el error conceptual de las alternativas,
  sin analizarlas una por una.

REGLAS COMUNES:
- No te limites a afirmar que la opción es correcta: explica la razón.
- No repitas el enunciado ni reproduzcas las opciones completas.
- No escribas "Respuesta A", "Respuesta B", "Respuesta C" o "Respuesta D",
  porque esa indicación ya se añade automáticamente en el PDF.
- No añadas encabezados, listas, conclusiones ni Markdown.
- Un único párrafo por pregunta.
- Entre 40 y 100 palabras, salvo que no sea posible alcanzar esa extensión sin
  repetir o inventar información.
- Texto directamente imprimible en el PDF de soluciones.

Devuelve exclusivamente un JSON con esta forma:
[
  {
    "orden": 1,
    "comentario": "Explicación de la respuesta correcta."
  }
]

Debes devolver exactamente un objeto por cada pregunta recibida y conservar su
valor de "orden".
""".strip()


def _limpiar_texto(valor: Any | None) -> str:
    """Convierte cualquier valor en texto limpio de una sola línea."""
    if valor is None:
        return ""

    return " ".join(str(valor).split()).strip()


def _normalizar_articulo(valor: Any | None) -> str:
    """
    Extrae la referencia numérica principal del artículo.

    Tolera formatos como:
        53
        Artículo 53
        art. 53
        53.1
        artículo 101.2
        Artículo 13 de Título 1
        Artículo 30. Cómputo de plazos
        Artículo 117 de Libro 2

    Se conserva la numeración completa del artículo y sus apartados
    (por ejemplo, 101.2 o 35.1), ignorando títulos, libros y descripciones.
    """
    texto = _limpiar_texto(valor).lower()

    if not texto:
        return ""

    texto = texto.replace(",", ".")

    coincidencia = re.search(
        r"\b\d+(?:\.\d+)*\b",
        texto,
    )

    if coincidencia is None:
        return ""

    return coincidencia.group(0)


def _dividir_lotes(
    elementos: list[dict[str, Any]],
    tamano: int,
) -> Iterable[list[dict[str, Any]]]:
    for inicio in range(0, len(elementos), tamano):
        yield elementos[inicio:inicio + tamano]


def _obtener_preguntas_pendientes(
    simulacro_id: int,
) -> list[dict[str, Any]]:
    """
    Recupera únicamente las preguntas del simulacro que todavía no tienen
    comentario de solución.
    """
    with conectar_usuario() as con:
        filas = con.execute(
            """
            SELECT
                sp.id AS simulacro_pregunta_id,
                sp.orden,

                ss.enunciado,
                ss.opcion_a,
                ss.opcion_b,
                ss.opcion_c,
                ss.opcion_d,
                ss.respuesta_correcta,

                ss.tipo_clasificacion,
                ss.tema_no_juridico,
                ss.nombre_norma,
                ss.articulo,
                ss.norma_id_normalizada,
                ss.articulo_normalizado,
                ss.comentario_solucion

            FROM simulacro_preguntas sp

            JOIN simulacro_snapshot ss
                ON ss.simulacro_pregunta_id = sp.id

            WHERE sp.simulacro_id = ?
              AND (
                    ss.comentario_solucion IS NULL
                    OR TRIM(ss.comentario_solucion) = ''
                  )

            ORDER BY sp.orden
            """,
            (simulacro_id,),
        ).fetchall()

    return [dict(fila) for fila in filas]


def _obtener_texto_articulo(
    norma_id_normalizada: Any | None,
    articulo_normalizado: Any | None,
) -> str | None:
    """
    Localiza el texto del artículo a través de:

        temario_referencias.articulo_fuente_id
            -> articulos_fuente.id

    La comparación del artículo se hace en Python para tolerar diferencias
    sencillas de formato entre articulo_normalizado y articulo_solicitado.
    """
    norma_id = _limpiar_texto(norma_id_normalizada)
    articulo_buscado = _normalizar_articulo(articulo_normalizado)

    if not norma_id or not articulo_buscado:
        return None

    with conectar() as con:
        filas = con.execute(
            """
            SELECT
                tr.articulo_solicitado,
                af.texto

            FROM temario_referencias tr

            JOIN articulos_fuente af
                ON af.id = tr.articulo_fuente_id

            WHERE CAST(tr.norma_id AS TEXT) = ?
              AND af.texto IS NOT NULL
              AND TRIM(af.texto) <> ''
            """,
            (norma_id,),
        ).fetchall()

    # Prioridad controlada: referencia exacta y, si no existe en el corpus,
    # sus artículos/apartados padres. Ej.: 34.1.b -> 34.1 -> 34.
    #
    # No se altera ni "corrige" la referencia almacenada. Sólo se utiliza un
    # padre cuando ese padre existe realmente entre las referencias de la norma.
    candidatos_por_articulo: dict[str, str] = {}

    for fila in filas:
        articulo_candidato = _normalizar_articulo(
            fila["articulo_solicitado"]
        )
        texto = _limpiar_texto(fila["texto"])

        if articulo_candidato and texto:
            candidatos_por_articulo.setdefault(
                articulo_candidato,
                texto,
            )

    referencias_busqueda = [articulo_buscado]
    partes = articulo_buscado.split(".")

    while len(partes) > 1:
        partes = partes[:-1]
        referencias_busqueda.append(".".join(partes))

    for referencia in referencias_busqueda:
        texto = candidatos_por_articulo.get(referencia)
        if texto:
            return texto

    return None


def _preparar_preguntas(
    preguntas: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[int],
    list[dict[str, Any]],
]:
    preparadas: list[dict[str, Any]] = []
    sin_fuente: list[int] = []
    detalle_sin_fuente: list[dict[str, Any]] = []

    for pregunta in preguntas:
        orden = int(pregunta["orden"])
        tipo_clasificacion = _limpiar_texto(
            pregunta.get("tipo_clasificacion")
        ).upper()

        es_juridica = tipo_clasificacion == "JURIDICA"
        texto_fuente: str | None = None

        if es_juridica:
            texto_fuente = _obtener_texto_articulo(
                pregunta.get("norma_id_normalizada"),
                pregunta.get("articulo_normalizado"),
            )

            if not texto_fuente:
                sin_fuente.append(orden)
                detalle_sin_fuente.append(
                    {
                        "orden": orden,
                        "tipo_clasificacion": tipo_clasificacion,
                        "tema_no_juridico": _limpiar_texto(
                            pregunta.get("tema_no_juridico")
                        ),
                        "nombre_norma": _limpiar_texto(
                            pregunta.get("nombre_norma")
                        ),
                        "norma_id_normalizada": pregunta.get(
                            "norma_id_normalizada"
                        ),
                        "articulo": _limpiar_texto(
                            pregunta.get("articulo")
                        ),
                        "articulo_normalizado": _limpiar_texto(
                            pregunta.get("articulo_normalizado")
                        ),
                        "enunciado": _limpiar_texto(
                            pregunta.get("enunciado")
                        ),
                    }
                )
                continue

        preparadas.append(
            {
                "simulacro_pregunta_id": int(
                    pregunta["simulacro_pregunta_id"]
                ),
                "orden": orden,
                "tipo_clasificacion": (
                    "JURIDICA"
                    if es_juridica
                    else (
                        tipo_clasificacion
                        or "NO_JURIDICA"
                    )
                ),
                "enunciado": _limpiar_texto(
                    pregunta.get("enunciado")
                ),
                "opciones": {
                    "A": _limpiar_texto(pregunta.get("opcion_a")),
                    "B": _limpiar_texto(pregunta.get("opcion_b")),
                    "C": _limpiar_texto(pregunta.get("opcion_c")),
                    "D": _limpiar_texto(pregunta.get("opcion_d")),
                },
                "respuesta_correcta": _limpiar_texto(
                    pregunta.get("respuesta_correcta")
                ).upper(),
                "norma": (
                    _limpiar_texto(
                        pregunta.get("nombre_norma")
                    )
                    if es_juridica
                    else ""
                ),
                "articulo": (
                    _limpiar_texto(
                        pregunta.get("articulo")
                    )
                    if es_juridica
                    else ""
                ),
                "texto_fuente": texto_fuente or "",
            }
        )

    return preparadas, sin_fuente, detalle_sin_fuente


def _crear_prompt(lote: list[dict[str, Any]]) -> str:
    datos_ia: list[dict[str, Any]] = []

    for pregunta in lote:
        datos_ia.append(
            {
                "orden": pregunta["orden"],
                "tipo_clasificacion": pregunta[
                    "tipo_clasificacion"
                ],
                "enunciado": pregunta["enunciado"],
                "opciones": pregunta["opciones"],
                "respuesta_correcta": pregunta[
                    "respuesta_correcta"
                ],
                "norma": pregunta["norma"],
                "articulo": pregunta["articulo"],
                "texto_fuente": pregunta["texto_fuente"],
            }
        )

    return (
        INSTRUCCIONES
        + "\n\nPREGUNTAS:\n"
        + json.dumps(
            datos_ia,
            ensure_ascii=False,
            indent=2,
        )
    )


def _guardar_log(
    simulacro_id: int,
    numero_lote: int,
    prompt: str,
    respuesta: Any | None,
    error: str | None = None,
) -> None:
    CARPETA_LOGS.mkdir(parents=True, exist_ok=True)

    marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    base = (
        f"simulacro_{simulacro_id:04d}_"
        f"lote_{numero_lote:03d}_{marca}"
    )

    (CARPETA_LOGS / f"{base}_prompt.txt").write_text(
        prompt,
        encoding="utf-8",
    )

    if respuesta is not None:
        (CARPETA_LOGS / f"{base}_respuesta.json").write_text(
            json.dumps(
                respuesta,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    if error:
        (CARPETA_LOGS / f"{base}_error.txt").write_text(
            error,
            encoding="utf-8",
        )


def _limitar_comentario_palabras(
    comentario: str,
    max_palabras: int = 100,
) -> str:
    """
    Garantiza de forma determinista el máximo de palabras del comentario.

    Si la IA excede el límite, se conserva exactamente el comienzo hasta
    max_palabras. No se realiza una segunda llamada IA por un exceso formal.
    """
    palabras = comentario.split()

    if len(palabras) <= max_palabras:
        return comentario

    return " ".join(palabras[:max_palabras]).strip()


def _validar_respuesta(
    respuesta: Any,
    lote: list[dict[str, Any]],
) -> dict[int, str]:
    if not isinstance(respuesta, list):
        raise ValueError(
            "La respuesta de la IA no es una lista JSON."
        )

    ordenes_esperados = {
        int(pregunta["orden"])
        for pregunta in lote
    }

    comentarios: dict[int, str] = {}

    for elemento in respuesta:
        if not isinstance(elemento, dict):
            raise ValueError(
                "La respuesta contiene un elemento que no es un objeto."
            )

        try:
            orden = int(elemento["orden"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Un comentario no contiene un orden válido."
            ) from exc

        comentario = _limpiar_texto(
            elemento.get("comentario")
        )

        if orden not in ordenes_esperados:
            raise ValueError(
                f"La IA devolvió un orden inesperado: {orden}."
            )

        if orden in comentarios:
            raise ValueError(
                f"La IA devolvió dos veces el orden {orden}."
            )

        if not comentario:
            raise ValueError(
                f"El comentario del orden {orden} está vacío."
            )

        comentario = _limitar_comentario_palabras(
            comentario,
            max_palabras=100,
        )

        comentarios[orden] = comentario

    faltantes = ordenes_esperados - set(comentarios)

    if faltantes:
        raise ValueError(
            "Faltan comentarios para los órdenes: "
            + ", ".join(
                str(valor)
                for valor in sorted(faltantes)
            )
        )

    return comentarios


def _guardar_comentarios(
    lote: list[dict[str, Any]],
    comentarios: dict[int, str],
) -> int:
    """
    Guarda todos los comentarios del lote mediante un único UPDATE remoto.

    Con Turso evita una petición HTTP por pregunta y reduce cada lote a una
    sola escritura.
    """
    ids_por_orden = {
        int(pregunta["orden"]): int(
            pregunta["simulacro_pregunta_id"]
        )
        for pregunta in lote
    }

    pares: list[tuple[int, str]] = [
        (ids_por_orden[int(orden)], comentario)
        for orden, comentario in comentarios.items()
    ]

    if not pares:
        return 0

    clausulas_case = " ".join(
        "WHEN ? THEN ?"
        for _ in pares
    )
    marcadores_ids = ", ".join(
        "?"
        for _ in pares
    )

    parametros: list[Any] = []

    for simulacro_pregunta_id, comentario in pares:
        parametros.extend(
            (simulacro_pregunta_id, comentario)
        )

    parametros.extend(
        simulacro_pregunta_id
        for simulacro_pregunta_id, _ in pares
    )

    sql = f"""
        UPDATE simulacro_snapshot

        SET comentario_solucion = CASE simulacro_pregunta_id
            {clausulas_case}
            ELSE comentario_solucion
        END

        WHERE simulacro_pregunta_id IN ({marcadores_ids})
          AND (
                comentario_solucion IS NULL
                OR TRIM(comentario_solucion) = ''
              )
    """

    with conectar_usuario() as con:
        cursor = con.execute(
            sql,
            tuple(parametros),
        )

    return cursor.rowcount


def _procesar_lote_ia(
    numero_lote: int,
    lote: list[dict[str, Any]],
    modelo: str,
) -> dict[str, Any]:
    """
    Ejecuta la llamada a IA y valida la respuesta.

    Cada lote dispone de dos intentos. No escribe en Turso ni en los logs.
    """
    prompt = _crear_prompt(lote)
    respuesta: Any | None = None
    errores_intentos: list[str] = []
    tiempo_ia = 0.0
    llamadas_ia = 0

    for intento in (1, 2):
        try:
            inicio_ia = time.perf_counter()

            try:
                respuesta = seleccionar_fragmento_json(
                    prompt=prompt,
                    modelo=modelo,
                    operacion=OPERACION_IA,
                )
            finally:
                tiempo_ia += time.perf_counter() - inicio_ia
                llamadas_ia += 1

            comentarios = _validar_respuesta(
                respuesta,
                lote,
            )

            return {
                "numero_lote": numero_lote,
                "lote": lote,
                "prompt": prompt,
                "respuesta": respuesta,
                "comentarios": comentarios,
                "error": None,
                "tiempo_ia": tiempo_ia,
                "llamadas_ia": llamadas_ia,
                "intentos_fallidos": intento - 1,
            }

        except Exception as exc:
            errores_intentos.append(
                f"Intento {intento}: "
                f"{type(exc).__name__}: {exc}"
            )

    return {
        "numero_lote": numero_lote,
        "lote": lote,
        "prompt": prompt,
        "respuesta": respuesta,
        "comentarios": None,
        "error": "\n".join(errores_intentos),
        "tiempo_ia": tiempo_ia,
        "llamadas_ia": llamadas_ia,
        "intentos_fallidos": 2,
    }


def generar_comentarios_soluciones(
    simulacro_id: int,
    modelo: str = MODELO_PREDETERMINADO,
    tamano_lote: int = TAMANO_LOTE,
    progreso: Callable[[int, int, int], None] | None = None,
    max_trabajadores_ia: int = MAX_TRABAJADORES_IA,
) -> dict[str, Any]:
    """
    Genera y guarda comentarios jurídicos e informáticos para un simulacro.

    Los lotes de IA se procesan en paralelo. Las escrituras en Turso y los
    logs se realizan después, de forma secuencial y controlada.
    """
    inicio_total = time.perf_counter()

    tiempo_lectura_turso = 0.0
    tiempo_preparacion = 0.0
    tiempo_ia_acumulado = 0.0
    tiempo_ia_pared = 0.0
    tiempo_guardado_turso = 0.0
    tiempo_logs = 0.0
    llamadas_ia = 0
    intentos_fallidos = 0
    total_lotes = 0

    resumen: dict[str, Any] = {
        "simulacro_id": simulacro_id,
        "pendientes_iniciales": 0,
        "con_fuente": 0,
        "sin_fuente": [],
        "detalle_sin_fuente": [],
        "actualizadas": 0,
        "errores": [],
        "lotes_procesados": 0,
    }

    try:
        if simulacro_id <= 0:
            raise ValueError(
                "simulacro_id debe ser mayor que cero."
            )

        if tamano_lote <= 0:
            raise ValueError(
                "tamano_lote debe ser mayor que cero."
            )

        if max_trabajadores_ia <= 0:
            raise ValueError(
                "max_trabajadores_ia debe ser mayor que cero."
            )

        inicio = time.perf_counter()
        pendientes = _obtener_preguntas_pendientes(
            simulacro_id
        )
        tiempo_lectura_turso += time.perf_counter() - inicio

        inicio = time.perf_counter()
        (
            preparadas,
            sin_fuente,
            detalle_sin_fuente,
        ) = _preparar_preguntas(
            pendientes
        )
        tiempo_preparacion += time.perf_counter() - inicio

        resumen.update(
            {
                "pendientes_iniciales": len(pendientes),
                "con_fuente": len(preparadas),
                "sin_fuente": sin_fuente,
                "detalle_sin_fuente": detalle_sin_fuente,
            }
        )

        if not preparadas:
            if progreso is not None:
                progreso(0, 0, 0)

            return resumen

        lotes = list(
            _dividir_lotes(preparadas, tamano_lote)
        )
        total_lotes = len(lotes)

        resultados: dict[int, dict[str, Any]] = {}

        inicio_ia_pared = time.perf_counter()

        with ThreadPoolExecutor(
            max_workers=min(
                max_trabajadores_ia,
                total_lotes,
            )
        ) as executor:
            futuros = {
                executor.submit(
                    _procesar_lote_ia,
                    numero_lote,
                    lote,
                    modelo,
                ): numero_lote
                for numero_lote, lote in enumerate(
                    lotes,
                    start=1,
                )
            }

            for futuro in as_completed(futuros):
                resultado = futuro.result()
                numero_lote = int(
                    resultado["numero_lote"]
                )
                resultados[numero_lote] = resultado

                tiempo_ia_acumulado += float(
                    resultado["tiempo_ia"]
                )
                llamadas_ia += int(
                    resultado["llamadas_ia"]
                )
                intentos_fallidos += int(
                    resultado["intentos_fallidos"]
                )

        tiempo_ia_pared = (
            time.perf_counter() - inicio_ia_pared
        )

        for numero_lote in range(1, total_lotes + 1):
            resultado = resultados[numero_lote]
            lote = resultado["lote"]
            prompt = resultado["prompt"]
            respuesta = resultado["respuesta"]
            error = resultado["error"]

            if error is None:
                inicio = time.perf_counter()
                actualizadas = _guardar_comentarios(
                    lote,
                    resultado["comentarios"],
                )
                tiempo_guardado_turso += (
                    time.perf_counter() - inicio
                )

                resumen["actualizadas"] += actualizadas
                resumen["lotes_procesados"] += 1

                inicio = time.perf_counter()
                _guardar_log(
                    simulacro_id=simulacro_id,
                    numero_lote=numero_lote,
                    prompt=prompt,
                    respuesta=respuesta,
                )
                tiempo_logs += time.perf_counter() - inicio

            else:
                ordenes = [
                    int(pregunta["orden"])
                    for pregunta in lote
                ]

                resumen["errores"].append(
                    {
                        "lote": numero_lote,
                        "ordenes": ordenes,
                        "error": error,
                    }
                )

                inicio = time.perf_counter()
                _guardar_log(
                    simulacro_id=simulacro_id,
                    numero_lote=numero_lote,
                    prompt=prompt,
                    respuesta=respuesta,
                    error=error,
                )
                tiempo_logs += time.perf_counter() - inicio

            if progreso is not None:
                progreso(
                    numero_lote,
                    total_lotes,
                    resumen["actualizadas"],
                )

        return resumen

    finally:
        tiempo_total = time.perf_counter() - inicio_total

        print(
            "TIEMPOS comentarios soluciones"
            f" | total={tiempo_total:.2f}s"
            f" | lectura_turso={tiempo_lectura_turso:.2f}s"
            f" | preparacion={tiempo_preparacion:.2f}s"
            f" | ia_pared={tiempo_ia_pared:.2f}s"
            f" | ia_acumulada={tiempo_ia_acumulado:.2f}s"
            f" | guardado_turso={tiempo_guardado_turso:.2f}s"
            f" | logs={tiempo_logs:.2f}s"
            f" | lotes={total_lotes}"
            f" | llamadas_ia={llamadas_ia}"
            f" | intentos_fallidos={intentos_fallidos}"
            f" | tamano_lote={tamano_lote}"
            f" | trabajadores_ia={max_trabajadores_ia}"
            f" | pendientes={resumen['pendientes_iniciales']}"
            f" | preparadas={resumen['con_fuente']}"
            f" | sin_fuente_juridica={len(resumen['sin_fuente'])}"
            f" | actualizadas={resumen['actualizadas']}"
            f" | lotes_error={len(resumen['errores'])}",
            flush=True,
        )

        if resumen["sin_fuente"]:
            print(
                "PREGUNTAS JURIDICAS SIN FUENTE PARA COMENTARIO: "
                + ", ".join(
                    str(orden)
                    for orden in resumen["sin_fuente"]
                ),
                flush=True,
            )

            for detalle in resumen["detalle_sin_fuente"]:
                print(
                    "DIAGNOSTICO SIN FUENTE"
                    f" | orden={detalle['orden']}"
                    f" | tipo_clasificacion={detalle['tipo_clasificacion']!r}"
                    f" | tema_no_juridico={detalle['tema_no_juridico']!r}"
                    f" | nombre_norma={detalle['nombre_norma']!r}"
                    f" | norma_id_normalizada={detalle['norma_id_normalizada']!r}"
                    f" | articulo={detalle['articulo']!r}"
                    f" | articulo_normalizado={detalle['articulo_normalizado']!r}"
                    f" | enunciado={detalle['enunciado']!r}",
                    flush=True,
                )

        if resumen["errores"]:
            for error_lote in resumen["errores"]:
                print(
                    "ERROR COMENTARIOS LOTE "
                    f'{error_lote["lote"]}: '
                    f'{error_lote["error"]}',
                    flush=True,
                )