import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from telegram_alerts import map_image

ROOT = Path(__file__).resolve().parent


class FacebookError(RuntimeError):
    def __init__(self, status=0, code=0, subcode=0):
        self.status, self.code, self.subcode = status, code, subcode
        super().__init__('HTTP %s, Graph code=%s, subcode=%s' % (status, code, subcode))


def load_config():
    values = {}
    path = ROOT / 'facebook' / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    def value(key, default=''):
        return os.environ.get(key, values.get(key, default))
    return {
        'FB_PAGE_ID': value('FB_PAGE_ID'),
        'FB_PAGE_ACCESS_TOKEN': value('FB_PAGE_ACCESS_TOKEN') or value('FACEBOOK_ACCESS_TOKEN'),
        'FB_GRAPH_VERSION': value('FB_GRAPH_VERSION', 'v24.0'),
        'FACEBOOK_ENABLED': value('FACEBOOK_ENABLED', '0'),
    }


def graph_request(config, path, payload=None, photo=None):
    version = config['FB_GRAPH_VERSION']
    if not re.fullmatch(r'v\d{1,2}\.0', version):
        raise ValueError('nieprawidłowa wersja Graph API')
    url = 'https://graph.facebook.com/%s/%s' % (version, path)
    data = None if payload is None else urllib.parse.urlencode(payload).encode('utf-8')
    content_type = 'application/x-www-form-urlencoded'
    if photo is not None:
        boundary = 'polataj_' + os.urandom(16).hex()
        parts = [('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                  % (boundary, key, value)).encode('utf-8') for key, value in payload.items()]
        parts.append(('--%s\r\nContent-Disposition: form-data; name="source"; '
                      'filename="trasa.png"\r\nContent-Type: image/png\r\n\r\n' % boundary).encode('utf-8')
                     + photo + b'\r\n')
        data = b''.join(parts) + ('--%s--\r\n' % boundary).encode('utf-8')
        content_type = 'multipart/form-data; boundary=' + boundary
    req = urllib.request.Request(url, data=data, headers={
        'Authorization': 'Bearer ' + config['FB_PAGE_ACCESS_TOKEN'],
        'Content-Type': content_type,
    })
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read(16384)).get('error', {})
            code, subcode = int(error.get('code', 0)), int(error.get('error_subcode', 0))
        except (OSError, ValueError, TypeError, AttributeError):
            code, subcode = 0, 0
        raise FacebookError(exc.code, code, subcode) from None
    except (OSError, ValueError, http.client.HTTPException):
        raise FacebookError() from None
    if not isinstance(result, dict):
        raise FacebookError()
    if result.get('error'):
        error = result['error']
        raise FacebookError(200, error.get('code', 0), error.get('error_subcode', 0))
    return result


def check_config(config):
    if not config['FB_PAGE_ID'].isdigit() or not config['FB_PAGE_ACCESS_TOKEN']:
        raise ValueError('brak poprawnego FB_PAGE_ID lub FB_PAGE_ACCESS_TOKEN')
    page = graph_request(config, 'me?fields=id,name,link')
    if str(page.get('id')) != config['FB_PAGE_ID']:
        raise ValueError('Token nie jest tokenem wskazanej strony — potrzebny Page Access Token.')
    print('facebook: strona=%s, id=%s, link=%s, API=%s' % (
        page.get('name'), page['id'], page.get('link', ''), config['FB_GRAPH_VERSION']))
    return page


def format_post(deal):
    text = ('✈️ %s → %s\n\n💰 %.2f zł w dwie strony\n📅 %s – %s\n'
            'Lotniska: %s → %s\n' % (
                deal['origin_city'], deal['dest_city'], deal['price'],
                deal['date_out'], deal['date_in'], deal['origin'], deal['dest']))
    if deal.get('airline'):
        text += 'Linia: %s\n' % deal['airline']
    return text + '\nSprawdź szczegóły i aktualną cenę na polataj.se.'


def publish_post(config, deal):
    if not config['FB_PAGE_ID'].isdigit():
        raise ValueError('nieprawidłowy FB_PAGE_ID')
    message = format_post(deal) + '\n\nhttps://polataj.se/%s/' % deal['port']
    photo = map_image(deal, label='facebook')
    if photo is not None:
        result = graph_request(config, config['FB_PAGE_ID'] + '/photos', {
            'message': message, 'published': 'true',
        }, photo=photo)
        if result.get('id'):
            result = {**result, 'photo_id': result['id'], 'id': result.get('post_id') or result['id']}
    else:
        result = graph_request(config, config['FB_PAGE_ID'] + '/feed', {'message': message})
    if not result.get('id'):
        raise FacebookError()
    print('facebook: opublikowano post id=%s' % result['id'])
    return result


def send_alert(config, deal):
    return bool(publish_post(config, deal).get('id'))


if __name__ == '__main__':
    try:
        check_config(load_config())
    except (FacebookError, ValueError) as exc:
        print('facebook: weryfikacja nieudana — %s' % exc)
        raise SystemExit(1)
