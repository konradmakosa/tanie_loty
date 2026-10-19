<?php
// GET lub POST (List-Unsubscribe-Post) — wypisanie, idempotentne.
require __DIR__ . '/db.php';
require __DIR__ . '/ports.php';

$site = cfg()['SITE_BASE'] ?? 'https://polataj.se';
$t = ($_GET['t'] ?? $_POST['t'] ?? '');
$port = '';

if (preg_match('/^[0-9a-f]{32}$/', $t)) {
    $pdo = db();
    $st = $pdo->prepare('SELECT port FROM subscribers WHERE token=?');
    $st->execute([$t]);
    $row = $st->fetch();
    if ($row) {
        $port = $row['port'];
        $pdo->prepare('DELETE FROM subscribers WHERE token=?')
            ->execute([$t]);
    }
}
// Nieznany token też → „wypisano" (idempotentnie, nie zdradzamy stanu).
header("Location: $site" . ($port ? "/$port" : '') . '/?alert=wypisano',
       true, 302);
