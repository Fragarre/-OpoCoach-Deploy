"""
==============================================================================
OpoCoach
Archivo: pages/04_Chat.py
==============================================================================

Descripción:
    Chat de la convocatoria y chat de conocimiento general.

==============================================================================
"""

import streamlit as st

from lib.chat_convocatoria import responder_chat
from lib.contexto import obtener_contexto
from lib.sesion import obtener_convocatoria_id


st.title("Chat")

convocatoria_id = obtener_convocatoria_id()

if convocatoria_id is None:
    st.warning(
        "Debe seleccionar una convocatoria en la página Inicio."
    )
    st.stop()

contexto = obtener_contexto()

if contexto is None:
    st.error("La convocatoria seleccionada no existe.")
    st.stop()

st.caption(
    f'{contexto["codigo"]} — '
    f'{contexto["puesto"]}'
)

opciones_modo = {
    "Convocatoria y OpoCoach": "CONVOCATORIA",
    "Conocimiento general de GPT": "GENERAL",
}

etiqueta_modo = st.radio(
    "Modo de consulta",
    options=list(opciones_modo),
    horizontal=True,
    key="chat_modo_etiqueta",
)

modo = opciones_modo[etiqueta_modo]

if modo == "CONVOCATORIA":
    st.info(
        "Las respuestas se limitan al corpus de la convocatoria "
        "activa y a la base de conocimiento de OpoCoach."
    )
    texto_entrada = (
        "Escriba una duda sobre la convocatoria o sobre OpoCoach..."
    )
    texto_spinner = "Consultando las fuentes disponibles..."
else:
    st.warning(
        "Este modo utiliza conocimiento general de GPT. Sus respuestas "
        "pueden incluir información ajena al temario y no están "
        "respaldadas por el corpus de la convocatoria."
    )
    texto_entrada = "Escriba una pregunta de conocimiento general..."
    texto_spinner = "Generando una respuesta de conocimiento general..."

clave_convocatoria_chat = "chat_convocatoria_id"

if (
    st.session_state.get(clave_convocatoria_chat)
    != convocatoria_id
):
    st.session_state[clave_convocatoria_chat] = convocatoria_id
    st.session_state["chat_mensajes_convocatoria"] = []
    st.session_state["chat_mensajes_general"] = []

clave_mensajes = (
    "chat_mensajes_convocatoria"
    if modo == "CONVOCATORIA"
    else "chat_mensajes_general"
)

mensajes = st.session_state.setdefault(
    clave_mensajes,
    [],
)

columna_limpiar, columna_espacio = st.columns([1, 4])

with columna_limpiar:
    if st.button(
        "Limpiar conversación",
        use_container_width=True,
        key=f"limpiar_chat_{modo.lower()}",
    ):
        st.session_state[clave_mensajes] = []
        st.rerun()

for mensaje in mensajes:
    rol = mensaje.get("role")

    if rol not in {"user", "assistant"}:
        continue

    with st.chat_message(rol):
        st.markdown(mensaje.get("content", ""))

pregunta = st.chat_input(texto_entrada)

if pregunta:
    pregunta_limpia = " ".join(pregunta.split())

    if pregunta_limpia:
        mensajes.append(
            {
                "role": "user",
                "content": pregunta_limpia,
            }
        )

        with st.chat_message("user"):
            st.markdown(pregunta_limpia)

        with st.chat_message("assistant"):
            with st.spinner(texto_spinner):
                try:
                    resultado = responder_chat(
                        convocatoria_id=convocatoria_id,
                        pregunta=pregunta_limpia,
                        mensajes_previos=mensajes[:-1],
                        modo=modo,
                    )

                    respuesta = resultado["respuesta"]
                    st.markdown(respuesta)

                except Exception as exc:
                    respuesta = (
                        "No se ha podido generar la respuesta. "
                        f"Error: {exc}"
                    )
                    st.error(respuesta)

        mensajes.append(
            {
                "role": "assistant",
                "content": respuesta,
            }
        )