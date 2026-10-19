<?php
// GET /confirm.php?t=TOKEN — potwierdzenie subskrypcji + redirect.
require __DIR__ . '/db.php';
require __DIR__ . '/ports.php';

$site = cfg()['SITE_BASE'] ?? 'https://polataj.se';
$t = $_GET['t'] ?? '';
if (!preg_match('/^[0-9a-f]{32}$/', $t)) {
    header("Location: $site/?alert=blad", true, 302);
    exit;
}

$pdo = db();
$st = $pdo->prepare('SELECT * FROM subscribers WHERE token=?');
$st->execute([$t]);
$row = $st->fetch();
if (!$row) {
    header("Location: $site/?alert=blad", true, 302);
    exit;
}
if ($row['confirmed_at'] === null) {
    $pdo->prepare('UPDATE subscribers SET confirmed_at=? WHERE id=?')
        ->execute([date('Y-m-d H:i:s'), $row['id']]);
}
header("Location: $site/{$row['port']}/?alert=ok", true, 302);
