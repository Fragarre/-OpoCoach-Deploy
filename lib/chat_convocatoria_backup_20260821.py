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
from tools.openai_api import seleccionar_fragmento


MODELO_PREDETERMINADO = "gpt-5.4-nano"
OPERACION_IA = "chat_convocatoria"
OPERACION_IA_GENERAL = "chat_conocimiento_general"

MAX_FRAGMENTOS = 8
MAX_FRAGMENTOS_APLICACION = 4
MAX_CARACTERES_CONTEXTO = 30_000

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
        14.1
    """
    normalizada = _normalizar(pregunta)
    encontrados: set[str] = set()

    patrones = [
        r"\bart(?:iculo|iculos)?\s+(\d+(?:\.\d+)*)",
        r"\bart\s+(\d+(?:\.\d+)*)",
    ]

    for patron in patrones:
        for coincidencia in re.findall(patron, normalizada):
            encontrados.add(coincidencia.rstrip("."))

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
    with conectar() as con:
        filas = con.execute(
            """
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
              AND af.texto IS NOT NULL
              AND TRIM(af.texto) <> ''

            ORDER BY
                tt.parte,
                tt.numero_tema,
                tr.nombre_norma_csv,
                tr.articulo_solicitado
            """,
            (convocatoria_id,),
        ).fetchall()

    return [dict(fila) for fila in filas]


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
    for articulo in articulos_pregunta:
        if (
            articulo == articulo_solicitado
            or articulo in articulo_boe
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

    fragmentos_aplicacion = buscar_fragmentos_aplicacion(
        pregunta=pregunta_limpia,
        historial_usuario=historial_usuario,
    )

    if not fragmentos and not fragmentos_aplicacion:
        return {
            "respuesta": (
                "No he encontrado información suficiente en el corpus "
                "asignado a esta convocatoria ni en la base de conocimiento "
                "de OpoCoach para responder con seguridad."
            ),
            "fuentes": [],
            "modelo": None,
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
- No uses conocimiento externo.
- No inventes contenido ausente.
- No afirmes que una fuente dice algo que no aparece en ella.
- Si las fuentes no bastan, indícalo expresamente.
- Si la pregunta es ajena a la convocatoria y al funcionamiento de OpoCoach,
  recházala brevemente.
- Distingue con claridad el contenido normativo de los ejemplos explicativos.
- No des asesoramiento jurídico para casos reales.
- Responde en español.
- Sé claro, directo y proporcionado a la pregunta.
- Cuando el usuario pregunte cómo realizar una acción dentro de OpoCoach,
  responde primero con los pasos concretos indicados en las fuentes; no te
  limites a describir la función o el contenido del elemento.
- Al final añade una línea breve titulada "Fuentes consultadas:". Para fuentes
  normativas, indica norma y artículo. Para fuentes de funcionamiento, indica
  "Manual de OpoCoach" y el nombre del apartado realmente utilizado.
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