"""
==============================================================================
OpoCoach
Archivo: analisis_rendimiento.py
==============================================================================

Construcción del prompt y generación del comentario IA sobre el rendimiento
acumulado de una convocatoria.

La estadística llega ya calculada desde lib.repositorio. Este módulo no accede
a SQLite ni modifica datos.
==============================================================================
"""

from tools.openai_api import generar_analisis_rendimiento_ia


def _umbral_equilibrio(
    valor_acierto: float,
    valor_fallo: float,
    valor_no_contesta: float,
) -> float | None:
    """Devuelve la probabilidad mínima de acierto para que contestar compense."""

    denominador = valor_acierto - valor_fallo

    if denominador <= 0:
        return None

    return (valor_no_contesta - valor_fallo) / denominador


def _rendimiento_neto_por_respuesta(
    aciertos: int,
    fallos: int,
    valor_acierto: float,
    valor_fallo: float,
) -> float | None:
    """Puntuación bruta media observada por respuesta contestada."""

    contestadas = aciertos + fallos

    if contestadas <= 0:
        return None

    return (
        aciertos * valor_acierto
        + fallos * valor_fallo
    ) / contestadas


def _impacto_frente_a_omitir(
    aciertos: int,
    fallos: int,
    valor_acierto: float,
    valor_fallo: float,
    valor_no_contesta: float,
) -> float:
    """
    Diferencia de puntuación bruta entre haber contestado esas preguntas y
    haberlas dejado todas sin contestar.
    """

    return (
        aciertos * (valor_acierto - valor_no_contesta)
        + fallos * (valor_fallo - valor_no_contesta)
    )


def _porcentaje(parte: int | float, total: int | float) -> float:
    if total <= 0:
        return 0.0
    return 100.0 * parte / total


def _calidad_muestra(n: int) -> str:
    """Etiqueta descriptiva para ayudar a moderar la interpretación."""

    if n < 5:
        return "muestra reducida"
    if n < 15:
        return "muestra intermedia"
    return "muestra amplia"


