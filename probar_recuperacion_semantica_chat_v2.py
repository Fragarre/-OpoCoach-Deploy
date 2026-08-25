"""
Prueba optimizada de recuperación semántica para el Chat de OpoCoach.

SOLO LECTURA:
- No modifica SQLite.
- No modifica archivos del proyecto.
- Sí realiza llamadas reales a la API y registra costes mediante OpoCoach.

Objetivo:
1) Seleccionar la norma mínima necesaria.
2) Seleccionar artículos por norma, no mezclando cientos de artículos.
3) Limitar el resultado a un máximo razonable de artículos.

Ejecutar desde la raíz de OpoCoach:
    python probar_recuperacion_semantica_chat_v2.py
"""

from __future__ import annotations

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

MAX_NORMAS = 2
MAX_ARTICULOS_POR_NORMA = 4
MAX_ARTICULOS_TOTALES = 4


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

    for nombre in normas_disponibles:
        if _normalizar(nombre) == objetivo:
            return nombre

    candidatos = [
        nombre
        for nombre in normas_disponibles
        if objetivo in _normalizar(nombre)
        or _normalizar(nombre) in objetivo
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def seleccionar_normas_minimas(
    pregunta: str,
    normas_disponibles: list[str],
) -> list[str]:
    inventario = "\n".join(f"- {n}" for n in normas_disponibles)

    prompt = f"""
Actúas únicamente como selector de fuentes jurídicas para un sistema RAG.

PREGUNTA:
{pregunta}

NORMAS DISPONIBLES:
{inventario}

TAREA:
Selecciona la norma o, sólo si es jurídicamente imprescindible, las dos normas
mínimas necesarias para poder resolver la pregunta.

Reglas:
- No respondas la pregunta.
- No uses conocimiento externo para añadir normas fuera de la lista.
- Si una sola norma puede contener toda la regulación necesaria, selecciona
  únicamente esa norma.
- No añadas normas por contexto general, jerarquía normativa o relación
  institucional si no son necesarias para contestar.
- Máximo {MAX_NORMAS} normas.
- Devuelve exclusivamente JSON válido:
{{"normas": ["..."]}}
""".strip()

    resultado = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_normas_v2",
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


def filas_unicas_norma(
    corpus: list[dict],
    norma: str,
) -> dict[str, dict]:
    objetivo = _normalizar(norma)
    por_articulo: dict[str, dict] = {}

    for fila in corpus:
        if _normalizar(nombre_norma(fila)) != objetivo:
            continue

        art = articulo(fila)
        if art and art not in por_articulo:
            por_articulo[art] = fila

    return por_articulo


def seleccionar_articulos_de_norma(
    pregunta: str,
    norma: str,
    por_articulo: dict[str, dict],
) -> list[str]:
    inventario = "\n".join(
        f"- art. {art} | {titulo(fila)}"
        for art, fila in sorted(
            por_articulo.items(),
            key=lambda x: (
                int(x[0].split(".")[0]) if x[0].split(".")[0].isdigit() else 10**9,
                x[0],
            ),
        )
    )

    prompt = f"""
Actúas únicamente como selector de artículos para un sistema RAG jurídico.

PREGUNTA:
{pregunta}

NORMA YA SELECCIONADA:
{norma}

ÍNDICE DE ARTÍCULOS DISPONIBLES:
{inventario}

TAREA:
Selecciona sólo los artículos de esta norma que sean directamente necesarios
o especialmente útiles para resolver la pregunta.

Reglas:
- No respondas la pregunta.
- No inventes artículos.
- Usa sólo artículos del índice.
- Prioriza los artículos cuya materia coincida conceptualmente con el supuesto,
  aunque la pregunta use otra forma gramatical de la misma idea
  (por ejemplo, "desiste" frente a "desistimiento").
- Si la pregunta exige combinar una regla general y una regla específica,
  incluye ambas.
- No selecciones artículos sólo por compartir palabras genéricas como
  "Administración", "solicitud", "procedimiento" o "resolución".
- Máximo {MAX_ARTICULOS_POR_NORMA} artículos.
- Devuelve exclusivamente JSON válido:
{{"articulos": ["21", "94"]}}
""".strip()

    resultado = seleccionar_fragmento_json(
        prompt=prompt,
        modelo=MODELO_PREDETERMINADO,
        operacion="chat_seleccion_articulos_v2",
    )

    bruto = resultado.get("articulos", [])
    if not isinstance(bruto, list):
        raise ValueError("La selección de artículos no devolvió una lista.")

    seleccion: list[str] = []
    for valor in bruto:
        art = str(valor).strip()
        if art in por_articulo and art not in seleccion:
            seleccion.append(art)

    return seleccion[:MAX_ARTICULOS_POR_NORMA]


def main() -> int:
    print("=" * 78)
    print("PRUEBA RECUPERACIÓN SEMÁNTICA V2 - SOLO LECTURA")
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
    print("FASE 1 - NORMA(S) MÍNIMA(S)")
    print("-" * 78)

    normas_sel = seleccionar_normas_minimas(PREGUNTA, normas)
    if not normas_sel:
        print("No se seleccionó ninguna norma válida.")
        return 1

    for norma in normas_sel:
        print(f"  - {norma}")

    print()

    seleccion_total: list[tuple[str, str, dict]] = []

    for norma in normas_sel:
        por_articulo = filas_unicas_norma(corpus, norma)

        print("-" * 78)
        print(f"FASE 2 - ARTÍCULOS DE {norma}")
        print("-" * 78)
        print(f"Artículos candidatos: {len(por_articulo)}")

        seleccion = seleccionar_articulos_de_norma(
            PREGUNTA,
            norma,
            por_articulo,
        )

        if not seleccion:
            print("  Ningún artículo seleccionado.")
            continue

        for art in seleccion:
            fila = por_articulo[art]
            seleccion_total.append((norma, art, fila))
            print(f"  - art. {art} | {titulo(fila)}")

    # Corte global conservando el orden generado por las fases.
    seleccion_total = seleccion_total[:MAX_ARTICULOS_TOTALES]

    print()
    print("=" * 78)
    print("SELECCIÓN FINAL V2")
    print("=" * 78)

    for norma, art, fila in seleccion_total:
        print(f"- {norma} | art. {art} | {titulo(fila)}")

    control_21 = any(
        "ley 39 2015" in _normalizar(norma) and art == "21"
        for norma, art, _ in seleccion_total
    )
    control_94 = any(
        "ley 39 2015" in _normalizar(norma) and art == "94"
        for norma, art, _ in seleccion_total
    )

    print()
    print("Caso de control:")
    print(f"  Ley 39/2015 art. 21: {'SI' if control_21 else 'NO'}")
    print(f"  Ley 39/2015 art. 94: {'SI' if control_94 else 'NO'}")

    print()
    print("=" * 78)
    print("FIN - SIN CAMBIOS EN SQLITE NI EN EL CÓDIGO")
    print("=" * 78)

    return 0 if control_21 and control_94 else 2


if __name__ == "__main__":
    raise SystemExit(main())
