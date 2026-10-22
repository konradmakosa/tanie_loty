<?php
// POST form-urlencoded: email, port, hp (honeypot). Double opt-in.
require __DIR__ . '/db.php';
require __DIR__ . '/ports.php';
require __DIR__ . '/mail.php';

cors();
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_err('metoda niedozwolona', 405);
}

// Honeypot — boty wypełniają ukryte pole; udajemy sukces.
if (!empty($_POST['hp'])) {
    json_out(['ok' => true, 'status' => 'sent']);
}

$email = strtolower(trim($_POST['email'] ?? ''));
$port = $_POST['port'] ?? '';
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    json_err('nieprawidłowy e-mail', 400);
}
if (!port_ok($port)) {
    json_err('nieprawidłowy port', 400);
}

$pdo = db();
$st = $pdo->prepare('SELECT * FROM subscribers WHERE email=? AND port=?');
$st->execute([$email, $port]);
$row = $st->fetch();

if ($row && $row['confirmed_at'] !== null) {
    json_out(['ok' => true, 'status' => 'already']);
}

if ($row) {
    // Niepotwierdzony: ponowny mail najwcześniej po 10 min (anty-bombing).
    if (strtotime($row['created_at']) > time() - 600) {
        json_out(['ok' => true, 'status' => 'sent']);
    }
    $token = $row['token'];
    $pdo->prepare('UPDATE subscribers SET created_at=? WHERE token=?')
        ->execute([date('Y-m-d H:i:s'), $token]);
} else {
    $token = bin2hex(random_bytes(16));
    $pdo->prepare('INSERT INTO subscribers (email, port, token, created_at)
                   VALUES (?,?,?,?)')
        ->execute([$email, $port, $token,
                   date('Y-m-d H:i:s')]);
}

send_confirm_mail($email, $port, $token);
json_out(['ok' => true, 'status' => 'sent']);
