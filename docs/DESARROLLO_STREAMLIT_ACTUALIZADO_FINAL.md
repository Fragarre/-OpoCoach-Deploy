DESARROLLO_STREAMLIT.md

1. Finalidad

Documento de continuidad para el desarrollo de la aplicación Streamlit OpoCoach.

Proyecto:

OpoCoach

No confundir con:

OpoCoach-Mantenimiento

OpoCoach contiene la aplicación Streamlit.OpoCoach-Mantenimiento contiene importación, clasificación, IA, corpus, BOE, procesos masivos y auditorías.

2. Reglas de trabajo

Trabajar exclusivamente sobre el directorio OpoCoach.

No modificar OpoCoach-Mantenimiento.

No rediseñar la arquitectura sin petición expresa.

No inventar tablas, funciones o estructuras.

Pedir el script o la base de datos cuando falte información.

Aplicar cambios pequeños y comprobables.

Si cambian varias partes de un archivo, entregar el script completo.

Mantener compatibilidad con Windows y con el entorno virtual del proyecto.

No mezclar mejoras estéticas y funcionales salvo petición expresa.

3. Estado general

La aplicación Streamlit está funcional.

Funcionalidades confirmadas:

selección de convocatoria;

consulta del temario;

creación y persistencia de simulacros;

descarga del PDF de preguntas;

descarga del PDF de soluciones;

generación automática de comentarios IA para las soluciones;

almacenamiento permanente de esos comentarios;

eliminación de simulacros con confirmación.

4. Separación entre proyectos

OpoCoach

Responsabilidades:

interfaz Streamlit;

navegación;

selección de convocatoria;

consulta del temario;

creación y consulta de simulacros;

PDFs de preguntas y soluciones;

uso de datos ya preparados.

OpoCoach-Mantenimiento

Responsabilidades:

alta de convocatorias;

importación de temarios y preguntas;

clasificación;

BOE;

normas y artículos;

corpus;

auditorías;

procesos masivos;

mantenimiento de base de datos.

Streamlit no debe asumir tareas propias de mantenimiento.

5. Estructura conocida

OpoCoach/
│
├── pages/
│   └── 02_Simulacros.py
│
├── lib/
│   ├── database.py
│   ├── repositorio.py
│   ├── sesion.py
│   ├── pdf_simulacro.py
│   ├── pdf_soluciones.py
│   └── explicaciones_soluciones.py
│
├── tools/
│   └── openai_api.py
│
└── ...

La estructura completa debe verificarse con el repositorio. No se debe ampliar esta lista por suposición.

6. Página de simulacros

Archivo:

pages/02_Simulacros.py

Responsabilidades actuales:

obtener la convocatoria seleccionada;

detener la ejecución si no hay convocatoria;

mostrar datos de la convocatoria;

crear simulacros;

listar simulacros existentes;

mostrar número, fecha y total de preguntas;

descargar el PDF de preguntas;

generar y descargar el PDF de soluciones;

eliminar simulacros con confirmación.

Funciones importadas de lib.repositorio:

obtener_preguntas_simulacro
crear_simulacro
obtener_convocatoria
obtener_simulacros
eliminar_simulacro

Función de sesión:

obtener_convocatoria_id()

7. PDF de preguntas

Módulo:

lib/pdf_simulacro.py

Función conocida:

generar_pdf_simulacro(
    nombre_simulacro=nombre_simulacro,
    preguntas=preguntas,
)

El PDF de preguntas no debe generar comentarios IA.

8. PDF de soluciones

Módulo:

lib/pdf_soluciones.py

Firma confirmada:

def generar_pdf_soluciones(
    simulacro_id: int,
    nombre_simulacro: str,
    preguntas,
) -> bytes:

Importaciones relevantes:

from lib.database import conectar_usuario
from lib.explicaciones_soluciones import generar_comentarios_soluciones

Al comienzo de la función:

generar_comentarios_soluciones(simulacro_id)
soluciones = _cargar_soluciones(simulacro_id)

La función _cargar_soluciones(simulacro_id) vuelve a leer la base de datos después de generar los comentarios.

Campos conocidos:

sp.orden
ss.respuesta_correcta
ss.comentario_solucion

Tablas conocidas:

simulacro_preguntas
simulacro_snapshot

La consulta completa debe revisarse en el archivo real antes de modificarla.

9. Comentarios IA

Módulo:

lib/explicaciones_soluciones.py

Función principal:

generar_comentarios_soluciones(simulacro_id)

Reglas confirmadas:

se ejecuta solo al solicitar el PDF de soluciones;

no se ejecuta al crear el PDF de preguntas;

solo procesa registros con comentario_solucion IS NULL;

no regenera comentarios existentes;

guarda los comentarios en la base de datos;

debe ser idempotente;

trabaja por lotes;

el tamaño de lote se incrementó para reducir llamadas;

puede tardar más de dos minutos;

la optimización adicional queda aplazada.

Módulo de OpenAI:

tools/openai_api.py

Función utilizada:

seleccionar_fragmento_json

Dependencia necesaria:

