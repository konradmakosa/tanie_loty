<?php
// /panel-radar/ — radar okazji do komentowania (tylko dla admina).
// Dostęp: hasło z config.php (sesja PHP). Maszynowo: api.php + X-Ingest-Key.
if (!is_file(__DIR__ . '/config.php')) {
    http_response_code(500);
    exit('brak config.php — uruchom deploy_site.py');
}
$CFG = require __DIR__ . '/config.php';

function radar_cookie() {
    global $CFG;
    return hash_hmac('sha256', 'radar-panel', (string)$CFG['PANEL_HASLO']);
}
$authed = hash_equals(radar_cookie(), (string)($_COOKIE['radar_auth'] ?? ''));

if (($_GET['logout'] ?? '') === '1') {
    setcookie('radar_auth', '', time() - 3600, '/panel-radar/', '', true, true);
    header('Location: index.php');
    exit;
}

$err = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['pw'])) {
    $pw = (string)($_POST['pw'] ?? '');
    $exp = (string)($CFG['PANEL_HASLO'] ?? '');
    if ($exp !== '' && hash_equals($exp, $pw)) {
        setcookie('radar_auth', radar_cookie(), 0, '/panel-radar/', '',
                  true, true);
        header('Location: index.php');
        exit;
    }
    $err = 'złe hasło';
    sleep(1);
}

