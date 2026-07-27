"""
==============================================================================
OpoCoach
Archivo: lib/conocimiento_opocoach.py
==============================================================================

Descripción:
    Base de conocimiento interna sobre el funcionamiento de OpoCoach.

    Cada elemento es un bloque autosuficiente que puede ser recuperado por el
    chat. Este archivo no accede a la base de datos y no modifica el corpus
    normativo de las convocatorias.

==============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EntradaConocimientoOpoCoach:
    clave: str
    titulo: str
    palabras_clave: tuple[str, ...]
    texto: str


ENTRADAS_CONOCIMIENTO_OPOCOACH: tuple[EntradaConocimientoOpoCoach, ...] = (
    EntradaConocimientoOpoCoach(
        clave="descripcion_general",
        titulo="Qué es OpoCoach y para qué sirve",
        palabras_clave=(
            "opocoach", "aplicacion", "funcionamiento", "para que sirve",
            "objetivo", "entrenamiento", "oposicion", "oposiciones",
        ),
        texto=(
            "OpoCoach es una aplicación de entrenamiento para oposiciones. "
            "Permite seleccionar una convocatoria, generar simulacros basados "
            "en su estructura y banco de preguntas, responderlos dentro de la "
            "aplicación o mediante un PDF, corregirlos y consultar resultados y "
            "explicaciones. Su finalidad es ayudar a practicar, detectar puntos "
            "fuertes y débiles y revisar los errores. No sustituye las bases de "
            "la convocatoria, la legislación vigente ni los materiales oficiales."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="convocatoria_activa",
        titulo="Convocatoria activa",
        palabras_clave=(
            "convocatoria", "convocatoria activa", "seleccionar convocatoria",
            "cambiar convocatoria", "temario", "reglas puntuacion",
        ),
        texto=(
            "La convocatoria activa determina el ámbito de trabajo de OpoCoach. "
            "Cada convocatoria dispone de su propio temario, banco de preguntas, "
            "corpus documental, estructura del examen y reglas de puntuación. "
            "Antes de utilizar los simulacros o el chat debe seleccionarse una "
            "convocatoria en la página de inicio. Al cambiar de convocatoria, el "
            "chat inicia una conversación independiente para evitar mezclar "
            "contenidos de convocatorias distintas."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="banco_preguntas",
        titulo="Banco de preguntas",
        palabras_clave=(
            "banco", "banco de preguntas", "preguntas disponibles",
            "origen preguntas", "preguntas oficiales", "repetir preguntas",
            "seleccion preguntas", "numero de preguntas disponibles",
        ),
        texto=(
            "Los simulacros se generan a partir del banco de preguntas asociado "
            "a la convocatoria activa. Las preguntas están clasificadas y "
            "vinculadas al temario correspondiente. El número de preguntas "
            "disponibles puede variar cuando se amplía o revisa el banco. La "
            "aplicación selecciona las preguntas necesarias para respetar la "
            "estructura configurada del simulacro. Que una pregunta proceda del "
            "banco no significa necesariamente que sea una pregunta oficial de "
            "la convocatoria activa; su procedencia depende de los materiales "
            "incorporados y clasificados en el banco."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="generacion_simulacro",
        titulo="Generación de simulacros",
        palabras_clave=(
            "generar", "crear simulacro", "nuevo simulacro", "simulacro",
            "estructura examen", "bloques", "teoricas", "practicas",
            "informatica", "preguntas generales",
        ),
        texto=(
            "OpoCoach genera cada simulacro respetando la estructura definida "
            "para la convocatoria activa. Esa estructura puede distribuir las "
            "preguntas en bloques, por ejemplo teoría, práctica, informática o "
            "parte general. La selección se realiza entre las preguntas válidas "
            "del banco para esa convocatoria. Un simulacro queda guardado para "
            "poder descargarlo, corregirlo o consultar posteriormente sus "
            "resultados."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="realizacion_simulacro",
        titulo="Cómo responder un simulacro",
        palabras_clave=(
            "responder", "contestar", "respuesta", "a b c d", "sin contestar",
            "dejar en blanco", "realizar examen", "hacer simulacro",
        ),
        texto=(
            "En la corrección del simulacro puede seleccionarse una respuesta A, "
            "B, C o D para cada pregunta. También es posible dejar una pregunta "
            "sin contestar. Una respuesta solo se considera contestada cuando se "
            "ha seleccionado una opción. El nivel de seguridad es un dato "
            "adicional y no sustituye la respuesta. Las respuestas y la seguridad "
            "indicadas se guardan para calcular el resultado y permitir su revisión."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="nivel_seguridad",
        titulo="Nivel de seguridad de una respuesta",
        palabras_clave=(
            "seguridad", "nivel de seguridad", "muy seguro", "bastante seguro",
            "poco seguro", "confianza", "grado de seguridad", "para que se usa",
        ),
        texto=(
            "El nivel de seguridad expresa el grado de confianza con el que el "
            "usuario contesta una pregunta. Los niveles disponibles son Muy "
            "seguro, Bastante seguro y Poco seguro. Este dato no cambia la "
            "respuesta elegida ni modifica directamente la nota del simulacro. "
            "Se utiliza para comparar el resultado real con la percepción del "
            "usuario: permite distinguir un conocimiento firme, una respuesta "
            "dudosa y un posible error conceptual asumido como correcto. Conviene "
            "indicarlo con sinceridad antes de conocer la solución."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="interpretacion_seguridad",
        titulo="Cómo interpretar la seguridad y el resultado",
        palabras_clave=(
            "error muy seguro", "fallo seguro", "acierto poco seguro",
            "interpretar seguridad", "analisis confianza", "riesgo",
            "conocimiento firme", "error conceptual",
        ),
        texto=(
            "Un acierto marcado como Muy seguro suele indicar conocimiento firme. "
            "Un error marcado como Muy seguro merece una revisión prioritaria, "
            "porque puede revelar un concepto aprendido de forma incorrecta. Un "
            "acierto marcado como Poco seguro puede indicar conocimiento todavía "
            "inestable, descarte entre opciones o acierto con dudas. Un error "
            "marcado como Poco seguro confirma que el usuario ya percibía falta de "
            "dominio. Esta interpretación sirve para decidir qué contenidos "
            "revisar primero, pero no altera por sí sola la puntuación."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="correccion_resultados",
        titulo="Corrección y resultados del simulacro",
        palabras_clave=(
            "corregir", "correccion", "resultado", "resultados", "nota",
            "acertadas", "falladas", "no contestadas", "puntuacion",
            "porcentaje", "estadisticas por tema",
        ),
        texto=(
            "La corrección compara las respuestas del usuario con las respuestas "
            "correctas guardadas en el simulacro. El resultado muestra preguntas "
            "acertadas, falladas y no contestadas, y calcula la nota aplicando las "
            "reglas de puntuación de la convocatoria activa. Cuando están "
            "disponibles, también se presentan estadísticas por temas o bloques "
            "para localizar áreas con mejor o peor rendimiento. La nota depende de "
            "aciertos, errores, respuestas en blanco y fórmula configurada; el "
            "nivel de seguridad no modifica ese cálculo."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="pdf_preguntas",
        titulo="PDF de preguntas",
        palabras_clave=(
            "pdf preguntas", "descargar preguntas", "imprimir examen",
            "hacer fuera aplicacion", "documento preguntas", "marcar seguridad",
        ),
        texto=(
            "Para descargar el PDF de preguntas, abra la página Simulacros, "
            "localice en el listado o cuadrícula el simulacro correspondiente y "
            "pulse el botón «Descargar preguntas» de ese simulacro. El documento "
            "permite realizar el examen fuera de la aplicación o imprimirlo. "
            "Contiene las preguntas, sus opciones de respuesta y espacios para "
            "anotar la opción elegida y el nivel de seguridad. Las marcas hechas "
            "en papel no se corrigen automáticamente: para obtener el resultado "
            "en OpoCoach deben trasladarse las respuestas a la página de "
            "corrección del simulacro."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="pdf_soluciones",
        titulo="PDF de soluciones",
        palabras_clave=(
            "pdf soluciones", "descargar soluciones", "comentario solucion",
            "explicacion respuesta", "soluciones", "respuesta correcta",
        ),
        texto=(
            "Para descargar el PDF de soluciones, abra la página Simulacros, "
            "localice en el listado o cuadrícula el simulacro correspondiente y "
            "pulse el botón «Descargar soluciones» de ese simulacro. El PDF "
            "contiene el listado de respuestas correctas y puede incluir un "
            "resumen y un comentario explicativo para cada pregunta. En las "
            "preguntas jurídicas, la explicación se basa en la norma y el "
            "artículo asociados a la convocatoria. En las preguntas de "
            "informática, explica el concepto técnico relacionado con la "
            "respuesta correcta. Los comentarios tienen finalidad didáctica y "
            "no sustituyen la consulta de las fuentes oficiales."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="chat_convocatoria",
        titulo="Chat de la convocatoria",
        palabras_clave=(
            "chat", "asistente", "preguntar", "que puede responder",
            "fuentes chat", "corpus", "conocimiento externo", "no responde",
            "limpiar conversacion",
        ),
        texto=(
            "El chat responde utilizando únicamente dos fuentes internas: el "
            "corpus asignado a la convocatoria activa y esta base de conocimiento "
            "sobre el funcionamiento de OpoCoach. Puede explicar contenidos del "
            "temario recuperados del corpus y resolver dudas sobre el uso de la "
            "aplicación. No debe completar la respuesta con información externa. "
            "Si las fuentes recuperadas no contienen información suficiente, debe "
            "decirlo. El botón Limpiar conversación elimina el historial visible "
            "de la conversación actual, pero no modifica simulacros ni resultados."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="limites_uso",
        titulo="Alcance y limitaciones de OpoCoach",
        palabras_clave=(
            "limitaciones", "fiabilidad", "legislacion vigente", "oficial",
            "asesoramiento", "errores", "garantia", "sustituye", "actualizado",
        ),
        texto=(
            "OpoCoach es una herramienta de entrenamiento. Sus simulacros, "
            "explicaciones y estadísticas ayudan a estudiar, pero no sustituyen "
            "las bases oficiales, la legislación vigente ni los materiales "
            "publicados por la administración convocante. El chat no presta "
            "asesoramiento jurídico para casos reales. Si una respuesta no está "
            "respaldada por el corpus de la convocatoria o por la base de "
            "conocimiento de la aplicación, el asistente debe reconocer que no "
            "dispone de información suficiente."
        ),
    ),
    EntradaConocimientoOpoCoach(
        clave="uso_recomendado",
        titulo="Uso recomendado de OpoCoach",
        palabras_clave=(
            "recomendaciones", "como usar", "mejor forma", "estudiar",
            "revisar errores", "repetir simulacros", "consejos uso",
        ),
        texto=(
            "Para aprovechar OpoCoach conviene realizar simulacros completos, "
            "contestar antes de consultar las soluciones, indicar el nivel de "
            "seguridad con sinceridad y revisar especialmente los errores marcados "
            "como Muy seguro. También es útil estudiar los comentarios de las "
            "soluciones, observar los resultados por temas y repetir simulacros "
            "periódicamente para comparar la evolución."
        ),
    ),
)