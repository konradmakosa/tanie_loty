import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import facebook_publisher as facebook
import social_publisher as social

FB = {'FB_PAGE_ID': '123', 'FB_PAGE_ACCESS_TOKEN': 'secret-token',
      'FB_GRAPH_VERSION': 'v24.0', 'FACEBOOK_ENABLED': '1'}
TG = {'TELEGRAM_ENABLED': '1', 'TELEGRAM_CHANNEL_ID': '@test', 'TELEGRAM_BOT_TOKEN': 'secret-token'}
DEAL = {'origin_city': 'Warszawa', 'dest_city': 'Oslo', 'origin': 'WAW', 'dest': 'OSL',
        'port': 'zwarszawy', 'price': 99, 'date_out': '2026-11-12', 'date_in': '2026-11-16'}


class SocialPublisherTest(unittest.TestCase):
    def test_facebook_token_is_sent_in_header_not_url(self):
        with patch('facebook_publisher.urllib.request.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'{"id":"123_456"}'
            self.assertEqual(facebook.publish_post(FB, DEAL), {'id': '123_456'})
        req = request.call_args.args[0]
        self.assertNotIn('secret-token', req.full_url)
        self.assertNotIn(b'secret-token', req.data)
        self.assertEqual(req.get_header('Authorization'), 'Bearer secret-token')
        self.assertEqual(req.full_url, 'https://graph.facebook.com/v24.0/123/feed')
        self.assertNotIn(b'link=', req.data)
        self.assertIn(b'https%3A%2F%2Fpolataj.se%2Fzwarszawy%2F', req.data)

    def test_facebook_photo_uses_route_map_and_post_id(self):
        with patch('facebook_publisher.map_image', return_value=b'png-bytes'), \
                patch('facebook_publisher.graph_request', return_value={'id': 'photo1', 'post_id': '123_456'}) as api:
            result = facebook.publish_post(FB, DEAL)
        self.assertEqual(result['id'], '123_456')
        self.assertEqual(result['photo_id'], 'photo1')
        self.assertEqual(api.call_args.args[1], '123/photos')
        self.assertEqual(api.call_args.kwargs['photo'], b'png-bytes')
        self.assertNotIn('link', api.call_args.args[2])
        self.assertIn('https://polataj.se/zwarszawy/', api.call_args.args[2]['message'])

    def test_photo_upload_uses_binary_multipart_without_exposing_token(self):
        with patch('facebook_publisher.urllib.request.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'{"id":"photo1","post_id":"123_456"}'
            facebook.graph_request(FB, '123/photos', {'message': 'Test'}, photo=b'png-bytes')
        req = request.call_args.args[0]
        self.assertIn('multipart/form-data', req.get_header('Content-type'))
        self.assertIn(b'name="source"', req.data)
        self.assertIn(b'png-bytes', req.data)
        self.assertNotIn(b'secret-token', req.data)
        self.assertNotIn('secret-token', req.full_url)

    def test_graph_errors_do_not_expose_response_or_token(self):
        body = json.dumps({'error': {'code': 190, 'error_subcode': 463,
                                    'message': 'secret-token'}}).encode()
        error = urllib.error.HTTPError('https://graph.facebook.com', 400, 'secret-token', {}, io.BytesIO(body))
        with patch('facebook_publisher.urllib.request.urlopen', side_effect=error):
            with self.assertRaises(facebook.FacebookError) as raised:
                facebook.graph_request(FB, 'me')
        self.assertEqual(raised.exception.code, 190)
        self.assertNotIn('secret-token', str(raised.exception))

    def test_page_identity_must_match_before_posting(self):
        with patch('facebook_publisher.graph_request', return_value={'id': '999'}):
            with self.assertRaises(ValueError):
                facebook.check_config(FB)

    def test_settled_jobs_continue_after_one_platform_fails(self):
        called = Mock(return_value=1)
        def fail():
            raise RuntimeError('secret-token')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = social.settle({'facebook': fail, 'telegram': called})
        self.assertFalse(result['facebook']['ok'])
        self.assertTrue(result['telegram']['ok'])
        called.assert_called_once()
        self.assertNotIn('secret-token', output.getvalue())

    def test_reverse_platform_failure_is_independent(self):
        def fail():
            raise RuntimeError()
        result = social.settle({'telegram': fail, 'facebook': lambda: 1})
        self.assertTrue(result['facebook']['ok'])
        self.assertFalse(result['telegram']['ok'])

    def test_facebook_has_separate_deduplication_and_budget(self):
        now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            with patch('facebook_publisher.check_config'), \
                    patch('facebook_publisher.send_alert', return_value=True) as sender:
                result = social.publish_all('batch', {'deal': DEAL}, now,
                                            {'TELEGRAM_ENABLED': '0'}, FB, Path(temp))
                self.assertTrue(result['facebook']['ok'])
                self.assertEqual(result['facebook']['result'], 1)
                again = social.publish_all('next', {'deal': DEAL}, now,
                                           {'TELEGRAM_ENABLED': '0'}, FB, Path(temp))
                self.assertEqual(again['facebook']['result'], 0)
                sender.assert_called_once()

    def test_disabling_facebook_does_not_disable_telegram(self):
        with patch('telegram_alerts.process', return_value=1) as public, \
                patch('telegram_alerts.publish_private', return_value=0):
            result = social.publish_all('batch', {}, datetime.now(timezone.utc), TG,
                                        {**FB, 'FACEBOOK_ENABLED': '0'})
        self.assertNotIn('facebook', result)
        self.assertTrue(result['telegram']['ok'])
        public.assert_called_once()


if __name__ == '__main__':
    unittest.main()
