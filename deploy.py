#!/usr/bin/env python3
"""Deploy plików PHP na hosting (FTP/FTP_TLS) + generuje server/config.php
ze zmiennych środowiskowych lub .env (env ma pierwszeństwo — w Actions
nie ma .env). Użycie: python3 deploy.py [--dry-run]"""

import ftplib
import io
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
SERVER_DIR = ROOT / "server"
FILES = ["db.php", "ingest.php", "history.php", "typical.php",
         "ports.php", "mail.php", "subscribe.php", "confirm.php",
         "unsubscribe.php", "notify.php", "subscribers.php",
         "config.php", "config.sample.php", "schema.sql", ".htaccess"]

# Kandydaci docroota dla makosa.org (kolejność jak w home.pl i typowych).
DOCROOT_CANDIDATES = [
    "/makosa.org/public_html", "/makosa.org", "/public_html",
    "/domains/makosa.org/public_html", "/httpdocs", "/www", "/",
]

CONFIG_TEMPLATE = """<?php
// Wygenerowane przez deploy.py — nie edytuj ręcznie.
return [
    'DB_DSN' => %s,
    'DB_USER' => %s,
    'DB_PASS' => %s,
    'INGEST_KEY' => %s,
    'ALLOWED_ORIGINS' => ['https://loty.makosa.org', 'https://polataj.se',
                          'https://www.polataj.se', 'https://makosa.org'],
    'MAIL_FROM' => 'alerty@polataj.se',
    'SITE_BASE' => 'https://polataj.se',
    'API_BASE' => 'https://makosa.org/tanie_loty/api',
    // 'MAIL_DEBUG_DIR' => '/tmp/tl_mail',   // testy lokalne: zapis .eml
];
"""


