import streamlit as st
import streamlit.components.v1 as components

from lib.analisis_rendimiento import (
    generar_analisis_rendimiento,
)
from lib.repositorio import (
    guardar_respuesta_simulacro,
    obtener_preguntas_simulacro,
    obtener_resultado_acumulado_convocatoria,
    obtener_resultado_simulacro,
)


def desplazar_al_inicio() -> None:
    """Desplaza la vista principal de Streamlit al inicio de la página."""

    components.html(
        """
        <script>
        const parentWindow = window.parent;
        const parentDocument = parentWindow.document;

        const contenedores = [
            parentDocument.querySelector('[data-testid="stAppViewContainer"]'),
            parentDocument.querySelector('[data-testid="stMain"]'),
            parentDocument.scrollingElement,
            parentDocument.documentElement,
            parentDocument.body
        ];

        for (const contenedor of contenedores) {
            if (contenedor && typeof contenedor.scrollTo === 'function') {
                contenedor.scrollTo({top: 0, left: 0, behavior: 'instant'});
            }
        }

        parentWindow.scrollTo(0, 0);
        </script>
        """,
        height=0,
        width=0,
    )


RESPUESTAS = ["A", "B", "C", "D"]

SEGURIDADES = {
    "Muy seguro": "MUY_SEGURO",
    "Bastante seguro": "BASTANTE_SEGURO",
    "Poco seguro": "POCO_SEGURO",
}

SEGURIDADES_INVERSAS = {
    valor: etiqueta
    for etiqueta, valor in SEGURIDADES.items()
}


def inicializar_estado_pregunta(
    simulacro_pregunta_id: int,
    respuesta_guardada: str | None,
    seguridad_guardada: str | None,
) -> tuple[str, str]:
    """
    Inicializa en session_state los valores guardados
    de una pregunta del simulacro.
    """

    respuesta_key = (
        f"respuesta_{simulacro_pregunta_id}"
    )

    seguridad_key = (
        f"seguridad_{simulacro_pregunta_id}"
    )

    if respuesta_key not in st.session_state:
        st.session_state[respuesta_key] = (
            respuesta_guardada
        )

    if seguridad_key not in st.session_state:
        st.session_state[seguridad_key] = (
            SEGURIDADES_INVERSAS.get(
                seguridad_guardada
            )
        )

    return respuesta_key, seguridad_key


def marcar_correccion_modificada(
    simulacro_id: int,
) -> None:
    """
    Invalida el guardado y el resultado anterior
    cuando se modifica la corrección.
    """

    st.session_state.pop(
        f"correccion_guardada_{simulacro_id}",
        None,
    )

    st.session_state.pop(
        f"resultado_simulacro_{simulacro_id}",
        None,
    )

    # La firma acumulada invalidará también cualquier análisis previo
    # cuando vuelvan a mostrarse los resultados guardados.




def mostrar_analisis_rendimiento(
    resultado_actual: dict,
    resultado_acumulado: dict,
) -> None:
    """Muestra y, bajo petición, genera el análisis IA acumulado."""

    st.divider()
    st.subheader("Análisis acumulado de la convocatoria")

    if resultado_acumulado["simulacros"] <= 0:
        st.info(
            "Todavía no hay simulacros corregidos suficientes para "
            "generar el análisis acumulado."
        )
        return

    st.caption(
        "El análisis utiliza todas las pruebas corregidas del mismo "
        "tipo que la prueba abierta y que se conservan actualmente en "
        "esta convocatoria, no solo esta "
        "corrección. Si se elimina o modifica un simulacro, los datos "
        "se recalculan."
    )

    st.write(
        f'**Datos considerados:** {resultado_acumulado["simulacros"]} '
        f'simulacros · {resultado_acumulado["preguntas"]} preguntas.'
    )

    cache_key = (
        f'analisis_rendimiento_{resultado_actual["convocatoria_id"]}'
    )
    cache = st.session_state.get(cache_key)

    if (
        cache is not None
        and cache.get("firma_datos")
        != resultado_acumulado["firma_datos"]
    ):
        st.session_state.pop(cache_key, None)
        cache = None

    if cache is not None:
        st.markdown(cache["texto"])

    etiqueta_boton = (
        "Regenerar análisis de rendimiento"
        if cache is not None
        else "Generar análisis de rendimiento"
    )

    if st.button(
        etiqueta_boton,
        key=(
            "generar_analisis_rendimiento_"
            f'{resultado_actual["simulacro_id"]}'
        ),
        use_container_width=False,
    ):
        try:
            with st.spinner(
                "Analizando los resultados acumulados..."
            ):
                texto = generar_analisis_rendimiento(
                    resultado_actual=resultado_actual,
                    resultado_acumulado=resultado_acumulado,
                )
        except Exception as exc:
            st.error(
                "No se ha podido generar el análisis de rendimiento. "
                f"Detalle: {exc}"
            )
            return

        st.session_state[cache_key] = {
            "firma_datos": resultado_acumulado["firma_datos"],
            "texto": texto,
        }
        st.rerun()


