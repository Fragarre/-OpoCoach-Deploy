import streamlit as st

from lib.pdf_simulacro import generar_pdf_simulacro
from lib.pdf_soluciones import generar_pdf_soluciones
from lib.repositorio import (
    crear_test,
    eliminar_test,
    obtener_convocatoria,
    obtener_preguntas_simulacro,
    obtener_normas_test,
    obtener_puntos_temario_test,
    obtener_tests,
)
from lib.sesion import obtener_convocatoria_id
from ui.correccion import mostrar_correccion


st.title("Tests")

convocatoria_id = obtener_convocatoria_id()

if convocatoria_id is None:
    st.warning("Debe seleccionar una convocatoria en la página Inicio.")
    st.stop()

if st.session_state.get("vista_tests") == "correccion":
    test_id_correccion = st.session_state.get(
        "test_id_correccion"
    )

    if test_id_correccion is None:
        st.error("No se ha seleccionado ningún test.")

        if st.button("Volver a tests"):
            st.session_state.pop("vista_tests", None)
            st.rerun()

        st.stop()

    if st.button("← Volver a tests"):
        st.session_state.pop("vista_tests", None)
        st.session_state.pop("test_id_correccion", None)
        st.rerun()

    mostrar_correccion(
        simulacro_id=test_id_correccion,
        nombre_prueba="test",
    )

    st.divider()

    if st.button(
        "← Volver a tests",
        key="volver_tests_inferior",
        use_container_width=True,
    ):
        st.session_state.pop("vista_tests", None)
        st.session_state.pop("test_id_correccion", None)
        st.rerun()

    st.stop()

convocatoria = obtener_convocatoria(convocatoria_id)

if convocatoria is None:
    st.error("La convocatoria seleccionada no existe.")
    st.stop()

st.subheader(
    f'{convocatoria["codigo"]} — {convocatoria["puesto"]}'
)

resultado_creacion = st.session_state.pop(
    "resultado_creacion_test",
    None,
)

if resultado_creacion is not None:
    st.success(
        f'Test {resultado_creacion["numero"]} creado con '
        f'{resultado_creacion["total_generado"]} preguntas.'
    )

    for aviso in resultado_creacion["avisos"]:
        st.warning(aviso)

puntos = obtener_puntos_temario_test(
    convocatoria_id
)
normas = obtener_normas_test(
    convocatoria_id
)

puntos_disponibles = [
    punto
    for punto in puntos
    if punto["disponibles"] > 0
]

normas_disponibles = [
    norma
    for norma in normas
    if norma["disponibles"] > 0
]

opciones_puntos = {
    int(punto["id"]): (
        f'{punto["numero_tema"]}. {punto["parte"]} — '
        f'{punto["titulo"]} '
        f'({punto["disponibles"]} disponibles)'
    )
    for punto in puntos_disponibles
}

opciones_normas = {
    str(norma["norma_clave"]): (
        f'{norma["norma_nombre"]} '
        f'({norma["disponibles"]} disponibles)'
    )
    for norma in normas_disponibles
}

modo_etiqueta = st.radio(
    "Generar preguntas por",
    options=[
        "Puntos del temario",
        "Ley o norma",
    ],
    horizontal=True,
    key=f"modo_creacion_test_{convocatoria_id}",
)

with st.form(
    f"formulario_crear_test_{modo_etiqueta}_{convocatoria_id}"
):
    numero_preguntas = st.number_input(
        "Número de preguntas",
        min_value=1,
        value=20,
        step=1,
    )

    temas_seleccionados: list[int] = []
    normas_seleccionadas: list[str] = []

    if modo_etiqueta == "Puntos del temario":
        if puntos_disponibles:
            temas_seleccionados = st.multiselect(
                "Puntos del temario",
                options=list(opciones_puntos),
                format_func=(
                    lambda tema_id: opciones_puntos[
                        tema_id
                    ]
                ),
                key=f"temas_test_{convocatoria_id}",
            )
        else:
            st.info(
                "No hay puntos del temario con preguntas "
                "disponibles para esta convocatoria."
            )
    else:
        if normas_disponibles:
            normas_seleccionadas = st.multiselect(
                "Leyes o normas",
                options=list(opciones_normas),
                format_func=(
                    lambda clave: opciones_normas[clave]
                ),
                key=f"normas_test_{convocatoria_id}",
            )
        else:
            st.info(
                "No hay leyes o normas con preguntas "
                "disponibles para esta convocatoria."
            )

    crear = st.form_submit_button(
        "Crear test",
        type="primary",
        use_container_width=True,
    )