python-dotenv

Instalación en Windows:

.\.venv\Scripts\python.exe -m pip install python-dotenv

10. Persistencia

Campo:

comentario_solucion

Tabla conocida:

simulacro_snapshot

Flujo:

comentario_solucion IS NULL
        ↓
generar comentario
        ↓
guardar comentario
        ↓
reutilizarlo en descargas posteriores

Esto evita llamadas repetidas, costes innecesarios y cambios entre descargas.

11. Flujo de descarga de soluciones

Flujo actual:

Pulsar Soluciones.

Generar comentarios pendientes.

Crear el PDF.

Mostrar Descargar PDF.

Descargar el archivo.

Código conocido:

if fila[4].button(
    "Soluciones",
    key=f"soluciones_{simulacro_id}",
    use_container_width=True,
):
    pdf_soluciones = generar_pdf_soluciones(
        simulacro_id=simulacro_id,
        nombre_simulacro=nombre_simulacro,
        preguntas=preguntas,
    )

    st.download_button(
        label="Descargar PDF",
        data=pdf_soluciones,
        file_name=f"{nombre_simulacro}_soluciones.pdf",
        mime="application/pdf",
        key=f"descarga_soluciones_{simulacro_id}",
    )

Se eliminó una llamada antigua a generar_pdf_soluciones() situada fuera del botón. Esa llamada provocaba generación automática al cargar la página.

12. Formato del PDF

Se redujo la cabecera para intentar que el solucionario inicial cupiera en una página.

Valores orientativos aplicados:

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

Espacio vertical reducido:

contenido.append(Spacer(1, 5 * mm))

Debe verificarse el archivo actual porque el usuario corrigió personalmente la ubicación de los estilos.

13. Acceso a datos

Módulo:

lib/repositorio.py

La página debe usar las funciones del repositorio siempre que sea posible.

Evitar SQL directo en las páginas salvo que el diseño actual ya lo contemple.

Módulo de conexión:

lib/database.py

Función conocida:

conectar_usuario()

No modificar tablas desde Streamlit sin comprobar su relación con el proyecto de mantenimiento.

14. Convenciones de desarrollo

Código

un cambio cada vez;

probar después de cada cambio;

evitar refactorizaciones innecesarias;

conservar firmas públicas;

trabajar sobre el traceback completo cuando aparezca un error.

Scripts

cambio pequeño: indicar bloque exacto;

cambio amplio: entregar archivo completo;

no ofrecer fragmentos inconexos cuando afecten a varias zonas.

Base de datos

mantener idempotencia;

no regenerar datos;

no eliminar sin confirmación;

evitar bloqueos innecesarios;

verificar siempre la tabla correcta.

IA

usarla solo donde esté decidida;

minimizar llamadas;

reutilizar resultados;

no ejecutarla automáticamente al cargar páginas;

exigir una acción explícita del usuario para procesos costosos.

15. Dependencias conocidas

streamlit
reportlab
python-dotenv

También se utiliza el cliente de OpenAI configurado en:

tools/openai_api.py

Debe verificarse el contenido real de:

requirements.txt

16. Problemas resueltos

Generación automática al cargar la página

Causa: llamada a generar_pdf_soluciones() fuera del botón.

Solución: mantenerla exclusivamente dentro de la acción Soluciones.

Falta de dotenv

Error:

ModuleNotFoundError: No module named 'dotenv'

Solución:

.\.venv\Scripts\python.exe -m pip install python-dotenv

Estilo no definido

Error:

NameError: name 'estilo_titulo' is not defined

Fue un error manual de ubicación y quedó corregido.

Generación lenta

La creación de comentarios puede superar dos minutos.

Se aumentó el tamaño de lote. De momento se acepta el tiempo actual.

17. Estado funcional confirmado

La página de simulacros funciona.

El botón Soluciones inicia la generación.

Los comentarios se generan y guardan.

El PDF de soluciones se crea.

La descarga funciona mediante un segundo botón.

Los comentarios existentes no se regeneran.

La cabecera del PDF se redujo.

No existe todavía barra de progreso.

La generación sigue siendo algo lenta.

18. Pendientes conocidos

barra o indicador de progreso;

optimización del tiempo de generación;

tratamiento visual de errores de API;

posible conservación temporal del PDF en st.session_state;

revisión estética del PDF;

nuevas funcionalidades solicitadas por el usuario.

No iniciar ninguno de estos trabajos sin petición expresa.

19. Información que debe completarse desde el repositorio

Antes de considerar completa la documentación técnica deben revisarse:

árbol completo;

todas las páginas Streamlit;

esquema completo de base de datos;

requirements.txt;

funciones completas de lib/repositorio.py;

flujo de selección de convocatoria;

configuración de OpenAI;

sistema de errores y registros;

relación exacta con la base preparada por Mantenimiento;

instalación y puesta en marcha.

Estas partes no deben inventarse.

20. Git y repositorios

Mantener dos repositorios separados:

OpoCoach
OpoCoach-Mantenimiento

Antes de una funcionalidad:

