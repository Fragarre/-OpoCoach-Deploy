# Inventario de scripts

## Scripts operativos

Forman parte del flujo del menú o son dependencias directas de ese flujo.

- `alta_convocatoria_orquestador.py`
- `auditar_banco_preguntas.py`
- `auditar_bd.py`
- `auditar_vigencia_preguntas.py`
- `boe_api.py`
- `buscador_preguntas.py`
- `buscar_norma_por_respuesta_correcta.py`
- `construir_catalogo_normas.py`
- `construir_corpus_convocatoria.py`
- `depurar_preguntas.py`
- `enlazar_normas.py`
- `enriquecer_preguntas.py`
- `extraer_temario_convocatoria.py`
- `importacion_preguntas_comun.py`
- `importar_examenes.py`
- `importar_preguntas_informatica.py`
- `importar_temario.py`
- `importar_tests_academia.py`
- `importar_tests_academia_texto.py`
- `importar_tests_imagen.py`
- `listar_preguntas_pendientes.py`
- `localizador_normativa.py`
- `mantener_banco_preguntas.py`
- `mantenimiento_preguntas.py`
- `modificar_pregunta_manual.py`
- `mostrar_resumen_banco_convocatoria.py`
- `mostrar_resumen_lote_preguntas.py`
- `normalizador_normas.py`
- `normalizar_lote_preguntas_definitivo.py`
- `openai_api.py`
- `pdf_normas.py`
- `recuperar_pendientes_busqueda_auditoria.py`
- `resolver_referencias_boe.py`
- `revisar_importaciones.py`

## Utilidades auxiliares vigentes

No forman parte del flujo periódico, pero se conservan para diagnóstico o tareas específicas.

- `auditar_consistencia_global.py`
- `auditar_corpus_temario.py`
- `auditar_estructura_banco.py`
- `generar_preguntas_informatica.py`
- `inventariar_denominaciones_normas.py`

## Scripts históricos

Se conservan en `historico_scripts/`. No deben ejecutarse en la operativa normal.

- `actualizar_banco_preguntas_juridicas.py`
- `actualizar_banco_preguntas_juridicas_old.py`
- `actualizar_banco_preguntas_no_juridicas.py`
- `actualizar_banco_preguntas_no_juridicas_old.py`
- `actualizar_resolvedor_pdf.py`
- `alta_convocatoria.py`
- `clasificar_teorica_practica.py`
- `corregir_partes_temario_y_banco_c2.py`
- `eliminar_preguntas_no_clasificables.py`
- `extraer_temario_convocatoria_antes_localizador_20260726_222743.py`
- `gemini_api.py`
- `migrar_partes_banco.py`
- `procesar_preguntas_juridicas.py`
- `recuperar_pendientes.py`
- `recuperar_preguntas_pendientes.py`
- `recuperar_preguntas_pendientes_estrategia2.py`
- `recuperar_preguntas_pendientes_estrategia3_revision_estricta_todas.py`
- `reparar_vinculaciones_normas.py`
- `resolver_referencias_boe_antes_pdf_20260728_172716.py`

## Criterio de mantenimiento

- El menú solo debe llamar scripts presentes en `scripts/`.
- `scripts/` no debe contener versiones `old`, copias `antes_...`, migraciones o parches ya aplicados.
- Antes de recuperar un script histórico debe identificarse una necesidad concreta y compararse con el flujo vigente.
