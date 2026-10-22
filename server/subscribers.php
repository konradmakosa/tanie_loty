<?php
// GET /subscribers.php — podgląd subskrybentów (nagłówek X-Ingest-Key).
require __DIR__ . '/db.php';

$key = $_SERVER['HTTP_X_INGEST_KEY'] ?? '';
$expected = cfg()['INGEST_KEY'] ?? '';
if (!$expected || !hash_equals($expected, $key)) {
    json_err('nieprawidłowy klucz', 401);
}

$pdo = db();
if ($_SERVER['REQUEST_METHOD'] === 'DELETE') {
    $email = trim($_GET['email'] ?? '');
    if ($email === '') json_err('brak email', 400);
    $st = $pdo->prepare('DELETE FROM subscribers WHERE email=?');
    $st->execute([$email]);
    json_out(['ok' => true, 'deleted' => $st->rowCount()]);
}
$rows = $pdo->query(
    'SELECT email, port, confirmed_at, created_at, last_sent_at, reminded_at
     FROM subscribers ORDER BY created_at DESC')->fetchAll();
$sent = (int)$pdo->query('SELECT COUNT(*) FROM alerts_sent')->fetchColumn();
json_out([
    'ok' => true,
    'total' => count($rows),
    'confirmed' => count(array_filter($rows, fn($r) => $r['confirmed_at'])),
    'alerts_sent' => $sent,
    'subscribers' => $rows,
]);
