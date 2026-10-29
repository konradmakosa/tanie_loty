import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import http.client as _hc
import io as _io


def map_image(deal, label="facebook"):
    """Osobne pliki: czysta mapka trasy + zdjęcie miasta (jeśli jest)."""
    images = []
    try:
        from route_map import render_route_map, city_photo, _cover, WIDTH, HEIGHT
        if deal.get("dest_geo"):
            images.append(render_route_map(deal, bare=True))
        photo = city_photo(deal["dest_city"])
        if photo is not None:
            buf = _io.BytesIO()
            _cover(photo, WIDTH, HEIGHT).save(buf, "JPEG", quality=88)
            images.append(buf.getvalue())
    except (ImportError, OSError, ValueError, KeyError, TypeError, _hc.HTTPException):
        print("%s: ilustracja niedostępna" % label)
    return images

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
    dates = deal['date_out'] + (' – %s' % deal['date_in'] if deal.get('date_in')
                                else ' (w jedną stronę)')
    unit = 'w dwie strony' if deal.get('date_in') else 'w jedną stronę'
    text = ('✈️ %s → %s\n\n💰 %.2f zł %s\n📅 %s\n'
            'Lotniska: %s → %s\n' % (
                deal['origin_city'], deal['dest_city'], deal['price'],
                unit, dates, deal['origin'], deal['dest']))
    if deal.get('airline'):
        text += 'Linia: %s\n' % deal['airline']
    return text + '\nSprawdź szczegóły i aktualną cenę na https://polataj.se/%s/' % deal['port']


def publish_post(config, deal):
    if not config['FB_PAGE_ID'].isdigit():
        raise ValueError('nieprawidłowy FB_PAGE_ID')
    message = format_post(deal)
    images = map_image(deal, label='facebook')
    media_ids = []
    for image in images:
        try:
            uploaded = graph_request(config, config['FB_PAGE_ID'] + '/photos',
                                     {'published': 'false'}, photo=image)
            if uploaded.get('id'):
                media_ids.append(uploaded['id'])
        except FacebookError:
            print('facebook: zdjęcie nieopublikowane, pomijam')
    if media_ids:
        result = graph_request(config, config['FB_PAGE_ID'] + '/feed', {
            'message': message,
            'attached_media': json.dumps([{'media_fbid': i} for i in media_ids]),
        })
        result['photo_id'] = ','.join(media_ids)
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
