"""
==============================================================================
OpoCoach
Archivo: lib/chat_convocatoria.py
==============================================================================

Descripción:
    Recuperación del corpus jurídico de la convocatoria activa y generación
    de respuestas del chat especializado.

Lee:
    - oposiciones.sqlite3:
        convocatorias
        temarios
        temario_temas
        temario_referencias
        articulos_fuente

Escribe:
    - Ninguna tabla.

Utiliza:
    - lib.database
    - tools.openai_api

==============================================================================
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from lib.conocimiento_opocoach import (
    ENTRADAS_CONOCIMIENTO_OPOCOACH,
    EntradaConocimientoOpoCoach,
)
from lib.database import conectar
from tools.openai_api import seleccionar_fragmento, seleccionar_fragmento_json


MODELO_PREDETERMINADO = "gpt-5.4-nano"
OPERACION_IA = "chat_convocatoria"
OPERACION_IA_GENERAL = "chat_conocimiento_general"

MAX_FRAGMENTOS = 8
MAX_FRAGMENTOS_APLICACION = 4
MAX_CARACTERES_CONTEXTO = 30_000

# Recuperación semántica para consultas jurídicas conceptuales.
MAX_TERMINOS_SEMANTICOS = 12
MAX_CANDIDATOS_SEMANTICOS = 24
MAX_ARTICULOS_SEMANTICOS = 4
MAX_EXTRACTO_SEMANTICO = 700

PALABRAS_VACIAS = {
    "a", "al", "algo", "ante", "como", "con", "contra", "cual", "cuando",
    "de", "del", "desde", "donde", "dos", "el", "ella", "ellas", "ellos",
    "en", "entre", "era", "es", "esa", "ese", "eso", "esta", "este",
    "esto", "estos", "fue", "ha", "hay", "la", "las", "le", "les", "lo",
    "los", "más", "me", "mi", "muy", "no", "nos", "o", "para", "pero",
    "por", "porque", "que", "qué", "se", "según", "ser", "si", "sin",
    "sobre", "son", "su", "sus", "te", "tiene", "un", "una", "uno",
    "unos", "y", "ya",
}


@dataclass(frozen=True)
class FragmentoCorpus:
    articulo_fuente_id: int
    tema_id: int
    parte: str
    numero_tema: int
    titulo_tema: str
    nombre_norma: str
    articulo_solicitado: str
    articulo_boe: str
    titulo_bloque: str
    texto: str
    puntuacion: float


@dataclass(frozen=True)
class FragmentoAplicacion:
    clave: str
    titulo: str
    texto: str
    puntuacion: float


def _normalizar(texto: Any | None) -> str:
    valor = "" if texto is None else str(texto)
    valor = unicodedata.normalize("NFKD", valor)
    valor = "".join(
        caracter
        for caracter in valor
        if not unicodedata.combining(caracter)
    )
    valor = valor.lower()
    valor = re.sub(r"[^a-z0-9]+", " ", valor)
    return " ".join(valor.split())


def _terminos(texto: str) -> set[str]:
    return {
        termino
        for termino in _normalizar(texto).split()
        if len(termino) >= 3
        and termino not in PALABRAS_VACIAS
    }


def _extraer_articulos(pregunta: str) -> set[str]:
    """
    Detecta referencias como:
        artículo 14
        art. 14
        artículos 14 y 15
        artículos 30, 31, 32 y 33
        artículo 14.1

    Para esta extracción se conservan los puntos de los subapartados.
    """
    valor = unicodedata.normalize("NFKD", str(pregunta or ""))
    valor = "".join(
        caracter
        for caracter in valor
        if not unicodedata.combining(caracter)
    ).lower()

    encontrados: set[str] = set()
    patron_lista = (
        r"\bart(?:\.|iculo|iculos)?\s+"
        r"(\d+(?:\.\d+)*(?:\s*(?:,|y|e)\s*\d+(?:\.\d+)*)*)"
    )

    for bloque in re.findall(patron_lista, valor):
        for articulo in re.findall(r"\d+(?:\.\d+)*", bloque):
            encontrados.add(articulo.rstrip("."))

    return encontrados


def _extraer_normas(pregunta: str) -> set[str]:
    """
    Extrae identificadores frecuentes de normas:
        Ley 39/2015
        Decreto 123/2020
        Constitución
        Estatuto
    """
    normalizada = _normalizar(pregunta)
    normas: set[str] = set()

    for coincidencia in re.findall(
        r"\b(?:ley|decreto|real decreto|orden|reglamento)"
        r"\s+\d+\s+\d{4}\b",
        normalizada,
    ):
        normas.add(coincidencia)

    for termino in (
        "constitucion",
        "estatuto",
        "procedimiento administrativo",
        "transparencia",
        "subvenciones",
        "hacienda publica",
        "funcion publica",
        "proteccion de datos",
    ):
        if termino in normalizada:
            normas.add(termino)

    return normas


def _obtener_corpus_convocatoria(
    convocatoria_id: int,
) -> list[dict[str, Any]]:
    """
    Recupera el corpus jurídico utilizable por el Chat para una convocatoria.

    Una norma entra en el ámbito del Chat si aparece en temario_referencias
    de la convocatoria con estado COMPLETADO y norma_id informado. Su fuente
    documental se deduce sólo a partir de artículos ya enlazados y validados
    en el propio temario. Después se habilitan todos los artículos disponibles
    de esa misma fuente en articulos_fuente.

    Las referencias antiguas sin norma_id conservan el comportamiento previo.
    Esta función es de solo lectura.
    """
    with conectar() as con:
        filas = con.execute(
            """
            WITH fuentes_candidatas AS (
                SELECT
                    tr.norma_id,
                    af.id_boe,
                    COUNT(DISTINCT tr.id) AS enlaces_temario,
                    (
                        SELECT COUNT(*)
                        FROM articulos_fuente af_total
                        WHERE af_total.id_boe = af.id_boe
                          AND af_total.texto IS NOT NULL
                          AND TRIM(af_total.texto) <> ''
                    ) AS articulos_fuente_total
                FROM temarios t
                JOIN temario_temas tt
                    ON tt.temario_id = t.id
                JOIN temario_referencias tr
                    ON tr.tema_id = tt.id
                JOIN articulos_fuente af
                    ON af.id = tr.articulo_fuente_id
                WHERE t.convocatoria_id = ?
                  AND tr.estado = 'COMPLETADO'
                  AND tr.norma_id IS NOT NULL
                  AND af.texto IS NOT NULL
                  AND TRIM(af.texto) <> ''
                GROUP BY tr.norma_id, af.id_boe
            ),
            fuentes_principales AS (
                SELECT
                    norma_id,
                    id_boe,
                    ROW_NUMBER() OVER (
                        PARTITION BY norma_id
                        ORDER BY
                            articulos_fuente_total DESC,
                            enlaces_temario DESC,
                            id_boe
                    ) AS orden_fuente
                FROM fuentes_candidatas
            ),
            referencias_norma AS (
                SELECT DISTINCT
                    tt.id AS tema_id,
                    tt.parte,
                    tt.numero_tema,
                    tt.titulo AS titulo_tema,
                    tr.norma_id,
                    tr.nombre_norma_csv,
                    tr.nombre_norma_normalizada
                FROM temarios t
                JOIN temario_temas tt
                    ON tt.temario_id = t.id
                JOIN temario_referencias tr
                    ON tr.tema_id = tt.id
                WHERE t.convocatoria_id = ?
                  AND tr.estado = 'COMPLETADO'
                  AND tr.norma_id IS NOT NULL
            ),
            corpus_ampliado AS (
                SELECT DISTINCT
                    af.id AS articulo_fuente_id,
                    rn.tema_id,
                    rn.parte,
                    rn.numero_tema,
                    rn.titulo_tema,
                    rn.nombre_norma_csv,
                    rn.nombre_norma_normalizada,
                    af.articulo_boe AS articulo_solicitado,
                    af.articulo_boe,
                    af.titulo_bloque,
                    af.texto
                FROM referencias_norma rn
                JOIN fuentes_principales fp
                    ON fp.norma_id = rn.norma_id
                   AND fp.orden_fuente = 1
                JOIN articulos_fuente af
                    ON af.id_boe = fp.id_boe
                WHERE af.texto IS NOT NULL
                  AND TRIM(af.texto) <> ''
            ),
            corpus_legacy AS (
                SELECT DISTINCT
                    af.id AS articulo_fuente_id,
                    tt.id AS tema_id,
                    tt.parte,
                    tt.numero_tema,
                    tt.titulo AS titulo_tema,
                    tr.nombre_norma_csv,
                    tr.nombre_norma_normalizada,
                    tr.articulo_solicitado,
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
                  AND tr.estado = 'COMPLETADO'
                  AND tr.norma_id IS NULL
                  AND af.texto IS NOT NULL
                  AND TRIM(af.texto) <> ''
            )
            SELECT * FROM corpus_ampliado
            UNION
            SELECT * FROM corpus_legacy
            ORDER BY
                parte,
                numero_tema,
                nombre_norma_csv,
                articulo_solicitado
            """,
            (
                convocatoria_id,
                convocatoria_id,
                convocatoria_id,
            ),
        ).fetchall()

    return [dict(fila) for fila in filas]



def _nombre_norma_fila(fila: dict[str, Any]) -> str:
    return str(
        fila.get("nombre_norma_csv")
        or fila.get("nombre_norma_normalizada")
        or ""
    ).strip()


def _articulo_fila(fila: dict[str, Any]) -> str:
    return str(
        fila.get("articulo_boe")
        or fila.get("articulo_solicitado")
        or ""
    ).strip()


def _titulo_fila(fila: dict[str, Any]) -> str:
    return " ".join(str(fila.get("titulo_bloque") or "").split())


def _texto_fila(fila: dict[str, Any]) -> str:
    return " ".join(str(fila.get("texto") or "").split())


def _normas_disponibles_corpus(
    corpus: list[dict[str, Any]],
) -> list[str]:
    por_normalizado: dict[str, str] = {}

    for fila in corpus:
        nombre = _nombre_norma_fila(fila)
        clave = _normalizar(nombre)
        if clave and clave not in por_normalizado:
            por_normalizado[clave] = nombre

    return sorted(
        por_normalizado.values(),
        key=_normalizar,
    )


def _resolver_nombre_norma(
    solicitado: str,
    normas_disponibles: list[str],
) -> str | None:
    objetivo = _normalizar(solicitado)

    if not objetivo:
        return None

    for nombre in normas_disponibles:
        if _normalizar(nombre) == objetivo:
            return nombre

    candidatos = [
        nombre
        for nombre in normas_disponibles
        if objetivo in _normalizar(nombre)
        or _normalizar(nombre) in objetivo
    ]

    if len(candidatos) == 1:
        return candidatos[0]

    return None


def _seleccionar_norma_semantica(
    pregunta: str,
    corpus: list[dict[str, Any]],
) -> str | None:
    normas_disponibles = _normas_disponibles_corpus(corpus)

    # Si el usuario ya identifica inequívocamente una norma, no gastamos
    # una llamada IA para volver a seleccionarla.
    normas_explicitas = _extraer_normas(pregunta)
    if normas_explicitas:
        resueltas = []
        for valor in normas_explicitas:
            nombre = _resolver_nombre_norma(
                valor,
                normas_disponibles,
            )
            if nombre and nombre not in resueltas:
                resueltas.append(nombre)

        if len(resueltas) == 1:
            return resueltas[0]

    inventario = "\n".join(
        f"- {nombre}"
        for nombre in normas_disponibles
    )

    prompt = f"""