if crear:
    modo_seleccion = (
        "TEMA"
        if modo_etiqueta == "Puntos del temario"
        else "NORMA"
    )

    seleccion_vacia = (
        not temas_seleccionados
        if modo_seleccion == "TEMA"
        else not normas_seleccionadas
    )

    if seleccion_vacia:
        if modo_seleccion == "TEMA":
            st.error(
                "Debe seleccionar al menos un punto del temario."
            )
        else:
            st.error(
                "Debe seleccionar al menos una ley o norma."
            )
    else:
        try:
            resultado = crear_test(
                convocatoria_id=convocatoria_id,
                numero_preguntas=int(numero_preguntas),
                temas_seleccionados=temas_seleccionados,
                normas_seleccionadas=normas_seleccionadas,
                modo_seleccion=modo_seleccion,
            )

            st.session_state[
                "resultado_creacion_test"
            ] = resultado

            st.rerun()

        except Exception as exc:
            st.error(
                f"No se ha podido crear el test: {exc}"
            )

st.divider()

tests = obtener_tests(convocatoria_id)

if not tests:
    st.info("Todavía no existe ningún test.")
    st.stop()

st.subheader("Tests generados")

cabecera = st.columns(
    [0.6, 1.6, 0.9, 1.0, 1.2, 1.2, 0.7]
)

cabecera[0].markdown("**N.º**")
cabecera[1].markdown("**Fecha**")
cabecera[2].markdown("**Preguntas**")
cabecera[3].markdown("**PDF**")
cabecera[4].markdown("**Soluciones**")
cabecera[5].markdown("**Corrección**")
cabecera[6].markdown("**Elimina**")

for test in tests:
    test_id = test["id"]
    numero_test = test["numero"]

    fila = st.columns(
        [0.6, 1.6, 0.9, 1.0, 1.2, 1.2, 0.7]
    )

    fila[0].write(numero_test)
    fila[1].write(test["fecha_generacion"])
    fila[2].write(test["total_preguntas"])

    preguntas = obtener_preguntas_simulacro(test_id)

    nombre_test = (
        f"Test-{numero_test:02d}-"
        f'{test["fecha_generacion"][:7]}'
    )

    pdf_test = generar_pdf_simulacro(
        nombre_simulacro=nombre_test,
        preguntas=preguntas,
    )

    fila[3].download_button(
        label="PDF",
        data=pdf_test,
        file_name=f"{nombre_test}.pdf",
        mime="application/pdf",
        key=f"pdf_test_{test_id}",
        use_container_width=True,
    )

    if fila[4].button(
        "Soluciones",
        key=f"soluciones_test_{test_id}",
        use_container_width=True,
    ):
        pdf_soluciones = generar_pdf_soluciones(
            simulacro_id=test_id,
            nombre_simulacro=nombre_test,
            preguntas=preguntas,
        )

        st.download_button(
            label="Descargar PDF",
            data=pdf_soluciones,
            file_name=f"{nombre_test}_soluciones.pdf",
            mime="application/pdf",
            key=f"descarga_soluciones_test_{test_id}",
        )

    test_corregido = bool(test["corregido"])

    etiqueta_correccion = (
        "🟢 Corrección"
        if test_corregido
        else "Corrección"
    )

    if fila[5].button(
        etiqueta_correccion,
        key=f"correccion_test_{test_id}",
        use_container_width=True,
        help=(
            "Corrección guardada"
            if test_corregido
            else "Test pendiente de corregir"
        ),
    ):
        st.session_state["test_id_correccion"] = test_id
        st.session_state["vista_tests"] = "correccion"
        st.rerun()

    confirmar_key = f"confirmar_eliminar_test_{test_id}"

    if fila[6].button(
        "🗑️",
        key=f"eliminar_test_{test_id}",
        help=f"Eliminar test nº {numero_test}",
        use_container_width=True,
    ):
        st.session_state[confirmar_key] = True

    if st.session_state.get(confirmar_key, False):
        st.warning(
            f"¿Eliminar definitivamente el test nº {numero_test}?"
        )

        columna_confirmar, columna_cancelar = st.columns(2)

        if columna_confirmar.button(
            "Sí, eliminar",
            key=f"confirmar_si_test_{test_id}",
            type="primary",
        ):
            eliminado = eliminar_test(
                test_id=test_id,
                convocatoria_id=convocatoria["id"],
            )

            st.session_state.pop(confirmar_key, None)

            if eliminado:
                st.success(f"Test nº {numero_test} eliminado.")
                st.rerun()
            else:
                st.error("No se ha podido eliminar el test.")

        if columna_cancelar.button(
            "Cancelar",
            key=f"confirmar_no_test_{test_id}",
        ):
            st.session_state.pop(confirmar_key, None)
            st.rerun()

    st.divider()