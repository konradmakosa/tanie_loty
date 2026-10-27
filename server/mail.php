<?php
// Wysyłka e-mail (multipart/alternative, UTF-8). MAIL_DEBUG_DIR → pliki .eml.

function _enc_hdr(string $s): string {
    return '=?UTF-8?B?' . base64_encode($s) . '?=';
}

function send_mail(string $to, string $subject, string $html, string $text,
                   string $extraHeaders = ''): bool {
    $c = cfg();
    $from = $c['MAIL_FROM'] ?? 'alerty@polataj.se';
    // Baner z logo na granatowym tle (znak jest jasny).
    $html = '<div style="background:#0a1f44;padding:16px 20px;'
        . 'border-radius:12px;margin-bottom:18px">'
        . '<a href="https://polataj.se/"><img src="https://polataj.se/'
        . 'assets/logo-520.png" width="220" alt="polataj.se" '
        . 'style="display:block"></a></div>' . $html;

    $sep = "=_pl_" . bin2hex(random_bytes(8));
    $body = "--$sep\r\n"
        . "Content-Type: text/plain; charset=UTF-8\r\n"
        . "Content-Transfer-Encoding: base64\r\n\r\n"
        . chunk_split(base64_encode($text))
        . "--$sep\r\n"
        . "Content-Type: text/html; charset=UTF-8\r\n"
        . "Content-Transfer-Encoding: base64\r\n\r\n"
        . chunk_split(base64_encode($html))
        . "--$sep--\r\n";

    $headers = "From: =?UTF-8?B?" . base64_encode('polataj.se') . "?= <$from>\r\n"
        . "Reply-To: $from\r\n"
        . "MIME-Version: 1.0\r\n"
        . "Content-Type: multipart/alternative; boundary=\"$sep\"\r\n"
        . $extraHeaders;
    $subj = _enc_hdr($subject);

    $debug = $c['MAIL_DEBUG_DIR'] ?? '';
    if ($debug) {
        if (!is_dir($debug)) mkdir($debug, 0777, true);
        $eml = "To: $to\r\nSubject: $subj\r\n$headers\r\n" . $body;
        file_put_contents($debug . '/' . time() . '_' .
            bin2hex(random_bytes(4)) . '.eml', $eml);
        return true;
    }
    return mail($to, $subj, $body, $headers);
}

// Mail potwierdzający zapis (double opt-in). $reminder=true → wariant
// przypominający (jednorazowy, wysyłany przez maintenance.php).
function send_confirm_mail(string $email, string $port, string $token,
                           bool $reminder = false): bool {
    require_once __DIR__ . '/ports.php';
    $api = cfg()['API_BASE'] ?? 'https://makosa.org/tanie_loty/api';
    $city = PORTS[$port] ?? $port;
    $confirm = "$api/confirm.php?t=$token";

    $intro_html = $reminder
        ? '<p>Wczoraj ktoś zapisał ten adres na alerty o rekordowo '
          . "tanich lotach z $city. Jeśli to Ty — kliknij poniżej. "
          . 'Jeśli nie — zignoruj, to jedyne przypomnienie, '
          . 'więcej nie napiszemy.</p>'
        : '<p>Hej! Kliknij, by potwierdzić alerty o rekordowo '
          . "tanich lotach z $city:</p>";
    $subject = $reminder
        ? "Przypomnienie: potwierdź alerty o tanich lotach z $city"
        : "Potwierdź alerty o tanich lotach z $city";

    $text = "Potwierdź zapis alertów o tanich lotach z $city:\n$confirm\n\n"
        . "Jeśli to nie Ty — zignoruj tę wiadomość.\n";
    $html = $intro_html
        . '<p><a href="' . htmlspecialchars($confirm) . '" style="display:'
        . 'inline-block;background:#4ade80;color:#0b1733;padding:10px 22px;'
        . 'border-radius:999px;font-weight:700;text-decoration:none">'
        . 'Potwierdzam zapis</a></p>'
        . '<p style="color:#888;font-size:13px">Jeśli to nie Ty — zignoruj '
        . 'tę wiadomość.</p>';
    return send_mail($email, $subject, $html, $text);
}
