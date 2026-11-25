<?php
// /panel-radar/api.php — JSON API radaru okazji.
// Dostęp: sesja (login w index.php) albo nagłówek X-Ingest-Key (maszynowo).
// Dane w data/ — katalog zablokowany dla WWW (.htaccess), pisze tylko PHP.
if (!is_file(__DIR__ . '/config.php')) {
    http_response_code(500);
    echo json_encode(['error' => 'brak config.php — uruchom deploy']);
    exit;
}
$CFG = require __DIR__ . '/config.php';
$DATA = __DIR__ . '/data';
if (!is_dir($DATA)) mkdir($DATA, 0750, true);

header('Content-Type: application/json; charset=utf-8');
header('X-Robots-Tag: noindex, nofollow');
header('Cache-Control: no-store');

function out($x, $code = 200) {
    http_response_code($code);
    echo json_encode($x, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}
function body() {
    $raw = file_get_contents('php://input', false, null, 0, 512 * 1024 + 1);
    return $raw ? json_decode($raw, true) : [];
}
function rfile($p, $def) {
    return is_file($p) ? (json_decode(file_get_contents($p), true) ?: $def) : $def;
}
function wfile($p, $x) {
    $tmp = $p . '.tmp';
    file_put_contents($tmp, json_encode($x,
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));
    rename($tmp, $p);
}

// --- autoryzacja ---
// home.pl nie zapisuje sesji (session.save_path bez praw zapisu),
// więc logowanie to podpisane ciasteczko HMAC zamiast sesji PHP.
$session = hash_equals(
    hash_hmac('sha256', 'radar-panel', (string)($CFG['PANEL_HASLO'] ?? '')),
    (string)($_COOKIE['radar_auth'] ?? ''));
$machine = false;
$key = $_SERVER['HTTP_X_INGEST_KEY'] ?? '';
$expected = $CFG['INGEST_KEY'] ?? '';
if ($expected && hash_equals($expected, $key)) $machine = true;

$action = $_GET['action'] ?? '';
// akcje czysto maszynowe
$machine_ok = ['upload', 'scan_flag', 'queries', 'items_raw'];
if (!$session && !($machine && in_array($action, $machine_ok, true))) {
    out(['error' => 'brak autoryzacji'], 401);
}

$items_p = "$DATA/items.json";
$state_p = "$DATA/state.json";
$queries_p = "$DATA/queries.json";
$flag_p = "$DATA/scan.flag";

switch ($action) {

case 'items':               // widok dla panelu: items + status
    $items = rfile($items_p, []);
    $state = rfile($state_p, []);
    foreach ($items as &$i) {
        $id = sha1($i['url'] ?? '');
        $i['id'] = $id;
        $st = $state[$id] ?? [];
        $i['status'] = $st['status'] ?? 'new';
        if (!empty($st['reply'])) $i['reply'] = $st['reply'];
    }
    out(['items' => $items, 'count' => count($items)]);

case 'items_raw':           // dla skanera — surowe items do scalenia
    if (!$machine) out(['error' => 'brak autoryzacji'], 401);
    out(['items' => rfile($items_p, [])]);

case 'upload':              // skaner → pełny zapis items.json
    if (!$machine || $_SERVER['REQUEST_METHOD'] !== 'POST')
        out(['error' => 'brak autoryzacji'], 401);
    $b = body();
    $items = $b['items'] ?? null;
    if (!is_array($items) || count($items) > 200)
        out(['error' => 'nieprawidłowy payload'], 400);
    $clean = [];
    foreach ($items as $i) {
        if (empty($i['url']) || strpos($i['url'], 'http') !== 0) continue;
        $clean[] = [
            'url' => substr($i['url'], 0, 500),
            'title' => substr($i['title'] ?? '', 0, 300),
            'snippet' => substr($i['snippet'] ?? '', 0, 900),
            'date' => substr($i['date'] ?? '', 0, 30),
            'source' => substr($i['source'] ?? '', 0, 30),
            'score' => (int)($i['score'] ?? 0),
            'summary' => substr($i['summary'] ?? '', 0, 300),
            'reply' => substr($i['reply'] ?? '', 0, 900),
            'found_at' => substr($i['found_at'] ?? '', 0, 40),
        ];
    }
    wfile($items_p, $clean);
    @unlink($flag_p);
    out(['ok' => true, 'count' => count($clean)]);

case 'set_status':          // now|done|hidden
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') out(['error'=>'metoda'],405);
    $b = body();
    $id = preg_replace('/[^a-f0-9]/', '', (string)($b['id'] ?? ''));
    $st = $b['status'] ?? '';
    if (strlen($id) !== 40 || !in_array($st, ['new','done','hidden'], true))
        out(['error' => 'nieprawidłowe dane'], 400);
    $state = rfile($state_p, []);
    $state[$id]['status'] = $st;
    $state[$id]['at'] = gmdate('c');
    wfile($state_p, $state);
    out(['ok' => true]);

case 'save_reply':          // edytowany komentarz
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') out(['error'=>'metoda'],405);
    $b = body();
    $id = preg_replace('/[^a-f0-9]/', '', (string)($b['id'] ?? ''));
    if (strlen($id) !== 40) out(['error' => 'nieprawidłowe dane'], 400);
    $state = rfile($state_p, []);
    $state[$id]['reply'] = substr((string)($b['text'] ?? ''), 0, 900);
    wfile($state_p, $state);
    out(['ok' => true]);

case 'queries':             // lista zapytań (panel + skaner)
    out(rfile($queries_p, ['queries' => null]));

case 'save_queries':
    if (!$session || $_SERVER['REQUEST_METHOD'] !== 'POST')
        out(['error' => 'brak autoryzacji'], 401);
    $b = body();
    $q = $b['queries'] ?? null;
    $r = $b['reddit'] ?? [];
    if (!is_array($q)) out(['error' => 'nieprawidłowe dane'], 400);
    $clean = ['queries' => [], 'reddit' => []];
    foreach ($q as $x) {
        if (empty($x['q'])) continue;
        $clean['queries'][] = [
            'q' => substr($x['q'], 0, 500),
            'tbs' => in_array($x['tbs'] ?? '', ['qdr:d','qdr:w'], true)
                ? $x['tbs'] : 'qdr:w'];
        if (count($clean['queries']) >= 30) break;
    }
    foreach ((array)$r as $x) {
        if (empty($x['sub']) || empty($x['q'])) continue;
        $clean['reddit'][] = [
            'sub' => substr(preg_replace('/[^A-Za-z0-9_]/', '', $x['sub']), 0, 30),
            'q' => substr($x['q'], 0, 300)];
        if (count($clean['reddit']) >= 10) break;
    }
    wfile($queries_p, $clean);
    out(['ok' => true]);

case 'request_scan':        // flaga „Szukaj teraz"
    if (!$session || $_SERVER['REQUEST_METHOD'] !== 'POST')
        out(['error' => 'brak autoryzacji'], 401);
    touch($flag_p);
    out(['ok' => true, 'note' => 'skan ruszy w ciągu ~15 min']);

case 'scan_flag':           // dla timera flagowego na VPS
    if (!$machine) out(['error' => 'brak autoryzacji'], 401);
    out(['pending' => is_file($flag_p)]);

case 'logout':
    setcookie('radar_auth', '', time() - 3600, '/panel-radar/', '', true, true);
    out(['ok' => true]);

default:
    out(['error' => 'nieznana akcja'], 404);
}
