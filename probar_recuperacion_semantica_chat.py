"""
Prueba aislada de recuperación semántica para el Chat de OpoCoach.

SOLO LECTURA:
- No modifica SQLite.
- No modifica archivos del proyecto.
- Sí realiza llamadas reales a la API de OpenAI y registra su coste mediante
  la infraestructura ya existente de OpoCoach.

Ejecutar desde la raíz de OpoCoach:
    python probar_recuperacion_semantica_chat.py
"""

from __future__ import annotations

from collections import defaultdict

from lib.chat_convocatoria import (
    MODELO_PREDETERMINADO,
    _normalizar,
    _obtener_corpus_convocatoria,
)
from tools.openai_api import seleccionar_fragmento_json


CONVOCATORIA_ID = 2

PREGUNTA = (
    "Si una persona presenta una solicitud ante la Administración y posteriormente "
    "desiste de ella. ¿Está obligada la Administración a dictar una resolución "
    "expresa? En caso afirmativo, ¿qué debe contener esa resolución? "
    "Razona la respuesta indicando los artículos aplicables."
)

MAX_NORMAS = 3
MAX_ARTICULOS = 8


def nombre_norma(fila: dict) -> str:
    return str(
        fila.get("nombre_norma_csv")
        or fila.get("nombre_norma_normalizada")
        or ""
    ).strip()


def articulo(fila: dict) -> str:
    return str(
        fila.get("articulo_boe")
        or fila.get("articulo_solicitado")
        or ""
    ).strip()


def titulo(fila: dict) -> str:
    return " ".join(str(fila.get("titulo_bloque") or "").split())


def deduplicar_normas(corpus: list[dict]) -> list[str]:
    por_normalizado: dict[str, str] = {}

    for fila in corpus:
        nombre = nombre_norma(fila)
        clave = _normalizar(nombre)
        if clave and clave not in por_normalizado:
            por_normalizado[clave] = nombre

    return sorted(por_normalizado.values(), key=_normalizar)


def resolver_nombre_norma(
    solicitado: str,
    normas_disponibles: list[str],
) -> str | None:
    objetivo = _normalizar(solicitado)
    if not objetivo:
        return None

    # Coincidencia exacta normalizada.
    for nombre in normas_disponibles:
        if _normalizar(nombre) == objetivo:
            return nombre

    # Coincidencia por inclusión, útil si la IA devuelve "Ley 39/2015"
    # y el corpus guarda "Ley 39/2015, de 1 de octubre".
    candidatos = [
        nombre
        for nombre in normas_disponibles
        if objetivo in _normalizar(nombre)
        or _normalizar(nombre) in objetivo
    ]

    if len(candidatos) == 1:
        return candidatos[0]

    return None


def seleccionar_normas(
    pregunta: str,
    normas_disponibles: list[str],
) -> list[str]:
    inventario = "\n".join(
        f"- {nombre}" for nombre in normas_disponibles
    )

    prompt = f"""
Actúas únicamente como selector de fuentes jurídicas para un sistema RAG.

PREGUNTA DEL USUARIO:
{pregunta}

NORMAS DISPONIBLES EN EL CORPUS DE ESTA CONVOCATORIA:
{inventario}

TAREA:
Selecciona sólo las normas que pueden contener los preceptos necesarios para
resolver jurídicamente la pregunta.

Reglas:
- No respondas la pregunta.
- No uses normas que no estén en la lista.
- No inventes normas.
- Selecciona como máximo {MAX_NORMAS}.
- Si una sola norma basta, selecciona sólo esa.
- Devuelve exclusivamente JSON válido con esta forma:
{{"normas": ["nombre exacto o suficientemente identificable"]}}
""".strip()

    resultado = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_normas",
    )

    bruto = resultado.get("normas", [])
    if not isinstance(bruto, list):
        raise ValueError("La selección de normas no devolvió una lista.")

    resueltas: list[str] = []
    for valor in bruto:
        nombre = resolver_nombre_norma(str(valor), normas_disponibles)
        if nombre and nombre not in resueltas:
            resueltas.append(nombre)

    return resueltas[:MAX_NORMAS]


def inventario_articulos(
    corpus: list[dict],
    normas_seleccionadas: list[str],
) -> tuple[str, dict[tuple[str, str], dict]]:
    claves_norma = {
        _normalizar(nombre): nombre
        for nombre in normas_seleccionadas
    }

    por_clave: dict[tuple[str, str], dict] = {}

    for fila in corpus:
        nombre = nombre_norma(fila)
        nombre_n = _normalizar(nombre)

        norma_resuelta = None
        for clave, original in claves_norma.items():
            if clave == nombre_n:
                norma_resuelta = original
                break

        if not norma_resuelta:
            continue

        art = articulo(fila)
        if not art:
            continue

        clave_fila = (norma_resuelta, art)
        if clave_fila not in por_clave:
            por_clave[clave_fila] = fila

    lineas = []
    for (norma, art), fila in sorted(
        por_clave.items(),
        key=lambda item: (
            _normalizar(item[0][0]),
            item[0][1],
        ),
    ):
        lineas.append(
            f"- {norma} | art. {art} | {titulo(fila)}"
        )

    return "\n".join(lineas), por_clave


