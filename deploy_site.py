"""Wgrywa statyczną stronę docs/ na serwer home.pl (makosa.org/polataj).

Użycie:
    python deploy_site.py            # wgraj zmienione pliki
    python deploy_site.py --dry-run  # tylko wypisz co by się wgrało

Wymaga w .env / środowisku: TL_FTP_HOST, TL_FTP_USER, TL_FTP_PASS,
TL_WEB_DIR (bez autodetekcji — musi być ustawione, np. /makosa.org).
"""
import ftplib
import os
import sys
from pathlib import Path

from deploy import load_env, ftp_connect, mkdirs

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
ENV_PATH = ROOT / ".env"
SITE_DIR = "polataj"          # <TL_WEB_DIR>/polataj
SKIP = {"CNAME"}              # Pages-only


def collect_files():
    files = []
    for p in sorted(DOCS_DIR.rglob("*")):
        if not p.is_file() or p.name in SKIP:
            continue
        files.append(p)
    return files


def remote_size(ftp, path):
    try:
        return ftp.size(path)
    except Exception:
        return None


def main():
    dry = "--dry-run" in sys.argv
    env = load_env(ENV_PATH)
    web_dir = env.get("TL_WEB_DIR", "").rstrip("/")
    if not web_dir:
        sys.exit("Brak TL_WEB_DIR — ustaw w .env lub środowisku "
                 "(np. TL_WEB_DIR=/makosa.org).")

    target = web_dir + "/" + SITE_DIR
    files = collect_files()
    print("docs/: %d plików → %s" % (len(files), target))
    if dry:
        for p in files:
            print("  %s" % p.relative_to(DOCS_DIR).as_posix())
        return

    ftp = ftp_connect(env)
    mkdirs(ftp, target)

    sent = skipped = 0
    for p in files:
        rel = p.relative_to(DOCS_DIR).as_posix()
        remote = target + "/" + rel
        size = p.stat().st_size
        # .json/.html/.htaccess zawsze (json zmienia się co przebieg,
        # html/.htaccess są małe — porównanie po rozmiarze bywało
        # fałszywie dodatnie przy edycjach tej samej długości);
        # reszta tylko gdy rozmiar się różni lub plik nie istnieje.
        if (p.suffix not in (".json", ".html") and p.name != ".htaccess"
                and remote_size(ftp, remote) == size):
            skipped += 1
            continue
        mkdirs(ftp, remote.rsplit("/", 1)[0])
        with open(p, "rb") as f:
            ftp.storbinary("STOR " + remote, f)
        sent += 1
        print("  ↑ %s (%d B)" % (rel, size))
    ftp.quit()
    print("Wgrano %d, pominięto %d niezmienionych." % (sent, skipped))


if __name__ == "__main__":
    main()
