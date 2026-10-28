import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import hit_detector
from social_publisher import settle

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
ADMIN = {'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHANNEL_ID': '@pub',
         'TELEGRAM_ADMIN_CHAT_ID': '922'}


def deal(price, typical=300, origin='WAW', dest='OSL', d='2026-11-12', r='2026-11-16'):
    return {'origin_city': 'Warszawa', 'dest_city': 'Oslo', 'origin': origin,
            'dest': dest, 'port': 'zwarszawy', 'price': price,
            'typical_price': typical, 'date_out': d, 'date_in': r}


class HitDetectorTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertTrue(hit_detector.is_hit(deal(60, typical=1000)))
        self.assertFalse(hit_detector.is_hit(deal(61, typical=100)))
        self.assertTrue(hit_detector.is_hit(deal(90, typical=300)))
        self.assertFalse(hit_detector.is_hit(deal(91, typical=300)))
        self.assertTrue(hit_detector.is_hit(deal(10, typical=None)))
        self.assertFalse(hit_detector.is_hit(deal(0, typical=100)))

    def test_groups_dates_and_message_blocks(self):
        candidates = {'a': deal(55, d='2026-11-12', r='2026-11-14'),
                      'b': deal(58, d='2026-11-19', r='2026-11-21'),
                      'c': deal(60, d='2026-11-26', r='2026-11-28'),
                      'd': deal(150)}
        hits = hit_detector.group_hits(candidates)
        self.assertEqual(len(hits), 1)
        best = next(iter(hits.values()))
        self.assertEqual(len(best['_dates']), 3)
        msg = hit_detector.pepper_message(best)
        for block in ('TYTUŁ:', 'CENA:', 'LINK:', 'OPIS DO WKLEJENIA:', 'Przykładowe daty:'):
            self.assertIn(block, msg)
        self.assertEqual(msg.count('•'), 3)
        self.assertIn('https://polataj.se/zwarszawy/', msg)
        self.assertIn('https://t.me/polataj_se', msg)

    def test_send_uses_admin_chat_not_channel(self):
        api = Mock(return_value={'message_id': 7})
        best = deal(55); best['_dates'] = [best]
        import unittest.mock as m
        with m.patch('hit_detector.api_call', api):
            self.assertTrue(hit_detector.send_admin_hit(ADMIN, best))
        payload = api.call_args.args[2]
        self.assertEqual(payload['chat_id'], '922')
        self.assertNotEqual(payload['chat_id'], '@pub')
        self.assertTrue(payload['link_preview_options']['is_disabled'])

    def test_publish_has_own_state_and_admin_failure_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'hits.sqlite'
            candidates = {'a': deal(55)}
            sender = Mock(return_value=True)
            import unittest.mock as m
            with m.patch('hit_detector.send_admin_hit', sender):
                self.assertEqual(hit_detector.publish_admin_hits(
                    ADMIN, 'batch', candidates, state, NOW), 1)
                self.assertEqual(hit_detector.publish_admin_hits(
                    ADMIN, 'batch2', candidates, state, NOW), 0)
                sender.assert_called_once()
        outcomes = settle({'admin_hits': Mock(side_effect=RuntimeError),
                           'telegram': Mock(return_value=1)})
        self.assertFalse(outcomes['admin_hits']['ok'])
        self.assertTrue(outcomes['telegram']['ok'])

    def test_no_admin_id_means_no_job(self):
        self.assertEqual(hit_detector.publish_admin_hits(
            {**ADMIN, 'TELEGRAM_ADMIN_CHAT_ID': ''}, 'b', {}, Path('/tmp/x.db'), NOW), 0)


if __name__ == '__main__':
    unittest.main()
