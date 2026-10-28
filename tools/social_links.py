import hashlib
from pathlib import Path


def social_links(home=False):
    css = Path(__file__).resolve().parent.parent / 'docs/assets/social.css'
    version = hashlib.sha256(css.read_bytes()).hexdigest()[:12]
    plane = ('<svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
             '<circle cx="12" cy="12" r="12" fill="#229ed9"/>'
             '<path d="M21 3 3 10l7 3 3 8 8-18ZM10 13 21 3" transform="translate(4 4) scale(.67)" '
             'fill="none" stroke="white" stroke-width="2" stroke-linejoin="round"/></svg>')
    facebook = ('<svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
                '<rect width="24" height="24" rx="6" fill="#1877f2"/>'
                '<path d="M14 8h3V4h-3c-4 0-6 2-6 6v2H5v4h3v8h4v-8h4l1-4h-5v-2c0-1 .5-2 2-2Z" '
                'transform="translate(2 1) scale(.85)" fill="white"/></svg>')
    links = [
        ('https://t.me/polataj_se', 'Telegram', 'Kanał Telegram — okazje z całej Polski', plane),
        ('https://www.facebook.com/1393638090497267', 'Facebook', 'Facebook — okazje z całej Polski', facebook),
    ]
    networks = ''.join(
        '<a class="social-network" href="%s" title="%s" aria-label="%s" target="_blank" rel="noopener">'
        '%s<span class="social-network-name">%s</span></a>' % (url, title, title, icon, name)
        for url, name, title, icon in links)
    subscribe = (
        '<details class="social-subscribe">'
        '<summary aria-label="Alerty z moich miast — jak uruchomić prywatnego bota">'
        '<span class="social-bot-label">%s<span class="social-long">Alerty z moich miast</span>'
        '<span class="social-short">Bot</span></span>'
        '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        '<path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2"/></svg></summary>'
        '<div class="social-guide"><strong>Tanie loty z wybranych miast prosto na Telegram.</strong>'
        '<ol><li>Otwórz bota i naciśnij <strong>Start</strong>.</li>'
        '<li>Zaznacz jedno lub kilka miast wylotu.</li>'
        '<li>Naciśnij <strong>Zapisz i łap okazje</strong>.</li></ol>'
        '<p>Bot odezwie się, gdy znajdzie pasującą okazję.</p>'
        '<a class="social-bot" href="https://t.me/polatajsebot" target="_blank" rel="noopener" '
        'aria-label="Uruchom prywatne alerty polataj.se na Telegramie">Uruchom bota na Telegramie</a>'
        '<small>Bezpłatnie, bez podawania e-maila. Nowe rekordy do 200 zł w obie strony, '
        'maks. 3 okazje po skanie co 6 h.</small></div></details>')
    if home:
        return ('<nav class="social-links" aria-label="Obserwuj polataj.se i wybierz swoje alerty" '
                'data-home="true" style="pointer-events:auto;text-shadow:none">'
                '<link rel="stylesheet" href="/assets/social.css?v=%s">'
                '<div class="social-networks">%s</div>%s</nav>'
                % (version, networks, subscribe % plane))
    return ('<nav class="social-links" aria-label="Obserwuj polataj.se i wybierz swoje alerty" '
            'data-home="false" style="pointer-events:auto;text-shadow:none">'
            '<link rel="stylesheet" href="/assets/social.css?v=%s">'
            '<div class="social-channels"><span>Obserwuj polataj.se</span>'
            '<div class="social-networks">%s</div></div>%s'
            '<div class="social-caption">Prywatny bot na Telegramie — Ty wybierasz miasta.</div>'
            '</nav>' % (version, networks, subscribe % plane))
