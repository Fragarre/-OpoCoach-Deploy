from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

ARCHIVOS = {'lib/repositorio.py': {'expected_before': '578b8a444c0beb285e46a23d8512ae467260abba55205823e264f20cf9eee3e1', 'payload': '5a6bffe07b8e23b2e9c0a30cfbe3324f747335aeda99eb9c90c13a0ba6b7231a'}, 'lib/sesion.py': {'expected_before': 'a349eefcd786c497571f57d17cce872b41fb7c323c24ae947a2780b585d258aa', 'payload': 'ccdb3dc2805cac50cc982705d4fe62d32100c51eb93fbd29dbe35d3169e3ae08'}, 'pages/01_Inicio.py': {'expected_before': 'ff0ec052a58c79b05c9fa722545e7c33096baf3c8e9da155789f6cf513e6b1dd', 'payload': 'b8382a9bb95e8f688ad849c5fe5a5a06061693b41f2223bc4c09655b80e63131'}}

def sha256(ruta: Path) -> str:
    h=hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1024*1024), b""):
            h.update(bloque)
    return h.hexdigest()

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Raíz del proyecto que se actualiza")
    args=parser.parse_args()
    raiz=Path(args.root).resolve()
    paquete=Path(__file__).resolve().parent
    payload=paquete / "payload"

    errores=[]
    for rel, firmas in ARCHIVOS.items():
        destino=raiz / rel
        origen=payload / rel
        if not destino.is_file(): errores.append(f"No existe destino: {destino}")
        elif sha256(destino) != firmas["expected_before"]:
            errores.append(f"{rel} no coincide con la versión revisada; no se sobrescribe.")
        if not origen.is_file(): errores.append(f"Falta payload: {origen}")
        elif sha256(origen) != firmas["payload"]: errores.append(f"Payload alterado: {rel}")
    if errores:
        print("ERROR: actualización cancelada antes de modificar archivos.")
        for e in errores: print("-",e)
        return 1

    marca=datetime.now().strftime("%Y%m%d_%H%M%S")
    backup=raiz / "copias_actualizacion" / f"antes_convocatorias_activas_{marca}"
    for rel in ARCHIVOS:
        destino=raiz / rel
        copia=backup / rel
        copia.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(destino,copia)

    temporales=[]
    try:
        for rel in ARCHIVOS:
            destino=raiz / rel
            origen=payload / rel
            temporal=destino.with_suffix(destino.suffix+".tmp_opocoach")
            shutil.copy2(origen,temporal)
            temporales.append(temporal)
        for rel,temporal in zip(ARCHIVOS,temporales):
            temporal.replace(raiz/rel)
    except Exception:
        for rel in ARCHIVOS:
            copia=backup/rel
            if copia.is_file(): shutil.copy2(copia,raiz/rel)
        for t in temporales:
            if t.exists(): t.unlink()
        raise

    print("="*78)
    print("ACTUALIZACIÓN INSTALADA")
    print("="*78)
    print(f"Proyecto: {raiz}")
    print(f"Backup:   {backup}")
    print("Archivos actualizados:")
    for rel in ARCHIVOS: print(f"- {rel}")
    print("La base de datos NO ha sido modificada por este instalador.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