git status
git add .
git commit -m "Estado estable antes de nueva funcionalidad"
git push

Después de completar y probar:

git status
git add .
git commit -m "Descripción breve del cambio"
git push

21. Inicio recomendado del nuevo chat

Vamos a continuar exclusivamente el desarrollo de la aplicación Streamlit OpoCoach.

El código está en el directorio OpoCoach.

No trabajar sobre OpoCoach-Mantenimiento.

Usa DESARROLLO_STREAMLIT.md como documento principal de continuidad.

Trabajaremos paso a paso, sin rediseñar la arquitectura ni inventar estructuras.

Cuando falte información, pide el script o la base de datos necesarios.

Antes de modificar código, confirma el objetivo concreto de la siguiente funcionalidad.

Adjuntar después:

DESARROLLO_STREAMLIT.md

y únicamente los archivos relacionados con la siguiente funcionalidad.

22. Punto de reanudación

OpoCoach queda funcional después de integrar los comentarios IA en el PDF de soluciones.

El siguiente desarrollo todavía no está definido.

La primera pregunta del nuevo chat debe ser:

¿Qué nueva funcionalidad quieres incorporar ahora a OpoCoach?



23. Cambios incorporados (julio 2026)

Generación de simulacros

- La selección de preguntas aplica la regla de niveles de oposición:
  - A1 admite preguntas A1.
  - A2 admite preguntas A2 y A1.
  - C1 admite preguntas C1, A2 y A1.
  - C2 admite preguntas C2, C1, A2 y A1.
- Las preguntas no jurídicas continúan siendo válidas cuando no disponen de origen_oposicion.

PDF de preguntas

Archivo:

lib/pdf_simulacro.py

Estado actual:

- Se añadió el campo "Seguridad en la respuesta".
- El campo aparece una única vez al final de cada pregunta, después de la opción D.
- Se sustituyeron los caracteres Unicode por marcas "(   )" para garantizar compatibilidad con ReportLab y la fuente Helvetica.

Repositorio

Archivo:

lib/repositorio.py

Se adaptaron las funciones:

- obtener_resumen_convocatoria()
- obtener_disponibilidad_simulacro()

Ambas utilizan exactamente el mismo criterio de selección que crear_simulacro(), evitando discrepancias entre el número de preguntas disponibles mostrado en pantalla y las realmente utilizables.

24. Nuevo punto de reanudación

Estado funcional confirmado:

- Selección de convocatoria.
- Consulta del temario.
- Creación de simulacros.
- Corrección de simulacros.
- Descarga del PDF de preguntas.
- Descarga del PDF de soluciones.
- Comentarios IA persistentes.
- Campo de seguridad incorporado en el PDF de preguntas.
- Regla de niveles A1/A2/C1/C2 aplicada tanto a la generación de simulacros como a los contadores de disponibilidad.

El proyecto continúa exactamente desde este estado.


25. Cambios incorporados (26 julio 2026)

Ramas de desarrollo

- Se mantiene la rama principal con la regla de niveles de oposición.
- Se crea una rama alternativa denominada "sin-regla-niveles" donde dicha restricción se elimina completamente.
- En esta rama todas las preguntas incluidas en banco_preguntas para la convocatoria son válidas para simulacros y tests, independientemente de origen_oposicion.

Repositorio

Archivo:

lib/repositorio.py

En la rama sin-regla-niveles se eliminó el filtrado por origen_oposicion en:

- obtener_resumen_convocatoria()
- obtener_disponibilidad_simulacro()
- crear_simulacro()
- obtener_puntos_temario_test()
- crear_test()

La selección de preguntas queda limitada únicamente por:

- convocatoria_id
- estado = 'INCLUIDA'

Generación del PDF de soluciones

Archivos:

pages/02_Simulacros.py
lib/pdf_soluciones.py
lib/explicaciones_soluciones.py

Se añadió un indicador de progreso real durante la generación de comentarios IA.

Características:

- aparece junto al botón "Crear simulacro";
- informa del lote actual y del total de lotes;
- muestra el número de preguntas procesadas;
- indica la fase de construcción del PDF;
- desaparece al finalizar la operación.

Comentarios IA

Archivo:

lib/explicaciones_soluciones.py

Se amplió el prompt para que los comentarios:

- comiencen citando expresamente la norma y el artículo;
- expliquen la regla jurídica aplicable y el elemento decisivo de la respuesta;
- no se limiten a confirmar que la opción coincide con el precepto;
- eviten repetir "Respuesta A/B/C/D", ya incorporado por el PDF;
- tengan una longitud orientativa de entre 45 y 100 palabras.

26. Punto de reanudación

Estado congelado.

La aplicación Streamlit queda estable con:

- simulacros y tests plenamente operativos;
- generación incremental de comentarios IA;
- comentarios persistentes en base de datos;
- indicador de progreso durante la generación de soluciones;
- comentarios jurídicos ampliados con referencia expresa a norma y artículo.

No existen desarrollos pendientes. El siguiente trabajo se decidirá expresamente al iniciar un nuevo chat.