def mostrar_resultado(
    resultado: dict,
    nombre_prueba: str = "simulacro",
) -> None:
    """
    Muestra el resultado particular de la prueba y las estadísticas
    acumuladas de los simulacros conservados de la convocatoria.
    """

    st.subheader("Resultado")

    fila_1 = st.columns(3)
    fila_1[0].metric(
        "Preguntas",
        resultado["total"],
    )
    fila_1[1].metric(
        "Contestadas",
        resultado["contestadas"],
    )
    fila_1[2].metric(
        "No contestadas",
        resultado["no_contestadas"],
    )

    fila_2 = st.columns(3)
    fila_2[0].metric(
        "Aciertos",
        resultado["aciertos"],
    )
    fila_2[1].metric(
        "Fallos",
        resultado["fallos"],
    )
    fila_2[2].metric(
        "Nota",
        f'{resultado["nota"]:.2f}',
    )

    st.caption(
        "Este bloque corresponde exclusivamente al "
        f"{nombre_prueba} abierto. La nota se ha calculado con las "
        "reglas de puntuación configuradas en la convocatoria."
    )

    resultado_acumulado = (
        obtener_resultado_acumulado_convocatoria(
            resultado["convocatoria_id"],
            tipo_prueba=resultado["tipo_prueba"],
        )
    )

    st.divider()
    tipo_acumulado = (
        "tests"
        if resultado["tipo_prueba"] == "TEST"
        else "simulacros"
    )

    st.subheader("Rendimiento acumulado de la convocatoria")

    if resultado_acumulado["simulacros"] <= 0:
        st.info(
            "Todavía no existen simulacros corregidos para mostrar "
            "estadísticas acumuladas."
        )
        return

    st.info(
        f"Las tablas siguientes corresponden a todos los {tipo_acumulado} "
        "corregidos que se conservan actualmente en esta convocatoria, "
        "no únicamente al simulacro abierto. Si se modifica o elimina "
        "un simulacro, los resultados se recalculan automáticamente."
    )

    st.write(
        f'**Datos acumulados:** {resultado_acumulado["simulacros"]} '
        f'{tipo_acumulado} · {resultado_acumulado["preguntas"]} preguntas · '
        f'{resultado_acumulado["contestadas"]} contestadas · '
        f'{resultado_acumulado["no_contestadas"]} no contestadas.'
    )

    st.subheader("Resultados acumulados por tema")

    datos_temas = []

    for tema in resultado_acumulado["temas"]:
        datos_temas.append(
            {
                "Tema": (
                    f'{tema["parte"]} '
                    f'{tema["numero_tema"]}. '
                    f'{tema["titulo"]}'
                ),
                "Preguntas": tema["preguntas"],
                "% acumulado": (
                    f'{tema["porcentaje_convocatoria"]:.1f} %'
                ),
                "Aciertos": tema["aciertos"],
                "% aciertos": (
                    f'{tema["porcentaje_aciertos"]:.1f} %'
                ),
                "Fallos": tema["fallos"],
                "% fallos": (
                    f'{tema["porcentaje_fallos"]:.1f} %'
                ),
                "No contestadas": tema["no_contestadas"],
            }
        )

    st.dataframe(
        datos_temas,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "El porcentaje acumulado indica el peso de cada tema sobre "
        "todas las preguntas analizadas. Los porcentajes de aciertos "
        "y fallos se calculan sobre el total de preguntas de ese tema."
    )

    st.divider()
    st.subheader("Resultados acumulados por ley o norma")

    datos_normas = []

    for norma in resultado_acumulado["normas"]:
        datos_normas.append(
            {
                "Ley o norma": norma["norma"],
                "Preguntas": norma["preguntas"],
                "% acumulado": (
                    f'{norma["porcentaje_convocatoria"]:.1f} %'
                ),
                "Aciertos": norma["aciertos"],
                "% aciertos": (
                    f'{norma["porcentaje_aciertos"]:.1f} %'
                ),
                "Fallos": norma["fallos"],
                "% fallos": (
                    f'{norma["porcentaje_fallos"]:.1f} %'
                ),
                "No contestadas": norma["no_contestadas"],
            }
        )

    st.dataframe(
        datos_normas,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Las preguntas jurídicas se agrupan por la ley o norma "
        "congelada en cada simulacro. Las preguntas de informática "
        "aparecen agrupadas como «Informática»."
    )

    st.divider()
    st.subheader("Resultados acumulados por nivel de seguridad")

    datos_seguridad = []

    for seguridad in resultado_acumulado["seguridad"]:
        datos_seguridad.append(
            {
                "Seguridad": seguridad["seguridad"],
                "Contestadas": seguridad["contestadas"],
                "Aciertos": seguridad["aciertos"],
                "% aciertos": (
                    f'{seguridad["porcentaje_aciertos"]:.1f} %'
                ),
                "Fallos": seguridad["fallos"],
                "% fallos": (
                    f'{seguridad["porcentaje_fallos"]:.1f} %'
                ),
            }
        )

    st.dataframe(
        datos_seguridad,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Los porcentajes se calculan sobre todas las preguntas "
        f"contestadas con cada nivel de seguridad en los {tipo_acumulado} "
        "conservados."
    )

    mostrar_analisis_rendimiento(
        resultado_actual=resultado,
        resultado_acumulado=resultado_acumulado,
    )


