import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram_alerts import check_config, load_config, send_alert


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-test", action="store_true",
                        help="Publikuje prawdziwy post testowy na skonfigurowanym kanale")
    args = parser.parse_args()
    config = load_config()
    if not config["TELEGRAM_BOT_TOKEN"] or not config["TELEGRAM_CHANNEL_ID"]:
        print("telegram: brak tokenu lub kanału")
        return 1
    if not check_config(config):
        return 1
    if not args.send_test:
        print("telegram: konfiguracja OK; test bez publikacji")
        return 0
    sent = send_alert(config, {
        "origin_city": "TEST — Warszawa", "dest_city": "Oslo (oferta testowa)",
        "origin": "WAW", "dest": "OSL", "port": "zwarszawy",
        "price": 99, "date_out": "przykładowy wylot",
        "date_in": "przykładowy powrót", "airline": "TEST — nie jest rzeczywistą ofertą",
    })
    print("telegram: post testowy %s" % ("wysłany" if sent else "niepotwierdzony"))
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
