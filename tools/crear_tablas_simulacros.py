"""
==============================================================================
OpoCoach
Archivo: crear_tablas_simulacros.py
==============================================================================

Descripción:
    Crea en usuario.sqlite3 las tablas necesarias para guardar simulacros
    inmutables.

Ejecutar desde la raíz del proyecto:

    python tools/crear_tablas_simulacros.py

==============================================================================
"""

from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from lib.database import conectar_usuario


SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS simulacros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convocatoria_id INTEGER NOT NULL,
    numero INTEGER NOT NULL,
    fecha_generacion TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_preguntas INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'GENERADO'
        CHECK (estado IN ('GENERADO', 'ANULADO')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (convocatoria_id, numero)
);

CREATE TABLE IF NOT EXISTS simulacro_preguntas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacro_id INTEGER NOT NULL,
    orden INTEGER NOT NULL,

    pregunta_id INTEGER,
    banco_pregunta_id INTEGER,
    parte_id INTEGER,

    parte_nombre TEXT,
    parte_orden INTEGER,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (simulacro_id)
        REFERENCES simulacros(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE,

    UNIQUE (simulacro_id, orden),
    UNIQUE (simulacro_id, pregunta_id)
);

CREATE TABLE IF NOT EXISTS simulacro_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulacro_pregunta_id INTEGER NOT NULL UNIQUE,

    enunciado TEXT NOT NULL,
    opcion_a TEXT NOT NULL,
    opcion_b TEXT NOT NULL,
    opcion_c TEXT NOT NULL,
    opcion_d TEXT NOT NULL,
    respuesta_correcta TEXT NOT NULL,

    tipo_clasificacion TEXT NOT NULL,
    tipo_norma TEXT,
    nombre_norma TEXT,
    articulo TEXT,
    tema_no_juridico TEXT,

    origen_oposicion TEXT,
    tipo_fuente TEXT NOT NULL,

    importacion_fichero_id INTEGER,
    pagina_origen INTEGER,

    norma_id_normalizada INTEGER,
    articulo_normalizado TEXT,
    teorica_practica TEXT,
    tipo_norma_normalizado TEXT,
    nombre_norma_normalizado TEXT,

    banco_tipo_vinculacion TEXT,
    banco_estado TEXT,
    banco_metodo_vinculacion TEXT,
    banco_motivo_revision TEXT,

    temas_json TEXT,
    comentario_solucion TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (simulacro_pregunta_id)
        REFERENCES simulacro_preguntas(id)
        ON UPDATE CASCADE
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_simulacros_convocatoria
    ON simulacros(convocatoria_id);

CREATE INDEX IF NOT EXISTS idx_simulacro_preguntas_simulacro
    ON simulacro_preguntas(simulacro_id);

CREATE INDEX IF NOT EXISTS idx_simulacro_preguntas_pregunta
    ON simulacro_preguntas(pregunta_id);
"""


def main() -> None:
    with conectar_usuario() as con:
        con.executescript(SQL)

    print("Base de usuario y tablas de simulacros creadas correctamente.")


if __name__ == "__main__":
    main()