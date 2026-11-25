#!/usr/bin/env bash
# A gyűjtők eredményét (gas.json, history.json) a "data" ágra menti, NEM a main-re.
# Így sosem ütközik a kézi feltöltésekkel vagy más futásokkal, és a main története sem telik meg adatfájlokkal.
# A data ág tartalmát az Adatfrissítés (update.yml) olvassa be közzétételkor.
# Használat:  bash scripts/save_data.sh gas.json [másik.json ...]      (DATA_MSG: a commit üzenete)
set -u
if [ "$#" -lt 1 ]; then echo "használat: save_data.sh fájl..."; exit 2; fi
msg="${DATA_MSG:-adatok frissítése}"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

keep="$(mktemp -d)"
for f in "$@"; do cp "$f" "$keep/$(basename "$f")" || { echo "Hiányzik: $f"; exit 1; }; done

for i in 1 2 3 4 5; do
  W="$(mktemp -d)/w"
  if git fetch --depth=1 origin data; then
    git worktree add --detach "$W" FETCH_HEAD || exit 1
  else
    echo "Még nincs data ág, most jön létre."
    git worktree add --orphan -b "data-helyi-$$-$i" "$W" || exit 1
  fi
  for f in "$@"; do cp "$keep/$(basename "$f")" "$W/$(basename "$f")"; done
  git -C "$W" add -A
  if git -C "$W" diff --cached --quiet; then echo "Nincs változás."; exit 0; fi
  git -C "$W" commit -q -m "$msg" || exit 1
  if git -C "$W" push origin HEAD:refs/heads/data; then echo "Mentve a data ágra."; exit 0; fi
  git worktree remove --force "$W" >/dev/null 2>&1 || true
  echo "A mentés nem sikerült ($i. próba), újra próbálom..."
  sleep $((i * 5))
done
echo "A mentés nem sikerült."
exit 1
