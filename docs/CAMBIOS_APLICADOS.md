# Cambios aplicados en la revisión de agosto de 2026

## Código

- `importar_examenes.py`: las preguntas no extraíbles íntegramente como texto se omiten individualmente. Probado con `Examen_A1-01_1_24_P.pdf`: 40 respuestas, 39 preguntas extraídas y 1 pregunta tabular omitida (n.º 33).
- `importar_tests_imagen.py`: se conserva la versión con PDF + PNG GoFullPage, agrupación de capturas, segmentación vertical y progreso visible.
- `mantenimiento_preguntas.py`: se conserva el resumen mínimo de consola y el paso de mensajes de progreso de la fase PNG.
- `importar_tests_academia.py`: versión correcta del importador estructurado de `data_academia`; carpeta sin PDF no es error.
- `importar_tests_academia_texto.py`: carpeta sin PDF no es error.
- `menu_mantenimiento.py`: eliminada la opción obsoleta de enriquecimiento de preguntas modelo; menú renumerado a 16 opciones; eliminada del alta la solicitud de `examen_modelo`, que el orquestador vigente no utiliza.

## Limpieza

- `scripts/`: 39 scripts vigentes (34 del flujo/dependencias + 5 utilidades auxiliares).
- `historico_scripts/`: 19 scripts antiguos, migraciones, estrategias anteriores o parches ya aplicados. No se han borrado.
- Ver `INVENTARIO_SCRIPTS.md` para el detalle.

## Verificaciones

- Todos los scripts vigentes compilan con Python.
- El menú compila y todos los scripts que invoca existen en `scripts/`.
- No hay referencias desde el código operativo a los scripts trasladados a `historico_scripts/`.
- `auditar_bd.py` ejecutado sobre la base adjunta termina con código 0: base íntegra, con avisos históricos de importación para revisión.
- Agrupación PNG probada con `tests_imagenes.zip`: 2 simulacros, 7 capturas, 47 tramos (29 A1 + 18 A2).

## Documentación

Actualizados:

- `Manual_Mantenimiento_OpoCoach_v9.docx`
- `PROCESO_IMPORTACION.md`
- `DESARROLLO_MANTENIMIENTO.md`
- `INVENTARIO_SCRIPTS.md`
