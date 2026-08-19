
from __future__ import annotations

import html
import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from libsql_client import create_client_sync


RAIZ = Path(__file__).resolve().parent
SALIDA_DIR = RAIZ / "registros"


def obtener_secreto(nombre: str) -> str:
    valor = os.getenv(nombre, "").strip()

    if valor:
        return valor

    try:
        import streamlit as st
        return str(st.secrets.get(nombre, "")).strip()
    except Exception:
        return ""


def normalizar_url_turso(url: str) -> str:
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    return url


def esc(valor) -> str:
    if valor is None:
        return ""
    return html.escape(str(valor))


def etiqueta_tipo(tipo: str | None) -> str:
    valor = (tipo or "").strip().upper()
    if valor == "TEST":
        return "TEST"
    if valor == "SIMULACRO":
        return "SIMULACRO"
    return valor or "SIN TIPO"


def etiqueta_seguridad(valor: str | None) -> str:
    mapa = {
        "MUY_SEGURO": "Muy seguro",
        "BASTANTE_SEGURO": "Bastante seguro",
        "POCO_SEGURO": "Poco seguro",
    }
    return mapa.get(valor or "", valor or "")


def clase_resultado(
    respuesta_usuario: str | None,
    respuesta_correcta: str | None,
) -> str:
    if not respuesta_usuario:
        return "no_contestada"
    if respuesta_usuario == respuesta_correcta:
        return "acierto"
    return "fallo"


def texto_resultado(
    respuesta_usuario: str | None,
    respuesta_correcta: str | None,
) -> str:
    if not respuesta_usuario:
        return "No contestada"
    if respuesta_usuario == respuesta_correcta:
        return "Acierto"
    return "Fallo"


def obtener_pruebas(cliente):
    return cliente.execute(
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
            factor_escala_nota,
            created_at,
            updated_at
        FROM simulacros
        ORDER BY fecha_generacion DESC, id DESC
        """
    ).rows


def obtener_preguntas(cliente, prueba_id: int):
    return cliente.execute(
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
            sp.created_at AS pregunta_created_at,

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
            ss.origen_oposicion,
            ss.tipo_fuente,

            ss.importacion_fichero_id,
            ss.pagina_origen,
            ss.norma_id_normalizada,
            ss.articulo_normalizado,
            ss.teorica_practica,
            ss.tipo_norma_normalizado,
            ss.nombre_norma_normalizado,

            ss.banco_tipo_vinculacion,
            ss.banco_estado,
            ss.banco_metodo_vinculacion,
            ss.banco_motivo_revision,

            ss.temas_json,
            ss.comentario_solucion,
            ss.created_at AS snapshot_created_at

        FROM simulacro_preguntas sp
        JOIN simulacro_snapshot ss
            ON ss.simulacro_pregunta_id = sp.id
        WHERE sp.simulacro_id = ?
        ORDER BY sp.orden
        """,
        (prueba_id,),
    ).rows


def generar_html(pruebas, preguntas_por_prueba) -> str:
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    partes = []

    partes.append(f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Contenido de Turso - OpoCoach</title>
<style>
body {{
    font-family: Arial, Helvetica, sans-serif;
    margin: 28px;
    line-height: 1.45;
    color: #222;
    background: #f6f7f9;
}}
h1, h2, h3 {{
    color: #172033;
}}
.prueba {{
    background: white;
    border: 1px solid #d9dde5;
    border-radius: 10px;
    padding: 18px;
    margin-bottom: 28px;
}}
.resumen {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 10px;
    margin: 14px 0 18px 0;
}}
.celda {{
    background: #f1f3f6;
    border-radius: 7px;
    padding: 10px 12px;
}}
.celda b {{
    display: block;
    margin-bottom: 4px;
}}
.pregunta {{
    border-top: 1px solid #e1e4ea;
    padding: 16px 0;
}}
.pregunta:first-of-type {{
    border-top: none;
}}
.opciones {{
    margin: 8px 0 10px 20px;
}}
.opciones div {{
    margin: 4px 0;
}}
.correcta {{
    font-weight: bold;
}}
.acierto {{
    color: #146c2e;
    font-weight: bold;
}}
.fallo {{
    color: #a61b1b;
    font-weight: bold;
}}
.no_contestada {{
    color: #666;
    font-weight: bold;
}}
.meta {{
    font-size: 0.92em;
    color: #555;
    background: #fafbfc;
    border: 1px solid #eceff3;
    border-radius: 7px;
    padding: 10px;
    margin-top: 10px;
}}
.comentario {{
    background: #fff8dc;
    border-left: 4px solid #d6a900;
    padding: 10px 12px;
    margin-top: 10px;
}}
code {{
    background: #eef1f5;
    padding: 1px 4px;
    border-radius: 4px;
}}
</style>
</head>
<body>
<h1>Contenido de Turso - OpoCoach</h1>
<p><b>Generado:</b> {esc(ahora)}</p>
<p><b>Pruebas encontradas:</b> {len(pruebas)}</p>
""")

    for prueba in pruebas:
        prueba_id = prueba[0]
        preguntas = preguntas_por_prueba.get(prueba_id, [])

        tipo = etiqueta_tipo(prueba[6])
        codigo = prueba[7] or ""
        puesto = prueba[8] or ""

        partes.append(f"""
<section class="prueba">
<h2>{esc(tipo)} #{esc(prueba[2])} — {esc(codigo)}</h2>

<div class="resumen">
    <div class="celda"><b>ID interno</b>{esc(prueba_id)}</div>
    <div class="celda"><b>Convocatoria</b>{esc(codigo)}</div>
    <div class="celda"><b>Puesto</b>{esc(puesto)}</div>
    <div class="celda"><b>Fecha</b>{esc(prueba[3])}</div>
    <div class="celda"><b>Preguntas</b>{esc(prueba[4])}</div>
    <div class="celda"><b>Estado</b>{esc(prueba[5])}</div>
