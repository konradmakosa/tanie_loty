<?php
// Przyjmowanie paczki ofert ze search.py.
// POST /ingest.php, nagłówek X-Ingest-Key, body JSON (opcjonalnie gzip).
require __DIR__ . '/db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_err('metoda niedozwolona', 405);
}

$key = $_SERVER['HTTP_X_INGEST_KEY'] ?? '';
$expected = cfg()['INGEST_KEY'] ?? '';
if (!$expected || !hash_equals($expected, $key)) {
    json_err('nieprawidłowy klucz', 401);
}

$raw = file_get_contents('php://input', false, null, 0, 10 * 1024 * 1024 + 1);
if ($raw === false || strlen($raw) > 10 * 1024 * 1024) {
    json_err('za duże body (limit 10 MB)', 413);
}
$enc = $_SERVER['HTTP_CONTENT_ENCODING'] ?? '';
if ($enc === 'gzip') {
    $raw = gzdecode($raw);
    if ($raw === false) json_err('błędny gzip', 400);
}

$payload = json_decode($raw, true);
if (!is_array($payload) || !isset($payload['ts'], $payload['tab']) ||
    !is_array($payload['offers'] ?? null)) {
    json_err('nieprawidłowy payload', 400);
}
$tab = $payload['tab'];
if (!in_array($tab, ['okazje', 'daleko'], true)) {
    json_err('nieprawidłowe tab', 400);
}
$ts = $payload['ts'];
$offers = $payload['offers'];

$required = ['origin', 'dest', 'date_out', 'date_in', 'price'];
foreach ($offers as $i => $o) {
    foreach ($required as $k) {
        if (!isset($o[$k])) json_err("oferta #$i: brak pola $k", 400);
    }
}

$pdo = db();
$pdo->beginTransaction();
try {
    $runId = db_insert_run($pdo, $ts, $tab, count($offers));

    $ins = $pdo->prepare(
        'INSERT INTO offers (run_id, ts, tab, origin, dest, dest_city,
            country, country_code, date_out, date_in, nights, price,
            airline_code, category, source, transfers_out, transfers_in)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)');
    $day = substr($ts, 0, 10);
    $n = 0;
    foreach ($offers as $o) {
        $ins->execute([
            $runId, $ts, $tab,
            substr($o['origin'], 0, 3), substr($o['dest'], 0, 3),
            $o['dest_city'] ?? null, $o['country'] ?? null,
            $o['country_code'] ?? null,
            $o['date_out'], $o['date_in'], $o['nights'] ?? null,
            $o['price'], $o['airline_code'] ?? null,
            $o['category'] ?? null, $o['source'] ?? null,
            $o['transfers_out'] ?? null, $o['transfers_in'] ?? null,
        ]);
        db_upsert_route_daily($pdo, $day, substr($o['origin'], 0, 3),
            substr($o['dest'], 0, 3), substr($o['date_out'], 0, 7),
            (float)$o['price']);
        $n++;
    }
    $pdo->commit();
    json_out(['ok' => true, 'inserted' => $n]);
} catch (Throwable $e) {
    $pdo->rollBack();
    json_err('błąd zapisu: ' . $e->getMessage(), 500);
}
