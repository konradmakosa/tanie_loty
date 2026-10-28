#!/bin/bash
# Przebieg wyszukiwania dla wszystkich portów; log w journald.
set -u
cd /home/tl/tanie_loty
exec 9>/tmp/tl_search.lock
flock -n 9 || { echo "$(date -Is) poprzedni przebieg jeszcze trwa — pomijam"; exit 0; }

# Dane z ostatniego przebiegu są commitowane na końcu; przed pulem
# zostawiamy czyste drzewo, żeby ff-only zawsze zadziałał.
git add docs/ data/history.jsonl 2>/dev/null
git diff --cached --quiet || git commit -q -m "Aktualizacja okazji (VPS)"
git pull --rebase -X theirs -q && git push -q || echo "$(date -Is) pull/push blad"
git reset -q --hard origin/main 2>/dev/null || true

for p in zwarszawy zkrakowa zgdanska zpoznania zwroclawia zkatowic; do
  echo "=== $p search ==="
  python3 search.py "$p" || echo "search $p: BLAD"
  echo "=== $p ingest ==="
  python3 ingest.py "$p" || echo "ingest $p: BLAD"
done

echo "=== social ==="
python3 social_publisher.py --auto || echo "social: BLAD"

echo "=== build_seo_routes ==="
python3 tools/build_seo_routes.py || echo "build_seo_routes: BLAD"

git add docs/ data/history.jsonl
if ! git diff --cached --quiet; then
  git commit -q -m "Aktualizacja okazji (VPS)"
  for i in 1 2 3; do
    git pull --rebase -X theirs -q && git push -q && break
    git rebase --abort -q 2>/dev/null || true
    sleep 15
  done
fi
echo "$(date -Is) koniec przebiegu"
