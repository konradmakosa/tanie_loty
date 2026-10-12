#!/usr/bin/env python3
"""Deploy plików PHP na hosting (FTP/FTP_TLS) + generuje server/config.php
ze zmiennych .env. Użycie: python3 deploy.py [--dry-run]"""

import ftplib
import json
import os
import secrets
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
SERVER_DIR = ROOT / "server"
FILES = ["db.php", "ingest.php", "history.php", "typical.php",
         "config.php", "config.sample.php", "schema.sql", ".htaccess"]

CONFIG_TEMPLATE = """<?php
// Wygenerowane przez deploy.py — nie edytuj ręcznie.
return [
    'DB_DSN' => 'mysql:host=%s;dbname=%s;charset=utf8mb4',
    'DB_USER' => %s,
    'DB_PASS' => %s,
    'INGEST_KEY' => %s,
    'ALLOWED_ORIGIN' => 'https://loty.makosa.org',
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


def build_config(env):
    key = env.get("TL_INGEST_KEY")
    return CONFIG_TEMPLATE % (
        env.get("TL_DB_HOST", ""), env.get("TL_DB_NAME", ""),
        q(env.get("TL_DB_USER")), q(env.get("TL_DB_PASS")), q(key))


def mkdirs(ftp, path):
    parts = [p for p in path.split("/") if p]
    for i in range(len(parts)):
        sub = "/" + "/".join(parts[:i + 1])
        try:
            ftp.mkd(sub)
        except ftplib.error_perm:
            pass


def main():
    dry = "--dry-run" in sys.argv
    env = load_env(ENV_PATH)

    # Klucz ingest — generuj i dopisz do .env jeśli brak.
    if not env.get("TL_INGEST_KEY"):
        env["TL_INGEST_KEY"] = secrets.token_hex(24)
        if not dry:
            write_env({"TL_INGEST_KEY": env["TL_INGEST_KEY"]})
        print("Wygenerowano TL_INGEST_KEY" +
              (" (dry-run, nie zapisano)" if dry else " i dopisano do .env"))

    missing = [k for k in ("TL_FTP_HOST", "TL_FTP_USER", "TL_FTP_PASS",
                           "TL_WEB_DIR", "TL_DB_HOST", "TL_DB_NAME",
                           "TL_DB_USER", "TL_DB_PASS") if not env.get(k)]
    if missing and not dry:
        print("Brak zmiennych w .env: %s — przerywam" % ", ".join(missing))
        sys.exit(1)

    config_php = build_config(env)
    cfg_path = SERVER_DIR / "config.php"
    if not dry:
        cfg_path.write_text(config_php, encoding="utf-8")

    target = (env.get("TL_WEB_DIR", "").rstrip("/") + "/tanie_loty/api")
    print("Pliki do wysłania do %s:" % target)
    for f in FILES:
        print("  server/%s" % f)
    if dry:
        print("\n--- config.php (podgląd) ---\n" + config_php)
        print("[dry-run] nic nie wysłano.")
        return

    try:
        ftp = ftplib.FTP_TLS(env["TL_FTP_HOST"], timeout=30)
        ftp.login(env["TL_FTP_USER"], env["TL_FTP_PASS"])
        ftp.prot_p()
        print("Połączono FTP_TLS")
    except Exception as e:
        print("FTP_TLS nie działa (%s) — próbuję zwykły FTP" % e)
        ftp = ftplib.FTP(env["TL_FTP_HOST"], timeout=30)
        ftp.login(env["TL_FTP_USER"], env["TL_FTP_PASS"])

    mkdirs(ftp, target)
    ftp.cwd(target)
    for name in FILES:
        with open(SERVER_DIR / name, "rb") as f:
            ftp.storbinary("STOR " + name, f)
        print("Wgrano %s" % name)
    ftp.quit()

    base = (env.get("TL_API_BASE") or "").rstrip("/")
    if base:
        url = base + "/history.php?route=WMI-ARN"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                print("Sprawdzenie API: HTTP %d %s"
                      % (r.status, r.read()[:200]))
        except Exception as e:
            print("Sprawdzenie API nieudane: %s" % e)


if __name__ == "__main__":
    main()
