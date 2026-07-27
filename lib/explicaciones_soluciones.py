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
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from lib.database import conectar, conectar_usuario
from tools.openai_api import seleccionar_fragmento_json


TAMANO_LOTE = 16
MODELO_PREDETERMINADO = "gpt-5.4-mini"
OPERACION_IA = "comentarios_pdf_soluciones"

ROOT = Path(__file__).resolve().parents[1]
CARPETA_LOGS = ROOT / "logs" / "ia" / "soluciones"


INSTRUCCIONES = """
Eres preparador de oposiciones.

La respuesta correcta de cada pregunta ya está determinada. No debes resolver
la pregunta de nuevo ni cuestionar la respuesta indicada.

Recibirás preguntas de dos tipos: JURIDICA e INFORMATICA. Redacta un comentario
claro que explique por qué la opción indicada es correcta.

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

REGLAS PARA PREGUNTAS INFORMATICAS:
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
    Normaliza una referencia de artículo para poder comparar formatos como:
        53
        Artículo 53
        art. 53
        53.1
    """
    texto = _limpiar_texto(valor).lower()

    if not texto:
        return ""

    texto = texto.replace("artículo", "")
    texto = texto.replace("articulo", "")
    texto = re.sub(r"\bart\.?\b", "", texto)
    texto = re.sub(r"\s+", "", texto)
    texto = texto.rstrip(".")

    return texto


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

    for fila in filas:
        articulo_candidato = _normalizar_articulo(
            fila["articulo_solicitado"]
        )

        if articulo_candidato == articulo_buscado:
            texto = _limpiar_texto(fila["texto"])
            return texto or None

    return None


def _preparar_preguntas(
    preguntas: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[int]]:
    preparadas: list[dict[str, Any]] = []
    sin_fuente: list[int] = []

    for pregunta in preguntas:
        orden = int(pregunta["orden"])
        tipo_clasificacion = _limpiar_texto(
            pregunta.get("tipo_clasificacion")
        ).upper()

        es_informatica = tipo_clasificacion == "INFORMATICA"
        texto_fuente: str | None = None

        if not es_informatica:
            texto_fuente = _obtener_texto_articulo(
                pregunta.get("norma_id_normalizada"),
                pregunta.get("articulo_normalizado"),
            )

            if not texto_fuente:
                sin_fuente.append(orden)
                continue

        preparadas.append(
            {
                "simulacro_pregunta_id": int(
                    pregunta["simulacro_pregunta_id"]
                ),
                "orden": orden,
                "tipo_clasificacion": (
                    "INFORMATICA" if es_informatica else "JURIDICA"
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
                    "" if es_informatica else _limpiar_texto(
                        pregunta.get("nombre_norma")
                    )
                ),
                "articulo": (
                    "" if es_informatica else _limpiar_texto(
                        pregunta.get("articulo")
                    )
                ),
                "texto_fuente": texto_fuente or "",
            }
        )

    return preparadas, sin_fuente


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

        palabras = len(comentario.split())

        if palabras > 100:
            raise ValueError(
                f"El comentario del orden {orden} tiene "
                f"{palabras} palabras; el máximo es 100."
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
    ids_por_orden = {
        int(pregunta["orden"]): int(
            pregunta["simulacro_pregunta_id"]
        )
        for pregunta in lote
    }

    actualizados = 0

    with conectar_usuario() as con:
        # con.execute("BEGIN IMMEDIATE")

        for orden, comentario in comentarios.items():
            cursor = con.execute(
                """
                UPDATE simulacro_snapshot

                SET comentario_solucion = ?

                WHERE simulacro_pregunta_id = ?
                  AND (
                        comentario_solucion IS NULL
                        OR TRIM(comentario_solucion) = ''
                      )
                """,
                (
                    comentario,
                    ids_por_orden[orden],
                ),
            )

            actualizados += cursor.rowcount

    return actualizados


def generar_comentarios_soluciones(
    simulacro_id: int,
    modelo: str = MODELO_PREDETERMINADO,
    tamano_lote: int = TAMANO_LOTE,
    progreso: Callable[[int, int, int], None] | None = None,
) -> dict[str, Any]:
    """
    Genera y guarda comentarios jurídicos e informáticos para un simulacro.

    max_lotes:
        Permite limitar una prueba. Por ejemplo, max_lotes=1 procesa
        únicamente el primer lote pendiente.

    Devuelve un resumen de ejecución.
    """
    if simulacro_id <= 0:
        raise ValueError(
            "simulacro_id debe ser mayor que cero."
        )

    if tamano_lote <= 0:
        raise ValueError(
            "tamano_lote debe ser mayor que cero."
        )

    pendientes = _obtener_preguntas_pendientes(
        simulacro_id
    )

    preparadas, sin_fuente = _preparar_preguntas(
        pendientes
    )

    resumen: dict[str, Any] = {
        "simulacro_id": simulacro_id,
        "pendientes_iniciales": len(pendientes),
        "con_fuente": len(preparadas),
        "sin_fuente": sin_fuente,
        "actualizadas": 0,
        "errores": [],
        "lotes_procesados": 0,
    }

    if not preparadas:
        if progreso is not None:
            progreso(0, 0, 0)
        return resumen

    lotes = list(
        _dividir_lotes(preparadas, tamano_lote)
    )

    total_lotes = len(lotes)

    for numero_lote, lote in enumerate(
        lotes,
        start=1,
    ):
        prompt = _crear_prompt(lote)
        respuesta: None
        errores_intentos: list[str] = []
        lote_completado = False

        for intento in (1, 2):
            try:
                respuesta = seleccionar_fragmento_json(
                    prompt=prompt,
                    modelo=modelo,
                    operacion=OPERACION_IA,
                )

                comentarios = _validar_respuesta(
                    respuesta,
                    lote,
                )

                actualizadas = _guardar_comentarios(
                    lote,
                    comentarios,
                )

                resumen["actualizadas"] += actualizadas
                resumen["lotes_procesados"] += 1

                _guardar_log(
                    simulacro_id=simulacro_id,
                    numero_lote=numero_lote,
                    prompt=prompt,
                    respuesta=respuesta,
                )

                lote_completado = True

                if progreso is not None:
                    progreso(
                        numero_lote,
                        total_lotes,
                        resumen["actualizadas"],
                    )

                break

            except Exception as exc:
                errores_intentos.append(
                    f"Intento {intento}: "
                    f"{type(exc).__name__}: {exc}"
                )

        if not lote_completado:
            ordenes = [
                int(pregunta["orden"])
                for pregunta in lote
            ]
            texto_error = "\n".join(errores_intentos)

            resumen["errores"].append(
                {
                    "lote": numero_lote,
                    "ordenes": ordenes,
                    "error": texto_error,
                }
            )

            _guardar_log(
                simulacro_id=simulacro_id,
                numero_lote=numero_lote,
                prompt=prompt,
                respuesta=respuesta,
                error=texto_error,
            )

    return resumen