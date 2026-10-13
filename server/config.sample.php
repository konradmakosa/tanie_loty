<?php
// Przykładowa konfiguracja — skopiuj do config.php (generuje deploy.py).
return [
    // PostgreSQL w produkcji (home.pl); lokalnie może być
    // mysql:host=…;dbname=…;charset=utf8mb4 albo sqlite:/ścieżka/tl.db
    'DB_DSN' => 'pgsql:host=localhost;port=5432;dbname=NAZWA_BAZY',
    'DB_USER' => 'uzytkownik',
    'DB_PASS' => 'haslo',
    'INGEST_KEY' => 'dlugi-losowy-klucz',
    'ALLOWED_ORIGIN' => 'https://loty.makosa.org',
];