def seleccionar_articulos(
    pregunta: str,
    inventario: str,
    por_clave: dict[tuple[str, str], dict],
) -> list[tuple[str, str]]:
    prompt = f"""
Actúas únicamente como selector de artículos jurídicos para un sistema RAG.

PREGUNTA DEL USUARIO:
{pregunta}

ARTÍCULOS DISPONIBLES DE LAS NORMAS YA SELECCIONADAS:
{inventario}

TAREA:
Selecciona los artículos cuyo texto sea necesario o especialmente útil para
resolver correctamente la pregunta.

Reglas:
- No respondas la pregunta.
- No inventes artículos.
- Usa sólo artículos del inventario.
- Prioriza los preceptos directamente aplicables al supuesto.
- Incluye varios artículos si la respuesta requiere combinar reglas.
- No selecciones artículos sólo porque compartan palabras genéricas como
  "Administración", "solicitud" o "resolución".
- Selecciona como máximo {MAX_ARTICULOS}.
- Devuelve exclusivamente JSON válido con esta forma:
{{
  "articulos": [
    {{"norma": "nombre de la norma", "articulo": "número"}}
  ]
}}
""".strip()

    resultado = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_articulos",
    )

    bruto = resultado.get("articulos", [])
    if not isinstance(bruto, list):
        raise ValueError("La selección de artículos no devolvió una lista.")

    disponibles = {
        (_normalizar(norma), str(art).strip()): (norma, art)
        for norma, art in por_clave
    }

    seleccion: list[tuple[str, str]] = []

    for item in bruto:
        if not isinstance(item, dict):
            continue

        norma = _normalizar(item.get("norma"))
        art = str(item.get("articulo") or "").strip()

        # Primero intentamos coincidencia exacta de norma normalizada.
        clave = (norma, art)
        encontrado = disponibles.get(clave)

        # Después permitimos inclusión inequívoca del nombre.
        if encontrado is None:
            candidatos = [
                valor
                for (norma_disp, art_disp), valor in disponibles.items()
                if art_disp == art
                and (
                    norma in norma_disp
                    or norma_disp in norma
                )
            ]
            if len(candidatos) == 1:
                encontrado = candidatos[0]

        if encontrado and encontrado not in seleccion:
            seleccion.append(encontrado)

    return seleccion[:MAX_ARTICULOS]


def main() -> int:
    print("=" * 78)
    print("PRUEBA RECUPERACIÓN SEMÁNTICA DEL CHAT - SOLO LECTURA")
    print("=" * 78)
    print(f"Convocatoria: {CONVOCATORIA_ID}")
    print(f"Modelo:       {MODELO_PREDETERMINADO}")
    print(f"Pregunta:     {PREGUNTA}")
    print()

    corpus = _obtener_corpus_convocatoria(CONVOCATORIA_ID)
    normas = deduplicar_normas(corpus)

    print(f"Filas del corpus:      {len(corpus)}")
    print(f"Normas disponibles:    {len(normas)}")
    print()

    print("-" * 78)
    print("FASE 1 - SELECCIÓN SEMÁNTICA DE NORMA(S)")
    print("-" * 78)

    normas_seleccionadas = seleccionar_normas(PREGUNTA, normas)

    if not normas_seleccionadas:
        print("La IA no seleccionó ninguna norma válida del inventario.")
        return 1

    for nombre in normas_seleccionadas:
        print(f"  - {nombre}")

    print()

    inventario, por_clave = inventario_articulos(
        corpus,
        normas_seleccionadas,
    )

    print("-" * 78)
    print("FASE 2 - SELECCIÓN SEMÁNTICA DE ARTÍCULO(S)")
    print("-" * 78)
    print(f"Artículos candidatos: {len(por_clave)}")

    articulos_seleccionados = seleccionar_articulos(
        PREGUNTA,
        inventario,
        por_clave,
    )

    if not articulos_seleccionados:
        print("La IA no seleccionó ningún artículo válido del inventario.")
        return 1

    print()
    print("Artículos seleccionados:")
    for norma, art in articulos_seleccionados:
        fila = por_clave[(norma, art)]
        print(f"  - {norma} | art. {art} | {titulo(fila)}")

    print()
    print("-" * 78)
    print("COMPROBACIÓN DEL CASO DE CONTROL")
    print("-" * 78)

    control_21 = any(
        "ley 39 2015" in _normalizar(norma) and art == "21"
        for norma, art in articulos_seleccionados
    )
    control_94 = any(
        "ley 39 2015" in _normalizar(norma) and art == "94"
        for norma, art in articulos_seleccionados
    )

    print(f"Ley 39/2015 art. 21 seleccionado: {'SI' if control_21 else 'NO'}")
    print(f"Ley 39/2015 art. 94 seleccionado: {'SI' if control_94 else 'NO'}")

    print()
    print("=" * 78)
    print("FIN - NO SE HA MODIFICADO SQLITE NI EL CÓDIGO DE OPOCOACH")
    print("=" * 78)

    return 0 if control_21 and control_94 else 2


if __name__ == "__main__":
    raise SystemExit(main())
