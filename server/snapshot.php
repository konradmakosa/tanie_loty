<?php
require __DIR__ . '/db.php';
require __DIR__ . '/ports.php';

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    cors();
    $port = $_GET['port'] ?? '';
    if (!is_string($port) || !port_ok($port)) {
        json_err('nieprawidłowy port', 400);
    }
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
$inputStream = fopen('php://input', 'rb');
$raw = '';
while (!feof($inputStream) && strlen($raw) <= 5 * 1024 * 1024) {
    $part = fread($inputStream, 8192);
    if ($part === false) json_err('błąd odczytu', 400);
    if ($part === '') break;
    $raw .= $part;
}
fclose($inputStream);
if (strlen($raw) > 5 * 1024 * 1024) {
    json_err('za duże body', 413);
}
if (isset($_SERVER['CONTENT_LENGTH']) &&
    strlen($raw) !== (int)$_SERVER['CONTENT_LENGTH']) {
    json_err('niepełne body', 400);
}
if (($_SERVER['HTTP_CONTENT_ENCODING'] ?? '') === 'gzip') {
    $raw = gzdecode($raw, 25 * 1024 * 1024);
    if ($raw === false) json_err('błędny gzip', 400);
}
if (strlen($raw) > 25 * 1024 * 1024) json_err('za duże dane', 413);
$input = json_decode($raw, true);
$staged = false;
if (is_array($input) && array_key_exists('part', $input)) {
    $port = $input['port'] ?? '';
    $chunkTs = $input['generated_at'] ?? '';
    $index = $input['part'];
    $total = $input['total'] ?? null;
    $data = $input['data'] ?? null;
    if (!is_string($port) || !port_ok($port) ||
        !is_string($chunkTs) ||
        !preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$/',
                    $chunkTs) ||
        !is_int($index) || !is_int($total) ||
        $total < 1 || $total > 1000 || $index < 0 || $index >= $total ||
        !is_string($data) || strlen($data) > 8000 ||
        base64_decode($data, true) === false) {
        json_err('nieprawidłowa część', 400);
    }
    $pdo = db();
    if (db_driver($pdo) === 'mysql') {
        $sql = 'INSERT INTO snapshot_parts
            (port, generated_at, part, total, data) VALUES (?,?,?,?,?)
            ON DUPLICATE KEY UPDATE total=VALUES(total), data=VALUES(data)';
    } else {
        $sql = 'INSERT INTO snapshot_parts
            (port, generated_at, part, total, data) VALUES (?,?,?,?,?)
            ON CONFLICT(port, generated_at, part) DO UPDATE SET
            total=excluded.total, data=excluded.data';
    }
    $pdo->prepare($sql)->execute([$port, $chunkTs, $index, $total, $data]);
    $st = $pdo->prepare('SELECT part, total, data FROM snapshot_parts
        WHERE port=? AND generated_at=? ORDER BY part');
    $st->execute([$port, $chunkTs]);
    $parts = $st->fetchAll();
    if (count($parts) < $total) json_out(['ok' => true, 'complete' => false]);
    $compressed = '';
    foreach ($parts as $i => $part) {
        if ((int)$part['part'] !== $i || (int)$part['total'] !== $total) {
            json_err('niespójne części', 400);
        }
        $compressed .= base64_decode($part['data'], true);
    }
    if (strlen($compressed) > 5 * 1024 * 1024) {
        json_err('za duży snapshot', 413);
    }
    $complete = gzdecode($compressed, 25 * 1024 * 1024);
    if ($complete === false) json_err('błędny snapshot', 400);
    $input = json_decode($complete, true);
    if (($input['port'] ?? null) !== $port ||
        ($input['tabs']['okazje']['generated_at'] ?? null) !== $chunkTs) {
        json_err('niespójne dane snapshotu', 400);
    }
    $staged = true;
}
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
$updated = $st->rowCount() > 0;
if ($staged) {
    $pdo->prepare('DELETE FROM snapshot_parts
        WHERE port=? AND generated_at<=?')->execute([$port, $ts]);
}
json_out(['ok' => true, 'updated' => $updated, 'complete' => true]);
