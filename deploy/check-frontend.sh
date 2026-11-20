#!/usr/bin/env bash
set -euo pipefail
base=${1:?base URL required}
expected=${2:?frontend version required}
[[ "$base" =~ ^https?://[A-Za-z0-9.:/-]+$ ]]
[[ "$expected" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$ ]]
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl -fsS --max-time 20 -H 'Cache-Control: no-cache' "${base%/}/version.json" > "$work/version"
# Match an exact JSON string (versions contain no JSON escape characters).
actual=$(sed -nE 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/p' "$work/version")
[[ "$actual" == "$expected" ]]
curl -fsS --max-time 20 -H 'Cache-Control: no-cache' "${base%/}/" > "$work/index"
grep -q '<div id="app"' "$work/index"
grep -oE '(src|href)="/assets/[^" ]+\.(js|css)"' "$work/index" | cut -d '"' -f 2 > "$work/assets"
[[ -s "$work/assets" ]]
while IFS= read -r asset; do
    curl -fsS --max-time 20 -D "$work/headers" "${base%/}$asset" -o "$work/body"
    [[ -s "$work/body" ]]
    case "$asset" in
        *.js) grep -Eiq '^content-type:.*(javascript|ecmascript)' "$work/headers" ;;
        *.css) grep -Eiq '^content-type:.*text/css' "$work/headers" ;;
    esac
done < "$work/assets"
echo "Frontend verified: $expected at $base"
