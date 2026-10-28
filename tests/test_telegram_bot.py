import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from telegram_alerts import process, publish_private
from telegram_bot import (active_subscribers, apply_update, city_label, confirmed_menu,
                          flush_outbox, menu, open_store, read_subscriber, settings_menu)

PORTS = {
    'zwarszawy': {'city': 'Warszawa', 'airports': ['WMI', 'WAW', 'RDO']},
    'zkrakowa': {'city': 'Kraków', 'airports': ['KRK']},
}
NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
CONFIG = {'TELEGRAM_CHANNEL_ID': '@test', 'TELEGRAM_BOT_TOKEN': 'test-token'}


def update(number, action='/start', chat=111, callback=False, private=True):
    message = {'message_id': 42, 'chat': {'id': chat, 'type': 'private' if private else 'group'}}
    if callback:
        return {'update_id': number, 'callback_query': {'id': 'test-query', 'from': {'id': chat},
                'data': action, 'message': message}}
    return {'update_id': number, 'message': {**message, 'text': action}}


def flight(origin, port, price=99):
    return {'origin': origin, 'dest': 'OSL', 'port': port, 'price': price,
            'date_out': '2026-11-12', 'date_in': '2026-11-16'}


class TelegramBotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'subscribers.sqlite'
        self.delivery = Path(self.tmp.name) / 'delivery.sqlite'
        self.db = open_store(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def apply(self, number, action='/start', chat=111, callback=False):
        apply_update(self.db, update(number, action, chat, callback), PORTS)

    def test_start_and_multi_city_preferences(self):
        self.apply(1)
        self.assertEqual(read_subscriber(111, self.path), (set(), False))
        self.assertFalse(active_subscribers(self.path))
        self.apply(2, 'port:zwarszawy', callback=True)
        self.apply(3, 'port:zkrakowa', callback=True)
        self.assertEqual(read_subscriber(111, self.path)[0], set())
        self.assertFalse(active_subscribers(self.path))
        self.apply(4, 'save', callback=True)
        self.assertEqual(read_subscriber(111, self.path)[0], set(PORTS))
        self.assertIn('WAW · WMI · RDO', city_label('zwarszawy', PORTS['zwarszawy']))
        self.apply(5, 'port:zwarszawy', callback=True)
        self.assertEqual(read_subscriber(111, self.path)[0], set(PORTS))
        self.apply(6, 'save', callback=True)
        self.assertEqual(read_subscriber(111, self.path)[0], {'zkrakowa'})

    def test_replayed_callback_does_not_toggle_twice(self):
        self.apply(1)
        self.apply(2, 'port:zwarszawy', callback=True)
        self.apply(2, 'port:zwarszawy', callback=True)
        self.assertEqual(read_subscriber(111, self.path)[0], set())
        self.apply(3, 'save', callback=True)
        self.assertEqual(read_subscriber(111, self.path)[0], {'zwarszawy'})
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 1)

    def test_pause_resume_and_unsubscribe(self):
        self.apply(1)
        self.apply(2, 'port:zwarszawy', callback=True)
        self.apply(3, 'save', callback=True)
        self.apply(4, '/pauza')
        self.assertFalse(active_subscribers(self.path))
        self.apply(5, '/wznow')
        self.assertEqual(len(active_subscribers(self.path)), 1)
        self.apply(6, '/wypisz')
        self.assertIsNone(read_subscriber(111, self.path))
        self.assertFalse(active_subscribers(self.path))

    def test_menu_encourages_signup_and_keeps_pause_in_settings(self):
        text, keyboard = menu(PORTS, {'zwarszawy'}, False, {'zkrakowa'})
        buttons = [button for row in keyboard['inline_keyboard'] for button in row]
        self.assertIn('Skąd chcesz łapać tanie loty?', text)
        self.assertTrue(any('Zapisz i łap okazje' in button['text'] for button in buttons))
        self.assertFalse(any(button['callback_data'] in ('pause', 'unsubscribe') for button in buttons))
        self.assertNotIn('/wypisz', text)
        saved, _ = confirmed_menu(PORTS, {'zkrakowa'}, False)
        self.assertIn('Gotowe!', saved)
        self.assertIn('Kraków', saved)
        _, settings = settings_menu(PORTS, {'zkrakowa'}, False)
        self.assertEqual([b['callback_data'] for row in settings['inline_keyboard'] for b in row],
                         ['pause', 'home'])

    def test_empty_save_does_not_subscribe(self):
        self.apply(1)
        self.apply(2, 'save', callback=True)
        self.assertFalse(active_subscribers(self.path))
        payload = json.loads(self.db.execute('SELECT payload FROM outbox').fetchone()[0])
        self.assertIn('Wybierz najpierw', payload['text'])

    def test_draft_survives_reopening_without_activating_alerts(self):
        self.apply(1)
        self.apply(2, 'port:zwarszawy', callback=True)
        reopened = open_store(self.path)
        try:
            self.assertEqual(json.loads(reopened.execute('SELECT draft_ports FROM subscribers').fetchone()[0]),
                             ['zwarszawy'])
        finally:
            reopened.close()
        sender = Mock(return_value=True)
        candidates = {'WAW': flight('WAW', 'zwarszawy')}
        self.assertEqual(publish_private(CONFIG, 'batch', candidates, self.delivery,
                                         NOW, self.path, sender), 0)
        sender.assert_not_called()
        self.apply(3, 'save', callback=True)
        self.assertEqual(publish_private(CONFIG, 'batch', candidates, self.delivery,
                                         NOW, self.path, sender), 1)

    def test_save_explicitly_resumes_paused_alerts(self):
        self.apply(1)
        self.apply(2, 'port:zwarszawy', callback=True)
        self.apply(3, 'save', callback=True)
        self.apply(4, '/pauza')
        self.apply(5, 'port:zkrakowa', callback=True)
        self.assertEqual(read_subscriber(111, self.path), ({'zwarszawy'}, True))
        self.apply(6, 'save', callback=True)
        self.assertEqual(read_subscriber(111, self.path), (set(PORTS), False))

    def test_legacy_migration_preserves_selection_and_pause(self):
        path = Path(self.tmp.name) / 'legacy.sqlite'
        legacy = sqlite3.connect(path)
        with legacy:
            legacy.execute('CREATE TABLE subscribers (chat_id INTEGER PRIMARY KEY, ports TEXT, paused INTEGER)')
            legacy.execute('INSERT INTO subscribers VALUES(111,?,1)', (json.dumps(['zwarszawy']),))
        legacy.close()
        migrated = open_store(path)
        try:
            self.assertEqual(json.loads(migrated.execute('SELECT draft_ports FROM subscribers').fetchone()[0]),
                             ['zwarszawy'])
        finally:
            migrated.close()
        self.assertEqual(read_subscriber(111, path), ({'zwarszawy'}, True))

    def test_groups_and_forged_callbacks_are_ignored(self):
        apply_update(self.db, update(1, private=False), PORTS)
        forged = update(2, 'port:zwarszawy', callback=True)
        forged['callback_query']['from']['id'] = 999
        apply_update(self.db, forged, PORTS)
        self.assertIsNone(read_subscriber(111, self.path))
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_outbox_survives_network_failure(self):
        self.apply(1)
        flush_outbox(self.db, 'test-token', api=Mock(return_value=None))
        self.assertEqual(self.db.execute('SELECT attempts FROM outbox').fetchone()[0], 1)
        with self.db:
            self.db.execute('UPDATE outbox SET retry_at=0')
        api = Mock(return_value={'message_id': 42})
        flush_outbox(self.db, 'test-token', api=api)
        self.assertEqual(self.db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)
        text = api.call_args.args[2]['text']
        self.assertIn('Warszawa obejmuje', text)
        self.assertNotIn('parse_mode', api.call_args.args[2])

    def test_personal_delivery_has_independent_limits_and_deduplication(self):
        for uid, action, chat in [
            (1, '/start', 111), (2, 'port:zwarszawy', 111), (3, 'save', 111),
            (4, '/start', 222), (5, 'port:zkrakowa', 222), (6, 'save', 222),
            (7, '/start', 333), (8, 'port:zwarszawy', 333), (9, 'save', 333), (10, 'pause', 333),
        ]:
            self.apply(uid, action, chat, not action.startswith('/'))
        candidates = {origin: flight(origin, 'zwarszawy', price)
                      for origin, price in [('WAW', 99), ('WMI', 100), ('RDO', 101)]}
        candidates['KRK'] = flight('KRK', 'zkrakowa', 90)
        candidates['GDN'] = flight('GDN', 'zgdanska', 80)
        sender = Mock(return_value=True)
        count = publish_private(CONFIG, 'batch', candidates, self.delivery, NOW, self.path, sender)
        self.assertEqual(count, 4)
        self.assertEqual({call.args[1]['origin'] for call in sender.call_args_list
                          if call.args[0]['TELEGRAM_CHANNEL_ID'] == '111'}, {'WAW', 'WMI', 'RDO'})
        self.assertEqual({call.args[1]['origin'] for call in sender.call_args_list
                          if call.args[0]['TELEGRAM_CHANNEL_ID'] == '222'}, {'KRK'})
        self.assertEqual(publish_private(CONFIG, 'next', candidates, self.delivery,
                                         NOW, self.path, sender), 0)
        self.assertEqual(sender.call_count, 4)

    def test_pending_deal_from_deselected_city_is_not_sent(self):
        sender = Mock(return_value=True)
        process(CONFIG, 'first', {'WAW': flight('WAW', 'zwarszawy')}, self.delivery,
                NOW, sender=Mock(return_value=False))
        self.assertEqual(process(CONFIG, 'next', {}, self.delivery, NOW,
                                 sender, allowed_ports={'zkrakowa'}), 0)
        sender.assert_not_called()

    def test_pause_is_checked_again_before_each_delivery(self):
        self.apply(1)
        self.apply(2, 'port:zwarszawy', callback=True)
        self.apply(3, 'save', callback=True)
        def send(config, deal):
            self.apply(4, '/pauza')
            return True
        sender = Mock(side_effect=send)
        candidates = {code: flight(code, 'zwarszawy') for code in ['WAW', 'WMI', 'RDO']}
        self.assertEqual(publish_private(CONFIG, 'batch', candidates, self.delivery,
                                         NOW, self.path, sender), 1)
        self.assertEqual(sender.call_count, 1)


if __name__ == '__main__':
    unittest.main()
