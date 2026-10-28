def social_links():
    style = ('display:flex;flex-wrap:wrap;justify-content:center;align-items:center;'
             'gap:12px;margin:12px auto;pointer-events:auto;font-size:12px;text-shadow:none')
    link_style = ('display:inline-flex;align-items:center;gap:5px;color:#e8eaf0;'
                  'text-decoration:none;background:#0b1733;padding:6px 10px;border-radius:20px')
    plane = '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 3 3 10l7 3 3 8 8-18ZM10 13 21 3" fill="none" stroke="#45b6e8" stroke-width="2" stroke-linejoin="round"/></svg>'
    facebook = '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 8h3V4h-3c-4 0-6 2-6 6v2H5v4h3v8h4v-8h4l1-4h-5v-2c0-1 .5-2 2-2Z" fill="#75a2ff"/></svg>'
    links = [
        ('https://t.me/polataj_se', 'Kanał Telegram z okazjami z całej Polski', plane + 'Telegram'),
        ('https://www.facebook.com/1393638090497267', 'Obserwuj polataj.se na Facebooku', facebook + 'Facebook'),
        ('https://t.me/polatajsebot', 'Wybierz miasta i zapisz się na prywatne alerty', 'Alerty z moich miast'),
    ]
    return '<nav class="social-links" aria-label="Obserwuj polataj.se" style="%s">%s</nav>' % (
        style, ''.join('<a href="%s" title="%s" aria-label="%s" target="_blank" rel="noopener" style="%s">%s</a>'
                       % (url, title, title, link_style, label) for url, title, label in links))
