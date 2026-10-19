<?php
// Przykładowa konfiguracja — skopiuj do config.php (generuje deploy.py).
return [
    // PostgreSQL w produkcji (home.pl); lokalnie może być
    // mysql:host=…;dbname=…;charset=utf8mb4 albo sqlite:/ścieżka/tl.db
    'DB_DSN' => 'pgsql:host=localhost;port=5432;dbname=NAZWA_BAZY',
    'DB_USER' => 'uzytkownik',
    'DB_PASS' => 'haslo',
    'INGEST_KEY' => 'dlugi-losowy-klucz',
    'ALLOWED_ORIGINS' => ['https://loty.makosa.org',
        'https://polataj.se', 'https://www.polataj.se',
        'https://makosa.org'],
    'MAIL_FROM' => 'alerty@polataj.se',
    'SITE_BASE' => 'https://polataj.se',
    'API_BASE' => 'https://makosa.org/tanie_loty/api',
    // 'MAIL_DEBUG_DIR' => '/tmp/tl_mail',
];