Actúas sólo como selector de norma para un sistema RAG jurídico.

PREGUNTA:
{pregunta}

NORMAS DISPONIBLES:
{inventario}

Selecciona la ÚNICA norma que contiene principalmente la regulación necesaria
para resolver la pregunta.

Reglas:
- No respondas la cuestión jurídica.
- No añadas normas de contexto general si una sola norma basta.
- No inventes normas ni uses ninguna que no esté en la lista.
- Si la pregunta no es jurídica o no necesita consultar una norma de la lista,
  devuelve null.
- Devuelve exclusivamente JSON válido:
{{"norma": "nombre de la norma o null"}}
""".strip()

    resultado = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_norma",
    )

    valor = resultado.get("norma")
    if valor is None:
        return None

    return _resolver_nombre_norma(
        str(valor),
        normas_disponibles,
    )


def _expandir_conceptos_semanticos(
    pregunta: str,
    norma: str,
) -> list[str]:
    prompt = f"""
Actúas sólo como generador de términos de búsqueda jurídica para un sistema RAG.

PREGUNTA:
{pregunta}

NORMA:
{norma}

Genera términos o expresiones jurídicas que probablemente aparezcan literalmente
en los artículos que contienen la respuesta.

Reglas:
- Incluye variantes nominales, verbales o técnicas de las ideas de la pregunta.
- Convierte lenguaje corriente en terminología jurídica probable.
- No indiques números de artículo.
- No respondas la pregunta.
- Máximo {MAX_TERMINOS_SEMANTICOS} términos o expresiones.
- Devuelve exclusivamente JSON válido:
{{"terminos": ["...", "..."]}}
""".strip()

    resultado = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_expandir_consulta",
    )

    bruto = resultado.get("terminos", [])
    if not isinstance(bruto, list):
        return []

    conceptos: list[str] = []

    for valor in bruto:
        concepto = _normalizar(valor)
        if concepto and concepto not in conceptos:
            conceptos.append(concepto)

    return conceptos[:MAX_TERMINOS_SEMANTICOS]


def _filas_unicas_norma(
    corpus: list[dict[str, Any]],
    norma: str,
) -> dict[str, dict[str, Any]]:
    objetivo = _normalizar(norma)
    por_articulo: dict[str, dict[str, Any]] = {}

    for fila in corpus:
        if _normalizar(_nombre_norma_fila(fila)) != objetivo:
            continue

        articulo = _articulo_fila(fila)
        if articulo and articulo not in por_articulo:
            por_articulo[articulo] = fila

    return por_articulo


def _puntuar_semantico_local(
    fila: dict[str, Any],
    pregunta: str,
    conceptos: list[str],
) -> tuple[float, list[str]]:
    titulo = _normalizar(_titulo_fila(fila))
    texto = _normalizar(_texto_fila(fila))

    terminos_pregunta = _terminos(pregunta)
    terminos_titulo = _terminos(titulo)
    terminos_texto = _terminos(texto)

    puntuacion = 0.0
    motivos: list[str] = []

    # Coincidencias originales: apoyo débil.
    for termino in terminos_pregunta:
        if termino in terminos_titulo:
            puntuacion += 5.0
        elif termino in terminos_texto:
            puntuacion += 1.0

    # Conceptos expandidos: apoyo fuerte, sobre todo si aparecen en la rúbrica.
    for concepto in conceptos:
        if concepto in titulo:
            puntuacion += 30.0
            motivos.append(f"T:{concepto}")
            continue

        if concepto in texto:
            puntuacion += 8.0
            motivos.append(f"X:{concepto}")
            continue

        tokens = _terminos(concepto)
        if not tokens:
            continue

        cobertura_titulo = len(tokens & terminos_titulo)
        cobertura_texto = len(tokens & terminos_texto)

        if cobertura_titulo:
            puntuacion += 7.0 * cobertura_titulo
            motivos.append(f"T~:{concepto}")
        elif cobertura_texto:
            puntuacion += 2.0 * cobertura_texto
            motivos.append(f"X~:{concepto}")

    return puntuacion, motivos


def _preseleccionar_semantico(
    por_articulo: dict[str, dict[str, Any]],
    pregunta: str,
    conceptos: list[str],
) -> list[tuple[float, str, dict[str, Any], list[str]]]:
    puntuados = []

    for articulo, fila in por_articulo.items():
        puntuacion, motivos = _puntuar_semantico_local(
            fila=fila,
            pregunta=pregunta,
            conceptos=conceptos,
        )

        if puntuacion <= 0:
            continue

        puntuados.append(
            (
                puntuacion,
                articulo,
                fila,
                motivos,
            )
        )

    def clave_orden(
        elemento: tuple[
            float,
            str,
            dict[str, Any],
            list[str],
        ],
    ) -> tuple[Any, ...]:
        puntuacion, articulo, _fila, _motivos = elemento
        prefijo = articulo.split(".")[0]
        numero = int(prefijo) if prefijo.isdigit() else 10**9

        return (
            -puntuacion,
            numero,
            articulo,
        )

    puntuados.sort(key=clave_orden)

    return puntuados[:MAX_CANDIDATOS_SEMANTICOS]


def _seleccionar_articulos_semanticos_finales(
    pregunta: str,
    norma: str,
    candidatos: list[
        tuple[
            float,
            str,
            dict[str, Any],
            list[str],
        ]
    ],
) -> list[str]:
    if not candidatos:
        return []

    bloques = []

    for _puntuacion, articulo, fila, _motivos in candidatos:
        extracto = _texto_fila(fila)[:MAX_EXTRACTO_SEMANTICO]
        bloques.append(
            "\n".join(
                [
                    f"[ARTÍCULO {articulo}]",
                    f"Rúbrica: {_titulo_fila(fila)}",
                    f"Extracto: {extracto}",
                ]
            )
        )

    inventario = "\n\n".join(bloques)

    prompt = f"""
