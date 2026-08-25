"""
==============================================================================
OpoCoach
Página: Instrucciones
==============================================================================

Página de ayuda para explicar qué hace la aplicación y cómo utilizarla.

==============================================================================
"""

import streamlit as st


st.set_page_config(
    page_title="Instrucciones | OpoCoach",
    page_icon="📘",
    layout="wide",
)


st.title("📘 OpoCoach – Guía rápida de uso")

st.markdown(
    """
OpoCoach es una plataforma de entrenamiento para oposiciones que permite
generar simulacros personalizados, realizarlos en condiciones similares a un
examen oficial y obtener una corrección detallada con explicaciones de cada
respuesta.

Su objetivo es ayudar al opositor a detectar sus puntos fuertes y débiles y a
organizar mejor el estudio.
"""
)

st.divider()

st.header("Cómo funciona")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Seleccionar una convocatoria")
    st.markdown(
        """
Elija la convocatoria que desea preparar.

Cada convocatoria dispone de:

- su propio temario;
- su banco de preguntas;
- su normativa y corpus documental asociados;
- sus reglas de puntuación.
"""
    )

    st.subheader("2. Generar un simulacro")
    st.markdown(
        """
OpoCoach crea un examen respetando la estructura definida para la convocatoria.

Antes de generarlo, puede elegir el origen de las preguntas entre:

- A1;
- A2;
- C1;
- C2.

Puede seleccionar uno, varios o todos los orígenes. Es obligatorio mantener al
menos uno seleccionado.

Las preguntas del banco que no tienen origen asignado se incorporan siempre de
forma automática. Estas preguntas no aparecen entre las opciones de selección.

El simulacro mantiene en todo caso la distribución configurada para la
convocatoria y puede incluir diferentes bloques:

- preguntas teóricas;
- casos prácticos;
- informática;
- preguntas generales.

Las preguntas se seleccionan del banco disponible para ofrecer exámenes
variados.
"""
    )

with col2:
    st.subheader("3. Realizar el examen")
    st.markdown(
        """
Durante el simulacro puede:

- responder A, B, C o D;
- dejar preguntas sin contestar;
- indicar el grado de seguridad de cada respuesta:
  - Muy seguro
  - Bastante seguro
  - Poco seguro

La seguridad indicada permite analizar posteriormente no solo los aciertos y
errores, sino también el nivel de confianza con el que se contestó.
"""
    )

    st.subheader("4. Corregir el simulacro")
    st.markdown(
        """
Al finalizar, OpoCoach muestra la corrección del examen.

La página de resultados incluye:

- preguntas acertadas;
- preguntas falladas;
- preguntas no contestadas;
- nota obtenida según las reglas de la convocatoria;
- estadísticas por materias o bloques.
"""
    )

st.divider()

st.header("Documentos del simulacro")

tab_preguntas, tab_soluciones = st.tabs(
    ["PDF de preguntas", "PDF de soluciones"]
)

with tab_preguntas:
    st.markdown(
        """
El PDF de preguntas permite realizar el simulacro fuera de la aplicación o
imprimirlo.

Incluye:

- todas las preguntas del examen;
- las opciones de respuesta;
- espacios para marcar la respuesta;
- indicación del grado de seguridad.
"""
    )

with tab_soluciones:
    st.markdown(
        """
El PDF de soluciones incluye:

- el listado completo de respuestas correctas;
- un resumen estadístico;
- un comentario explicativo para cada pregunta.

En las preguntas jurídicas, la explicación se basa en la normativa asociada a
la convocatoria.

En las preguntas de informática, la explicación describe el concepto técnico
que justifica la respuesta correcta.
"""
    )

st.divider()

st.header("Banco de preguntas")

st.markdown(
    """
Los simulacros se generan a partir de un banco preparado específicamente para
cada convocatoria.

Las preguntas han sido clasificadas y vinculadas al temario correspondiente.
Esto permite crear simulacros variados y mantener la coherencia con el
contenido exigido en la oposición.
"""
)

st.header("Recomendaciones de uso")

st.info(
    """
- Realice simulacros completos siempre que sea posible.
- Conteste antes de consultar las soluciones.
- Indique el nivel de seguridad de cada respuesta.
- Revise especialmente los errores contestados con mucha seguridad.
- Lea los comentarios del PDF de soluciones.
- Repita simulacros periódicamente para comprobar su evolución.
"""
)

st.warning(
    """
OpoCoach es una herramienta de entrenamiento.

Las explicaciones de las soluciones tienen finalidad didáctica. Para el estudio
debe prevalecer siempre la legislación vigente, las bases de la convocatoria y
los materiales oficiales.
"""
)