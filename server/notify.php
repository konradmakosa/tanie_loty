<?php
// POST /notify.php — alerty o rekordowo tanich lotach (X-Ingest-Key, gzip).
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

$raw = file_get_contents('php://input', false, null, 0, 1024 * 1024 + 1);
if ($raw === false || strlen($raw) > 1024 * 1024) {
    json_err('za duże body', 413);
}
if (($_SERVER['HTTP_CONTENT_ENCODING'] ?? '') === 'gzip') {
    $raw = gzdecode($raw);
    if ($raw === false) json_err('błędny gzip', 400);
}
$payload = json_decode($raw, true);
$port = $payload['port'] ?? '';
$deals = $payload['deals'] ?? null;
if (!is_array($payload) || !port_ok($port) || !is_array($deals)) {
    json_err('nieprawidłowy payload', 400);
}

$pdo = db();

// (a) nowe deal_id dla portu
$ids = array_map(function ($d) { return substr((string)($d['id'] ?? ''), 0, 48); },
                 $deals);
$new = [];
if ($ids) {
    $in = implode(',', array_fill(0, count($ids), '?'));
    $st = $pdo->prepare("SELECT deal_id FROM alerts_sent
                         WHERE port=? AND deal_id IN ($in)");
    $st->execute(array_merge([$port], $ids));
    $seen = array_column($st->fetchAll(), 'deal_id');
    $new = array_values(array_filter($deals, function ($d) use ($seen) {
        return !in_array(substr((string)$d['id'], 0, 48), $seen, true);
    }));
}

// (b) najtańsze 12
usort($new, function ($a, $b) {
    return ($a['price'] ?? 0) <=> ($b['price'] ?? 0);
});
$new = array_slice($new, 0, 12);

// (c) zapisz jako wysłane zawsze — nawet przy zerze subskrybentów,
// żeby pierwszy subskrybent nie dostał zalewu starych ofert.
$pdo->beginTransaction();
try {
    $ins = $pdo->prepare('INSERT INTO alerts_sent (deal_id, port, sent_at)
                          VALUES (?,?,?)');
    foreach ($new as $d) {
        $ins->execute([substr((string)$d['id'], 0, 48), $port,
                       date('Y-m-d H:i:s')]);
    }
    $pdo->commit();
} catch (Exception $e) {
    $pdo->rollBack();
    json_err('błąd zapisu: ' . $e->getMessage(), 500);
}
if (!$new) {
    json_out(['ok' => true, 'new' => 0, 'sent' => 0]);
}

$subs = $pdo->prepare('SELECT email, token FROM subscribers
                       WHERE port=? AND confirmed_at IS NOT NULL');
$subs->execute([$port]);
$subs = $subs->fetchAll();
if (!$subs) {
    json_out(['ok' => true, 'new' => count($new), 'sent' => 0]);
}

$MIES = ['sty','lut','mar','kwi','maj','cze','lip','sie','wrz','paź','lis','gru'];
$pl_date = function ($iso) use ($MIES) {
    $dt = date_create($iso);
    return $dt ? (int)$dt->format('j') . ' ' . $MIES[(int)$dt->format('n') - 1]
               : $iso;
};
$pl_nocy = function ($n) {
    if ($n == 1) return 'noc';
    $m = $n % 10; $s = $n % 100;
    return ($m >= 2 && $m <= 4 && !($s >= 12 && $s <= 14))
        ? 'noce' : 'nocy';
};

$city = PORTS[$port];
$site = cfg()['SITE_BASE'] ?? 'https://polataj.se';
$api = cfg()['API_BASE'] ?? 'https://makosa.org/tanie_loty/api';

// Temat: do 3 miast
$miasta = array_slice(array_unique(array_map(
    function ($d) { return $d['dest_city'] ?: $d['dest']; }, $new)), 0, 3);
$subject = '✈ Rekordowo tanio z ' . $city . ': '
    . implode(', ', array_map(function ($d) use ($miasta) {
        return $d['dest_city'] . ' ' . round($d['price']) . ' zł';
    }, array_slice($new, 0, count($miasta))))
    . (count($new) > count($miasta) ? '…' : '');

// Wiersze listy
$li_html = ''; $li_text = '';
foreach ($new as $d) {
    $dest = ($d['dest_city'] ?: $d['dest'])
        . ($d['dest_country'] ? ', ' . $d['dest_country'] : '');
    $cena = round($d['price']) . ' zł';
    $zwykle = !empty($d['median_price'])
        ? ' (zwykle ~' . round($d['median_price']) . ' zł)' : '';
    $term = $pl_date($d['date_out']) . '–' . $pl_date($d['date_in']);
    $noce = $d['nights'] . ' ' . $pl_nocy((int)$d['nights']);
    $linia = $d['airline'] ?? '';
    $link = $d['link'] ?? '';
    $li_html .= '<li><b>' . htmlspecialchars($dest) . '</b> — <b>' . $cena
        . '</b>' . htmlspecialchars($zwykle) . ' · ' . $term . ' · '
        . $noce . ' · ' . htmlspecialchars($linia)
        . ' → <a href="' . htmlspecialchars($link) . '">Sprawdź lot</a></li>';
    $li_text .= "- $dest — $cena$zwykle · $term · $noce · $linia → $link\n";
}

$sent = 0;
$upd = $pdo->prepare('UPDATE subscribers SET last_sent_at=? WHERE token=?');
foreach ($subs as $s) {
    $unsub = "$api/unsubscribe.php?t=" . $s['token'];
    $html = '<div style="font-family:sans-serif;max-width:560px">'
        . "<h2>Nowe rekordy cenowe z $city</h2>"
        . "<ul style=\"line-height:1.7;padding-left:1.2em\">$li_html</ul>"
        . '<p><a href="' . htmlspecialchars("$site/$port/")
        . '">Zobacz wszystkie okazje</a></p>'
        . '<p style="color:#888;font-size:12px">Dostajesz te maile, bo '
        . 'potwierdziłeś alerty na polataj.se. '
        . '<a href="' . htmlspecialchars($unsub) . '">Wypisz się</a></p></div>';
    $text = "Nowe rekordy cenowe z $city\n\n$li_text\n"
        . "Wszystkie okazje: $site/$port/\n"
        . "Wypisz się: $unsub\n";
    $extra = "List-Unsubscribe: <$unsub>\r\n"
        . "List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n";
    if (send_mail($s['email'], $subject, $html, $text, $extra)) {
        $sent++;
        $upd->execute([date('Y-m-d H:i:s'), $s['token']]);
    }
}
json_out(['ok' => true, 'new' => count($new), 'sent' => $sent]);
