
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from libsql_client import create_client_sync


RAIZ = Path(__file__).resolve().parent

VALORES_PERMITIDOS = {
    None,
    "MUY_SEGURO",
    "BASTANTE_SEGURO",
    "POCO_SEGURO",
    "SEGURO",
    "MENOS_SEGURO",
}

MIGRACION = {
    "MUY_SEGURO": "SEGURO",
    "BASTANTE_SEGURO": "MENOS_SEGURO",
    "POCO_SEGURO": "MENOS_SEGURO",
}


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


def leer_recuentos(cliente) -> dict[str | None, int]:
    resultado = cliente.execute(
        """
        SELECT
            seguridad_usuario,
            COUNT(*) AS cantidad
        FROM simulacro_preguntas
        GROUP BY seguridad_usuario
        ORDER BY seguridad_usuario
        """
    )

    return {
        fila[0]: int(fila[1])
        for fila in resultado.rows
    }


def mostrar_recuentos(titulo: str, recuentos: dict[str | None, int]) -> None:
    print()
    print(titulo)
    print("-" * len(titulo))

    if not recuentos:
        print("Sin registros.")
        return

    for valor, cantidad in recuentos.items():
        etiqueta = "NULL" if valor is None else valor
        print(f"{etiqueta:20} {cantidad:6}")


def main() -> int:
    load_dotenv(RAIZ / ".env")

    url = obtener_secreto("TURSO_DATABASE_URL")
    token = obtener_secreto("TURSO_AUTH_TOKEN")

    if not url:
        raise RuntimeError(
            "No está configurado TURSO_DATABASE_URL."
        )

    if not token:
        raise RuntimeError(
            "No está configurado TURSO_AUTH_TOKEN."
        )

    cliente = create_client_sync(
        url=normalizar_url_turso(url),
        auth_token=token,
    )

    try:
        print("=" * 78)
        print("MIGRACIÓN DE SEGURIDAD HISTÓRICA EN TURSO")
        print("=" * 78)
        print("Conversión prevista:")
        print("  MUY_SEGURO      -> SEGURO")
        print("  BASTANTE_SEGURO -> MENOS_SEGURO")
        print("  POCO_SEGURO     -> MENOS_SEGURO")

        antes = leer_recuentos(cliente)
        mostrar_recuentos("Valores antes de migrar", antes)

        encontrados = set(antes)

        no_permitidos = encontrados - VALORES_PERMITIDOS

        if no_permitidos:
            raise RuntimeError(
                "Se han encontrado valores de seguridad no previstos: "
                + ", ".join(
                    repr(valor)
                    for valor in sorted(
                        no_permitidos,
                        key=lambda x: str(x),
                    )
                )
                + ". No se ha modificado nada."
            )

        total_a_migrar = sum(
            antes.get(origen, 0)
            for origen in MIGRACION
        )

        if total_a_migrar == 0:
            print()
            print(
                "No hay valores históricos que migrar. "
                "La base ya está normalizada."
            )
            return 0

        print()
        print(
            f"Registros históricos a migrar: {total_a_migrar}"
        )

        respuesta = input(
            "Escribe MIGRAR para aplicar los cambios: "
        ).strip()

        if respuesta != "MIGRAR":
            print("Operación cancelada. No se ha modificado Turso.")
            return 1

        for origen, destino in MIGRACION.items():
            resultado = cliente.execute(
                """
                UPDATE simulacro_preguntas
                SET seguridad_usuario = ?
                WHERE seguridad_usuario = ?
                """,
                (destino, origen),
            )

            print(
                f"{origen:20} -> {destino:20} "
                f"| filas afectadas: {resultado.rows_affected}"
            )

        despues = leer_recuentos(cliente)
        mostrar_recuentos("Valores después de migrar", despues)

        antiguos_restantes = {
            valor: cantidad
            for valor, cantidad in despues.items()
            if valor in MIGRACION
        }

        if antiguos_restantes:
            raise RuntimeError(
                "La migración terminó, pero todavía quedan "
                "valores históricos en Turso."
            )

        esperados = {
            None,
            "SEGURO",
            "MENOS_SEGURO",
        }

        valores_finales = set(despues)

        inesperados_finales = valores_finales - esperados

        if inesperados_finales:
            raise RuntimeError(
                "La migración terminó, pero existen valores "
                "finales no previstos: "
                + ", ".join(
                    repr(valor)
                    for valor in sorted(
                        inesperados_finales,
                        key=lambda x: str(x),
                    )
                )
            )

        total_antes = sum(antes.values())
        total_despues = sum(despues.values())

        if total_antes != total_despues:
            raise RuntimeError(
                "El número total de filas cambió durante la migración."
            )

        print()
        print("=" * 78)
        print("MIGRACIÓN COMPLETADA Y VERIFICADA")
        print("=" * 78)
        print(
            f"Total registros antes:   {total_antes}"
        )
        print(
            f"Total registros después: {total_despues}"
        )
        print(
            "Los valores históricos han sido normalizados "
            "sin eliminar registros."
        )

        return 0

    finally:
        cliente.close()


if __name__ == "__main__":
    raise SystemExit(main())