</div>

<div class="meta">
<b>Configuración congelada</b><br>
Convocatoria ID: {esc(prueba[1])}<br>
Número convocatoria: {esc(prueba[9])}<br>
Año: {esc(prueba[10])}<br>
Preguntas convocatoria: {esc(prueba[11])}<br>
Valor acierto: {esc(prueba[12])}<br>
Valor fallo: {esc(prueba[13])}<br>
Valor no contestada: {esc(prueba[14])}<br>
Fórmula nota: {esc(prueba[15])}<br>
Factor escala: {esc(prueba[16])}<br>
Creado: {esc(prueba[17])}<br>
Actualizado: {esc(prueba[18])}
</div>
""")

        if not preguntas:
            partes.append("<p><i>No hay preguntas asociadas.</i></p>")
        else:
            for p in preguntas:
                respuesta_usuario = p[7]
                seguridad = etiqueta_seguridad(p[8])
                respuesta_correcta = p[15]
                clase = clase_resultado(
                    respuesta_usuario,
                    respuesta_correcta,
                )
                resultado = texto_resultado(
                    respuesta_usuario,
                    respuesta_correcta,
                )

                partes.append(f"""
<div class="pregunta">
<h3>Pregunta {esc(p[1])}</h3>

<p>{esc(p[10])}</p>

<div class="opciones">
    <div class="{'correcta' if respuesta_correcta == 'A' else ''}">A. {esc(p[11])}</div>
    <div class="{'correcta' if respuesta_correcta == 'B' else ''}">B. {esc(p[12])}</div>
    <div class="{'correcta' if respuesta_correcta == 'C' else ''}">C. {esc(p[13])}</div>
    <div class="{'correcta' if respuesta_correcta == 'D' else ''}">D. {esc(p[14])}</div>
</div>

<p>
<b>Respuesta correcta:</b> {esc(respuesta_correcta)}<br>
<b>Respuesta usuario:</b> {esc(respuesta_usuario) if respuesta_usuario else '—'}<br>
<b>Seguridad:</b> {esc(seguridad) if seguridad else '—'}<br>
<b>Resultado:</b> <span class="{clase}">{esc(resultado)}</span>
</p>

<div class="meta">
<b>Identificación y procedencia</b><br>
simulacro_pregunta_id: {esc(p[0])}<br>
pregunta_id: {esc(p[2])}<br>
banco_pregunta_id: {esc(p[3])}<br>
parte_id: {esc(p[4])}<br>
parte: {esc(p[5])}<br>
orden parte: {esc(p[6])}<br>
tipo_clasificacion: {esc(p[16])}<br>
teorica_practica: {esc(p[27])}<br>
origen_oposicion: {esc(p[21])}<br>
tipo_fuente: {esc(p[22])}<br>
importacion_fichero_id: {esc(p[23])}<br>
pagina_origen: {esc(p[24])}
</div>

<div class="meta">
<b>Clasificación jurídica / temática</b><br>
tipo_norma: {esc(p[17])}<br>
nombre_norma: {esc(p[18])}<br>
articulo: {esc(p[19])}<br>
tema_no_juridico: {esc(p[20])}<br>
norma_id_normalizada: {esc(p[25])}<br>
articulo_normalizado: {esc(p[26])}<br>
tipo_norma_normalizado: {esc(p[28])}<br>
nombre_norma_normalizado: {esc(p[29])}<br>
temas_json: <code>{esc(p[34])}</code>
</div>

<div class="meta">
<b>Vinculación al banco</b><br>
tipo_vinculacion: {esc(p[30])}<br>
estado_banco: {esc(p[31])}<br>
metodo_vinculacion: {esc(p[32])}<br>
motivo_revision: {esc(p[33])}
</div>
""")

                if p[35]:
                    partes.append(
                        f'<div class="comentario"><b>Comentario de solución</b><br>{esc(p[35])}</div>'
                    )

                partes.append("</div>")

        partes.append("</section>")

    partes.append("""
</body>
</html>
""")

    return "".join(partes)


def main() -> int:
    load_dotenv(RAIZ / ".env")

    url = obtener_secreto("TURSO_DATABASE_URL")
    token = obtener_secreto("TURSO_AUTH_TOKEN")

    if not url:
        raise RuntimeError("No está configurado TURSO_DATABASE_URL.")
    if not token:
        raise RuntimeError("No está configurado TURSO_AUTH_TOKEN.")

    cliente = create_client_sync(
        url=normalizar_url_turso(url),
        auth_token=token,
    )

    try:
        pruebas = obtener_pruebas(cliente)
        preguntas_por_prueba = {
            prueba[0]: obtener_preguntas(cliente, prueba[0])
            for prueba in pruebas
        }

        contenido = generar_html(
            pruebas,
            preguntas_por_prueba,
        )

        SALIDA_DIR.mkdir(parents=True, exist_ok=True)

        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        salida = SALIDA_DIR / f"contenido_turso_{marca}.html"

        salida.write_text(
            contenido,
            encoding="utf-8",
        )

        print("=" * 78)
        print("EXPORTACIÓN TURSO A HTML")
        print("=" * 78)
        print(f"Pruebas: {len(pruebas)}")
        print(
            "Preguntas: "
            f"{sum(len(v) for v in preguntas_por_prueba.values())}"
        )
        print(f"HTML: {salida}")
        print("=" * 78)

        return 0

    finally:
        cliente.close()


if __name__ == "__main__":
    raise SystemExit(main())
