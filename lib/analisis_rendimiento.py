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
    contestadas = aciertos + fallos

    if contestadas <= 0:
        return None

    return (
        aciertos * valor_acierto
        + fallos * valor_fallo
    ) / contestadas


def construir_prompt_analisis_rendimiento(
    resultado_actual: dict,
    resultado_acumulado: dict,
) -> str:
    """Construye un prompt cerrado basado solo en estadísticas objetivas."""

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
        lineas_temas.append(
            "- "
            f'{tema["parte"]} {tema["numero_tema"]}. {tema["titulo"]}: '
            f'{tema["preguntas"]} preguntas; '
            f'{tema["aciertos"]} aciertos; '
            f'{tema["fallos"]} fallos; '
            f'{tema["no_contestadas"]} no contestadas; '
            f'{tema["porcentaje_aciertos"]:.1f} % de aciertos sobre el total; '
            f'{tema["porcentaje_aciertos_contestadas"]:.1f} % de aciertos '
            "entre las contestadas; "
            f'{tema["fallos_muy_seguro"]} fallos marcados como Muy seguro.'
        )

    lineas_normas = []

    for norma in resultado_acumulado["normas"]:
        lineas_normas.append(
            "- "
            f'{norma["norma"]}: '
            f'{norma["preguntas"]} preguntas; '
            f'{norma["aciertos"]} aciertos; '
            f'{norma["fallos"]} fallos; '
            f'{norma["no_contestadas"]} no contestadas; '
            f'{norma["porcentaje_aciertos"]:.1f} % de aciertos '
            "sobre el total; "
            f'{norma["porcentaje_aciertos_contestadas"]:.1f} % de '
            "aciertos entre las contestadas; "
            f'{norma["fallos_muy_seguro"]} fallos marcados como '
            "Muy seguro."
        )

    lineas_seguridad = []

    for seguridad in resultado_acumulado["seguridad"]:
        rendimiento_neto = _rendimiento_neto_por_respuesta(
            aciertos=seguridad["aciertos"],
            fallos=seguridad["fallos"],
            valor_acierto=valor_acierto,
            valor_fallo=valor_fallo,
        )

        rendimiento_texto = (
            f"{rendimiento_neto:.3f} puntos por respuesta"
            if rendimiento_neto is not None
            else "sin muestra"
        )

        lineas_seguridad.append(
            "- "
            f'{seguridad["seguridad"]}: '
            f'{seguridad["contestadas"]} contestadas; '
            f'{seguridad["aciertos"]} aciertos; '
            f'{seguridad["fallos"]} fallos; '
            f'{seguridad["porcentaje_aciertos"]:.1f} % de aciertos; '
            f"rendimiento neto observado: {rendimiento_texto}."
        )

    umbral_texto = (
        f"{umbral * 100:.1f} %"
        if umbral is not None
        else "no calculable con estos valores"
    )

    return f"""
Eres el analista de rendimiento de OpoCoach.

Redacta un comentario breve, claro y útil para un opositor. Debes utilizar
exclusivamente los datos que aparecen a continuación. No consultes normas,
no aportes teoría jurídica y no uses conocimiento externo.

REGLAS OBLIGATORIAS

1. No inventes datos ni realices nuevos cálculos.
2. No atribuyas causas psicológicas o personales al usuario.
3. Distingue con claridad entre datos sólidos y muestras pequeñas.
4. Considera reducida cualquier muestra inferior a 5 preguntas y evita
   conclusiones firmes basadas en ella.
5. Para priorizar el estudio, valora conjuntamente los resultados
   acumulados por tema y por ley o norma, el número de preguntas, los
   fallos, las no contestadas y los fallos marcados como Muy seguro.
6. No conviertas automáticamente el tema con menor porcentaje en la máxima
   prioridad si su muestra es insuficiente.
7. La estrategia de riesgo debe apoyarse en el umbral de equilibrio ya
   calculado y en los resultados observados por nivel de seguridad.
8. No aconsejes responder completamente al azar. Puedes recomendar asumir
   más riesgo cuando exista una preferencia razonada o se hayan descartado
   opciones, si los datos lo justifican.
9. Indica expresamente que el análisis se refiere al conjunto de simulacros
   corregidos que se conservan actualmente en la convocatoria, no solo al
   simulacro abierto.
10. Máximo 450 palabras.

Usa exactamente estos encabezados Markdown:

### Resumen
### Prioridades de estudio
### Estrategia de examen
### Observaciones

DATOS DEL SIMULACRO ACTUAL

- Preguntas: {resultado_actual["total"]}
- Aciertos: {resultado_actual["aciertos"]}
- Fallos: {resultado_actual["fallos"]}
- No contestadas: {resultado_actual["no_contestadas"]}
- Nota: {resultado_actual["nota"]:.2f}

DATOS ACUMULADOS DE LA CONVOCATORIA

- Simulacros corregidos conservados: {resultado_acumulado["simulacros"]}
- Preguntas analizadas: {resultado_acumulado["preguntas"]}
- Contestadas: {resultado_acumulado["contestadas"]}
- Aciertos: {resultado_acumulado["aciertos"]}
- Fallos: {resultado_acumulado["fallos"]}
- No contestadas: {resultado_acumulado["no_contestadas"]}

REGLAS DE PUNTUACIÓN DEL SIMULACRO ACTUAL

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
            "No existen simulacros corregidos para generar el análisis."
        )

    prompt = construir_prompt_analisis_rendimiento(
        resultado_actual=resultado_actual,
        resultado_acumulado=resultado_acumulado,
    )

    return generar_analisis_rendimiento_ia(
        prompt=prompt,
    ).strip()