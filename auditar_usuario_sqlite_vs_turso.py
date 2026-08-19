
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from libsql_client import create_client_sync


RAIZ = Path(__file__).resolve().parent
RUTA_SQLITE = RAIZ / "db" / "usuario.sqlite3"
TABLAS = ("simulacros", "simulacro_preguntas", "simulacro_snapshot")


def obtener_secreto(nombre: str) -> str:
    valor = os.getenv(nombre, "").strip()
    if valor:
        return valor

    try:
        import streamlit as st
        return str(st.secrets.get(nombre, "")).strip()
    except Exception:
        return ""


def normalizar_url_turso(url: str) -> str:
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    return url


def canonico(columnas: list[str], valores: list[Any]) -> str:
    datos = {}
    for columna, valor in zip(columnas, valores):
        if isinstance(valor, bytes):
            valor = {"__bytes__": valor.hex()}
        datos[columna] = valor

    return json.dumps(
        datos,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def columnas_sqlite(con: sqlite3.Connection, tabla: str) -> list[str]:
    return [
        str(fila[1])
        for fila in con.execute(f"PRAGMA table_info({tabla})").fetchall()
    ]


def columnas_turso(cliente, tabla: str) -> list[str]:
    res = cliente.execute(f"PRAGMA table_info({tabla})")
    return [str(fila[1]) for fila in res.rows]


def existe_sqlite(con: sqlite3.Connection, tabla: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (tabla,),
    ).fetchone() is not None


def existe_turso(cliente, tabla: str) -> bool:
    res = cliente.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (tabla,),
    )
    return bool(res.rows)


def cargar_local(
    con: sqlite3.Connection,
    tabla: str,
    columnas: list[str],
) -> dict[Any, str]:
    if "id" not in columnas:
        raise RuntimeError(f"{tabla}: no existe columna id en SQLite.")

    sql = (
        "SELECT "
        + ", ".join(f'"{c}"' for c in columnas)
        + f' FROM "{tabla}" ORDER BY id'
    )
    filas = con.execute(sql).fetchall()
    idx = columnas.index("id")
    return {
        fila[idx]: canonico(columnas, list(fila))
        for fila in filas
    }


def cargar_turso(
    cliente,
    tabla: str,
    columnas: list[str],
) -> dict[Any, str]:
    if "id" not in columnas:
        raise RuntimeError(f"{tabla}: no existe columna id en Turso.")

    sql = (
        "SELECT "
        + ", ".join(f'"{c}"' for c in columnas)
        + f' FROM "{tabla}" ORDER BY id'
    )
    res = cliente.execute(sql)
    idx = columnas.index("id")
    return {
        fila[idx]: canonico(columnas, list(fila))
        for fila in res.rows
    }


def mostrar_ids(titulo: str, ids: list[Any], limite: int = 50) -> None:
    print(f"{titulo}: {len(ids)}")
    if ids:
        print("  " + ", ".join(str(x) for x in ids[:limite]))
        if len(ids) > limite:
            print(f"  ... y {len(ids) - limite} más.")


def main() -> int:
    load_dotenv(RAIZ / ".env")

    if not RUTA_SQLITE.is_file():
        raise FileNotFoundError(
            f"No existe la base local:\n{RUTA_SQLITE}"
        )

    url = obtener_secreto("TURSO_DATABASE_URL")
    token = obtener_secreto("TURSO_AUTH_TOKEN")

    if not url:
        raise RuntimeError("No está configurado TURSO_DATABASE_URL.")
    if not token:
        raise RuntimeError("No está configurado TURSO_AUTH_TOKEN.")

    cliente = create_client_sync(
        url=normalizar_url_turso(url),
        auth_token=token,
    )

    diferencias = 0

    print("=" * 78)
    print("AUDITORÍA usuario.sqlite3 vs TURSO")
    print("=" * 78)
    print(f"SQLite local: {RUTA_SQLITE}")
    print("Turso: credenciales cargadas")
    print("Modo: SOLO LECTURA")
    print()

    try:
        with sqlite3.connect(RUTA_SQLITE) as local:
            for tabla in TABLAS:
                print("-" * 78)
                print(f"TABLA: {tabla}")
                print("-" * 78)

                el = existe_sqlite(local, tabla)
                et = existe_turso(cliente, tabla)

                print(f"Existe local: {'SI' if el else 'NO'}")
                print(f"Existe Turso: {'SI' if et else 'NO'}")

                if not el or not et:
                    diferencias += 1
                    print()
                    continue

                cl = columnas_sqlite(local, tabla)
                ct = columnas_turso(cliente, tabla)

                solo_local = sorted(set(cl) - set(ct))
                solo_turso = sorted(set(ct) - set(cl))

                if solo_local:
                    print("Columnas solo en local: " + ", ".join(solo_local))
                if solo_turso:
                    print("Columnas solo en Turso: " + ", ".join(solo_turso))

                comunes = [c for c in cl if c in set(ct)]

                fl = cargar_local(local, tabla, comunes)
                ft = cargar_turso(cliente, tabla, comunes)

                ids_l = set(fl)
                ids_t = set(ft)

                faltan = sorted(ids_l - ids_t)
                sobran = sorted(ids_t - ids_l)
                distintos = sorted(
                    i for i in (ids_l & ids_t)
                    if fl[i] != ft[i]
                )

                print(f"Filas local: {len(fl)}")
                print(f"Filas Turso: {len(ft)}")
                mostrar_ids("IDs que faltan en Turso", faltan)
                mostrar_ids("IDs que sobran en Turso", sobran)
                mostrar_ids("IDs con contenido diferente", distintos)

                d_tabla = (
                    len(solo_local)
                    + len(solo_turso)
                    + len(faltan)
                    + len(sobran)
                    + len(distintos)
                )
                diferencias += d_tabla

                print(
                    "RESULTADO TABLA: IDENTICA"
                    if d_tabla == 0
                    else "RESULTADO TABLA: DIFERENCIAS DETECTADAS"
                )
                print()

    finally:
        cliente.close()

    print("=" * 78)
    if diferencias == 0:
        print(
            "RESULTADO FINAL: usuario.sqlite3 y Turso coinciden "
            "en las tablas auditadas."
        )
        return 0

    print(
        "RESULTADO FINAL: se han detectado diferencias entre "
        "usuario.sqlite3 y Turso."
    )
    print("No se ha modificado ninguna base.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
