"""Mirror artykułów bloga Soro (trysoro) na statyczne strony /blog/<slug>/.

Pobiera listę artykułów i ich treść z publicznego API osadzonego widgetu
(ten sam endpoint co skrypt embed) i generuje statyczne strony HTML —
indeksowalne, trwałe po wygaśnięciu subskrypcji, z własnym canonical
i JSON-LD. Uruchamiany przez run_search.sh przed build_seo_routes.py,
dzięki czemu nowe artykuły trafiają do sitemap w tym samym przebiegu.

Zero zależności poza stdlib. Błędy API nie przerywają pipeline (exit 0).
"""
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
BLOG_DIR = DOCS / "blog"
STATE = Path(__file__).resolve().parent.parent / "data" / "cache" / "soro.json"

SITE = "https://polataj.se"
TOKEN = "093c41ce-5624-4252-b2a1-579e1d47d347"
API = "https://app.trysoro.com/api/embed/" + TOKEN
TIMEOUT = 20

HEAD = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — polataj.se</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:title" content="{title} — polataj.se">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{ogimage}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{ogimage}">
<link rel="icon" href="../favicon.ico" sizes="48x48">
<link rel="icon" href="../favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="../apple-touch-icon.png">
<link rel="manifest" href="../site.webmanifest">
<meta name="theme-color" content="#0b1733">
<!-- Global site tag (gtag.js) - Google Analytics -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-CTFYNF714B"></script>
<script async src="https://www.googletagmanager.com/gtm.js?id=AW-1069452351"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('consent', 'default', {{ 'analytics_storage': 'granted', 'ad_storage': 'denied', 'ad_user_data': 'denied', 'ad_personalization': 'denied' }});
  gtag('js', new Date());
  gtag('config', 'G-CTFYNF714B', {{ anonymize_ip: true }});
  gtag('config', 'AW-1069452351');
