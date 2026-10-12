<?php
// Połączenie PDO + automigracja + dialekty MySQL/SQLite.

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
    if (db_driver($pdo) === 'sqlite') {
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

// Upsert agregatu dziennego trasy — dialekt zależny od drivera.
function db_upsert_route_daily(PDO $pdo, string $day, string $origin,
                             string $dest, string $month,
                             float $price): void {
    if (db_driver($pdo) === 'sqlite') {
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
