"""
==============================================================================
OpoCoach
Archivo: pdf_soluciones.py
==============================================================================

Generación del PDF de soluciones.

==============================================================================
"""

from collections import Counter
from io import BytesIO
from typing import Callable
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from lib.database import conectar_usuario
from lib.explicaciones_soluciones import generar_comentarios_soluciones


def _cargar_soluciones(simulacro_id: int) -> list[dict]:
    """
    Lee las respuestas y los comentarios actualizados del simulacro.
    """
    with conectar_usuario() as con:
        filas = con.execute(
            """
            SELECT
                sp.orden,
                ss.respuesta_correcta,
                ss.comentario_solucion

            FROM simulacro_preguntas sp

            JOIN simulacro_snapshot ss
                ON ss.simulacro_pregunta_id = sp.id

            WHERE sp.simulacro_id = ?

            ORDER BY sp.orden
            """,
            (simulacro_id,),
        ).fetchall()

    return [dict(fila) for fila in filas]


def generar_pdf_soluciones(
    simulacro_id: int,
    nombre_simulacro: str,
    preguntas,
    progreso: Callable[[int, int, int], None] | None = None,
) -> bytes:
    """
    Genera el PDF de soluciones de un simulacro.
    """

    generar_comentarios_soluciones(
        simulacro_id=simulacro_id,
        progreso=progreso,
    )

    soluciones = _cargar_soluciones(simulacro_id)

    buffer = BytesIO()

    margen_izquierdo = 20 * mm
    margen_derecho = 20 * mm
    margen_superior = 22 * mm
    margen_inferior = 18 * mm

    documento = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margen_izquierdo,
        rightMargin=margen_derecho,
        topMargin=margen_superior,
        bottomMargin=margen_inferior,
        title=nombre_simulacro,
        author="OpoCoach",
        subject="Soluciones",
    )

    ancho_pagina, alto_pagina = A4

    marco = Frame(
        margen_izquierdo,
        margen_inferior,
        ancho_pagina - margen_izquierdo - margen_derecho,
        alto_pagina - margen_superior - margen_inferior,
        id="principal",
    )

    def dibujar_pagina(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(
            margen_izquierdo,
            10 * mm,
            nombre_simulacro,
        )
        canvas.drawRightString(
            ancho_pagina - margen_derecho,
            10 * mm,
            f"Página {doc.page}",
        )
        canvas.restoreState()

    documento.addPageTemplates(
        [
            PageTemplate(
                id="soluciones",
                frames=[marco],
                onPage=dibujar_pagina,
            )
        ]
    )

    estilos = getSampleStyleSheet()

    # estilo_titulo = ParagraphStyle(
    #     "Titulo",
    #     parent=estilos["Title"],
    #     fontName="Helvetica-Bold",
    #     fontSize=13,
    #     leading=15,
    #     alignment=TA_CENTER,
    #     spaceAfter=2 * mm,
    # )

    # estilo_subtitulo = ParagraphStyle(
    #     "Subtitulo",
    #     parent=estilos["Heading2"],
    #     fontName="Helvetica-Bold",
    #     fontSize=10,
    #     leading=12,
    #     alignment=TA_CENTER,
    #     spaceAfter=3 * mm,
    # )

    estilo_titulo = ParagraphStyle(
        "Titulo",
        parent=estilos["Title"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=15,
        alignment=TA_CENTER,
        spaceAfter=2 * mm,
    )

    estilo_subtitulo = ParagraphStyle(
        "Subtitulo",
        parent=estilos["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        alignment=TA_CENTER,
        spaceAfter=3 * mm,
    )

    estilo_respuesta = ParagraphStyle(
        "Respuesta",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        alignment=TA_LEFT,
    )

    estilo_resumen_titulo = ParagraphStyle(
        "ResumenTitulo",
        parent=estilos["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=3 * mm,
    )

    estilo_resumen = ParagraphStyle(
        "Resumen",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
    )

    estilo_comentario = ParagraphStyle(
        "Comentario",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        alignment=TA_LEFT,
        spaceAfter=4 * mm,
    )

    contenido: list[Flowable] = [
        Paragraph("OPOCOACH", estilo_titulo),
        Paragraph(escape(nombre_simulacro), estilo_subtitulo),
        Paragraph("SOLUCIONES", estilo_subtitulo),
    ]

    respuestas = []

    for solucion in soluciones:
        numero = solucion["orden"]
        respuesta = solucion["respuesta_correcta"] or ""

        respuestas.append(
            (
                numero,
                str(respuesta).strip().upper(),
            )
        )

    total_respuestas = len(respuestas)
    filas_por_columna = (total_respuestas + 3) // 4

    columnas = []

    for numero_columna in range(4):
        inicio = numero_columna * filas_por_columna
        fin = inicio + filas_por_columna
        columnas.append(respuestas[inicio:fin])

    filas_tabla = []

    for indice_fila in range(filas_por_columna):
        fila = []

        for columna in columnas:
            if indice_fila < len(columna):
                numero, respuesta = columna[indice_fila]

                fila.append(
                    Paragraph(
                        f"<b>{numero}.</b>&nbsp;&nbsp;{escape(respuesta)}",
                        estilo_respuesta,
                    )
                )
            else:
                fila.append("")

        filas_tabla.append(fila)

    if filas_tabla:
        ancho_util = (
            ancho_pagina
            - margen_izquierdo
            - margen_derecho
        )

        tabla = Table(
            filas_tabla,
            colWidths=[ancho_util / 4] * 4,
            hAlign="LEFT",
        )

        tabla.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ]
            )
        )

        contenido.append(tabla)

    contenido.append(Spacer(1, 5 * mm))

    recuento = Counter(
        respuesta
        for _, respuesta in respuestas
        if respuesta in {"A", "B", "C", "D"}
    )

    contenido.append(
        Paragraph(
            "Resumen",
            estilo_resumen_titulo,
        )
    )

    contenido.append(
        Paragraph(
            f"Total preguntas: {total_respuestas}",
            estilo_resumen,
        )
    )

    contenido.append(
        Paragraph(
            (
                f"A: {recuento.get('A', 0)}"
                f"&nbsp;&nbsp;&nbsp;&nbsp;"
                f"B: {recuento.get('B', 0)}"
                f"&nbsp;&nbsp;&nbsp;&nbsp;"
                f"C: {recuento.get('C', 0)}"
                f"&nbsp;&nbsp;&nbsp;&nbsp;"
                f"D: {recuento.get('D', 0)}"
            ),
            estilo_resumen,
        )
    )

    contenido.append(PageBreak())

    contenido.append(
        Paragraph(
            "COMENTARIOS",
            estilo_subtitulo,
        )
    )

    for solucion in soluciones:
        numero = solucion["orden"]

        respuesta = str(
            solucion["respuesta_correcta"] or ""
        ).strip().upper()

        comentario = str(
            solucion["comentario_solucion"]
            or "Comentario no disponible."
        ).strip()

        contenido.append(
            Paragraph(
                (
                    f"<b>{numero}. Respuesta {escape(respuesta)}.</b> "
                    f"{escape(comentario)}"
                ),
                estilo_comentario,
            )
        )

    documento.build(contenido)

    pdf = buffer.getvalue()
    buffer.close()

    return pdf