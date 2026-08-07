# Proceso de importación de preguntas

## Fuentes vigentes

| Carpeta | Importador | Formato |
|---|---|---|
| `data_examenes/modelo` y `data_examenes/apoyo` | `scripts/importar_examenes.py` | Exámenes oficiales PDF con capa de texto y tabla de respuestas |
| `data_preguntas` | `scripts/importar_tests_imagen.py` | PDF-imagen o capturas PNG GoFullPage; respuesta verde y pie jurídico azul |
| `data_academia` | `scripts/importar_tests_academia.py` | PDF estructurado con metadatos `artículo ||| materia ||| norma ||| nivel` |
| `data_academia_texto` | `scripts/importar_tests_academia_texto.py` | PDF estructurado con corrección/explicación usada para identificar norma y artículo |
| `data_informatica` | `scripts/importar_preguntas_informatica.py` | Preguntas de informática |

Las carpetas `modelo` y `apoyo` de `data_examenes` indican únicamente la procedencia del examen. No existe un tratamiento posterior especial de «pregunta modelo» ni un campo `es_modelo` en el flujo actual.

## Regla para preguntas no representables en texto

Una pregunta de examen se omite individualmente cuando no pueden obtenerse íntegramente el enunciado, las opciones A, B, C y D o la respuesta correcta. Esto incluye preguntas gráficas o tabulares que no puedan representarse fielmente como texto. La incidencia se conserva en el log y el resto del examen continúa.

## Capturas PNG GoFullPage

Los PNG con nombres `nombre.png`, `nombre-2.png`, `nombre-3.png`, etc. se agrupan como una única importación lógica. Cada captura larga se divide en tramos verticales legibles antes del análisis. El importador muestra únicamente mensajes breves de progreso mientras procesa los tramos; el detalle completo queda en `logs/importar_tests_imagen.log` y en `logs/mantenimiento_preguntas.log` cuando se ejecuta desde el mantenimiento general.

## Criterio único de duplicado

Dos preguntas son duplicadas únicamente si coinciden exactamente:

- `enunciado`
- `opcion_a`
- `opcion_b`
- `opcion_c`
- `opcion_d`

No interviene ningún otro campo.

## Idempotencia y trazabilidad

1. Se calcula un hash del fichero o, en los grupos PNG, un hash conjunto del grupo.
2. Se consulta `importaciones_ficheros`.
3. Una importación ya `COMPLETADO` con el mismo contenido se omite salvo reimportación explícita o marca `reimportar = 1`.
4. La extracción y validación terminan antes de publicar las preguntas válidas.
5. La publicación usa `importacion_preguntas_comun.py` y conserva `importacion_fichero_id` y `pagina_origen`.
6. Los errores e incidencias se conservan en los logs y en la trazabilidad de importaciones.

## Mantenimiento periódico

La opción 4 del menú ejecuta, en este orden:

1. `importar_examenes.py`.
2. `importar_tests_imagen.py`.
3. `importar_tests_academia.py`.
4. `importar_tests_academia_texto.py`.
5. `importar_preguntas_informatica.py`.
6. `depurar_preguntas.py`.
7. `enriquecer_preguntas.py --aplicar`.
8. `construir_catalogo_normas.py`.
9. `enlazar_normas.py`.
10. `auditar_bd.py`.

En pantalla se muestran, por cada importador, los totales de preguntas importadas, preguntas ya existentes y duplicadas. En la fase PNG GoFullPage se muestran además mensajes de progreso por tramo para indicar que el proceso sigue activo. El detalle técnico permanece en los logs.

## Después de importar

La importación no actualiza automáticamente los bancos de las convocatorias. Cuando el lote está validado:

1. Si quedan `PENDIENTE`, usar la opción 5 del menú.
2. Actualizar el banco de cada convocatoria con la opción 7.
3. Auditar cada banco con la opción 8.
4. Copiar la base a OpoCoach con la opción 16 únicamente cuando las auditorías sean correctas.
