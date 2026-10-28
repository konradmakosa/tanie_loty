import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import facebook_publisher as facebook
import hit_detector
import telegram_alerts as telegram

ROOT = Path(__file__).resolve().parent


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


def publish_all(batch, candidates, now, tg, fb, root=ROOT):
    jobs = {}
    if tg.get('TELEGRAM_ENABLED') == '1':
        jobs['telegram'] = lambda: telegram.process(
            tg, batch, candidates, root / 'data/cache/telegram.sqlite', now)
        jobs['telegram_private'] = lambda: telegram.publish_private(
            tg, batch, candidates, root / 'data/cache/telegram.sqlite', now,
            subscribers_path=root / 'data/cache/telegram_subscribers.sqlite')
    if fb.get('FACEBOOK_ENABLED') == '1':
        def publish_facebook():
            facebook.check_config(fb)
            return telegram.process(
                {**fb, 'RECIPIENT_ID': 'facebook:' + fb['FB_PAGE_ID']},
                batch, candidates, root / 'data/cache/facebook.sqlite', now,
                sender=facebook.send_alert, label='facebook')
        jobs['facebook'] = publish_facebook
    if tg.get('TELEGRAM_ADMIN_CHAT_ID'):
        def admin_hits():
            h_batch, h_candidates = hit_detector.collect_hit_candidates(root, now)
            return hit_detector.publish_admin_hits(
                tg, h_batch, h_candidates, root / 'data/cache/hits_admin.sqlite', now)
        jobs['admin_hits'] = admin_hits
    return settle(jobs)


def test_deal():
    from route_map import airport_coordinates
    return {
        'origin_city': 'TEST — Warszawa', 'dest_city': 'Oslo (oferta testowa)',
        'origin': 'WAW', 'dest': 'OSL', 'port': 'zwarszawy', 'price': 99,
        'date_out': 'przykładowy wylot', 'date_in': 'przykładowy powrót',
        'dest_geo': airport_coordinates().get('OSL'),
    }


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
    mode.add_argument('--auto', action='store_true')
    mode.add_argument('--send-test', action='store_true')
    parser.add_argument('--platform', choices=['all', 'facebook', 'telegram'], default='all')
    args = parser.parse_args()
    tg, fb = telegram.load_config(), facebook.load_config()
    if args.send_test:
        results = publish_test(tg, fb, args.platform)
    else:
        now = datetime.now(timezone.utc)
        batch, candidates = telegram.collect_candidates(ROOT, now)
        if not args.auto:
            print('social: dry-run, %d rekordów do 200 zł; limit 3 na platformę/odbiorcę' % len(candidates))
            return 0
        results = publish_all(batch, candidates, now, tg, fb)
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(result['ok'] for result in results.values()) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError):
        print('social: błąd konfiguracji lub danych, bez ujawniania danych dostępowych')
        raise SystemExit(1)
