import argparse
import html
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import facebook_publisher as facebook
import hit_detector
import telegram_alerts as telegram
import wykop_publisher as wykop

ROOT = Path(__file__).resolve().parent
DAILY_ROUTE_DAYS = 7
MAX_EXTRAS = 3


def settle(jobs):
    outcomes = {}
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as executor:
        futures = {executor.submit(job): name for name, job in jobs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                outcomes[name] = {'ok': True, 'result': future.result()}
            except Exception as exc:
                error = str(exc) if isinstance(exc, facebook.FacebookError) else type(exc).__name__
                outcomes[name] = {'ok': False, 'error': error}
                print('social %s: błąd %s; pozostałe kanały kontynuują' % (name, error))
    return outcomes


def _daily_path(root):
    return root / 'data/cache/daily.json'


def load_daily(root):
    try:
        state = json.loads(_daily_path(root).read_text())
    except (OSError, ValueError):
        state = {}
    if 'routes' not in state:
        # jednorazowy seed z historii Wykopa — nie powtarzamy świeżych wpisów
        try:
            wy = json.loads((root / 'data/cache/wykop_state.json').read_text())
            state['routes'] = wy.get('routes') or {}
        except (OSError, ValueError):
            state['routes'] = {}
    return state


def save_daily(root, state):
    path = _daily_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def pick_daily(candidates, now, root):
    """Główna oferta + do MAX_EXTRAS dodatkowych (najlepiej z innych miast),
    bez tras publikowanych w ciągu ostatniego tygodnia."""
    routes = load_daily(root).get('routes') or {}
    cutoff = now.timestamp() - DAILY_ROUTE_DAYS * 86400
    fresh = sorted((d for d in candidates.values() if d.get('price', 0) > 0),
                   key=lambda d: (0 if d.get('dest_geo') else 1, d['price']))
    free = [d for d in fresh if routes.get(telegram.route_key(d), 0) <= cutoff]
    if not free:
        return None, []
    main = free[0]
    used = {telegram.route_key(main)}
    extras = []
    for only_other_cities in (True, False):
        for d in free:
            if len(extras) >= MAX_EXTRAS:
                break
            r = telegram.route_key(d)
            if r in used or (only_other_cities and
                             d.get('origin_city') == main.get('origin_city')):
                continue
            extras.append(d)
            used.add(r)
    return main, extras


def _extra_line(d):
    dates = d['date_out'] + (' – %s' % d['date_in'] if d.get('date_in') else '')
    return '• %s → %s — %.0f zł (%s)' % (d['origin_city'], d['dest_city'],
                                       d['price'], dates)


def _facts(main):
    oneway = main.get('trip') == 'oneway' or not main.get('date_in')
    dates = main['date_out'] + (' – %s' % main['date_in'] if main.get('date_in')
                                else ' (w jedną stronę)')
    facts = ['💰 %.2f zł %s' % (main['price'], 'w jedną stronę' if oneway else 'w dwie strony'),
             '📅 ' + dates,
             'Lotniska: %s → %s' % (main['origin'], main['dest'])]
    if main.get('airline'):
        facts.append('Linia: ' + main['airline'])
    return facts


def format_tg(main, extras, desc, url):
    esc = lambda v: html.escape(str(v))
    parts = ['<b>✈️ %s → %s</b>' % (esc(main['origin_city']), esc(main['dest_city']))]
    parts += [esc(f) for f in _facts(main)]
    parts += ['', esc(desc),
              '', '<a href="%s">Sprawdź szczegóły na polataj.se</a>' % esc(url)]
    if extras:
        parts += ['', '<b>Znaleźliśmy też jeszcze:</b>']
        parts += [esc(_extra_line(d)) for d in extras]
    return '\n'.join(parts)


def format_fb(main, extras, desc, url):
    parts = ['✈️ %s → %s' % (main['origin_city'], main['dest_city'])]
    parts += _facts(main)
    parts += ['', desc, '', 'Sprawdź szczegóły i aktualną cenę na %s' % url]
    if extras:
        parts += ['', 'Znaleźliśmy też jeszcze:'] + [_extra_line(d) for d in extras]
    return '\n'.join(parts)


def format_wykop(main, extras, desc, url):
    oneway = main.get('trip') == 'oneway' or not main.get('date_in')
    dates = main['date_out'] + (' – %s' % main['date_in'] if main.get('date_in') else '')
    parts = ['✈️ **%s ➡️ %s** – od %.0f zł (%s)' % (
                 main['origin_city'], main['dest_city'], main['price'],
                 'w jedną stronę' if oneway else 'w dwie strony'),
             '📅 Daty: ' + dates, '', desc,
             '', '🔗 Szczegóły: %s' % url]
    if extras:
        parts += ['', '**Znaleźliśmy też jeszcze:**'] + [_extra_line(d) for d in extras]
    parts += ['',
              '---', 'Skaner & alerty w czasie rzeczywistym: https://polataj.se | '
              'Telegram: https://t.me/polataj_se', '#polatajse #tanieloty #podroze #promocje']
    return '\n'.join(parts)


def tg_send(config, chat_id, text, images):
    """Ta sama wiadomość + album (mapka + zdjęcie miasta) do wskazanego czatu."""
    token = config['TELEGRAM_BOT_TOKEN']
    if images and len(text) <= 1024:
        if len(images) > 1:
            media = [{'type': 'photo', 'media': 'attach://photo0',
                      'caption': text, 'parse_mode': 'HTML'}]
            media += [{'type': 'photo', 'media': 'attach://photo%d' % i}
                      for i in range(1, len(images))]
            res = telegram.api_call(token, 'sendMediaGroup',
                                    {'chat_id': chat_id, 'media': json.dumps(media)},
                                    photos=images)
            return isinstance(res, list) and bool(res)
        res = telegram.api_call(token, 'sendPhoto', {
            'chat_id': chat_id, 'caption': text, 'parse_mode': 'HTML'},
            photo=images[0])
        return isinstance(res, dict) and bool(res.get('message_id'))
    if images:
        media = [{'type': 'photo', 'media': 'attach://photo%d' % i}
                 for i in range(len(images))]
        res = telegram.api_call(token, 'sendMediaGroup',
                                {'chat_id': chat_id, 'media': json.dumps(media)},
                                photos=images)
        if not (isinstance(res, list) and res):
            return False
    res = telegram.api_call(token, 'sendMessage', {
        'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML',
        'link_preview_options': {'is_disabled': True}})
    return isinstance(res, dict) and bool(res.get('message_id'))


def publish_daily(tg, fb, root=ROOT, now=None):
    """Jeden zbiorczy post dziennie — ta sama treść i obrazki na wszystkich kanałach."""
    now = now or datetime.now(timezone.utc)
    today = now.strftime('%Y-%m-%d')
    state = load_daily(root)
    sent = set(state.get('sent') or []) if state.get('date') == today else set()
    needed = set()
    if tg.get('TELEGRAM_ENABLED') == '1':
        needed.update(('telegram', 'telegram_private'))
        if tg.get('TELEGRAM_ADMIN_CHAT_ID'):
            needed.add('admin')
    if fb.get('FACEBOOK_ENABLED') == '1':
        needed.add('facebook')
    wy = wykop.load_config()
    if wy['key'] and wy['secret'] and wy['enabled']:
        needed.add('wykop')
    todo = needed - sent
    if not todo:
        return {'daily': {'ok': True, 'result': 'już opublikowane dziś' if needed else 'brak kanałów'}}
    _, all_deals = hit_detector.collect_hit_candidates(root, now)
    # tylko loty zagraniczne — krajowe odrzucamy wprost
    candidates = {k: d for k, d in all_deals.items()
                  if telegram.alert_worthy(d) and d.get('price', 0) > 0
                  and d.get('country_code') != 'PL' and not d.get('domestic')}
    main, extras = pick_daily(candidates, now, root)
    if main is None:
        return {'daily': {'ok': True, 'result': 'brak ofert'}}
    desc = hit_detector.description(main)
    url = hit_detector.route_url(main)
    images = telegram.deal_images(main, bare=True)
    text_tg = format_tg(main, extras, desc, url)
    jobs = {}
    if 'telegram' in todo:
        jobs['telegram'] = lambda: tg_send(
            tg, tg['TELEGRAM_CHANNEL_ID'], text_tg, images)
    if 'telegram_private' in todo:
        def private():
            from telegram_bot import active_subscribers
            subs = root / 'data/cache/telegram_subscribers.sqlite'
            ok = True
            for chat_id, _ports in active_subscribers(subs):
                ok = tg_send(tg, str(chat_id), text_tg, images) and ok
            return ok
        jobs['telegram_private'] = private
    if 'admin' in todo:
        jobs['admin'] = lambda: tg_send(
            tg, tg['TELEGRAM_ADMIN_CHAT_ID'], text_tg, images)
    if 'facebook' in todo:
        jobs['facebook'] = lambda: bool(facebook.post_message(
            fb, format_fb(main, extras, desc, url), images).get('id'))
    if 'wykop' in todo:
        jobs['wykop'] = lambda: bool(wykop.post(
            wy, format_wykop(main, extras, desc, url),
            images[0] if images else None))
    outcomes = settle(jobs)
    done = [name for name, r in outcomes.items() if r['ok'] and r['result']]
    if done:
        routes = state.get('routes') or {}
        for d in [main] + extras:
            routes[telegram.route_key(d)] = now.timestamp()
        state['routes'] = {r: ts for r, ts in routes.items()
                           if ts > now.timestamp() - 14 * 86400}
        state['sent'] = sorted(sent | set(done))
        state['date'] = today
        save_daily(root, state)
    return outcomes


def test_deal(root=ROOT):
    """Prawdziwa, najtańsza oferta — test wygląda 1:1 jak alert."""
    import json as _json
    from hit_detector import collect_hit_candidates
    now = datetime.now(timezone.utc)
    _, candidates = collect_hit_candidates(root, now)
    fresh = [d for d in candidates.values() if d.get('dest_geo')]
    if not fresh:
        cfg = _json.loads((root / 'config.json').read_text())['ports']
        for port, info in cfg.items():
            for name in ('deals.json', 'far.json', 'oneway.json'):
                path = root / 'docs' / port / name
                if not path.exists():
                    continue
                for deal in _json.loads(path.read_text())['deals']:
                    if deal.get('dest_geo') and deal['date_out'] > now.date().isoformat():
                        fresh.append({**deal, 'port': port,
                                      'origin_city': info['city'],
                                      'origin_city_gen': info['city_gen']})
    if not fresh:
        raise RuntimeError('brak ofert do testu')
    return min(fresh, key=lambda d: d['price'])


def publish_test(tg, fb, platform='all'):
    deal = test_deal()
    jobs = {}
    if platform in ('all', 'telegram'):
        def telegram_test():
            if not telegram.check_config(tg):
                raise RuntimeError('weryfikacja Telegrama nieudana')
            if not telegram.send_alert(tg, deal):
                raise RuntimeError('wysyłka Telegrama niepotwierdzona')
            return True
        jobs['telegram'] = telegram_test
    if platform in ('all', 'facebook'):
        def facebook_test():
            facebook.check_config(fb)
            return facebook.publish_post(fb, deal)
        jobs['facebook'] = facebook_test
    return settle(jobs)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--auto', action='store_true',
                      help='alias --daily (jeden zbiorczy post dziennie)')
    mode.add_argument('--daily', action='store_true')
    mode.add_argument('--send-test', action='store_true')
    parser.add_argument('--platform', choices=['all', 'facebook', 'telegram'], default='all')
    args = parser.parse_args()
    tg, fb = telegram.load_config(), facebook.load_config()
    if args.send_test:
        results = publish_test(tg, fb, args.platform)
    elif args.daily or args.auto:
        results = publish_daily(tg, fb)
    else:
        now = datetime.now(timezone.utc)
        batch, candidates = telegram.collect_candidates(ROOT, now)
        print('social: dry-run, %d rekordów do 200 zł; publikacja zbiorcza 1×/dziś (--daily)' % len(candidates))
        return 0
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(result.get('ok') for result in results.values()) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError):
        print('social: błąd konfiguracji lub danych, bez ujawniania danych dostępowych')
        raise SystemExit(1)