</script>
{jsonld}
<style>
  :root {{
    --bg: #171c2b; --card: #1b2030; --text: #e8eaf0;
    --muted: #9aa3b2; --accent: #7aa2ff; --line: rgba(255,255,255,.08);
  }}
  * {{ box-sizing: border-box; }}
  html {{ min-height: 100%; background: var(--bg)
    linear-gradient(180deg, #0b1733 0%, #121c34 50%, #171c2b 100%)
    no-repeat fixed; }}
  body {{ margin: 0; color: var(--text);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      "Helvetica Neue", Arial, sans-serif; }}
  main {{ max-width: 720px; margin: 0 auto; padding: 20px 16px 64px; }}
  a {{ color: var(--accent); }}
  .back {{ display: inline-block; margin-bottom: 14px;
    text-decoration: none; font-weight: 600; }}
  h1 {{ font-size: 1.6rem; margin: 6px 0 10px; line-height: 1.25; }}
  .date {{ color: var(--muted); font-size: .85rem; margin-bottom: 20px; }}
  .hero {{ width: 100%; border-radius: 12px; margin-bottom: 22px; }}
  .article h2 {{ font-size: 1.2rem; margin: 26px 0 8px; color: var(--accent); }}
  .article h3 {{ font-size: 1.05rem; margin: 20px 0 6px; }}
  .article p {{ margin: 0 0 14px; }}
  .article ul, .article ol {{ margin: 0 0 14px; padding-left: 22px; }}
  .article li {{ margin: 6px 0; }}
  .article img {{ max-width: 100%; height: auto; border-radius: 8px; }}
  .meta {{ color: var(--muted); font-size: .85rem; margin-top: 32px;
    border-top: 1px solid var(--line); padding-top: 14px; }}
</style>
</head>
<body>
<main>
  <a class="back" href="/blog/">← Blog podróżniczy</a>
  <h1>{h1}</h1>
  <p class="date">{date}</p>
  {hero}
  <div class="article">{content}</div>
  <p class="meta"><a href="/blog/">Wszystkie artykuły</a> ·
    <a href="/">polataj.se — tanie loty z polskich lotnisk</a></p>
</main>
</body>
</html>
"""


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "polataj.se"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def list_articles():
    """Wszystkie artykuły (paginacja po stronach)."""
    arts, page = [], 1
    while True:
        d = fetch_json("%s/articles?page=%d" % (API, page))
        arts.extend(d.get("articles") or [])
        if page >= (d.get("totalPages") or 1):
            return arts
        page += 1


def article_content(a):
    if a.get("content"):
        return a["content"]
    aid = a.get("id")
    if not aid:
        return ""
    try:
        return fetch_json("%s/article/%s" % (API, aid)).get("content") or ""
    except Exception as e:
        print("soro: brak treści %s: %s" % (aid, e), file=sys.stderr)
        return ""


def fmt_date(iso):
    try:
        return datetime.fromisoformat(
            iso.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except Exception:
        return iso[:10]


def render(article, content):
    slug = article.get("slug") or str(article.get("id") or "")
    title = article.get("title") or "Artykuł"
    desc = (article.get("excerpt") or title)[:160]
    iso = article.get("isoDate") or article.get("publishedAt") or ""
    image = article.get("image") or (SITE + "/og.png?v=c2dc00fb5b23")
    jsonld = ('<script type="application/ld+json">'
              + json.dumps({
                  "@context": "https://schema.org",
                  "@type": "BlogPosting",
                  "headline": title,
                  "description": desc,
                  "datePublished": iso,
                  "image": article.get("image") or None,
                  "url": "%s/blog/%s/" % (SITE, slug),
              }, ensure_ascii=False) + "</script>")
    hero = ('<img class="hero" src="%s" alt="%s">'
            % (escape(article["image"]), escape(title))
            if article.get("image") else "")
    return HEAD.format(
        title=escape(title), desc=escape(desc),
        canonical="%s/blog/%s/" % (SITE, slug),
        ogimage=escape(image), jsonld=jsonld, h1=escape(title),
        date=escape(fmt_date(iso)), hero=hero, content=content)


def render_index(articles):
    """Przepisuje sekcję statycznych linków w docs/blog/index.html."""
    idx = BLOG_DIR / "index.html"
    if not idx.exists():
        return
    items = "\n".join(
        '    <li><a href="/blog/%s/">%s</a> <small>%s</small></li>'
        % (a.get("slug") or a.get("id"), escape(a.get("title") or "Artykuł"),
           escape(fmt_date(a.get("isoDate") or a.get("publishedAt") or "")))
        for a in articles)
    block = ("  <h2>Wszystkie artykuły</h2>\n  <ul id=\"soro-static\">\n%s\n  </ul>"
             % items)
    s = idx.read_text(encoding="utf-8")
    s = re.sub(r"  <h2>Wszystkie artykuły</h2>\n  <ul id=\"soro-static\">.*?</ul>",
               block, s, flags=re.S)
    if 'id="soro-static"' not in s:
        s = s.replace('<div id="soro-blog"></div>',
                      '<div id="soro-blog"></div>\n' + block)
    idx.write_text(s, encoding="utf-8")


def main():
    try:
        articles = list_articles()
    except Exception as e:
        print("soro: API niedostępne: %s" % e, file=sys.stderr)
        return 0
    if not articles:
        print("soro: brak artykułów")
        return 0

    written = []
    for a in articles:
        slug = a.get("slug") or str(a.get("id") or "")
        if not slug:
            continue
        content = article_content(a)
        if not content:
            continue
        d = BLOG_DIR / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(render(a, content), encoding="utf-8")
        written.append(slug)
        time.sleep(0.2)

    render_index(articles)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(
        {"synced_at": datetime.now(timezone.utc).isoformat(),
         "articles": len(articles), "written": written},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("soro: %d artykułów, zapisano %d stron" % (len(articles), len(written)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
