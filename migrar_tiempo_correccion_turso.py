from pathlib import Path
import os
from dotenv import load_dotenv
from libsql_client import create_client_sync

RAIZ = Path(__file__).resolve().parent
load_dotenv(RAIZ / ".env")
url = os.getenv("TURSO_DATABASE_URL", "").strip()
token = os.getenv("TURSO_AUTH_TOKEN", "").strip()
if not url or not token:
    raise RuntimeError("Faltan TURSO_DATABASE_URL o TURSO_AUTH_TOKEN en .env")
if url.startswith("libsql://"):
    url = "https://" + url[len("libsql://"):]
cliente = create_client_sync(url=url, auth_token=token)
try:
    cols = {str(r[1]) for r in cliente.execute("PRAGMA table_info(simulacros)").rows}
    if "tiempo_correccion_segundos" not in cols:
        cliente.execute("ALTER TABLE simulacros ADD COLUMN tiempo_correccion_segundos INTEGER NOT NULL DEFAULT 0")
        print("OK: columna tiempo_correccion_segundos creada en Turso.")
    else:
        print("OK: la columna tiempo_correccion_segundos ya existía. No se modifica.")
finally:
    cliente.close()
