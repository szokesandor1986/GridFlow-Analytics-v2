#!/usr/bin/env bash
# A gyűjtők eredményét (fájlok és mappák: gas.json, history.json, hist/) a "data" ágra menti, NEM a main-re.
# Így sosem ütközik a kézi feltöltésekkel vagy más futásokkal, és a main története sem telik meg adatfájlokkal.
# A data ág tartalmát az Adatfrissítés (update.yml) olvassa be közzétételkor.
# Használat:  bash scripts/save_data.sh gas.json hist [...]      (DATA_MSG: a commit üzenete)
#   DATA_SQUASH=1  a data ág egyetlen, szülő nélküli commitra áll vissza (a nagy hist/ mappa története ne halmozódjon fel);
#                  a felülírás csak akkor történik meg, ha közben senki más nem írt az ágra (force-with-lease), különben újra próbál.
set -u
if [ "$#" -lt 1 ]; then echo "használat: save_data.sh fájl_vagy_mappa..."; exit 2; fi
msg="${DATA_MSG:-adatok frissítése}"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

keep="$(mktemp -d)"
for f in "$@"; do cp -a "$f" "$keep/$(basename "$f")" || { echo "Hiányzik: $f"; exit 1; }; done

for i in 1 2 3 4 5; do
  W="$(mktemp -d)/w"
  base=""
  if git fetch --depth=1 origin data; then
    base="$(git rev-parse FETCH_HEAD)"
    git worktree add --detach "$W" FETCH_HEAD || exit 1
  else
    echo "Még nincs data ág, most jön létre."
    git worktree add --orphan -b "data-helyi-$$-$i" "$W" || exit 1
  fi
  for f in "$@"; do
    n="$(basename "$f")"
    rm -rf "${W:?}/$n"
    cp -a "$keep/$n" "$W/$n"
  done
  git -C "$W" add -A
  if git -C "$W" diff --cached --quiet && [ -n "$base" ]; then echo "Nincs változás."; exit 0; fi
  if [ -n "${DATA_SQUASH:-}" ]; then
    tree="$(git -C "$W" write-tree)" || exit 1
    commit="$(git -C "$W" commit-tree "$tree" -m "$msg")" || exit 1
    if [ -n "$base" ]; then lease="--force-with-lease=refs/heads/data:$base"; else lease=""; fi
    if git -C "$W" push $lease origin "$commit:refs/heads/data"; then echo "Mentve a data ágra (egy commitra összevonva)."; exit 0; fi
  else
    git -C "$W" commit -q -m "$msg" || exit 1
    if git -C "$W" push origin HEAD:refs/heads/data; then echo "Mentve a data ágra."; exit 0; fi
  fi
  git worktree remove --force "$W" >/dev/null 2>&1 || true
  echo "A mentés nem sikerült ($i. próba), újra próbálom..."
  sleep $((i * 5))
done
echo "A mentés nem sikerült."
exit 1