Actúas únicamente como selector final de artículos para un sistema RAG jurídico.

PREGUNTA:
{pregunta}

NORMA:
{norma}

CANDIDATOS PRESELECCIONADOS:
{inventario}

Selecciona sólo los artículos cuyo texto sea realmente necesario o especialmente
útil para responder correctamente.

Reglas:
- No respondas la pregunta.
- No inventes artículos.
- Usa sólo candidatos de la lista.
- Prioriza la regla específica del supuesto y, cuando proceda, la regla general
  que deba combinarse con ella.
- No selecciones artículos sólo por palabras genéricas.
- Máximo {MAX_ARTICULOS_SEMANTICOS} artículos.
- Devuelve exclusivamente JSON válido:
{{"articulos": ["21", "94"]}}
""".strip()

    resultado = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_articulos",
    )

    bruto = resultado.get("articulos", [])
    if not isinstance(bruto, list):
        return []

    disponibles = {
        articulo
        for _puntuacion, articulo, _fila, _motivos
        in candidatos
    }

    seleccion: list[str] = []

    for valor in bruto:
        articulo = str(valor).strip()
        if articulo in disponibles and articulo not in seleccion:
            seleccion.append(articulo)

    return seleccion[:MAX_ARTICULOS_SEMANTICOS]


def _buscar_fragmentos_semanticos(
    corpus: list[dict[str, Any]],
    pregunta: str,
    max_fragmentos: int,
) -> list[FragmentoCorpus]:
    norma = _seleccionar_norma_semantica(
        pregunta=pregunta,
        corpus=corpus,
    )

    if not norma:
        return []

    por_articulo = _filas_unicas_norma(
        corpus=corpus,
        norma=norma,
    )

    if not por_articulo:
        return []

    conceptos = _expandir_conceptos_semanticos(
        pregunta=pregunta,
        norma=norma,
    )

    if not conceptos:
        return []

    candidatos = _preseleccionar_semantico(
        por_articulo=por_articulo,
        pregunta=pregunta,
        conceptos=conceptos,
    )

    seleccion_articulos = _seleccionar_articulos_semanticos_finales(
        pregunta=pregunta,
        norma=norma,
        candidatos=candidatos,
    )

    if not seleccion_articulos:
        return []

    salida: list[FragmentoCorpus] = []
    caracteres = 0

    for posicion, articulo in enumerate(
        seleccion_articulos,
        start=1,
    ):
        fila = por_articulo.get(articulo)
        if fila is None:
            continue

        texto = str(fila.get("texto") or "")
        longitud = len(texto)

        if (
            salida
            and caracteres + longitud > MAX_CARACTERES_CONTEXTO
        ):
            continue

        # Puntuación artificial sólo para conservar el orden decidido por el
        # reranking semántico. No altera ningún dato persistido.
        puntuacion = 1000.0 - float(posicion)

        salida.append(
            FragmentoCorpus(
                articulo_fuente_id=int(
                    fila["articulo_fuente_id"]
                ),
                tema_id=int(fila["tema_id"]),
                parte=str(fila["parte"]),
                numero_tema=int(fila["numero_tema"]),
                titulo_tema=str(fila["titulo_tema"]),
                nombre_norma=str(
                    fila["nombre_norma_csv"]
                    or fila["nombre_norma_normalizada"]
                ),
                articulo_solicitado=str(
                    fila["articulo_solicitado"]
                ),
                articulo_boe=str(fila["articulo_boe"]),
                titulo_bloque=str(fila["titulo_bloque"]),
                texto=texto,
                puntuacion=puntuacion,
            )
        )

        caracteres += longitud

        if len(salida) >= min(
            max_fragmentos,
            MAX_ARTICULOS_SEMANTICOS,
        ):
            break

    return salida

def _puntuar_fragmento(
    fila: dict[str, Any],
    pregunta: str,
    historial_usuario: list[str],
) -> float:
    pregunta_normalizada = _normalizar(pregunta)
    terminos_pregunta = _terminos(pregunta)
    articulos_pregunta = _extraer_articulos(pregunta)
    normas_pregunta = _extraer_normas(pregunta)

    historial_reciente = " ".join(historial_usuario[-3:])
    terminos_historial = _terminos(historial_reciente)

    nombre_norma = _normalizar(
        fila.get("nombre_norma_csv")
        or fila.get("nombre_norma_normalizada")
    )
    articulo_solicitado = _normalizar(
        fila.get("articulo_solicitado")
    )
    articulo_boe = _normalizar(fila.get("articulo_boe"))
    titulo_tema = _normalizar(fila.get("titulo_tema"))
    titulo_bloque = _normalizar(fila.get("titulo_bloque"))
    texto = _normalizar(fila.get("texto"))

    campos_cortos = " ".join(
        [
            nombre_norma,
            articulo_solicitado,
            articulo_boe,
            titulo_tema,
            titulo_bloque,
        ]
    )
    terminos_campos = _terminos(campos_cortos)
    terminos_texto = _terminos(texto)

    puntuacion = 0.0

    # Coincidencias explícitas de artículo.
    #
    # La comparación debe ser exacta. Una referencia al artículo 30 no puede
    # puntuar como coincidencia del artículo 330, por ejemplo.
    for articulo in articulos_pregunta:
        if (
            articulo == articulo_solicitado
            or articulo == articulo_boe
        ):
            puntuacion += 120.0

    # Coincidencias explícitas de norma.
    for norma in normas_pregunta:
        if norma in nombre_norma or norma in titulo_tema:
            puntuacion += 80.0

    # Coincidencias de términos en metadatos y texto.
    puntuacion += 10.0 * len(
        terminos_pregunta & terminos_campos
    )
    puntuacion += 2.0 * len(
        terminos_pregunta & terminos_texto
    )

    # El historial solo sirve como apoyo para preguntas de continuación.
    puntuacion += 1.0 * len(
        terminos_historial & terminos_campos
    )
    puntuacion += 0.25 * len(
        terminos_historial & terminos_texto
    )

    # Frases completas especialmente discriminantes.
    if pregunta_normalizada and pregunta_normalizada in texto:
        puntuacion += 50.0

    return puntuacion


def buscar_fragmentos(
    convocatoria_id: int,
    pregunta: str,
    historial_usuario: list[str] | None = None,
    max_fragmentos: int = MAX_FRAGMENTOS,
) -> list[FragmentoCorpus]:
    if convocatoria_id <= 0:
        raise ValueError(
            "convocatoria_id debe ser mayor que cero."
        )

    pregunta_limpia = " ".join(str(pregunta or "").split())

    if not pregunta_limpia:
        return []

    historial = historial_usuario or []
    corpus = _obtener_corpus_convocatoria(convocatoria_id)

    articulos_explicitos = _extraer_articulos(pregunta_limpia)
    normas_explicitas = _extraer_normas(pregunta_limpia)

    # Si el usuario identifica simultáneamente norma y artículo(s), esa
    # referencia explícita prevalece sobre coincidencias léxicas generales.
    # Sólo se aplica el filtro cuando existen candidatos que satisfacen ambas
    # condiciones, para no convertir una referencia no encontrada en un
    # resultado vacío artificial.
    if articulos_explicitos and normas_explicitas:
        corpus_explicito = []
        for fila in corpus:
            nombre_norma = _normalizar(
                fila.get("nombre_norma_csv")
                or fila.get("nombre_norma_normalizada")
            )
            articulo_solicitado = _normalizar(
                fila.get("articulo_solicitado")
            )
            articulo_boe = _normalizar(fila.get("articulo_boe"))

            coincide_norma = any(
                norma in nombre_norma
                for norma in normas_explicitas
            )
            coincide_articulo = any(
                articulo == articulo_solicitado
                or articulo == articulo_boe
                for articulo in articulos_explicitos
            )

            if coincide_norma and coincide_articulo:
                corpus_explicito.append(fila)

        if corpus_explicito:
            corpus = corpus_explicito
        else:
            # La combinación normativa explícita no existe en el corpus de
            # esta convocatoria. No se sustituye por el mismo artículo de
            # otra norma ni por otro artículo de una norma parecida.
            return []

    # Para consultas conceptuales sin artículo explícito, intentamos primero
    # recuperación semántica. Si no obtiene una selección válida, conservamos
    # como fallback el ranking léxico tradicional.
    if not articulos_explicitos:
        semanticos = _buscar_fragmentos_semanticos(
            corpus=corpus,
            pregunta=pregunta_limpia,
            max_fragmentos=max_fragmentos,
        )
        if semanticos:
            return semanticos

    puntuados: list[FragmentoCorpus] = []

    for fila in corpus:
        puntuacion = _puntuar_fragmento(
            fila=fila,
            pregunta=pregunta_limpia,
            historial_usuario=historial,
        )

        if puntuacion <= 0:
            continue

        puntuados.append(
            FragmentoCorpus(
                articulo_fuente_id=int(
                    fila["articulo_fuente_id"]
                ),
                tema_id=int(fila["tema_id"]),
                parte=str(fila["parte"]),
                numero_tema=int(fila["numero_tema"]),
                titulo_tema=str(fila["titulo_tema"]),
                nombre_norma=str(
                    fila["nombre_norma_csv"]
                    or fila["nombre_norma_normalizada"]
                ),
                articulo_solicitado=str(
                    fila["articulo_solicitado"]
                ),
                articulo_boe=str(fila["articulo_boe"]),
                titulo_bloque=str(fila["titulo_bloque"]),
                texto=str(fila["texto"]),
                puntuacion=puntuacion,
            )
        )

    puntuados.sort(
        key=lambda elemento: (
            -elemento.puntuacion,
            elemento.parte,
            elemento.numero_tema,
            elemento.nombre_norma,
            elemento.articulo_solicitado,
        )
    )

    seleccionados: list[FragmentoCorpus] = []
    ids_usados: set[int] = set()
    caracteres = 0

    for fragmento in puntuados:
        if fragmento.articulo_fuente_id in ids_usados:
            continue

        longitud = len(fragmento.texto)

        if (
            seleccionados
            and caracteres + longitud > MAX_CARACTERES_CONTEXTO
        ):
            continue

        seleccionados.append(fragmento)
        ids_usados.add(fragmento.articulo_fuente_id)
        caracteres += longitud

        if len(seleccionados) >= max_fragmentos:
            break

    return seleccionados



def _puntuar_entrada_aplicacion(
    entrada: EntradaConocimientoOpoCoach,
    pregunta: str,
    historial_usuario: list[str],
) -> float:
    pregunta_normalizada = _normalizar(pregunta)
    terminos_pregunta = _terminos(pregunta)
    historial_reciente = " ".join(historial_usuario[-3:])
    terminos_historial = _terminos(historial_reciente)

    titulo = _normalizar(entrada.titulo)
    palabras_clave = " ".join(
        _normalizar(valor)
        for valor in entrada.palabras_clave
    )
    texto = _normalizar(entrada.texto)

    terminos_metadatos = _terminos(
        titulo + " " + palabras_clave
    )
    terminos_texto = _terminos(texto)

    coincidencias_metadatos = (
        terminos_pregunta & terminos_metadatos
    )
    coincidencias_texto = terminos_pregunta & terminos_texto

    puntuacion = 0.0
    puntuacion += 12.0 * len(coincidencias_metadatos)
    puntuacion += 2.0 * len(coincidencias_texto)
    puntuacion += 1.0 * len(
        terminos_historial & terminos_metadatos
    )
    puntuacion += 0.25 * len(
        terminos_historial & terminos_texto
    )

    for expresion in entrada.palabras_clave:
        expresion_normalizada = _normalizar(expresion)
        if (
            expresion_normalizada
            and expresion_normalizada in pregunta_normalizada
        ):
            puntuacion += 35.0

    return puntuacion


def buscar_fragmentos_aplicacion(
    pregunta: str,
    historial_usuario: list[str] | None = None,
    max_fragmentos: int = MAX_FRAGMENTOS_APLICACION,
) -> list[FragmentoAplicacion]:
    pregunta_limpia = " ".join(str(pregunta or "").split())

    if not pregunta_limpia:
        return []

    historial = historial_usuario or []
    puntuados: list[FragmentoAplicacion] = []

    for entrada in ENTRADAS_CONOCIMIENTO_OPOCOACH:
        puntuacion = _puntuar_entrada_aplicacion(
            entrada=entrada,
            pregunta=pregunta_limpia,
            historial_usuario=historial,
        )

        # Evita incorporar el manual por coincidencias demasiado débiles.
        if puntuacion < 18.0:
            continue

        puntuados.append(
            FragmentoAplicacion(
                clave=entrada.clave,
                titulo=entrada.titulo,
                texto=entrada.texto,
                puntuacion=puntuacion,
            )
        )

    puntuados.sort(
        key=lambda elemento: (
            -elemento.puntuacion,
            elemento.titulo,
        )
    )

    return puntuados[:max_fragmentos]


def _crear_contexto_aplicacion(
    fragmentos: list[FragmentoAplicacion],
    indice_inicial: int,
) -> str:
    bloques: list[str] = []

    for desplazamiento, fragmento in enumerate(fragmentos):
        indice = indice_inicial + desplazamiento
        bloques.append(
            "\n".join(
                [
                    f"[FUENTE {indice} — FUNCIONAMIENTO OPOCOACH]",
                    f"Apartado: {fragmento.titulo}",
                    "Texto:",
                    fragmento.texto,
                ]
            )
        )

    return "\n\n".join(bloques)



def _crear_contexto(
    fragmentos: list[FragmentoCorpus],
) -> str:
    bloques: list[str] = []

    for indice, fragmento in enumerate(
        fragmentos,
        start=1,
    ):
        bloques.append(
            "\n".join(
                [
                    f"[FUENTE {indice} — CORPUS CONVOCATORIA]",
                    (
                        f"Tema: {fragmento.parte} "
                        f"{fragmento.numero_tema}. "
                        f"{fragmento.titulo_tema}"
                    ),
                    f"Norma: {fragmento.nombre_norma}",
                    (
                        f"Artículo solicitado: "
                        f"{fragmento.articulo_solicitado}"
                    ),
                    f"Artículo BOE: {fragmento.articulo_boe}",
                    f"Encabezado: {fragmento.titulo_bloque}",
                    "Texto:",
                    fragmento.texto,
                ]
            )
        )

    return "\n\n".join(bloques)


def _crear_historial(
    mensajes: list[dict[str, str]],
    max_mensajes: int = 8,
) -> str:
    recientes = mensajes[-max_mensajes:]
    lineas: list[str] = []

    for mensaje in recientes:
        rol = mensaje.get("role")
        contenido = " ".join(
            str(mensaje.get("content") or "").split()
        )

        if not contenido:
            continue

        if rol == "user":
            lineas.append(f"USUARIO: {contenido}")
        elif rol == "assistant":
            lineas.append(f"ASISTENTE: {contenido}")

    return "\n".join(lineas)



def _normalizar_formato_respuesta(respuesta: str) -> str:
    """
    Normaliza de forma determinista el formato visual de las respuestas.

    El prompt pide evitar encabezados Markdown grandes, pero el modelo puede
    generarlos ocasionalmente. Este postproceso convierte cualquier encabezado
    Markdown (#, ##, ###, etc.) en un apartado breve en negrita.
    """
    lineas = []

    for linea in str(respuesta or "").splitlines():
        coincidencia = re.match(
            r"^\s*#{1,6}\s+(.+?)\s*$",
            linea,
        )

        if coincidencia:
            titulo = coincidencia.group(1).strip()
            linea = f"**{titulo}**"

        lineas.append(linea)

    return "\n".join(lineas).strip()



def responder_chat_general(
    pregunta: str,
    mensajes_previos: list[dict[str, str]] | None = None,
    modelo: str = MODELO_PREDETERMINADO,
) -> dict[str, Any]:
    pregunta_limpia = " ".join(str(pregunta or "").split())

    if not pregunta_limpia:
        raise ValueError("La pregunta está vacía.")

    mensajes = mensajes_previos or []
    historial = _crear_historial(mensajes)

    instrucciones = """
Eres el asistente general de OpoCoach.

En este modo puedes responder utilizando tu conocimiento general. La respuesta
no está limitada al corpus de la convocatoria ni a la base de conocimiento de
OpoCoach.

Reglas obligatorias:
- Responde en español.
- Sé claro, directo y proporcionado a la pregunta.
- No presentes como contenido oficial de la convocatoria aquello que proceda
  de conocimiento general.
- No afirmes que una respuesta está respaldada por el corpus o por el temario.
- Cuando la pregunta sea jurídica, indica que se trata de una explicación
  general y que debe contrastarse con la normativa vigente y con el corpus de
  la convocatoria.
- No des asesoramiento jurídico personalizado para casos reales.
- Si la información puede depender de datos actuales y no puedes comprobarlos,
  advierte de esa limitación.
- Al final añade exactamente esta línea:
  Fuente: conocimiento general de GPT; respuesta no limitada al corpus de la convocatoria.
""".strip()

    prompt = (
        instrucciones
        + "\n\nHISTORIAL RECIENTE:\n"
        + (historial or "(sin historial)")
        + "\n\nPREGUNTA ACTUAL:\n"
        + pregunta_limpia
    )

    respuesta = seleccionar_fragmento(
        prompt=prompt,
        modelo=modelo,
        operacion=OPERACION_IA_GENERAL,
    ).strip()
    respuesta = _normalizar_formato_respuesta(respuesta)

    return {
        "respuesta": respuesta,
        "fuentes": [],
        "modelo": modelo,
        "modo": "GENERAL",
    }


def responder_chat(
    convocatoria_id: int,
    pregunta: str,
    mensajes_previos: list[dict[str, str]] | None = None,
    modelo: str = MODELO_PREDETERMINADO,
    modo: str = "CONVOCATORIA",
) -> dict[str, Any]:
    modo_normalizado = str(modo or "CONVOCATORIA").strip().upper()

    if modo_normalizado == "GENERAL":
        return responder_chat_general(
            pregunta=pregunta,
            mensajes_previos=mensajes_previos,
            modelo=modelo,
        )

    if modo_normalizado != "CONVOCATORIA":
        raise ValueError(
            "El modo debe ser CONVOCATORIA o GENERAL."
        )

    pregunta_limpia = " ".join(str(pregunta or "").split())

    if not pregunta_limpia:
        raise ValueError("La pregunta está vacía.")

    mensajes = mensajes_previos or []

    historial_usuario = [
        str(mensaje.get("content") or "")
        for mensaje in mensajes
        if mensaje.get("role") == "user"
    ]

    fragmentos = buscar_fragmentos(
        convocatoria_id=convocatoria_id,
        pregunta=pregunta_limpia,
        historial_usuario=historial_usuario,
    )

    tiene_referencia_normativa = bool(
        _extraer_articulos(pregunta_limpia)
        or _extraer_normas(pregunta_limpia)
    )

    fragmentos_aplicacion = (
        []
        if tiene_referencia_normativa
        else buscar_fragmentos_aplicacion(
            pregunta=pregunta_limpia,
            historial_usuario=historial_usuario,
        )
    )

    if not fragmentos and not fragmentos_aplicacion:
        tiene_referencia_normativa = bool(
            _extraer_articulos(pregunta_limpia)
            or _extraer_normas(pregunta_limpia)
        )

        if tiene_referencia_normativa:
            respuesta_sin_fuente = (
                "La norma o los artículos indicados no forman parte del corpus "
                "asignado a esta convocatoria. Si desea información general "
                "sobre esa norma, puede cambiar al modo "
                "\"Conocimiento general de GPT\"."
            )
        else:
            respuesta_sin_fuente = (
                "No he encontrado información suficiente en el corpus "
                "asignado a esta convocatoria ni en la base de conocimiento "
                "de OpoCoach para responder con seguridad."
            )

        return {
            "respuesta": respuesta_sin_fuente,
            "fuentes": [],
            "modelo": None,
            "modo": "CONVOCATORIA",
        }

    bloques_contexto: list[str] = []

    if fragmentos:
        bloques_contexto.append(_crear_contexto(fragmentos))

    if fragmentos_aplicacion:
        bloques_contexto.append(
            _crear_contexto_aplicacion(
                fragmentos_aplicacion,
                indice_inicial=len(fragmentos) + 1,
            )
        )

    contexto = "\n\n".join(bloques_contexto)
    historial = _crear_historial(mensajes)

    instrucciones = """
Eres el asistente especializado de OpoCoach y de la convocatoria activa.

Debes responder exclusivamente con la información contenida en las FUENTES
proporcionadas. Las fuentes pueden ser de dos tipos:
- CORPUS CONVOCATORIA: contenido normativo o de estudio de la convocatoria.
- FUNCIONAMIENTO OPOCOACH: explicaciones sobre el uso de la aplicación.

Puedes:
- aclarar conceptos;
- explicar artículos y normas con lenguaje más claro;
- explicar cómo funciona OpoCoach y cómo interpretar sus elementos;
- poner ejemplos didácticos coherentes con las fuentes;
- ampliar una explicación anterior;
- relacionar varias fuentes recuperadas cuando resulte necesario.

Reglas obligatorias:
- Actúa ante el usuario como un asistente especializado en el temario y en la
  normativa de la convocatoria. No describas el mecanismo interno de recuperación
  de información, el corpus, el RAG, los fragmentos recuperados ni limitaciones
  técnicas internas.
- No uses conocimiento externo.
- No inventes contenido ausente.
- No atribuyas a una norma, artículo o manual algo que no esté respaldado por el
  contenido disponible.
- Si la normativa disponible no permite sostener una conclusión concreta,
  expresa la cautela en términos jurídicos y naturales. Por ejemplo:
  "La Ley no establece específicamente...", "De estos preceptos no se desprende..."
  o "No puede concluirse de la normativa aplicable...".
- No digas al usuario expresiones como "tus fuentes", "las fuentes aportadas",
  "con lo disponible", "los fragmentos", "el corpus no contiene" o equivalentes,
  salvo que el propio usuario haya aportado expresamente documentos y pregunte
  por ellos.
- Si la pregunta es ajena a la convocatoria y al funcionamiento de OpoCoach,
  recházala brevemente.
- Distingue con claridad el contenido normativo de los ejemplos explicativos.
- No des asesoramiento jurídico para casos reales.
- En preguntas de continuación, usa el HISTORIAL RECIENTE para conservar el
  asunto, la norma y los conceptos ya establecidos. No repitas desde cero la
  explicación anterior salvo que sea necesario para responder con claridad.
- Responde primero a lo nuevo que pregunta el usuario y después añade sólo el
  contexto previo imprescindible.
- Responde en español.
- Sé claro, directo y proporcionado a la pregunta.
- Evita encabezados Markdown grandes (#, ##, ###). Si necesitas estructurar la
  respuesta, usa apartados breves en negrita, por ejemplo:
  **1. Obligación de resolver**
- No abuses de listas: úsalas sólo cuando mejoren la claridad.
- Cuando cites varios apartados de un mismo artículo, agrúpalos de forma compacta
  y natural, por ejemplo: "art. 94.1, 94.4 y 94.5".
- Cuando el usuario pregunte cómo realizar una acción dentro de OpoCoach,
  responde primero con los pasos concretos indicados en las fuentes; no te
  limites a describir la función o el contenido del elemento.
- Al final añade una línea breve titulada "Fuentes consultadas:". Para fuentes
  normativas, indica norma y artículo o apartados realmente utilizados, evitando
  repetir innecesariamente el nombre de la norma. Para fuentes de funcionamiento,
  indica "Manual de OpoCoach" y el nombre del apartado realmente utilizado.
""".strip()

    prompt = (
        instrucciones
        + "\n\nHISTORIAL RECIENTE:\n"
        + (historial or "(sin historial)")
        + "\n\nPREGUNTA ACTUAL:\n"
        + pregunta_limpia
        + "\n\nFUENTES DISPONIBLES:\n"
        + contexto
    )

    respuesta = seleccionar_fragmento(
        prompt=prompt,
        modelo=modelo,
        operacion=OPERACION_IA,
    ).strip()
    respuesta = _normalizar_formato_respuesta(respuesta)

    fuentes = [
        {
            "tipo": "CORPUS_CONVOCATORIA",
            "tema": (
                f"{fragmento.parte} "
                f"{fragmento.numero_tema}"
            ),
            "titulo_tema": fragmento.titulo_tema,
            "norma": fragmento.nombre_norma,
            "articulo": fragmento.articulo_solicitado,
            "articulo_boe": fragmento.articulo_boe,
        }
        for fragmento in fragmentos
    ]

    fuentes.extend(
        {
            "tipo": "FUNCIONAMIENTO_OPOCOACH",
            "clave": fragmento.clave,
            "titulo": fragmento.titulo,
        }
        for fragmento in fragmentos_aplicacion
    )

    return {
        "respuesta": respuesta,
        "fuentes": fuentes,
        "modelo": modelo,
        "modo": "CONVOCATORIA",
    }