def mostrar_correccion(
    simulacro_id: int,
    nombre_prueba: str = "simulacro",
) -> None:
    """
    Muestra la edición o el informe objetivo
    de la corrección del simulacro.
    """

    preguntas = obtener_preguntas_simulacro(
        simulacro_id
    )

    st.title(f"Corrección del {nombre_prueba}")

    scroll_key = f"scroll_inicio_correccion_{simulacro_id}"
    if st.session_state.pop(scroll_key, False):
        desplazar_al_inicio()

    if not preguntas:
        st.warning(
            f"El {nombre_prueba} no contiene preguntas."
        )
        return

    modo_key = f"modo_correccion_{simulacro_id}"
    resultado_key = (
        f"resultado_simulacro_{simulacro_id}"
    )

    if modo_key not in st.session_state:
        hay_respuestas_guardadas = any(
            pregunta["respuesta_usuario"] is not None
            or pregunta["seguridad_usuario"] is not None
            for pregunta in preguntas
        )

        st.session_state[modo_key] = (
            "resultado"
            if hay_respuestas_guardadas
            else "edicion"
        )

    if st.session_state[modo_key] == "resultado":
        if resultado_key not in st.session_state:
            st.session_state[resultado_key] = (
                obtener_resultado_simulacro(
                    simulacro_id
                )
            )

        if st.button(
            "Modificar respuestas",
            use_container_width=True,
            key=f"modificar_respuestas_{simulacro_id}",
        ):
            st.session_state[modo_key] = "edicion"
            st.rerun()

        st.divider()

        mostrar_resultado(
            st.session_state[resultado_key],
            nombre_prueba=nombre_prueba,
        )
        return

    st.caption(
        "Traslada las respuestas y el nivel de seguridad "
        "marcados en el simulacro. Para dejar una pregunta "
        "sin contestar, no selecciones ninguna opción o pulsa "
        "de nuevo sobre la opción seleccionada."
    )

    st.divider()

    cabecera = st.columns(
        [0.8, 2.2, 4.0],
        vertical_alignment="center",
    )

    cabecera[0].markdown("**Pregunta**")
    cabecera[1].markdown("**Respuesta**")
    cabecera[2].markdown("**Seguridad**")

    st.divider()

    respuestas_formulario = []

    for pregunta in preguntas:
        simulacro_pregunta_id = pregunta[
            "simulacro_pregunta_id"
        ]

        numero = pregunta["orden"]

        respuesta_key, seguridad_key = (
            inicializar_estado_pregunta(
                simulacro_pregunta_id=(
                    simulacro_pregunta_id
                ),
                respuesta_guardada=pregunta[
                    "respuesta_usuario"
                ],
                seguridad_guardada=pregunta[
                    "seguridad_usuario"
                ],
            )
        )

        fila = st.columns(
            [0.8, 2.2, 4.0],
            vertical_alignment="center",
        )

        fila[0].markdown(
            f"### {numero}"
        )

        with fila[1]:
            respuesta_usuario = st.segmented_control(
                label=(
                    f"Respuesta de la pregunta "
                    f"{numero}"
                ),
                options=RESPUESTAS,
                selection_mode="single",
                required=False,
                key=respuesta_key,
                label_visibility="collapsed",
                width="stretch",
                on_change=marcar_correccion_modificada,
                args=(simulacro_id,),
            )

        if respuesta_usuario is None:
            st.session_state[
                seguridad_key
            ] = None

        with fila[2]:
            seguridad_etiqueta = (
                st.segmented_control(
                    label=(
                        f"Seguridad de la pregunta "
                        f"{numero}"
                    ),
                    options=list(
                        SEGURIDADES.keys()
                    ),
                    selection_mode="single",
                    required=False,
                    key=seguridad_key,
                    disabled=(
                        respuesta_usuario is None
                    ),
                    label_visibility="collapsed",
                    width="stretch",
                    on_change=(
                        marcar_correccion_modificada
                    ),
                    args=(simulacro_id,),
                )
            )

        seguridad_usuario = (
            SEGURIDADES.get(
                seguridad_etiqueta
            )
            if respuesta_usuario is not None
            else None
        )

        respuestas_formulario.append(
            {
                "numero": numero,
                "simulacro_pregunta_id": (
                    simulacro_pregunta_id
                ),
                "respuesta_usuario": (
                    respuesta_usuario
                ),
                "seguridad_usuario": (
                    seguridad_usuario
                ),
            }
        )

        st.divider()

    guardar = st.button(
        "Guardar respuestas",
        type="primary",
        use_container_width=True,
        key=f"guardar_correccion_{simulacro_id}",
    )

    if guardar:
        preguntas_sin_seguridad = [
            respuesta["numero"]
            for respuesta in respuestas_formulario
            if (
                respuesta["respuesta_usuario"]
                is not None
                and respuesta["seguridad_usuario"]
                is None
            )
        ]

        if preguntas_sin_seguridad:
            numeros = ", ".join(
                str(numero)
                for numero in preguntas_sin_seguridad
            )

            st.error(
                "Falta indicar el nivel de seguridad "
                "en las siguientes preguntas "
                f"contestadas: {numeros}."
            )
            return

        guardadas = 0

        for respuesta in respuestas_formulario:
            resultado_guardado = (
                guardar_respuesta_simulacro(
                    simulacro_pregunta_id=respuesta[
                        "simulacro_pregunta_id"
                    ],
                    respuesta_usuario=respuesta[
                        "respuesta_usuario"
                    ],
                    seguridad_usuario=respuesta[
                        "seguridad_usuario"
                    ],
                )
            )

            if resultado_guardado:
                guardadas += 1

        if guardadas == len(
            respuestas_formulario
        ):
            contestadas = sum(
                1
                for respuesta in respuestas_formulario
                if respuesta[
                    "respuesta_usuario"
                ] is not None
            )

            no_contestadas = (
                len(respuestas_formulario)
                - contestadas
            )

            st.session_state[
                f"correccion_guardada_{simulacro_id}"
            ] = True

            st.session_state.pop(
                resultado_key,
                None,
            )

            st.success(
                "Respuestas guardadas correctamente. "
                f"Contestadas: {contestadas}. "
                f"No contestadas: {no_contestadas}."
            )
        else:
            st.warning(
                f"Se han guardado {guardadas} de "
                f"{len(respuestas_formulario)} preguntas."
            )

    correccion_guardada = st.session_state.get(
        f"correccion_guardada_{simulacro_id}",
        False,
    )

    if correccion_guardada:
        st.divider()

        calificar = st.button(
            f"Calificar {nombre_prueba}",
            type="primary",
            use_container_width=True,
            key=f"calificar_simulacro_{simulacro_id}",
        )

        if calificar:
            st.session_state[resultado_key] = (
                obtener_resultado_simulacro(
                    simulacro_id
                )
            )
            st.session_state[modo_key] = "resultado"
            st.session_state[scroll_key] = True
            st.rerun()