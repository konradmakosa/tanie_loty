<?php
// POST /maintenance.php — jednorazowe przypomnienie o potwierdzeniu
// (24–72 h od zapisu) + sprzątanie niepotwierdzonych (>14 dni).
// Wywoływane przez ingest.py po każdym przebiegu; idempotentne.
require __DIR__ . '/db.php';
require __DIR__ . '/ports.php';
require __DIR__ . '/mail.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_err('metoda niedozwolona', 405);
}
$key = $_SERVER['HTTP_X_INGEST_KEY'] ?? '';
$expected = cfg()['INGEST_KEY'] ?? '';
if (!$expected || !hash_equals($expected, $key)) {
    json_err('nieprawidłowy klucz', 401);
}

$pdo = db();
$now = date('Y-m-d H:i:s');
$d1 = date('Y-m-d H:i:s', time() - 24 * 3600);
$d3 = date('Y-m-d H:i:s', time() - 72 * 3600);
$d14 = date('Y-m-d H:i:s', time() - 14 * 24 * 3600);

// (a) przypomnienie — max 50 na wywołanie; reminded_at ustawiamy
// niezależnie od wyniku wysyłki, żeby nigdy nie posłać drugi raz.
$st = $pdo->prepare('SELECT email, port, token FROM subscribers
    WHERE confirmed_at IS NULL AND reminded_at IS NULL
      AND created_at <= ? AND created_at > ?
    ORDER BY created_at LIMIT 50');
$st->execute([$d1, $d3]);
$rows = $st->fetchAll();

$upd = $pdo->prepare('UPDATE subscribers SET reminded_at=? WHERE token=?');
$reminded = 0;
foreach ($rows as $r) {
    send_confirm_mail($r['email'], $r['port'], $r['token'], true);
    $upd->execute([$now, $r['token']]);
    $reminded++;
}

// (b) sprzątanie niepotwierdzonych starszych niż 14 dni.
$st = $pdo->prepare('DELETE FROM subscribers
    WHERE confirmed_at IS NULL AND created_at < ?');
$st->execute([$d14]);

json_out(['ok' => true, 'reminded' => $reminded,
          'purged' => $st->rowCount()]);