def load_env(path):
    env = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    # Zmienne środowiskowe mają pierwszeństwo (GitHub Actions).
    for k in ("TL_DB_TYPE", "TL_DB_HOST", "TL_DB_PORT", "TL_DB_NAME",
              "TL_DB_USER", "TL_DB_PASS", "TL_FTP_HOST", "TL_FTP_USER",
              "TL_FTP_PASS", "TL_WEB_DIR", "TL_API_BASE", "TL_INGEST_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def write_env(env):
    lines = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    have = {l.split("=", 1)[0].strip() for l in lines
            if "=" in l and not l.startswith("#")}
    for k, v in env.items():
        if k not in have:
            lines.append("%s=%s" % (k, v))
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def q(s):
    return "'" + (s or "").replace("\\", "\\\\").replace("'", "\\'") + "'"


def db_dsn(env):
    db_type = env.get("TL_DB_TYPE", "pgsql")
    host = env.get("TL_DB_HOST", "")
    name = env.get("TL_DB_NAME", "")
    port = env.get("TL_DB_PORT") or ("5432" if db_type == "pgsql" else "3306")
    if db_type == "mysql":
        return "mysql:host=%s;port=%s;dbname=%s;charset=utf8mb4" \
            % (host, port, name)
    return "pgsql:host=%s;port=%s;dbname=%s" % (host, port, name)


def build_config(env):
    return CONFIG_TEMPLATE % (
        q(db_dsn(env)), q(env.get("TL_DB_USER")), q(env.get("TL_DB_PASS")),
        q(env.get("TL_INGEST_KEY")))


def mkdirs(ftp, path):
    parts = [p for p in path.split("/") if p]
    for i in range(len(parts)):
        sub = "/" + "/".join(parts[:i + 1])
        try:
            ftp.mkd(sub)
        except ftplib.error_perm:
            pass


def http_get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()


def ftp_connect(env):
    try:
        ftp = ftplib.FTP_TLS(env["TL_FTP_HOST"], timeout=30)
        ftp.login(env["TL_FTP_USER"], env["TL_FTP_PASS"])
        ftp.prot_p()
        print("Połączono FTP_TLS")
    except Exception as e:
        print("FTP_TLS nie działa (%s) — próbuję zwykły FTP" % e)
        ftp = ftplib.FTP(env["TL_FTP_HOST"], timeout=30)
        ftp.login(env["TL_FTP_USER"], env["TL_FTP_PASS"])
    return ftp


def detect_web_dir(ftp, api_base):
    """Autodetekcja docroota: wgraj sondę ping.txt i sprawdź po HTTP."""
    print("TL_WEB_DIR nieznane — autodetekcja. Root FTP:")
    try:
        for entry in ftp.nlst("/"):
            print("  %s" % entry)
    except Exception:
        ftp.retrlines("LIST /")
    probe = secrets.token_hex(16)
    probe_rel = "tanie_loty/api/ping.txt"
    probe_url = api_base.rstrip("/") + "/ping.txt"
    for cand in DOCROOT_CANDIDATES:
        try:
            ftp.cwd(cand)
        except ftplib.error_perm:
            continue
        mkdirs(ftp, cand + "/tanie_loty/api")
        ftp.cwd(cand + "/tanie_loty/api")
        ftp.storbinary("STOR ping.txt", io.BytesIO(probe.encode()))
        code, body = http_get(probe_url)
        # Posprzątaj sondę.
        try:
            ftp.delete("ping.txt")
            ftp.cwd(cand)
            ftp.rmd("tanie_loty/api")
            ftp.rmd("tanie_loty")
        except ftplib.error_perm:
            pass
        if code == 200 and probe.encode() in body:
            print("Wykryto TL_WEB_DIR=%s" % cand)
            return cand
        print("  %s → HTTP %s" % (cand, code))
    print("Nie wykryto docroota. Listing katalogów pierwszego poziomu:")
    for cand in DOCROOT_CANDIDATES[:-1]:
        try:
            ftp.cwd(cand)
            for entry in ftp.nlst():
                print("  %s/%s" % (cand, entry))
        except ftplib.error_perm:
            pass
    return None


def main():
    dry = "--dry-run" in sys.argv
    env = load_env(ENV_PATH)

    if not env.get("TL_INGEST_KEY"):
        if ENV_PATH.exists():
            env["TL_INGEST_KEY"] = secrets.token_hex(24)
            if not dry:
                write_env({"TL_INGEST_KEY": env["TL_INGEST_KEY"]})
            print("Wygenerowano TL_INGEST_KEY" +
                  (" (dry-run, nie zapisano)" if dry else " i dopisano do .env"))
        else:
            print("Brak TL_INGEST_KEY (env/.env) — przerywam")
            sys.exit(1)

    missing = [k for k in ("TL_FTP_HOST", "TL_FTP_USER", "TL_FTP_PASS",
                           "TL_DB_HOST", "TL_DB_NAME", "TL_DB_USER",
                           "TL_DB_PASS", "TL_API_BASE")
               if not env.get(k)]
    if env.get("TL_DB_TYPE", "pgsql") not in ("pgsql", "mysql"):
        print("TL_DB_TYPE musi być 'pgsql' lub 'mysql' — przerywam")
        sys.exit(1)
    if missing and not dry:
        print("Brak zmiennych: %s — przerywam" % ", ".join(missing))
        sys.exit(1)

    config_php = build_config(env)
    if not dry:
        (SERVER_DIR / "config.php").write_text(config_php, encoding="utf-8")

    web_dir = env.get("TL_WEB_DIR", "")
    api_base = env.get("TL_API_BASE", "https://makosa.org/tanie_loty/api")
    target = (web_dir.rstrip("/") + "/tanie_loty/api") if web_dir \
        else "<auto>/tanie_loty/api"
    print("Pliki do wysłania do %s:" % target)
    for f in FILES:
        print("  server/%s" % f)
    if dry:
        print("\n--- config.php (podgląd) ---\n" + config_php)
        print("[dry-run] nic nie wysłano.")
        return

    ftp = ftp_connect(env)
    if not web_dir:
        web_dir = detect_web_dir(ftp, api_base)
        if not web_dir:
            sys.exit(1)
    target = web_dir.rstrip("/") + "/tanie_loty/api"
    mkdirs(ftp, target)
    ftp.cwd(target)
    for name in FILES:
        with open(SERVER_DIR / name, "rb") as f:
            ftp.storbinary("STOR " + name, f)
        print("Wgrano %s" % name)
    ftp.quit()

    url = api_base.rstrip("/") + "/history.php?route=WMI-ARN"
    code, body = http_get(url)
    print("Sprawdzenie API: HTTP %s %s" % (code, body[:300].decode("utf-8",
                                                                 "replace")))
    if code != 200:
        sys.exit(1)


if __name__ == "__main__":
    main()
