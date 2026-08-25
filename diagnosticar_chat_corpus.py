"""
Diagnóstico de recuperación del Chat de OpoCoach.
SOLO LECTURA: no modifica ninguna base de datos ni archivo.

Ejecutar desde la carpeta raíz de OpoCoach:
    python diagnosticar_chat_corpus.py
"""

from __future__ import annotations

from collections import Counter

from lib import chat_convocatoria as chat


PREGUNTA = (
    "Según el Decreto 54/2025, ¿qué regulan los artículos "
    "30, 31, 32 y 33?"
)

CONVOCATORIA_ID = 2


def mostrar_fila(fila: dict, puntuacion: float | None = None) -> None:
    partes = [
        f"af_id={fila.get('articulo_fuente_id')}",
        f"tema_id={fila.get('tema_id')}",
        f"norma_csv={fila.get('nombre_norma_csv')!r}",
        f"norma_norm={fila.get('nombre_norma_normalizada')!r}",
        f"art_solicitado={fila.get('articulo_solicitado')!r}",
        f"art_boe={fila.get('articulo_boe')!r}",
        f"titulo={fila.get('titulo_bloque')!r}",
    ]
    if puntuacion is not None:
        partes.insert(0, f"score={puntuacion:.2f}")
    print(" | ".join(partes))


def main() -> int:
    print("=" * 78)
    print("DIAGNÓSTICO CHAT - CORPUS AMPLIADO")
    print("=" * 78)
    print(f"Convocatoria: {CONVOCATORIA_ID}")
    print(f"Pregunta: {PREGUNTA}")
    print()

    articulos = chat._extraer_articulos(PREGUNTA)
    normas = chat._extraer_normas(PREGUNTA)

    print("DETECCIÓN")
    print("-" * 78)
    print(f"Artículos detectados: {sorted(articulos)}")
    print(f"Normas detectadas:    {sorted(normas)}")
    print()

    corpus = chat._obtener_corpus_convocatoria(CONVOCATORIA_ID)

    print("CORPUS CONSTRUIDO")
    print("-" * 78)
    print(f"Filas totales: {len(corpus)}")
    print(
        f"Artículos fuente únicos: "
        f"{len({fila['articulo_fuente_id'] for fila in corpus})}"
    )

    contador_normas = Counter(
        chat._normalizar(
            fila.get("nombre_norma_csv")
            or fila.get("nombre_norma_normalizada")
        )
        for fila in corpus
    )
    del contador_normas  # reservado para ampliar diagnóstico si hiciera falta

    objetivo_norma = "decreto 54 2025"
    candidatos_norma = [
        fila
        for fila in corpus
        if objetivo_norma
        in chat._normalizar(
            fila.get("nombre_norma_csv")
            or fila.get("nombre_norma_normalizada")
        )
    ]

    print(f"Filas cuya norma contiene '{objetivo_norma}': {len(candidatos_norma)}")
    print()

    print("ARTÍCULOS 30-33 DENTRO DEL DECRETO 54/2025")
    print("-" * 78)
    encontrados_objetivo = []
    for fila in candidatos_norma:
        art = chat._normalizar(fila.get("articulo_boe"))
        if art in {"30", "31", "32", "33"}:
            encontrados_objetivo.append(fila)
            mostrar_fila(
                fila,
                chat._puntuar_fragmento(
                    fila=fila,
                    pregunta=PREGUNTA,
                    historial_usuario=[],
                ),
            )

    if not encontrados_objetivo:
        print("NINGUNO")
    print()

    print("TOP 20 PUNTUACIONES EN TODO EL CORPUS")
    print("-" * 78)
    puntuados = []
    for fila in corpus:
        score = chat._puntuar_fragmento(
            fila=fila,
            pregunta=PREGUNTA,
            historial_usuario=[],
        )
        if score > 0:
            puntuados.append((score, fila))

    puntuados.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("nombre_norma_csv") or ""),
            str(item[1].get("articulo_boe") or ""),
        )
    )

    for score, fila in puntuados[:20]:
        mostrar_fila(fila, score)
    print()

    print("SELECCIÓN FINAL DE buscar_fragmentos()")
    print("-" * 78)
    seleccion = chat.buscar_fragmentos(
        convocatoria_id=CONVOCATORIA_ID,
        pregunta=PREGUNTA,
        historial_usuario=[],
    )

    if not seleccion:
        print("NINGÚN FRAGMENTO SELECCIONADO")
    else:
        for frag in seleccion:
            print(
                f"score={frag.puntuacion:.2f} | "
                f"af_id={frag.articulo_fuente_id} | "
                f"norma={frag.nombre_norma!r} | "
                f"art_solicitado={frag.articulo_solicitado!r} | "
                f"art_boe={frag.articulo_boe!r} | "
                f"titulo={frag.titulo_bloque!r}"
            )
    print()

    print("COMPROBACIÓN DE COINCIDENCIA EXPLÍCITA")
    print("-" * 78)
    for art in sorted(articulos):
        filas_articulo = [
            fila for fila in corpus
            if chat._normalizar(fila.get("articulo_boe")) == art
        ]
        print(f"Artículo {art}: {len(filas_articulo)} fila(s) en corpus")
        for fila in filas_articulo[:20]:
            norma = chat._normalizar(
                fila.get("nombre_norma_csv")
                or fila.get("nombre_norma_normalizada")
            )
            marca = "OBJETIVO" if objetivo_norma in norma else "OTRA NORMA"
            print(
                f"  [{marca}] "
                f"{fila.get('nombre_norma_csv') or fila.get('nombre_norma_normalizada')} "
                f"| af_id={fila.get('articulo_fuente_id')} "
                f"| titulo={fila.get('titulo_bloque')!r}"
            )

    print()
    print("=" * 78)
    print("FIN DEL DIAGNÓSTICO - SIN ESCRITURAS")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
