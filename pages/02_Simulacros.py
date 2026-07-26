import streamlit as st
from lib.pdf_simulacro import generar_pdf_simulacro
from lib.pdf_soluciones import generar_pdf_soluciones
from lib.repositorio import (
    obtener_preguntas_simulacro,
    crear_simulacro,
    obtener_convocatoria,
    obtener_simulacros,
    eliminar_simulacro,
)
from lib.sesion import obtener_convocatoria_id
from ui.correccion import mostrar_correccion

st.title("Simulacros")

convocatoria_id = obtener_convocatoria_id()

if convocatoria_id is None:
    st.warning("Debe seleccionar una convocatoria en la página Inicio.")
    st.stop()

if (
    st.session_state.get("vista_simulacros")
    == "correccion"
):
    simulacro_id_correccion = st.session_state.get(
        "simulacro_id_correccion"
    )

    if simulacro_id_correccion is None:
        st.error(
            "No se ha seleccionado ningún simulacro."
        )

        if st.button("Volver a simulacros"):
            st.session_state.pop(
                "vista_simulacros",
                None,
            )
            st.rerun()

        st.stop()

    if st.button("← Volver a simulacros"):
        st.session_state.pop(
            "vista_simulacros",
            None,
        )
        st.session_state.pop(
            "simulacro_id_correccion",
            None,
        )
        st.rerun()

    mostrar_correccion(
        simulacro_id=simulacro_id_correccion
    )

    st.divider()

    if st.button(
        "← Volver a simulacros",
        key="volver_simulacros_inferior",
        use_container_width=True,
    ):
        st.session_state.pop(
            "vista_simulacros",
            None,
        )
        st.session_state.pop(
            "simulacro_id_correccion",
            None,
        )
        st.rerun()

    st.stop()

convocatoria = obtener_convocatoria(convocatoria_id)

if convocatoria is None:
    st.error("La convocatoria seleccionada no existe.")
    st.stop()

st.subheader(
    f'{convocatoria["codigo"]} — {convocatoria["puesto"]}'
)

columna_crear, columna_progreso = st.columns(
    [1.1, 2.9],
    vertical_alignment="center",
)

if columna_crear.button(
    "Crear simulacro de prueba",
    type="primary",
    use_container_width=True,
):
    simulacro_id = crear_simulacro(convocatoria_id)

    st.success(
        f"Simulacro {simulacro_id} creado correctamente."
    )

    st.rerun()

contenedor_progreso = columna_progreso.empty()

simulacros = obtener_simulacros(convocatoria_id)

if not simulacros:
    st.info("Todavía no existe ningún simulacro.")
    st.stop()

if not simulacros:
    st.info("Todavía no hay simulacros generados.")

else:
    st.subheader("Simulacros generados")

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

    for simulacro in simulacros:
        simulacro_id = simulacro["id"]
        numero_simulacro = simulacro["numero"]

        fila = st.columns(
            [0.6, 1.6, 0.9, 1.0, 1.2, 1.2, 0.7]
        )

        fila[0].write(numero_simulacro)
        fila[1].write(simulacro["fecha_generacion"])
        fila[2].write(simulacro["total_preguntas"])

        preguntas = obtener_preguntas_simulacro(
            simulacro_id
        )

        nombre_simulacro = (
            f"{numero_simulacro:02d}-"
            f'{simulacro["fecha_generacion"][:7]}'
        )

        pdf_simulacro = generar_pdf_simulacro(
            nombre_simulacro=nombre_simulacro,
            preguntas=preguntas,
        )

        fila[3].download_button(
            label="PDF",
            data=pdf_simulacro,
            file_name=f"{nombre_simulacro}.pdf",
            mime="application/pdf",
            key=f"pdf_simulacro_{simulacro_id}",
            use_container_width=True,
        )

        if fila[4].button(
            "Soluciones",
            key=f"soluciones_{simulacro_id}",
            use_container_width=True,
        ):
            with contenedor_progreso.container():
                texto_progreso = st.empty()
                barra_progreso = st.progress(0)

            def actualizar_progreso(
                lote_actual: int,
                total_lotes: int,
                preguntas_actualizadas: int,
            ) -> None:
                if total_lotes <= 0:
                    texto_progreso.info(
                        "Los comentarios ya estaban generados. "
                        "Construyendo PDF..."
                    )
                    barra_progreso.progress(90)
                    return

                porcentaje = int(
                    lote_actual / total_lotes * 90
                )

                texto_progreso.info(
                    f"Generando comentarios IA: "
                    f"lote {lote_actual} de {total_lotes}. "
                    f"{preguntas_actualizadas} preguntas procesadas."
                )

                barra_progreso.progress(porcentaje)

            texto_progreso.info(
                "Preparando los comentarios de las soluciones..."
            )
            barra_progreso.progress(1)

            pdf_soluciones = generar_pdf_soluciones(
                simulacro_id=simulacro_id,
                nombre_simulacro=nombre_simulacro,
                preguntas=preguntas,
                progreso=actualizar_progreso,
            )

            texto_progreso.info("PDF de soluciones preparado.")
            barra_progreso.progress(100)

            st.download_button(
                label="Descargar PDF",
                data=pdf_soluciones,
                file_name=f"{nombre_simulacro}_soluciones.pdf",
                mime="application/pdf",
                key=f"descarga_soluciones_{simulacro_id}",
            )

        confirmar_key = (
            f"confirmar_eliminar_simulacro_{simulacro_id}"
        )

        simulacro_corregido = bool(
            simulacro["corregido"]
        )

        etiqueta_correccion = (
            "🟢 Corrección"
            if simulacro_corregido
            else "Corrección"
        )

        if fila[5].button(
            etiqueta_correccion,
            key=f"correccion_{simulacro_id}",
            use_container_width=True,
            help=(
                "Corrección guardada"
                if simulacro_corregido
                else "Simulacro pendiente de corregir"
            ),
        ):
            st.session_state[
                "simulacro_id_correccion"
            ] = simulacro_id

            st.session_state[
                "vista_simulacros"
            ] = "correccion"

            st.rerun()

        if fila[6].button(
            "🗑️",
            key=f"eliminar_simulacro_{simulacro_id}",
            help=f"Eliminar simulacro nº {numero_simulacro}",
            use_container_width=True,
        ):
            st.session_state[confirmar_key] = True

        if st.session_state.get(confirmar_key, False):
            st.warning(
                f"¿Eliminar definitivamente el simulacro "
                f"nº {numero_simulacro}?"
            )

            columna_confirmar, columna_cancelar = st.columns(2)

            if columna_confirmar.button(
                "Sí, eliminar",
                key=f"confirmar_si_{simulacro_id}",
                type="primary",
            ):
                eliminado = eliminar_simulacro(
                    simulacro_id=simulacro_id,
                    convocatoria_id=convocatoria["id"],
                )

                st.session_state.pop(
                    confirmar_key,
                    None,
                )

                if eliminado:
                    st.success(
                        f"Simulacro nº {numero_simulacro} eliminado."
                    )
                    st.rerun()
                else:
                    st.error(
                        "No se ha podido eliminar el simulacro."
                    )

            if columna_cancelar.button(
                "Cancelar",
                key=f"confirmar_no_{simulacro_id}",
            ):
                st.session_state.pop(
                    confirmar_key,
                    None,
                )
                st.rerun()

        st.divider()