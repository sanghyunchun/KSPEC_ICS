#!/usr/bin/env bash
# 이 저장소(kspec_metrology)의 git 추적 파일을 KSPEC_ICS 클론의 MTL/kspec_metrology/ 로 복사한다.
#   tools/sync_to_ics.sh /path/to/KSPEC_ICS
# 그 뒤 KSPEC_ICS 클론에서 git status / diff 를 보고 commit → push(fork) → Pull Request.
# .bak, 노트북 결과, 데이터 등 추적하지 않는 파일은 복사되지 않는다. ICS 쪽에만 있는 파일은 지우지 않는다.
set -euo pipefail
ICS="${1:?usage: tools/sync_to_ics.sh /path/to/KSPEC_ICS}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="$ICS/MTL/kspec_metrology"
[ -d "$ICS/MTL" ] || { echo "not a KSPEC_ICS clone: $ICS"; exit 1; }
mkdir -p "$DST"
cd "$SRC"
git ls-files -z | rsync -a --files-from=- --from0 "$SRC/" "$DST/"
echo "copied $(git ls-files | wc -l) tracked files ($(git log -1 --format='%h %cs')) -> $DST"
cd "$ICS" && git status --short MTL/kspec_metrology | head -40
