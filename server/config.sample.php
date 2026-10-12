<?php
// Przykładowa konfiguracja — skopiuj do config.php (generuje deploy.py).
return [
    // MySQL w produkcji; lokalnie może być sqlite:/ścieżka/tl.db
    'DB_DSN' => 'mysql:host=localhost;dbname=NAZWA_BAZY;charset=utf8mb4',
    'DB_USER' => 'uzytkownik',
    'DB_PASS' => 'haslo',
    'INGEST_KEY' => 'dlugi-losowy-klucz',
    'ALLOWED_ORIGIN' => 'https://loty.makosa.org',
];
