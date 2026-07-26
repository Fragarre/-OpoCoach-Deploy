"""
==============================================================================
OpoCoach
Archivo: pdf_simulacro.py
==============================================================================

Generación del PDF de un simulacro.

==============================================================================

"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.enums import (
    TA_CENTER,
    TA_JUSTIFY,
    TA_LEFT,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import (
    ParagraphStyle,
    getSampleStyleSheet,
)
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
)


def _texto_pdf(valor: object) -> str:
    """
    Convierte cualquier valor en texto seguro para PDF.
    """

    if valor is None:
        return ""

    return escape(
        str(valor).strip()
    ).replace(
        "\n",
        "<br/>",
    )


def generar_pdf_simulacro(
    nombre_simulacro: str,
    preguntas,
) -> bytes:

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
        subject="Simulacro",
    )

    ancho_pagina, alto_pagina = A4

    marco = Frame(
        margen_izquierdo,
        margen_inferior,
        ancho_pagina
        - margen_izquierdo
        - margen_derecho,
        alto_pagina
        - margen_superior
        - margen_inferior,
        id="principal",
    )

    def dibujar_pagina(canvas, doc):

        canvas.saveState()

        canvas.setFont(
            "Helvetica",
            8,
        )

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
                id="simulacro",
                frames=[marco],
                onPage=dibujar_pagina,
            )
        ]
    )

    estilos = getSampleStyleSheet()

    estilo_titulo = ParagraphStyle(
        "Titulo",
        parent=estilos["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
    )

    estilo_subtitulo = ParagraphStyle(
        "Subtitulo",
        parent=estilos["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
    )

    estilo_instrucciones = ParagraphStyle(
        "Instrucciones",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_JUSTIFY,
        spaceAfter=8 * mm,
    )

    estilo_pregunta = ParagraphStyle(
        "Pregunta",
        parent=estilos["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        keepWithNext=True,
        spaceBefore=3 * mm,
        spaceAfter=2 * mm,
    )

    estilo_opcion = ParagraphStyle(
        "Opcion",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        alignment=TA_LEFT,
        leftIndent=6 * mm,
        firstLineIndent=-5 * mm,
        spaceAfter=1.5 * mm,
    )

    estilo_seguridad = ParagraphStyle(
        "Seguridad",
        parent=estilos["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        leftIndent=6 * mm,
        spaceBefore=1 * mm,
        spaceAfter=2 * mm,
    )

    contenido = []

    contenido.append(
        Paragraph(
            "OPOCOACH",
            estilo_titulo,
        )
    )

    contenido.append(
        Paragraph(
            nombre_simulacro,
            estilo_subtitulo,
        )
    )

    contenido.append(
        Paragraph(
            "EXAMEN",
            estilo_subtitulo,
        )
    )

    contenido.append(
        Paragraph(
            (
                f"Este cuaderno contiene {len(preguntas)} preguntas. "
                "Cada pregunta tiene cuatro respuestas posibles. "
                "Seleccione únicamente una respuesta."
            ),
            estilo_instrucciones,
        )
    )

    for indice, pregunta in enumerate(
        preguntas,
        start=1,
    ):

        try:
            numero = pregunta["orden"]
        except Exception:
            numero = indice

        bloque = []

        bloque.append(
            Paragraph(
                (
                    f"<b>{numero}.</b> "
                    f"{_texto_pdf(pregunta['enunciado'])}"
                ),
                estilo_pregunta,
            )
        )

        opciones = [
            ("A", pregunta["opcion_a"]),
            ("B", pregunta["opcion_b"]),
            ("C", pregunta["opcion_c"]),
            ("D", pregunta["opcion_d"]),
        ]

        for letra, texto in opciones:

            if texto is None:
                texto = ""

            bloque.append(
                Paragraph(
                    f"<b>{letra})</b> {_texto_pdf(texto)}",
                    estilo_opcion,
                )
            )

        bloque.append(
            Paragraph(
                (
                    "<b>Seguridad en la respuesta:</b> "
                    "( &nbsp; ) Muy seguro"
                    "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                    "( &nbsp; ) Bastante seguro"
                    "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                    "( &nbsp; ) Poco seguro"
                ),
                estilo_seguridad,
            )
        )

        bloque.append(
            Spacer(
                1,
                3 * mm,
            )
        )

        contenido.append(
            KeepTogether(
                bloque
            )
        )

    documento.build(
        contenido
    )

    pdf = buffer.getvalue()

    buffer.close()

    return pdf