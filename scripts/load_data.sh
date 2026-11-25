#!/usr/bin/env bash
# A data ágon tárolt fájlok betöltése a munkakönyvtárba (felülírják a main-beli esetleges régi példányt).
# Használat:  bash scripts/load_data.sh history.json gas.json
set -u
if git fetch --depth=1 origin data 2>/dev/null; then
  for f in "$@"; do
    if git show "FETCH_HEAD:$f" > ".load_$f" 2>/dev/null; then
      mv ".load_$f" "$f"; echo "Betöltve a data ágról: $f"
    else
      rm -f ".load_$f"; echo "Nincs a data ágon: $f"
    fi
  done
else
  echo "Még nincs data ág."
fi
exit 0
