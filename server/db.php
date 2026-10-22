<?php
// Połączenie PDO + automigracja + dialekty PostgreSQL/MySQL/SQLite.

function cfg(): array {
    static $c = null;
    if ($c === null) {
        $f = __DIR__ . '/config.php';
        $c = file_exists($f) ? require $f : require __DIR__ . '/config.sample.php';
    }
    return $c;
}

function db(): PDO {
    static $pdo = null;
    if ($pdo === null) {
        $c = cfg();
        $pdo = new PDO($c['DB_DSN'], $c['DB_USER'] ?? null, $c['DB_PASS'] ?? null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        db_migrate($pdo);
    }
    return $pdo;
}

function db_driver(PDO $pdo): string {
    return $pdo->getAttribute(PDO::ATTR_DRIVER_NAME);
}

function db_migrate(PDO $pdo): void {
    $drv = db_driver($pdo);
    if ($drv === 'pgsql') {
        $pdo->exec("CREATE TABLE IF NOT EXISTS runs (
            id SERIAL PRIMARY KEY,
            ts TIMESTAMP NOT NULL, tab VARCHAR(8) NOT NULL,
            n_offers INT NOT NULL)");
        $pdo->exec("CREATE TABLE IF NOT EXISTS offers (
            id BIGSERIAL PRIMARY KEY,
            run_id INT NOT NULL, ts TIMESTAMP NOT NULL, tab VARCHAR(8) NOT NULL,
            origin CHAR(3) NOT NULL, dest CHAR(3) NOT NULL,
            dest_city VARCHAR(64), country VARCHAR(64), country_code CHAR(2),
            date_out DATE NOT NULL, date_in DATE NOT NULL, nights SMALLINT,
            price NUMERIC(9,2) NOT NULL, airline_code VARCHAR(4),
            category VARCHAR(4), source VARCHAR(12),
            transfers_out SMALLINT, transfers_in SMALLINT)");
        $pdo->exec("CREATE INDEX IF NOT EXISTS idx_route ON offers (origin, dest, ts)");
        $pdo->exec("CREATE INDEX IF NOT EXISTS idx_ts ON offers (ts)");
        $pdo->exec("CREATE TABLE IF NOT EXISTS route_daily (
            day DATE NOT NULL, origin CHAR(3) NOT NULL, dest CHAR(3) NOT NULL,
            dep_month CHAR(7) NOT NULL, min_price NUMERIC(9,2) NOT NULL,
            n INT NOT NULL DEFAULT 1,
            PRIMARY KEY (day, origin, dest, dep_month))");
        $pdo->exec("CREATE TABLE IF NOT EXISTS subscribers (
            id SERIAL PRIMARY KEY,
            email VARCHAR(190) NOT NULL, port VARCHAR(16) NOT NULL,
            token CHAR(32) NOT NULL UNIQUE,
            confirmed_at TIMESTAMP NULL, created_at TIMESTAMP NOT NULL,
            last_sent_at TIMESTAMP NULL, reminded_at TIMESTAMP NULL,
            UNIQUE (email, port))");
        $pdo->exec("ALTER TABLE subscribers
            ADD COLUMN IF NOT EXISTS reminded_at TIMESTAMP NULL");
        $pdo->exec("CREATE TABLE IF NOT EXISTS alerts_sent (
            deal_id VARCHAR(48) NOT NULL, port VARCHAR(16) NOT NULL,
            sent_at TIMESTAMP NOT NULL,
            PRIMARY KEY (deal_id, port))");
        return;
    }
    if ($drv === 'sqlite') {
        $pdo->exec("CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME NOT NULL, tab VARCHAR(8) NOT NULL,
            n_offers INT NOT NULL)");
        $pdo->exec("CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INT NOT NULL, ts DATETIME NOT NULL, tab VARCHAR(8) NOT NULL,
            origin CHAR(3) NOT NULL, dest CHAR(3) NOT NULL,
            dest_city VARCHAR(64), country VARCHAR(64), country_code CHAR(2),
            date_out DATE NOT NULL, date_in DATE NOT NULL, nights SMALLINT,
            price NUMERIC(9,2) NOT NULL, airline_code VARCHAR(4),
            category VARCHAR(4), source VARCHAR(12),
            transfers_out TINYINT, transfers_in TINYINT)");
        $pdo->exec("CREATE INDEX IF NOT EXISTS idx_route ON offers (origin, dest, ts)");
        $pdo->exec("CREATE INDEX IF NOT EXISTS idx_ts ON offers (ts)");
        $pdo->exec("CREATE TABLE IF NOT EXISTS route_daily (
            day DATE NOT NULL, origin CHAR(3) NOT NULL, dest CHAR(3) NOT NULL,
            dep_month CHAR(7) NOT NULL, min_price NUMERIC(9,2) NOT NULL,
            n INT NOT NULL DEFAULT 1,
            PRIMARY KEY (day, origin, dest, dep_month))");
        $pdo->exec("CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email VARCHAR(190) NOT NULL, port VARCHAR(16) NOT NULL,
            token CHAR(32) NOT NULL UNIQUE,
            confirmed_at DATETIME NULL, created_at DATETIME NOT NULL,
            last_sent_at DATETIME NULL, reminded_at DATETIME NULL,
            UNIQUE (email, port))");
        // SQLite nie zna ADD COLUMN IF NOT EXISTS — sprawdzamy PRAGMA.
        $cols = array_column($pdo->query(
            "PRAGMA table_info(subscribers)")->fetchAll(), 'name');
        if (!in_array('reminded_at', $cols, true)) {
            $pdo->exec("ALTER TABLE subscribers
                ADD COLUMN reminded_at DATETIME NULL");
        }
        $pdo->exec("CREATE TABLE IF NOT EXISTS alerts_sent (
            deal_id VARCHAR(48) NOT NULL, port VARCHAR(16) NOT NULL,
            sent_at DATETIME NOT NULL,
            PRIMARY KEY (deal_id, port))");
        return;
    }
    // MySQL — zgodnie ze schema.sql.
    $sql = file_get_contents(__DIR__ . '/schema.sql');
    foreach (array_filter(array_map('trim', explode(';', $sql))) as $stmt) {
        if (stripos($stmt, '--') === 0) {
            $stmt = preg_replace('/^--.*$/m', '', $stmt);
        }
        if ($stmt !== '') $pdo->exec($stmt);
    }
}

// INSERT do runs — zwraca id niezależnie od dialektu.
function db_insert_run(PDO $pdo, string $ts, string $tab, int $n): int {
    if (db_driver($pdo) === 'pgsql') {
        $stmt = $pdo->prepare(
            'INSERT INTO runs (ts, tab, n_offers) VALUES (?,?,?) RETURNING id');
        $stmt->execute([$ts, $tab, $n]);
        return (int)$stmt->fetchColumn();
    }
    $pdo->prepare('INSERT INTO runs (ts, tab, n_offers) VALUES (?,?,?)')
        ->execute([$ts, $tab, $n]);
    return (int)$pdo->lastInsertId();
}

// Upsert agregatu dziennego trasy — dialekt zależny od drivera.
function db_upsert_route_daily(PDO $pdo, string $day, string $origin,
                             string $dest, string $month,
                             float $price): void {
    $drv = db_driver($pdo);
    if ($drv === 'pgsql') {
        $pdo->prepare(
            "INSERT INTO route_daily (day, origin, dest, dep_month, min_price, n)
             VALUES (?,?,?,?,?,1)
             ON CONFLICT (day, origin, dest, dep_month)
             DO UPDATE SET min_price = LEAST(route_daily.min_price,
                                             EXCLUDED.min_price),
                           n = route_daily.n + EXCLUDED.n"
        )->execute([$day, $origin, $dest, $month, $price]);
    } elseif ($drv === 'sqlite') {
        $pdo->prepare(
            "INSERT INTO route_daily (day, origin, dest, dep_month, min_price, n)
             VALUES (?,?,?,?,?,1)
             ON CONFLICT(day,origin,dest,dep_month)
             DO UPDATE SET min_price = MIN(min_price, excluded.min_price),
                           n = n + 1"
        )->execute([$day, $origin, $dest, $month, $price]);
    } else {
        $pdo->prepare(
            "INSERT INTO route_daily (day, origin, dest, dep_month, min_price, n)
             VALUES (?,?,?,?,?,1)
             ON DUPLICATE KEY UPDATE
               min_price = LEAST(min_price, VALUES(min_price)), n = n + 1"
        )->execute([$day, $origin, $dest, $month, $price]);
    }
}

function json_out($data, int $status = 200): void {
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function json_err(string $msg, int $status): void {
    json_out(['ok' => false, 'error' => $msg], $status);
}

function cors(): void {
    // Lista dozwolonych originów; gdy brak nagłówka Origin (same-origin
    // z makosa.org) nie wysyłamy CORS-ów wcale.
    $allowed = cfg()['ALLOWED_ORIGINS']
        ?? [cfg()['ALLOWED_ORIGIN'] ?? 'https://loty.makosa.org'];
    $origin = $_SERVER['HTTP_ORIGIN'] ?? '';
    if ($origin === '') {
        return;
    }
    header('Access-Control-Allow-Origin: '
        . (in_array($origin, $allowed, true) ? $origin : $allowed[0]));
    header('Vary: Origin', false);
}