header('X-Robots-Tag: noindex, nofollow');
header('Cache-Control: no-store');
?>
<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>radar — polataj.se</title>
<style>
  :root { --bg:#171c2b; --card:#1b2030; --text:#e8eaf0; --muted:#9aa3b2;
    --accent:#7aa2ff; --ok:#4ade80; --line:rgba(255,255,255,.08);
    --fb:#1877f2; --rd:#ff4500; }
  * { box-sizing: border-box; }
  html { min-height:100%; background:var(--bg)
    linear-gradient(180deg,#0b1733 0%,#121c34 50%,#171c2b 100%)
    no-repeat fixed; }
  body { margin:0; color:var(--text);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
      "Helvetica Neue",Arial,sans-serif; }
  main { max-width:880px; margin:0 auto; padding:20px 16px 64px; }
  h1 { font-size:1.4rem; margin:4px 0 16px; }
  h1 small { color:var(--muted); font-weight:400; font-size:.8rem; }
  a { color:var(--accent); }
  .top { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
    margin-bottom:18px; }
  button, .btn { background:#24304a; color:var(--text); border:1px solid
    var(--line); border-radius:8px; padding:8px 14px; cursor:pointer;
    font:inherit; font-size:.88rem; }
  button:hover, .btn:hover { border-color:var(--accent); }
  .btn-primary { background:#2b3f66; }
  .card { background:var(--card); border:1px solid var(--line);
    border-radius:14px; padding:16px; margin-bottom:14px; }
  .card.hidden, .card.done { opacity:.45; }
  .meta { display:flex; gap:10px; align-items:center; flex-wrap:wrap;
    margin-bottom:8px; font-size:.8rem; color:var(--muted); }
  .badge { padding:2px 10px; border-radius:20px; font-size:.72rem;
    font-weight:600; color:#fff; }
  .b-fb { background:var(--fb); } .b-rd { background:var(--rd); }
  .b-www { background:#4b5563; }
  .score { font-weight:700; color:var(--ok); }
  .title { font-weight:600; margin-bottom:4px; }
  .snippet, .summary { color:var(--muted); font-size:.86rem;
    margin-bottom:8px; }
  .summary { color:var(--text); }
  .row { display:flex; gap:8px; flex-wrap:wrap; }
  .variants { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
  .variant { flex:1 1 200px; background:#12182a;
    border:1px solid var(--line); border-radius:10px; padding:10px;
    font-size:.85rem; }
  .variant b { display:block; color:var(--accent); font-size:.72rem;
    text-transform:uppercase; letter-spacing:.4px; margin-bottom:4px; }
  .variant p { margin:0 0 8px; }
  .variant button { font-size:.75rem; padding:4px 10px; }
  details { margin-top:24px; }
  summary { cursor:pointer; color:var(--muted); }
  .qrow { display:flex; gap:8px; margin-bottom:8px; }
  .qrow input { flex:1; background:#12182a; color:var(--text);
    border:1px solid var(--line); border-radius:8px; padding:8px;
    font:inherit; font-size:.85rem; }
  .login { max-width:320px; margin:12vh auto; }
  .login input { width:100%; background:var(--card); color:var(--text);
    border:1px solid var(--line); border-radius:8px; padding:10px;
    font:inherit; margin-bottom:10px; }
  .err { color:#f87171; font-size:.85rem; }
  .note { color:var(--muted); font-size:.8rem; }
</style>
</head>
<body>
<main>
<?php if (!$authed): ?>
  <div class="login">
    <h1>radar</h1>
    <form method="post">
      <input type="password" name="pw" placeholder="hasło" autofocus
        autocomplete="current-password">
      <button type="submit" class="btn-primary">Zaloguj</button>
      <?php if ($err): ?><p class="err"><?= htmlspecialchars($err) ?></p><?php endif; ?>
    </form>
  </div>
<?php else: ?>
  <div class="top">
    <h1 style="margin:0">radar <small>okazje do komentowania</small></h1>
    <button class="btn-primary" onclick="scanNow(this)">Szukaj teraz</button>
    <button onclick="load(true)">Odśwież</button>
    <label class="note"><input type="checkbox" id="showAll">
      pokaż ukryte/zrobione</label>
    <a class="btn" href="?logout=1" style="margin-left:auto">wyloguj</a>
  </div>
  <div id="list"></div>

  <details>
    <summary>Zapytania wyszukiwania</summary>
    <div id="qeditor" style="margin-top:12px"></div>
    <div class="row" style="margin-top:8px">
      <button onclick="saveQueries(this)">Zapisz zapytania</button>
      <span class="note" id="qnote"></span>
    </div>
  </details>

<script>
const api = (a, o) => fetch('api.php?action=' + a, o).then(r => r.json());
const post = (a, b) => api(a, {method:'POST',
  headers:{'Content-Type':'application/json'}, body:JSON.stringify(b)});
const esc = s => (s||'').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const badge = s => s === 'facebook' ? '<span class="badge b-fb">Facebook</span>'
  : s === 'reddit' ? '<span class="badge b-rd">Reddit</span>'
  : '<span class="badge b-www">' + esc(s) + '</span>';

async function load() {
  const d = await api('items');
  const showAll = document.getElementById('showAll').checked;
  const el = document.getElementById('list');
  const items = (d.items || []).filter(i => showAll || i.status === 'new');
  el.innerHTML = items.length ? items.map(card).join('')
    : '<p class="note">Brak pozycji — uruchom „Szukaj teraz”.';
}
function card(i) {
  return '<div class="card ' + i.status + '" data-id="' + i.id + '">'
    + '<div class="meta">' + badge(i.source)
    + '<span class="score">★ ' + (i.score || 0) + '</span>'
    + '<span>' + esc(i.date || (i.found_at || '').slice(0, 10)) + '</span>'
    + '<a href="' + esc(i.url) + '" target="_blank" rel="noopener">'
    + 'Otwórz wątek ↗</a></div>'
    + '<div class="title">' + esc(i.title) + '</div>'
    + '<div class="snippet">' + esc(i.snippet) + '</div>'
    + '<div class="row">'
    + '<button onclick="setStatus(this,\'done\')">Skomentowane ✓</button>'
    + '<button onclick="setStatus(this,\'hidden\')">Odrzuć</button>'
    + '</div>'
    + '<div class="variants">'
    + (i.variants && i.variants.length
        ? i.variants.map(variantHtml).join('')
        : '<button onclick="genVariants(this)">Warianty AI</button>')
    + '</div></div>';
}
function variantHtml(v) {
  return '<div class="variant"><b>' + esc(v.style) + '</b>'
    + '<p>' + esc(v.text) + '</p>'
    + '<button onclick="copyVariant(this)">Kopiuj</button></div>';
}
async function genVariants(b, fresh) {
  const c = b.closest('.card');
  b.disabled = true; b.textContent = 'Generuję…';
  const r = await post('gen_variants', {id: c.dataset.id, fresh: !!fresh});
  const box = c.querySelector('.variants');
  if (r.variants && r.variants.length) {
    box.innerHTML = r.variants.map(variantHtml).join('')
      + '<button onclick="genVariants(this,true)" '
      + 'style="align-self:center;background:none;border:none;'
      + 'color:var(--muted);font-size:.75rem">↻ jeszcze raz</button>';
  } else {
    b.disabled = false; b.textContent = r.error || 'Błąd — spróbuj ponownie';
  }
}
function copyVariant(b) {
  const t = b.closest('.variant').querySelector('p').textContent;
  navigator.clipboard.writeText(t);
  b.textContent = '✓'; setTimeout(() => b.textContent = 'Kopiuj', 1500);
}
async function setStatus(b, st) {
  const c = b.closest('.card');
  await post('set_status', {id: c.dataset.id, status: st});
  c.classList.add(st === 'done' ? 'done' : 'hidden');
  if (!document.getElementById('showAll').checked) c.remove();
}
async function scanNow(b) {
  b.disabled = true; b.textContent = 'Kolejkuję…';
  const r = await post('request_scan', {});
  b.textContent = r.note || 'OK';
  setTimeout(() => { b.disabled = false; b.textContent = 'Szukaj teraz';
    load(); }, 4000);
}
async function loadQueries() {
  const d = await api('queries');
  const qs = d.queries || [];
  const rs = d.reddit || [];
  document.getElementById('qeditor').innerHTML =
    '<p class="note">Serper/Google (jedno na wiersz):</p>'
    + qs.map((x, i) => qrow('q', i, x.q, x.tbs)).join('')
    + '<p class="note">Reddit (subreddit, fraza — po przecinku):</p>'
    + rs.map((x, i) => qrow('r', i, x.q, x.sub)).join('')
    + '<button onclick="addQ()">+ dodaj zapytanie</button>';
}
function qrow(t, i, v, m) {
  return '<div class="qrow"><input class="' + t + 'q" value="' + esc(v)
    + '"><input class="' + t + 'm" style="max-width:120px" value="'
    + esc(m || (t === 'q' ? 'qdr:w' : '')) + '" placeholder="'
    + (t === 'q' ? 'qdr:w' : 'sub') + '"></div>';
}
function addQ() {
  document.querySelector('#qeditor button')
    .insertAdjacentHTML('beforebegin', qrow('q', 0, '', 'qdr:w'));
}
async function saveQueries(b) {
  const qs = [...document.querySelectorAll('.qq')].map((x, i) => ({
    q: x.value, tbs: document.querySelectorAll('.qm')[i].value || 'qdr:w'
  })).filter(x => x.q.trim());
  const rs = [...document.querySelectorAll('.rq')].map((x, i) => ({
    sub: document.querySelectorAll('.rm')[i].value, q: x.value
  })).filter(x => x.q.trim() && x.sub.trim());
  const r = await post('save_queries', {queries: qs, reddit: rs});
  document.getElementById('qnote').textContent =
    r.ok ? 'zapisano — użyte przy następnym skanie' : 'błąd zapisu';
}
document.getElementById('showAll').addEventListener('change', load);
load(); loadQueries();
</script>
<?php endif; ?>
</main>
</body>
</html>
