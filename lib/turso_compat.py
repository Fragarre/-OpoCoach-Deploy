"""
==============================================================================
OpoCoach
Archivo: lib/turso_compat.py
==============================================================================

Capa de compatibilidad entre el código existente basado en sqlite3 y
libsql-client/Turso.

Mantiene la interfaz utilizada por OpoCoach:
    - with conectar_usuario() as con
    - con.execute(...).fetchone()
    - con.execute(...).fetchall()
    - fila["campo"] y fila[0]
    - dict(fila)
    - cursor.rowcount
    - cursor.lastrowid
============================================================================== 
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from libsql_client import create_client_sync


class TursoRow(Mapping[str, Any]):
    """Fila compatible con acceso por nombre, posición y dict(fila)."""

    def __init__(
        self,
        columnas: Sequence[str],
        valores: Sequence[Any],
    ) -> None:
        self._columnas = tuple(columnas)
        self._valores = tuple(valores)
        self._indices = {
            nombre: indice
            for indice, nombre in enumerate(self._columnas)
        }

    def __getitem__(self, clave: str | int | slice) -> Any:
        if isinstance(clave, str):
            return self._valores[self._indices[clave]]

        return self._valores[clave]

    def __iter__(self) -> Iterator[str]:
        return iter(self._columnas)

    def __len__(self) -> int:
        return len(self._columnas)

    def __repr__(self) -> str:
        return repr(dict(self))

    def keys(self):
        return self._columnas

    def values(self):
        return self._valores

    def items(self):
        return zip(self._columnas, self._valores)


class TursoCursor:
    """Cursor mínimo compatible con los usos actuales de OpoCoach."""

    def __init__(self, resultado: Any | None = None) -> None:
        self._posicion = 0

        if resultado is None:
            self._columnas: tuple[str, ...] = ()
            self._filas: list[TursoRow] = []
            self.rowcount = -1
            self.lastrowid = None
            return

        self._columnas = tuple(resultado.columns)
        self._filas = [
            TursoRow(self._columnas, fila)
            for fila in resultado.rows
        ]

        self.rowcount = int(resultado.rows_affected)
        self.lastrowid = resultado.last_insert_rowid

    @property
    def description(self):
        if not self._columnas:
            return None

        return tuple(
            (nombre, None, None, None, None, None, None)
            for nombre in self._columnas
        )

    def fetchone(self) -> TursoRow | None:
        if self._posicion >= len(self._filas):
            return None

        fila = self._filas[self._posicion]
        self._posicion += 1
        return fila

    def fetchall(self) -> list[TursoRow]:
        filas = self._filas[self._posicion:]
        self._posicion = len(self._filas)
        return filas

    def __iter__(self) -> Iterator[TursoRow]:
        while True:
            fila = self.fetchone()

            if fila is None:
                break

            yield fila


class TursoConnection:
    """
    Conexión compatible con la parte de sqlite3 utilizada por OpoCoach.

    Con URL HTTPS, el cliente antiguo libsql-client no ofrece transacciones
    remotas explícitas. Por eso BEGIN/COMMIT/ROLLBACK se aceptan para conservar
    la interfaz, mientras que cada sentencia remota se confirma en Turso.
    """

    def __init__(
        self,
        url: str,
        auth_token: str,
    ) -> None:
        self._client = create_client_sync(
            url,
            auth_token=auth_token,
        )
        self._cerrada = False

    def execute(
        self,
        sql: str,
        parametros: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> TursoCursor:
        if self._cerrada:
            raise RuntimeError("La conexión con Turso está cerrada.")

        sentencia = sql.strip()
        control = sentencia.rstrip(";").strip().upper()

        if control in {
            "BEGIN",
            "BEGIN IMMEDIATE",
            "BEGIN DEFERRED",
            "BEGIN EXCLUSIVE",
            "COMMIT",
            "END",
            "ROLLBACK",
        }:
            return TursoCursor()

        resultado = self._client.execute(
            sentencia,
            parametros,
        )

        return TursoCursor(resultado)

    def executemany(
        self,
        sql: str,
        secuencia_parametros: Sequence[Sequence[Any]],
    ) -> TursoCursor:
        ultimo = TursoCursor()

        for parametros in secuencia_parametros:
            ultimo = self.execute(sql, parametros)

        return ultimo

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        if not self._cerrada:
            self._client.close()
            self._cerrada = True

    def __enter__(self) -> "TursoConnection":
        return self

    def __exit__(
        self,
        tipo_excepcion,
        excepcion,
        traceback,
    ) -> None:
        self.close()
