<?php
require __DIR__ . '/db.php';
require __DIR__ . '/ports.php';

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    cors();
    $port = $_GET['port'] ?? '';
    if (!port_ok($port)) json_err('nieprawidłowy port', 400);
    $st = db()->prepare('SELECT payload FROM deal_snapshots WHERE port=?');
    $st->execute([$port]);
    $payload = $st->fetchColumn();
    if ($payload === false) json_err('brak danych', 404);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: public, max-age=120');
    echo $payload;
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') json_err('metoda niedozwolona', 405);
$key = $_SERVER['HTTP_X_INGEST_KEY'] ?? '';
$expected = cfg()['INGEST_KEY'] ?? '';
if (!$expected || !hash_equals($expected, $key)) {
    json_err('nieprawidłowy klucz', 401);
}
$raw = file_get_contents('php://input', false, null, 0, 5 * 1024 * 1024 + 1);
if ($raw === false || strlen($raw) > 5 * 1024 * 1024) {
    json_err('za duże body', 413);
}
if (($_SERVER['HTTP_CONTENT_ENCODING'] ?? '') === 'gzip') {
    $raw = gzdecode($raw, 25 * 1024 * 1024);
    if ($raw === false) json_err('błędny gzip', 400);
}
if (strlen($raw) > 25 * 1024 * 1024) json_err('za duże dane', 413);
$input = json_decode($raw, true);
$port = $input['port'] ?? '';
$tabs = $input['tabs'] ?? null;
if (!is_string($port) || !port_ok($port) || !is_array($tabs) ||
    array_keys($tabs) !== ['okazje', 'daleko', 'oneway']) {
    json_err('nieprawidłowy payload', 400);
}
$ts = $tabs['okazje']['generated_at'] ?? '';
if (!is_string($ts) ||
    !preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$/', $ts)) {
    json_err('nieprawidłowa data', 400);
}
foreach ($tabs as $tab) {
    if (($tab['generated_at'] ?? null) !== $ts ||
        !is_array($tab['config'] ?? null) ||
        !is_array($tab['deals'] ?? null) ||
        array_values($tab['deals']) !== $tab['deals']) {
        json_err('niekompletne dane zakładki', 400);
    }
}
$payload = json_encode($tabs, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
if ($payload === false) json_err('nieprawidłowy JSON', 400);
$pdo = db();
if (db_driver($pdo) === 'mysql') {
    $sql = 'INSERT INTO deal_snapshots (port, generated_at, payload)
        VALUES (?,?,?) ON DUPLICATE KEY UPDATE
        payload=IF(generated_at <= VALUES(generated_at), VALUES(payload), payload),
        generated_at=GREATEST(generated_at, VALUES(generated_at))';
} else {
    $sql = 'INSERT INTO deal_snapshots (port, generated_at, payload)
        VALUES (?,?,?) ON CONFLICT(port) DO UPDATE SET
        generated_at=excluded.generated_at, payload=excluded.payload
        WHERE deal_snapshots.generated_at <= excluded.generated_at';
}
$st = $pdo->prepare($sql);
$st->execute([$port, $ts, $payload]);
json_out(['ok' => true, 'updated' => $st->rowCount() > 0]);
