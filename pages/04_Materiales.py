from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from lib.materiales import (
    listar_normas_materiales,
    obtener_articulos_extracto,
    obtener_articulos_texto_completo,
    obtener_convocatoria_materiales,
)
from lib.pdf_materiales import generar_pdf_material
from lib.sesion import obtener_convocatoria_id


ROOT = Path(__file__).resolve().parent.parent
RESUMENES_DIR = ROOT / "materiales" / "resumenes"
CATALOGO_RESUMENES = RESUMENES_DIR / "catalogo_resumenes.json"


def _nombre_archivo(texto: str) -> str:
    valor = re.sub(r"[^A-Za-z0-9._-]+", "_", texto.strip())
    return re.sub(r"_+", "_", valor).strip("_") or "material"


@st.cache_data(show_spinner=False)
def _cargar_catalogo_resumenes() -> dict[int, dict]:
    if not CATALOGO_RESUMENES.is_file():
        return {}

    datos = json.loads(
        CATALOGO_RESUMENES.read_text(encoding="utf-8")
    )

    resultado: dict[int, dict] = {}
    for item in datos:
        try:
            norma_id = int(item["norma_id"])
        except Exception:
            continue
        resultado[norma_id] = dict(item)

    return resultado


def _obtener_resumen_pdf(norma_id: int) -> tuple[bytes, str]:
    catalogo = _cargar_catalogo_resumenes()
    item = catalogo.get(int(norma_id))

    if item is None:
        raise FileNotFoundError(
            "No existe resumen preparado para la norma seleccionada."
        )

    nombre = str(item.get("archivo") or "").strip()
    if not nombre:
        raise FileNotFoundError(
            "El catálogo no contiene el archivo del resumen."
        )

    ruta = RESUMENES_DIR / nombre

    if not ruta.is_file():
        raise FileNotFoundError(
            f"No se encuentra el resumen preparado: {nombre}"
        )

    return ruta.read_bytes(), nombre


st.title("Materiales de estudio")

convocatoria_id = obtener_convocatoria_id()

if convocatoria_id is None:
    st.warning("Debe seleccionar una convocatoria en la página Inicio.")
    st.stop()

convocatoria = obtener_convocatoria_materiales(convocatoria_id)

if convocatoria is None:
    st.error("La convocatoria seleccionada no existe.")
    st.stop()

if not bool(convocatoria.get("activa")):
    st.warning("La convocatoria seleccionada no está activa.")
    st.stop()

st.caption(
    f'{convocatoria["codigo"]} — {convocatoria["puesto"]}'
)

normas = listar_normas_materiales(convocatoria_id)

if not normas:
    st.info("No hay normas jurídicas disponibles para esta convocatoria.")
    st.stop()

por_id = {int(n["norma_id"]): n for n in normas}

norma_id = st.selectbox(
    "Ley / norma",
    options=list(por_id),
    format_func=lambda x: por_id[x]["nombre_canonico"],
)

tipo = st.radio(
    "¿Qué quieres descargar?",
    options=[
        "Resumen para estudiar",
        "Extracto para esta oposición",
        "Ley completa",
    ],
    index=0,
)

if tipo == "Resumen para estudiar":
    try:
        pdf, nombre_archivo = _obtener_resumen_pdf(int(norma_id))
    except Exception as exc:
        st.warning(str(exc))
        st.stop()

    st.download_button(
        "Descargar PDF",
        data=pdf,
        file_name=nombre_archivo,
        mime="application/pdf",
        type="primary",
        use_container_width=False,
    )
    st.stop()


try:
    if tipo == "Extracto para esta oposición":
        meta, articulos = obtener_articulos_extracto(
            convocatoria_id,
            int(norma_id),
        )
        nombre_tipo = "Extracto para esta oposición"
        sufijo = "extracto"
    else:
        meta, articulos = obtener_articulos_texto_completo(
            int(norma_id)
        )
        nombre_tipo = "Ley completa"
        sufijo = "completa"

except Exception as exc:
    st.error(f"No se puede preparar el material: {exc}")
    st.stop()

if not articulos:
    st.warning("No hay contenido disponible para esta selección.")
    st.stop()

clave_cache = (
    f"material_pdf_{convocatoria_id}_{norma_id}_{sufijo}"
)

if st.button(
    "Preparar PDF",
    type="primary",
):
    with st.spinner("Preparando PDF..."):
        st.session_state[clave_cache] = generar_pdf_material(
            convocatoria_codigo=convocatoria["codigo"],
            convocatoria_puesto=convocatoria["puesto"],
            norma_nombre=meta["nombre_canonico"],
            tipo_material=nombre_tipo,
            articulos=articulos,
            temas=None,
            fuente=None,
        )

pdf = st.session_state.get(clave_cache)

if pdf:
    archivo = (
        f'{_nombre_archivo(convocatoria["codigo"])}_'
        f'{_nombre_archivo(meta["nombre_canonico"])}_{sufijo}.pdf'
    )

    st.download_button(
        "Descargar PDF",
        data=pdf,
        file_name=archivo,
        mime="application/pdf",
        use_container_width=False,
    )