def construir_prompt_analisis_rendimiento(
    resultado_actual: dict,
    resultado_acumulado: dict,
) -> str:
    """Construye un prompt con indicadores objetivos ya calculados."""

    valor_acierto = float(resultado_actual["valor_acierto"])
    valor_fallo = float(resultado_actual["valor_fallo"])
    valor_no_contesta = float(resultado_actual["valor_no_contesta"])

    umbral = _umbral_equilibrio(
        valor_acierto=valor_acierto,
        valor_fallo=valor_fallo,
        valor_no_contesta=valor_no_contesta,
    )

    lineas_temas = []

    for tema in resultado_acumulado["temas"]:
        preguntas = int(tema["preguntas"])
        contestadas = int(tema["aciertos"]) + int(tema["fallos"])
        tasa_fallos_contestadas = _porcentaje(
            int(tema["fallos"]),
            contestadas,
        )
        tasa_omisiones = _porcentaje(
            int(tema["no_contestadas"]),
            preguntas,
        )

        lineas_temas.append(
            "- "
            f'{tema["parte"]} {tema["numero_tema"]}. {tema["titulo"]}: '
            f'{preguntas} preguntas ({_calidad_muestra(preguntas)}); '
            f'{tema["aciertos"]} aciertos; '
            f'{tema["fallos"]} fallos; '
            f'{tema["no_contestadas"]} no contestadas; '
            f'{tema["porcentaje_aciertos"]:.1f} % de aciertos sobre el total; '
            f'{tema["porcentaje_aciertos_contestadas"]:.1f} % de aciertos '
            "entre las contestadas; "
            f'{tasa_fallos_contestadas:.1f} % de fallos entre las contestadas; '
            f'{tasa_omisiones:.1f} % de omisiones; '
            f'{tema["fallos_muy_seguro"]} fallos marcados como Muy seguro.'
        )

    lineas_normas = []

    for norma in resultado_acumulado["normas"]:
        preguntas = int(norma["preguntas"])
        contestadas = int(norma["aciertos"]) + int(norma["fallos"])
        tasa_fallos_contestadas = _porcentaje(
            int(norma["fallos"]),
            contestadas,
        )
        tasa_omisiones = _porcentaje(
            int(norma["no_contestadas"]),
            preguntas,
        )

        lineas_normas.append(
            "- "
            f'{norma["norma"]}: '
            f'{preguntas} preguntas ({_calidad_muestra(preguntas)}); '
            f'{norma["aciertos"]} aciertos; '
            f'{norma["fallos"]} fallos; '
            f'{norma["no_contestadas"]} no contestadas; '
            f'{norma["porcentaje_aciertos"]:.1f} % de aciertos '
            "sobre el total; "
            f'{norma["porcentaje_aciertos_contestadas"]:.1f} % de '
            "aciertos entre las contestadas; "
            f'{tasa_fallos_contestadas:.1f} % de fallos entre las contestadas; '
            f'{tasa_omisiones:.1f} % de omisiones; '
            f'{norma["fallos_muy_seguro"]} fallos marcados como Muy seguro.'
        )

    lineas_seguridad = []

    for seguridad in resultado_acumulado["seguridad"]:
        contestadas = int(seguridad["contestadas"])
        aciertos = int(seguridad["aciertos"])
        fallos = int(seguridad["fallos"])
        tasa_aciertos = float(seguridad["porcentaje_aciertos"])

        rendimiento_neto = _rendimiento_neto_por_respuesta(
            aciertos=aciertos,
            fallos=fallos,
            valor_acierto=valor_acierto,
            valor_fallo=valor_fallo,
        )

        impacto_omitir = _impacto_frente_a_omitir(
            aciertos=aciertos,
            fallos=fallos,
            valor_acierto=valor_acierto,
            valor_fallo=valor_fallo,
            valor_no_contesta=valor_no_contesta,
        )

        rendimiento_texto = (
            f"{rendimiento_neto:+.3f} puntos brutos por respuesta"
            if rendimiento_neto is not None
            else "sin muestra"
        )

        if umbral is not None and contestadas > 0:
            margen_umbral = tasa_aciertos - (umbral * 100.0)
            margen_texto = (
                f"{margen_umbral:+.1f} puntos porcentuales respecto "
                "al umbral de equilibrio"
            )
        else:
            margen_texto = "margen respecto al umbral no calculable"

        lineas_seguridad.append(
            "- "
            f'{seguridad["seguridad"]}: '
            f'{contestadas} contestadas ({_calidad_muestra(contestadas)}); '
            f'{aciertos} aciertos; '
            f'{fallos} fallos; '
            f'{tasa_aciertos:.1f} % de aciertos; '
            f'{margen_texto}; '
            f"rendimiento neto observado: {rendimiento_texto}; "
            f"impacto observado de contestarlas frente a haberlas dejado "
            f"en blanco: {impacto_omitir:+.3f} puntos brutos."
        )

    umbral_texto = (
        f"{umbral * 100:.1f} %"
        if umbral is not None
        else "no calculable con estos valores"
    )

    total_preguntas = int(resultado_acumulado["preguntas"])
    total_contestadas = int(resultado_acumulado["contestadas"])
    total_fallos = int(resultado_acumulado["fallos"])
    total_no_contestadas = int(resultado_acumulado["no_contestadas"])

    tasa_contestacion = _porcentaje(total_contestadas, total_preguntas)
    tasa_error_contestadas = _porcentaje(total_fallos, total_contestadas)
    tasa_omisiones = _porcentaje(total_no_contestadas, total_preguntas)

    return f"""
Eres el analista de rendimiento de OpoCoach. Tu función no es repetir las
estadísticas, sino convertirlas en decisiones útiles de estudio y estrategia
de examen para un opositor.

Utiliza exclusivamente los datos e indicadores ya calculados que aparecen a
continuación. No consultes normas, no aportes teoría jurídica y no uses
conocimiento externo.

REGLAS OBLIGATORIAS

1. No inventes datos. Puedes comparar e interpretar los indicadores que ya
   están calculados, pero no presentes cifras nuevas que no figuren en los
   datos proporcionados.
2. Evita resumir las tablas en prosa salvo cuando un dato sea necesario para
   justificar una conclusión concreta.
3. Cada prioridad o recomendación debe explicar POR QUÉ importa y QUÉ debería
   hacer el opositor con ella.
4. Distingue claramente entre:
   - riesgo de conocimiento: fallos u omisiones concentrados en materias;
   - riesgo de falsa seguridad: fallos marcados como Muy seguro;
   - riesgo estratégico: niveles de seguridad cuyo rendimiento observado se
     acerca o cae por debajo del umbral de equilibrio.
5. Trata los fallos marcados como Muy seguro como señales especialmente
   importantes: pueden revelar conocimiento incorrectamente consolidado. No
   atribuyas causas psicológicas ni personales.
6. Considera reducida cualquier muestra inferior a 5 preguntas y evita
   conclusiones firmes basadas en ella. Las muestras de 5 a 14 son
   intermedias y las de 15 o más permiten conclusiones más consistentes.
7. Para priorizar estudio, combina tamaño de muestra, fallos, omisiones,
   porcentaje de aciertos y fallos Muy seguro. No conviertas automáticamente
   el menor porcentaje en la máxima prioridad.
8. En estrategia de examen, usa el margen respecto al umbral y el impacto
   observado de contestar frente a dejar en blanco. Si una categoría aporta
   puntuación positiva, dilo; si destruye puntuación, dilo claramente. No
   aconsejes contestar al azar.
9. Cuando los datos lo permitan, identifica una política práctica distinta
   para Muy seguro, Bastante seguro y Poco seguro. No uses una recomendación
   genérica común para los tres niveles.
10. Las preguntas no contestadas carecen de nivel de seguridad. No supongas
    por qué se dejaron en blanco.
11. Indica el grado de confianza del diagnóstico según el volumen de datos:
    con una sola prueba, habla de señales iniciales, no de patrones estables.
12. Termina con un plan de actuación concreto, priorizado y breve. Debe ser
    posible aplicarlo al siguiente bloque de estudio o al siguiente examen.
13. Máximo 600 palabras.

Usa exactamente estos encabezados Markdown:

### Diagnóstico general
### Riesgos prioritarios
### Estrategia de examen
### Plan de actuación

DATOS DE LA PRUEBA ACTUAL

- Preguntas: {resultado_actual["total"]}
- Aciertos: {resultado_actual["aciertos"]}
- Fallos: {resultado_actual["fallos"]}
- No contestadas: {resultado_actual["no_contestadas"]}
- Nota: {resultado_actual["nota"]:.2f}

DATOS ACUMULADOS DE LA CONVOCATORIA

- Pruebas corregidas conservadas: {resultado_acumulado["simulacros"]}
- Preguntas analizadas: {total_preguntas}
- Contestadas: {total_contestadas}
- Aciertos: {resultado_acumulado["aciertos"]}
- Fallos: {total_fallos}
- No contestadas: {total_no_contestadas}
- Tasa de contestación ya calculada: {tasa_contestacion:.1f} %
- Tasa de error entre contestadas ya calculada: {tasa_error_contestadas:.1f} %
- Tasa de omisiones ya calculada: {tasa_omisiones:.1f} %

REGLAS DE PUNTUACIÓN DE LA PRUEBA ACTUAL

- Acierto: {valor_acierto:+.3f} puntos
- Fallo: {valor_fallo:+.3f} puntos
- No contestada: {valor_no_contesta:+.3f} puntos
- Umbral de equilibrio ya calculado: {umbral_texto} de probabilidad de acierto

RESULTADOS ACUMULADOS POR TEMA

{chr(10).join(lineas_temas)}

RESULTADOS ACUMULADOS POR LEY O NORMA

{chr(10).join(lineas_normas)}

RESULTADOS ACUMULADOS POR NIVEL DE SEGURIDAD

{chr(10).join(lineas_seguridad)}
""".strip()


def generar_analisis_rendimiento(
    resultado_actual: dict,
    resultado_acumulado: dict,
) -> str:
    """Solicita a la IA la redacción del análisis acumulado."""

    if resultado_acumulado["simulacros"] <= 0:
        raise ValueError(
            "No existen pruebas corregidas para generar el análisis."
        )

    prompt = construir_prompt_analisis_rendimiento(
        resultado_actual=resultado_actual,
        resultado_acumulado=resultado_acumulado,
    )

    return generar_analisis_rendimiento_ia(
        prompt=prompt,
    ).strip()