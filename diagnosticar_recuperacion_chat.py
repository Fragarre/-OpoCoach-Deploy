"""
Diagnóstico SOLO LECTURA de la recuperación conceptual del Chat de OpoCoach.

Ejecutar desde la raíz de OpoCoach:
    python diagnosticar_recuperacion_chat.py

No modifica SQLite ni ningún fichero del proyecto.
"""

from lib.chat_convocatoria import (
    _normalizar,
    _terminos,
    _obtener_corpus_convocatoria,
    _puntuar_fragmento,
    buscar_fragmentos,
)

CONVOCATORIA_ID = 2
PREGUNTA = (
    "Si una persona presenta una solicitud ante la Administración y posteriormente "
    "desiste de ella. ¿Está obligada la Administración a dictar una resolución "
    "expresa? En caso afirmativo, ¿qué debe contener esa resolución? "
    "Razona la respuesta indicando los artículos aplicables."
)
NORMA_OBJETIVO = "ley 39 2015"
ARTICULOS_CONTROL = {"21", "94"}
TOP = 30


def articulo_de(fila):
    return str(fila.get("articulo_boe") or fila.get("articulo_solicitado") or "").strip()


def nombre_norma_de(fila):
    return str(
        fila.get("nombre_norma_csv")
        or fila.get("nombre_norma_normalizada")
        or ""
    ).strip()


def coincidencias(fila, terminos_pregunta):
    nombre_norma = _normalizar(
        fila.get("nombre_norma_csv")
        or fila.get("nombre_norma_normalizada")
    )
    articulo_solicitado = _normalizar(fila.get("articulo_solicitado"))
    articulo_boe = _normalizar(fila.get("articulo_boe"))
    titulo_tema = _normalizar(fila.get("titulo_tema"))
    titulo_bloque = _normalizar(fila.get("titulo_bloque"))
    texto = _normalizar(fila.get("texto"))

    campos = " ".join(
        [
            nombre_norma,
            articulo_solicitado,
            articulo_boe,
            titulo_tema,
            titulo_bloque,
        ]
    )
    return (
        sorted(terminos_pregunta & _terminos(campos)),
        sorted(terminos_pregunta & _terminos(texto)),
    )


print("=" * 78)
print("DIAGNÓSTICO RECUPERACIÓN CHAT - SOLO LECTURA")
print("=" * 78)
print(f"Convocatoria: {CONVOCATORIA_ID}")
print(f"Pregunta: {PREGUNTA}")
print()

corpus = _obtener_corpus_convocatoria(CONVOCATORIA_ID)
terminos_pregunta = _terminos(PREGUNTA)

print(f"Filas totales del corpus de Chat: {len(corpus)}")
print("Términos extraídos de la pregunta:")
print(", ".join(sorted(terminos_pregunta)))
print()

filas_ley = []
for fila in corpus:
    nombre = _normalizar(
        fila.get("nombre_norma_csv")
        or fila.get("nombre_norma_normalizada")
    )
    if NORMA_OBJETIVO in nombre:
        filas_ley.append(fila)

ids_articulos = {int(f["articulo_fuente_id"]) for f in filas_ley}
articulos = sorted({articulo_de(f) for f in filas_ley})

print("-" * 78)
print("LEY 39/2015 DISPONIBLE PARA EL CHAT")
print("-" * 78)
print(f"Filas: {len(filas_ley)}")
print(f"Artículos fuente distintos: {len(ids_articulos)}")
print(f"Referencias de artículo distintas: {len(articulos)}")
print(f"Artículo 21 disponible: {'SI' if '21' in articulos else 'NO'}")
print(f"Artículo 94 disponible: {'SI' if '94' in articulos else 'NO'}")
print()

# Deduplicamos por articulo_fuente_id porque una misma norma puede aparecer
# vinculada a más de un tema de la convocatoria.
mejor_por_id = {}
for fila in filas_ley:
    puntuacion = _puntuar_fragmento(
        fila=fila,
        pregunta=PREGUNTA,
        historial_usuario=[],
    )
    clave = int(fila["articulo_fuente_id"])
    anterior = mejor_por_id.get(clave)
    if anterior is None or puntuacion > anterior[0]:
        mejor_por_id[clave] = (puntuacion, fila)

ranking = sorted(
    mejor_por_id.values(),
    key=lambda x: (-x[0], articulo_de(x[1]))
)

print("-" * 78)
print(f"RANKING LEY 39/2015 - TOP {TOP}")
print("-" * 78)

for posicion, (puntuacion, fila) in enumerate(ranking[:TOP], start=1):
    meta, texto = coincidencias(fila, terminos_pregunta)
    print(
        f"{posicion:>3}. art. {articulo_de(fila):<8} "
        f"puntuación={puntuacion:>6.2f}"
    )
    print(f"     encabezado: {str(fila.get('titulo_bloque') or '').strip()}")
    print(f"     coincidencias metadatos: {meta or '-'}")
    print(f"     coincidencias texto:     {texto or '-'}")

print()
print("-" * 78)
print("ARTÍCULOS DE CONTROL")
print("-" * 78)

for objetivo in ("21", "94"):
    encontrados = [
        (pos, puntuacion, fila)
        for pos, (puntuacion, fila) in enumerate(ranking, start=1)
        if articulo_de(fila) == objetivo
    ]
    if not encontrados:
        print(f"Art. {objetivo}: NO DISPONIBLE en el corpus recuperado.")
        continue

    pos, puntuacion, fila = encontrados[0]
    meta, texto = coincidencias(fila, terminos_pregunta)
    print(
        f"Art. {objetivo}: posición={pos}, puntuación={puntuacion:.2f}, "
        f"encabezado={str(fila.get('titulo_bloque') or '').strip()!r}"
    )
    print(f"  coincidencias metadatos: {meta or '-'}")
    print(f"  coincidencias texto:     {texto or '-'}")

print()
print("-" * 78)
print("SELECCIÓN FINAL ACTUAL DE buscar_fragmentos()")
print("-" * 78)

seleccion = buscar_fragmentos(
    convocatoria_id=CONVOCATORIA_ID,
    pregunta=PREGUNTA,
    historial_usuario=[],
)

if not seleccion:
    print("Sin fragmentos.")
else:
    for i, f in enumerate(seleccion, start=1):
        print(
            f"{i:>2}. {f.nombre_norma} | art. {f.articulo_boe} | "
            f"puntuación={f.puntuacion:.2f} | {f.titulo_bloque}"
        )

print()
print("=" * 78)
print("FIN DEL DIAGNÓSTICO - NO SE HA MODIFICADO LA BASE DE DATOS")
print("=" * 78)
