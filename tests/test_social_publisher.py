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
        'port': 'zwarszawy', 'price': 99, 'date_out': '2026-11-12', 'date_in': '2026-11-16',
        'record_low': True}


class SocialPublisherTest(unittest.TestCase):
    def test_facebook_token_is_sent_in_header_not_url(self):
        with patch('facebook_publisher.map_image', return_value=[]), \
                patch('facebook_publisher.urllib.request.urlopen') as request:
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
        def graph(config, path, payload=None, photo=None):
            if path.endswith('/photos'):
                return {'id': 'photo1'}
            return {'id': '123_456'}
        with patch('facebook_publisher.map_image', return_value=[b'png-bytes']), \
                patch('facebook_publisher.graph_request', side_effect=graph) as api:
            result = facebook.publish_post(FB, DEAL)
        self.assertEqual(result['id'], '123_456')
        self.assertEqual(result['photo_id'], 'photo1')
        self.assertEqual(api.call_args_list[0].args[1], '123/photos')
        feed = api.call_args_list[1]
        self.assertEqual(feed.args[1], '123/feed')
        self.assertIn('attached_media', feed.args[2])
        self.assertNotIn('link', feed.args[2])
        self.assertIn('https://polataj.se/zwarszawy/', feed.args[2]['message'])

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

    def test_daily_publishes_once_per_day_per_channel(self):
        now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch('social_publisher.hit_detector.collect_hit_candidates',
                       return_value=('b', {'a': DEAL})), \
                    patch('social_publisher.hit_detector.description', return_value='x'), \
                    patch('social_publisher.hit_detector.route_url', return_value='https://x/'), \
                    patch('social_publisher.telegram.deal_images', return_value=[]), \
                    patch('social_publisher.tg_send', return_value=True) as tg_send, \
                    patch('telegram_bot.active_subscribers', return_value=[]), \
                    patch('social_publisher.wykop.load_config',
                          return_value={'key': '', 'secret': '', 'enabled': False}), \
                    patch('social_publisher.facebook.post_message',
                          return_value={'id': '1'}) as post:
                result = social.publish_daily(TG, FB, root, now)
                self.assertEqual(result['facebook']['result'], True)
                self.assertEqual(result['telegram']['result'], True)
                again = social.publish_daily(TG, FB, root, now)
                self.assertEqual(again['daily']['result'], 'już opublikowane dziś')
            self.assertEqual(post.call_count, 1)
            self.assertEqual(tg_send.call_count, 1)  # kanał (admin wyłączony)

    def test_daily_marks_routes_and_skips_them_next_week(self):
        now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data/cache').mkdir(parents=True)
            main, extras = social.pick_daily({'a': DEAL}, now, root)
            self.assertEqual(main['dest_city'], 'Oslo')
            (root / 'data/cache/daily.json').write_text(json.dumps({
                'date': '2026-10-28', 'sent': ['telegram'],
                'routes': {'Warszawa-Oslo': now.timestamp()}}))
            # wszystko w cooldownzie -> fallback na najdawniej publikowaną trasę
            main, _ = social.pick_daily({'a': DEAL}, now, root)
            self.assertEqual(main['dest_city'], 'Oslo')

    def test_daily_extras_prefer_other_cities(self):
        now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data/cache').mkdir(parents=True)
            other = {**DEAL, 'origin_city': 'Kraków', 'origin': 'KRK',
                     'dest_city': 'Kopenhaga', 'dest': 'CPH', 'price': 40}
            main, extras = social.pick_daily({'a': DEAL, 'b': other}, now, root)
            self.assertEqual(main['origin_city'], 'Kraków')  # najtańsza
            self.assertEqual([e['dest_city'] for e in extras], ['Oslo'])


if __name__ == '__main__':
    unittest.main()
