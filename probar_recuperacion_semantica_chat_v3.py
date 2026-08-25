"""
Prueba V3 de recuperación semántica para el Chat de OpoCoach.

SOLO LECTURA:
- No modifica SQLite.
- No modifica archivos del proyecto.
- Sí realiza llamadas reales a la API y registra costes mediante OpoCoach.

Diseño:
1) Seleccionar la norma mínima.
2) Pedir a la IA conceptos jurídicos / términos de búsqueda equivalentes.
3) Preseleccionar localmente artículos de esa norma usando título + texto.
4) Pedir a la IA que elija los artículos finales sobre un conjunto pequeño.

Ejecutar desde la raíz de OpoCoach:
    python probar_recuperacion_semantica_chat_v3.py
"""

from __future__ import annotations

from lib.chat_convocatoria import (
    MODELO_PREDETERMINADO,
    _normalizar,
    _terminos,
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

MAX_NORMAS = 1
MAX_TERMINOS_EXPANDIDOS = 12
MAX_CANDIDATOS_LOCAL = 24
MAX_ARTICULOS_FINALES = 4
MAX_EXTRACTO = 700


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


def texto(fila: dict) -> str:
    return " ".join(str(fila.get("texto") or "").split())


def deduplicar_normas(corpus: list[dict]) -> list[str]:
    por_normalizado = {}
    for fila in corpus:
        nombre = nombre_norma(fila)
        clave = _normalizar(nombre)
        if clave and clave not in por_normalizado:
            por_normalizado[clave] = nombre
    return sorted(por_normalizado.values(), key=_normalizar)


def resolver_nombre_norma(solicitado: str, disponibles: list[str]) -> str | None:
    objetivo = _normalizar(solicitado)
    if not objetivo:
        return None

    for nombre in disponibles:
        if _normalizar(nombre) == objetivo:
            return nombre

    candidatos = [
        nombre
        for nombre in disponibles
        if objetivo in _normalizar(nombre)
        or _normalizar(nombre) in objetivo
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def seleccionar_norma(pregunta: str, disponibles: list[str]) -> str | None:
    inventario = "\n".join(f"- {n}" for n in disponibles)

    prompt = f"""
Actúas sólo como selector de norma para un sistema RAG jurídico.

PREGUNTA:
{pregunta}

NORMAS DISPONIBLES:
{inventario}

Selecciona la ÚNICA norma que contiene principalmente la regulación necesaria
para resolver la pregunta. No añadas normas de contexto general si una sola
norma basta.

No respondas la cuestión jurídica.
Devuelve exclusivamente JSON válido:
{{"norma": "nombre de la norma"}}
""".strip()

    r = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_norma_v3",
    )

    return resolver_nombre_norma(str(r.get("norma") or ""), disponibles)


def expandir_conceptos(pregunta: str, norma: str) -> list[str]:
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
- No inventes hechos.
- Máximo {MAX_TERMINOS_EXPANDIDOS} términos o expresiones.
- Devuelve exclusivamente JSON válido:
{{"terminos": ["...", "..."]}}
""".strip()

    r = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_expandir_consulta_v3",
    )

    bruto = r.get("terminos", [])
    if not isinstance(bruto, list):
        raise ValueError("La expansión semántica no devolvió una lista.")

    salida = []
    for valor in bruto:
        n = _normalizar(valor)
        if n and n not in salida:
            salida.append(n)

    return salida[:MAX_TERMINOS_EXPANDIDOS]


def filas_unicas_norma(corpus: list[dict], norma: str) -> dict[str, dict]:
    objetivo = _normalizar(norma)
    por_articulo = {}

    for fila in corpus:
        if _normalizar(nombre_norma(fila)) != objetivo:
            continue

        art = articulo(fila)
        if art and art not in por_articulo:
            por_articulo[art] = fila

    return por_articulo


def puntuar_local(fila: dict, pregunta: str, conceptos: list[str]) -> tuple[float, list[str]]:
    titulo_n = _normalizar(titulo(fila))
    texto_n = _normalizar(texto(fila))

    terminos_pregunta = _terminos(pregunta)
    score = 0.0
    motivos = []

    # Coincidencias originales: sirven de apoyo.
    for termino in terminos_pregunta:
        if termino in _terminos(titulo_n):
            score += 5.0
        elif termino in _terminos(texto_n):
            score += 1.0

    # Conceptos expandidos por IA: pesan mucho más, especialmente en rúbrica.
    for concepto in conceptos:
        if concepto in titulo_n:
            score += 30.0
            motivos.append(f"T:{concepto}")
        elif concepto in texto_n:
            score += 8.0
            motivos.append(f"X:{concepto}")
        else:
            # Para expresiones de varias palabras, también contamos cobertura
            # parcial de sus términos significativos.
            tokens = _terminos(concepto)
            if tokens:
                cobertura_titulo = len(tokens & _terminos(titulo_n))
                cobertura_texto = len(tokens & _terminos(texto_n))
                if cobertura_titulo:
                    score += 7.0 * cobertura_titulo
                    motivos.append(f"T~:{concepto}")
                elif cobertura_texto:
                    score += 2.0 * cobertura_texto
                    motivos.append(f"X~:{concepto}")

    return score, motivos


def preseleccionar_local(
    por_articulo: dict[str, dict],
    pregunta: str,
    conceptos: list[str],
):
    puntuados = []

    for art, fila in por_articulo.items():
        score, motivos = puntuar_local(fila, pregunta, conceptos)
        if score > 0:
            puntuados.append((score, art, fila, motivos))

    puntuados.sort(
        key=lambda x: (
            -x[0],
            int(x[1].split(".")[0]) if x[1].split(".")[0].isdigit() else 10**9,
            x[1],
        )
    )

    return puntuados[:MAX_CANDIDATOS_LOCAL]


def seleccionar_final(
    pregunta: str,
    norma: str,
    candidatos,
) -> list[str]:
    bloques = []

    for score, art, fila, motivos in candidatos:
        extracto = texto(fila)[:MAX_EXTRACTO]
        bloques.append(
            f"[ARTÍCULO {art}]\n"
            f"Rúbrica: {titulo(fila)}\n"
            f"Extracto: {extracto}\n"
        )

    inventario = "\n".join(bloques)

    prompt = f"""
Actúas únicamente como selector final de artículos para un sistema RAG jurídico.

PREGUNTA:
{pregunta}

NORMA:
{norma}

CANDIDATOS PRESELECCIONADOS:
{inventario}

Selecciona sólo los artículos cuyo TEXTO sea realmente necesario o especialmente
útil para responder correctamente.

Reglas:
- No respondas la pregunta.
- No inventes artículos.
- Usa sólo candidatos de la lista.
- Prioriza la regla específica del supuesto y, cuando proceda, la regla general
  que deba combinarse con ella.
- No selecciones artículos sólo por palabras genéricas.
- Máximo {MAX_ARTICULOS_FINALES} artículos.
- Devuelve exclusivamente JSON válido:
{{"articulos": ["21", "94"]}}
""".strip()

    r = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_final_v3",
    )

    disponibles = {art for _, art, _, _ in candidatos}
    bruto = r.get("articulos", [])
    if not isinstance(bruto, list):
        raise ValueError("La selección final no devolvió una lista.")

    salida = []
    for valor in bruto:
        art = str(valor).strip()
        if art in disponibles and art not in salida:
            salida.append(art)

    return salida[:MAX_ARTICULOS_FINALES]


def main() -> int:
    print("=" * 78)
    print("PRUEBA RECUPERACIÓN SEMÁNTICA V3 - SOLO LECTURA")
    print("=" * 78)
    print(f"Convocatoria: {CONVOCATORIA_ID}")
    print(f"Modelo:       {MODELO_PREDETERMINADO}")
    print(f"Pregunta:     {PREGUNTA}")
    print()

    corpus = _obtener_corpus_convocatoria(CONVOCATORIA_ID)
    normas = deduplicar_normas(corpus)

    print(f"Filas del corpus:   {len(corpus)}")
    print(f"Normas disponibles: {len(normas)}")
    print()

    print("-" * 78)
    print("FASE 1 - NORMA PRINCIPAL")
    print("-" * 78)
    norma = seleccionar_norma(PREGUNTA, normas)

    if not norma:
        print("No se pudo resolver una norma válida.")
        return 1

    print(f"  {norma}")
    print()

    print("-" * 78)
    print("FASE 2 - EXPANSIÓN CONCEPTUAL")
    print("-" * 78)
    conceptos = expandir_conceptos(PREGUNTA, norma)
    for c in conceptos:
        print(f"  - {c}")
    print()

    por_articulo = filas_unicas_norma(corpus, norma)

    print("-" * 78)
    print("FASE 3 - PRESELECCIÓN LOCAL")
    print("-" * 78)
    candidatos = preseleccionar_local(por_articulo, PREGUNTA, conceptos)

    print(f"Artículos de la norma: {len(por_articulo)}")
    print(f"Candidatos enviados a reranking: {len(candidatos)}")
    print()

    for i, (score, art, fila, motivos) in enumerate(candidatos, start=1):
        print(
            f"{i:>2}. art. {art:<6} score={score:>6.1f} | "
            f"{titulo(fila)}"
        )
        print(f"    motivos: {', '.join(motivos[:8]) or '-'}")

    print()
    print("-" * 78)
    print("FASE 4 - SELECCIÓN FINAL IA")
    print("-" * 78)

    finales = seleccionar_final(PREGUNTA, norma, candidatos)

    for art in finales:
        fila = por_articulo[art]
        print(f"  - art. {art} | {titulo(fila)}")

    print()
    print("=" * 78)
    print("CASO DE CONTROL")
    print("=" * 78)

    ok21 = "21" in finales
    ok94 = "94" in finales

    print(f"Ley 39/2015 art. 21: {'SI' if ok21 else 'NO'}")
    print(f"Ley 39/2015 art. 94: {'SI' if ok94 else 'NO'}")
    print()

    print("=" * 78)
    print("FIN - SIN CAMBIOS EN SQLITE NI EN EL CÓDIGO")
    print("=" * 78)

    return 0 if ok21 and ok94 else 2


if __name__ == "__main__":
    raise SystemExit(main())
