#!/usr/bin/env python3
"""A dist/ mappa fájljait feltölti egy webtárhelyre FTPS-en (FTP TLS-sel).

Környezeti változók:
    FTP_HOST   a tárhely FTP-címe (kötelező)
    FTP_USER   felhasználónév (kötelező)
    FTP_PASS   jelszó (kötelező)
    FTP_DIR    a távoli célmappa, pl. /public_html vagy /www (alapértelmezés: a belépési mappa)
    FTP_PORT   port (alapértelmezés: 21)
    FTP_CAFILE csak tesztelésre: saját CA-tanúsítvány (éles használatnál ne állítsd be)

A kapcsolat titkosítása és a tanúsítvány ellenőrzése kötelező. Ha a tárhely csak sima FTP-t tud,
a szkript hibával leáll, és a jelszó nem megy ki titkosítatlanul.
Az adatfájlt először ideiglenes néven tölti fel, majd átnevezi, így a látogató nem kap fél fájlt.
"""
import ftplib
import os
import pathlib
import ssl
import sys


def put(ftp, local, name):
    tmp = name + ".tmp"
    with open(local, "rb") as f:
        ftp.storbinary("STOR " + tmp, f)
    try:
        ftp.rename(tmp, name)
    except ftplib.error_perm:
        # néhány szerver nem írja felül a meglévő fájlt átnevezéssel
        ftp.delete(name)
        ftp.rename(tmp, name)


def main():
    try:
        host, user, pw = os.environ["FTP_HOST"], os.environ["FTP_USER"], os.environ["FTP_PASS"]
    except KeyError as e:
        sys.exit(f"Hiányzó környezeti változó: {e.args[0]}")
    port = int(os.environ.get("FTP_PORT", "21"))
    remote_dir = os.environ.get("FTP_DIR", "").strip()
    src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    # a gyökér fájljai és az alkönyvtárak (pl. assets/) fájljai; a data.json van utolsónak, hogy az oldal ne lásson félkész állapotot
    files = sorted((p for p in src.rglob("*") if p.is_file()), key=lambda p: (p.relative_to(src).as_posix() == "data.json", p.relative_to(src).as_posix()))
    if not any(p.relative_to(src).as_posix() == "data.json" for p in files):
        sys.exit(f"Nincs {src}/data.json, nincs mit feltölteni.")

    ctx = ssl.create_default_context(cafile=os.environ.get("FTP_CAFILE") or None)
    with ftplib.FTP_TLS(context=ctx, timeout=30) as ftp:
        ftp.connect(host, port)
        ftp.login(user, pw)  # a login() előbb AUTH TLS-t kér
        ftp.prot_p()  # az adatcsatorna is titkosított
        if remote_dir:
            ftp.cwd(remote_dir)
        made = set()
        for p in files:
            rel = p.relative_to(src).as_posix()
            parts = rel.split("/")[:-1]
            for k in range(1, len(parts) + 1):  # a hiányzó alkönyvtárak létrehozása (ha már megvan, a hibát figyelmen kívül hagyjuk)
                d = "/".join(parts[:k])
                if d not in made:
                    try:
                        ftp.mkd(d)
                    except ftplib.error_perm:
                        pass
                    made.add(d)
            put(ftp, p, rel)
            print("feltöltve:", rel, p.stat().st_size, "bájt")


if __name__ == "__main__":
    try:
        main()
    except (*ftplib.all_errors, ssl.SSLError) as e:
        sys.exit(f"Feltöltési hiba: {type(e).__name__}: {e}")
