<?php
// GET /typical.php — typowe ceny wszystkich tras (mediana daily 90 dni).
require __DIR__ . '/db.php';

header('Access-Control-Allow-Origin: ' . (cfg()['ALLOWED_ORIGIN'] ?? '*'));
header('Vary: Origin');
header('Cache-Control: public, max-age=3600');

$pdo = db();
$cut90 = date('Y-m-d', time() - 90 * 86400);
// Min per (day, route) ponad dep_month — potem mediana per trasa
// i mediana per dep_month.
$rows = $pdo->query(
    'SELECT origin, dest, dep_month, day, MIN(min_price) AS mp
     FROM route_daily WHERE day >= "' . $cut90 . '"
     GROUP BY origin, dest, dep_month, day');

$routes = [];
foreach ($rows as $r) {
    $key = $r['origin'] . '-' . $r['dest'];
    $routes[$key]['vals'][] = (float)$r['mp'];
    $routes[$key]['by_month'][$r['dep_month']][] = (float)$r['mp'];
    $routes[$key]['days'][$r['day']] = true;
}

function median(array $v): ?float {
    if (!$v) return null;
    sort($v);
    $mid = intdiv(count($v), 2);
    return count($v) % 2 ? $v[$mid] : ($v[$mid - 1] + $v[$mid]) / 2;
}

$out = [];
foreach ($routes as $key => $r) {
    $bm = [];
    foreach ($r['by_month'] as $mo => $v) $bm[$mo] = median($v);
    $out[$key] = [
        'typical_90d' => median($r['vals']),
        'n_days' => count($r['days']),
        'by_month' => $bm,
    ];
}
json_out($out);
