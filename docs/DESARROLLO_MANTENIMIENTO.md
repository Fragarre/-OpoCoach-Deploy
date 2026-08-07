# DESARROLLO_MANTENIMIENTO.md

## Objetivo

Herramientas de mantenimiento de OpoCoach para construir, auditar y mantener el repositorio maestro de preguntas, los corpus jurídicos y los bancos de las convocatorias.

## Estado del proyecto

El flujo operativo queda estabilizado sobre `menu_mantenimiento.py` y la carpeta `scripts/`. Los cambios funcionales deben mantener la idempotencia, la trazabilidad y la estructura de datos existente. Los scripts históricos se conservan aparte en `historico_scripts/` para evitar que se confundan con herramientas vigentes.

## Reglas

- Trabajar exclusivamente sobre `OpoCoach-Mantenimiento` salvo la copia final explícita a OpoCoach.
- No modificar Streamlit desde este proyecto.
- Mantener procesos idempotentes.
- Registrar costes y trazabilidad de IA.
- No introducir cambios de esquema o arquitectura sin necesidad funcional expresa.
- Antes de publicar cambios en un banco, usar vista previa y auditoría cuando estén disponibles.

## Flujo operativo actual

El menú es el punto normal de entrada y contiene 16 opciones:

1. Extraer temario desde PDF.
2. Alta de convocatoria y temario.
3. Construir o validar corpus jurídico.
4. Importar, depurar y enriquecer lote de preguntas.
5. Recuperar pendientes y preparar lote para los bancos.
6. Reconstruir catálogo y enlaces.
7. Actualizar banco de preguntas.
8. Auditar banco de preguntas.
9. Buscar preguntas por norma y artículo.
10. Revisar importaciones.
11. Listar preguntas pendientes.
12. Modificar pregunta manualmente.
13. Ver resumen general del lote de preguntas.
14. Ver resumen del banco de una convocatoria.
15. Auditar vigencia de preguntas jurídicas.
16. Actualizar BD de OpoCoach.

La antigua opción de enriquecimiento específico de «preguntas de examen modelo» se elimina: el flujo actual no usa `es_modelo` ni dispone del script `enriquecer_preguntas_modelo_ia_boe.py`.

## Importación periódica de preguntas

`mantenimiento_preguntas.py` procesa cinco fuentes:

- `data_examenes/modelo` y `data_examenes/apoyo` mediante `importar_examenes.py`.
- `data_preguntas` mediante `importar_tests_imagen.py` (PDF y PNG GoFullPage).
- `data_academia` mediante `importar_tests_academia.py`.
- `data_academia_texto` mediante `importar_tests_academia_texto.py`.
- `data_informatica` mediante `importar_preguntas_informatica.py`.

Después ejecuta depuración, enriquecimiento/normalización, catálogo, enlaces y auditoría.

Las preguntas gráficas o tabulares de exámenes que no puedan convertirse íntegramente a texto se omiten individualmente y quedan registradas en el log; no deben provocar el rechazo del resto del examen.

## Recuperación de pendientes

El recuperador operativo es:

`scripts/recuperar_pendientes_busqueda_auditoria.py`

El menú lo ejecuta con `--aplicar` después de solicitar un límite y permite reintentar casos `NO_RESUELTA`. Si termina correctamente, ejecuta a continuación `enriquecer_preguntas.py --aplicar`, `construir_catalogo_normas.py`, `enlazar_normas.py` y `auditar_bd.py`.

Los antiguos `recuperar_pendientes.py` y `recuperar_preguntas_pendientes*.py` se conservan solo en `historico_scripts/`.

## Banco de preguntas

El script operativo único para construir o completar un banco es:

`scripts/mantener_banco_preguntas.py`

El menú ejecuta primero una vista previa y solo guarda tras confirmación. Los scripts anteriores de actualización jurídica/no jurídica y `procesar_preguntas_juridicas.py` quedan históricos.

## Documentación autoritativa

- `Manual_Mantenimiento_OpoCoach_v9.docx`: guía operativa completa.
- `PROCESO_IMPORTACION.md`: referencia breve del flujo de importación.
- `INVENTARIO_SCRIPTS.md`: separación entre scripts operativos, auxiliares e históricos.

Cuando cambie el flujo, estos documentos deben actualizarse junto con el menú.
