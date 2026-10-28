import html

from telegram_alerts import api_call, process

ABSOLUTE_MAX = 60.0
DISCOUNT_RATIO = 0.30
MAX_DATES = 3


def is_hit(deal):
    price = deal.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return False
    if price <= ABSOLUTE_MAX:
        return True
    typical = deal.get("typical_price")
    return bool(isinstance(typical, (int, float)) and typical > 0 and
                price <= typical * DISCOUNT_RATIO)


def pepper_message(deal):
    esc = lambda value: html.escape(str(value))
    title = "Loty z %s do %s za %.0f zł! (w dwie strony)" % (
        deal["origin_city"], deal["dest_city"], deal["price"])
    dates = "\n".join("• %s – %s" % (esc(d["date_out"]), esc(d["date_in"]))
                      for d in deal["_dates"][:MAX_DATES])
    return (
        "🔥 <b>HIT NA PEPPER.PL</b> 🔥\n\n"
        "<b>TYTUŁ:</b>\n%s\n\n"
        "<b>CENA:</b>\n%.0f\n\n"
        "<b>LINK:</b>\nhttps://polataj.se/%s/\n\n"
        "<b>OPIS DO WKLEJENIA:</b>\n"
        "Automatyczny alert z polataj.se wyłapał okazję na loty z %s do %s.\n\n"
        "<b>Przykładowe daty:</b>\n%s\n\n"
        "Szybsze alerty o takich błędach cenowych i okazjach wpadają na nasz Telegram: "
        "https://t.me/polataj_se"
        % (esc(title), deal["price"], esc(deal["port"]),
           esc(deal["origin_city"]), esc(deal["dest_city"]), dates))


def send_admin_hit(config, deal):
    result = api_call(config["TELEGRAM_BOT_TOKEN"], "sendMessage", {
        "chat_id": config["TELEGRAM_ADMIN_CHAT_ID"],
        "text": pepper_message(deal),
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    })
    return isinstance(result, dict) and bool(result.get("message_id"))


def group_hits(candidates):
    hits = [deal for deal in candidates.values() if is_hit(deal)]
    by_route = {}
    for deal in hits:
        key = (deal["origin"], deal["dest"])
        by_route.setdefault(key, []).append(deal)
    selected = {}
    for key, deals in by_route.items():
        deals.sort(key=lambda d: (d["price"], d["date_out"]))
        best = {**deals[0], "_dates": deals}
        selected["%s-%s-%s-%s" % (key[0], key[1], best["date_out"], best["date_in"])] = best
    return selected


def publish_admin_hits(config, batch, candidates, state_path, now):
    if not config.get("TELEGRAM_ADMIN_CHAT_ID"):
        return 0
    hits = group_hits(candidates)
    target = {**config, "RECIPIENT_ID": "admin:%s" % config["TELEGRAM_ADMIN_CHAT_ID"],
              "TELEGRAM_CHANNEL_ID": config["TELEGRAM_ADMIN_CHAT_ID"]}
    return process(target, batch, hits, state_path, now,
                   sender=send_admin_hit, label="hit-admin")
