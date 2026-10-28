import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from telegram_alerts import api_call, collect_candidates, format_alert, main, process, send_alert


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
CONFIG = {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHANNEL_ID": "@test"}


def deal(price=99):
    return {
        "origin": "WMI", "dest": "BTS", "dest_city": "Bratysława",
        "origin_city": "Warszawa", "port": "zwarszawy", "price": price,
        "date_out": "2026-11-12", "date_in": "2026-11-16",
        "record_low": True, "airline": "Ryanair",
    }


class TelegramTest(unittest.TestCase):
    @patch('telegram_alerts.publish_private', return_value=0)
    def test_automatic_publishing_is_opt_in(self, private):
        for enabled, expected in [('0', False), ('1', True)]:
            with patch('telegram_alerts.load_config', return_value={
                    **CONFIG, 'TELEGRAM_ENABLED': enabled}):
                with patch('telegram_alerts.collect_candidates', return_value=('batch', {})):
                    with patch('telegram_alerts.process', return_value=0) as run:
                        with patch('sys.argv', ['telegram_alerts.py', '--auto']):
                            self.assertEqual(main(), 0)
                        self.assertEqual(run.called, expected)
        with patch('telegram_alerts.load_config', return_value={
                **CONFIG, 'TELEGRAM_ENABLED': '1'}):
            with patch('telegram_alerts.collect_candidates', return_value=('batch', {})):
                with patch('telegram_alerts.process') as run:
                    with patch('sys.argv', ['telegram_alerts.py']):
                        self.assertEqual(main(), 0)
                    run.assert_not_called()

    def test_html_is_escaped_and_link_matches_label(self):
        item = deal()
        item.update(dest_city='A < B & "C"', airline='<script>')
        text = format_alert(item)
        self.assertIn('A &lt; B &amp; &quot;C&quot;', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('href="https://polataj.se/zwarszawy/"', text)
        self.assertIn('99.00 zł (w dwie strony)', text)

    def test_missing_airline_omits_line(self):
        item = deal()
        del item['airline']
        text = format_alert(item)
        self.assertNotIn('<b>Linia:</b>', text)
        self.assertIn('<b>Lotniska:</b>', text)

    def test_send_checks_message_id(self):
        with patch('telegram_alerts.api_call', return_value={"message_id": 42}) as call:
            self.assertTrue(send_alert(CONFIG, deal()))
        payload = call.call_args.args[2]
        self.assertEqual(payload['chat_id'], '@test')
        self.assertEqual(payload['parse_mode'], 'HTML')
        self.assertEqual(payload['link_preview_options'], {'is_disabled': True})
        with patch('telegram_alerts.api_call', return_value=None):
            self.assertFalse(send_alert(CONFIG, deal()))

    def test_photo_uses_caption_and_does_not_send_second_message(self):
        with patch('telegram_alerts.map_image', return_value=b'PNG'):
            with patch('telegram_alerts.api_call', return_value={'message_id': 123}) as call:
                self.assertTrue(send_alert(CONFIG, deal()))
        call.assert_called_once()
        self.assertEqual(call.call_args.args[1], 'sendPhoto')
        self.assertEqual(call.call_args.kwargs['photo'], b'PNG')
        self.assertIn('caption', call.call_args.args[2])

    def test_failed_upload_does_not_send_duplicate_text(self):
        with patch('telegram_alerts.map_image', return_value=b'PNG'):
            with patch('telegram_alerts.api_call', return_value=None) as call:
                self.assertFalse(send_alert(CONFIG, deal()))
        call.assert_called_once()
        self.assertEqual(call.call_args.args[1], 'sendPhoto')

    def test_map_failure_falls_back_to_text(self):
        with patch('route_map.render_route_map', side_effect=TimeoutError):
            with patch('telegram_alerts.api_call', return_value={'message_id': 1}) as call:
                self.assertTrue(send_alert(CONFIG, {**deal(), 'dest_geo': '60.19,11.1'}))
        self.assertEqual(call.call_args.args[1], 'sendMessage')

    def test_repeated_menu_edit_is_treated_as_delivered(self):
        error = urllib.error.HTTPError('https://api.telegram.org/bottest-token/editMessageText',
                                       400, 'bad request', {}, io.BytesIO(
                                           b'{"description":"Bad Request: message is not modified"}'))
        with patch('telegram_alerts.urllib.request.urlopen', side_effect=error):
            self.assertIs(api_call('test-token', 'editMessageText', {}), True)

    def test_photo_request_is_multipart(self):
        with patch('telegram_alerts.urllib.request.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'{"ok":true,"result":{"message_id":1}}'
            self.assertEqual(api_call('test-token', 'sendPhoto', {
                'chat_id': '@test', 'caption': 'Warszawa → Oslo', 'parse_mode': 'HTML'},
                photo=b'PNG'), {'message_id': 1})
        req = request.call_args.args[0]
        self.assertIn('multipart/form-data', req.get_header('Content-type'))
        self.assertIn(b'filename="trasa.png"', req.data)
        self.assertIn('Warszawa → Oslo'.encode(), req.data)
        self.assertEqual(request.call_args.kwargs['timeout'], 30)

    def test_network_errors_do_not_leak_token(self):
        for error in (
            urllib.error.URLError('https://api.telegram.org/bottest-token/sendMessage'),
            urllib.error.HTTPError('https://api.telegram.org/bottest-token/sendMessage',
                                   429, 'test-token', {}, None),
            TimeoutError('test-token'),
        ):
            output = io.StringIO()
            with patch('telegram_alerts.urllib.request.urlopen', side_effect=error):
                with contextlib.redirect_stdout(output):
                    self.assertIsNone(api_call('test-token', 'sendMessage', {}))
            self.assertNotIn('test-token', output.getvalue())

    def test_collection_filters_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'config.json').write_text(json.dumps({
                'ports': {'zwarszawy': {'city': 'Warszawa'}}}))
            path = root / 'docs' / 'zwarszawy'
            path.mkdir(parents=True)
            records = [deal(), deal(100), deal(201), deal(0), deal(-1), deal(True),
                       deal(float('nan')), deal(float('inf')),
                       {**deal(), 'record_low': False},
                       {**deal(), 'trip': 'oneway', 'date_in': None},
                       {**deal(), 'date_out': '2026-10-28'},
                       {**deal(), 'dest': 'KRK', 'price': 200}]
            def snapshot(name, stamp, deals):
                (path / name).write_text(json.dumps({
                    'generated_at': stamp.isoformat(), 'deals': deals}))
            snapshot('deals.json', NOW, records)
            snapshot('far.json', NOW, [deal()])
            batch, candidates = collect_candidates(root, NOW)
            self.assertEqual(len(candidates), 2)
            self.assertEqual(sorted(d['price'] for d in candidates.values()), [99, 200])
            snapshot('deals.json', NOW - timedelta(hours=9), records)
            snapshot('far.json', NOW + timedelta(hours=1), records)
            self.assertFalse(collect_candidates(root, NOW)[1])
            self.assertNotEqual(batch, collect_candidates(root, NOW)[0])

    def test_global_limit_persists_and_sent_deals_are_not_repeated(self):
        candidates = {str(i): {**deal(100 + i), 'dest': str(i)} for i in range(6)}
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state.sqlite'
            sender = Mock(return_value=True)
            self.assertEqual(process(CONFIG, 'batch-1', candidates, state, NOW, sender), 3)
            self.assertEqual(process(CONFIG, 'batch-1', candidates, state, NOW, sender), 0)
            self.assertEqual(process(CONFIG, 'batch-2', candidates, state,
                                     NOW + timedelta(hours=6), sender), 3)
            self.assertEqual(process(CONFIG, 'batch-3', candidates, state,
                                     NOW + timedelta(hours=12), sender), 0)
            self.assertEqual(sender.call_count, 6)

    def test_failed_alert_is_retried_without_record_low_in_next_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state.sqlite'
            failed = Mock(return_value=False)
            self.assertEqual(process(CONFIG, 'first', {'a': deal()}, state, NOW, failed), 0)
            sender = Mock(return_value=True)
            self.assertEqual(process(CONFIG, 'second', {}, state,
                                     NOW + timedelta(hours=6), sender), 1)
            self.assertEqual(process(CONFIG, 'third', {}, state,
                                     NOW + timedelta(hours=12), sender), 0)

    def test_expired_pending_alerts_are_not_sent(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'state.sqlite'
            process(CONFIG, 'first', {'a': deal()}, state, NOW, Mock(return_value=False))
            sender = Mock(return_value=True)
            self.assertEqual(process(CONFIG, 'second', {}, state,
                                     NOW + timedelta(hours=25), sender), 0)
            sender.assert_not_called()


if __name__ == '__main__':
    unittest.main()
