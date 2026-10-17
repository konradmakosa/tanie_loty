<?php
// GET /history.php?route=WAW-BKK&days=365 — historia trasy z route_daily.
require __DIR__ . '/db.php';

cors();
header('Cache-Control: public, max-age=1800');

$route = $_GET['route'] ?? '';
if (!preg_match('/^([A-Z]{3})-([A-Z]{3})$/', $route, $m)) {
    json_err('nieprawidłowy route (oczekiwany XXX-YYY)', 400);
}
$origin = $m[1];
$dest = $m[2];
$days = max(1, min(1200, (int)($_GET['days'] ?? 365)));

$pdo = db();
$cutoff = date('Y-m-d', time() - $days * 86400);
$rows = $pdo->prepare(
    'SELECT day, dep_month, min_price FROM route_daily
     WHERE origin=? AND dest=? AND day>=? ORDER BY day');
$rows->execute([$origin, $dest, $cutoff]);

$daily = [];        // min po wszystkich dep_month
$byMonth = [];      // dep_month => [[day, min_price]]
foreach ($rows as $r) {
    $d = $r['day'];
    $p = (float)$r['min_price'];
    if (!isset($daily[$d]) || $p < $daily[$d]) $daily[$d] = $p;
    $byMonth[$r['dep_month']][$d] = isset($byMonth[$r['dep_month']][$d])
        ? min($byMonth[$r['dep_month']][$d], $p) : $p;
}

$dailyList = [];
foreach ($daily as $d => $p) $dailyList[] = [$d, $p];
$byMonthList = [];
foreach ($byMonth as $mo => $arr) {
    $l = [];
    foreach ($arr as $d => $p) $l[] = [$d, $p];
    $byMonthList[$mo] = $l;
}

// Mediana z daily z ostatnich 90 dni.
$cut90 = date('Y-m-d', time() - 90 * 86400);
$vals = array_values(array_filter($daily, fn($p, $d) => $d >= $cut90,
    ARRAY_FILTER_USE_BOTH));
sort($vals);
$typical = null;
if (count($vals) >= 5) {
    $mid = intdiv(count($vals), 2);
    $typical = count($vals) % 2
        ? $vals[$mid] : ($vals[$mid - 1] + $vals[$mid]) / 2;
}

json_out([
    'route' => $route,
    'daily' => $dailyList,
    'by_month' => $byMonthList,
    'typical_90d' => $typical,
    'min_all' => $vals ? min(array_values($daily)) : null,
    'since' => $dailyList ? $dailyList[0][0] : null,
]);
