<?php
// Wysyłka e-mail (multipart/alternative, UTF-8). MAIL_DEBUG_DIR → pliki .eml.

function _enc_hdr(string $s): string {
    return '=?UTF-8?B?' . base64_encode($s) . '?=';
}

function send_mail(string $to, string $subject, string $html, string $text,
                   string $extraHeaders = ''): bool {
    $c = cfg();
    $from = $c['MAIL_FROM'] ?? 'alerty@polataj.se';

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

    $headers = "From: =?UTF-8?B?" . base64_encode('Polataj.se') . "?= <$from>\r\n"
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
