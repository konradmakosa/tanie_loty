<?php
// Porty lotnicze obsługiwane przez serwis (slug → miasto w dopełniaczu).
const PORTS = [
    'zwarszawy'  => 'Warszawy',
    'zkrakowa'   => 'Krakowa',
    'zgdanska'   => 'Gdańska',
    'zpoznania'  => 'Poznania',
    'zwroclawia' => 'Wrocławia',
    'zkatowic'   => 'Katowic',
];

function port_ok(string $p): bool {
    return isset(PORTS[$p]);
}
