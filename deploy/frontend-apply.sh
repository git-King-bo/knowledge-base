#!/usr/bin/env bash
# Apply only an already tested frontend image to an existing company deployment.
set -euo pipefail
umask 077
version=${1:?image tag required}
public_url=${2:?public URL required}
image_id=${3:?image ID required}
[[ "$version" =~ ^frontend-v[0-9]+\.[0-9]+\.[0-9]+-[a-f0-9]{12}$ ]]
[[ "$public_url" =~ ^https?://[A-Za-z0-9.:/-]+$ ]]
[[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]]
mode=${4:-apply}
[[ "$mode" == apply || "$mode" == rollback ]]
root=/opt/knowledge-base
incoming=$PWD
state="$root/deploy/company-version.env"
image="knowledge-company-frontend:$version"
exec 9>"$root/deploy.lock"
flock -w 300 9
[[ -f "$state" && -f "$root/deploy/compose.company.yaml" ]]
compose=(docker compose -p knowledge-company --env-file "$state" -f "$root/deploy/compose.company.yaml")
rollback_state="$incoming/previous-version.env"
rollback_image="$incoming/previous-image-id"
rollback() {
    trap - ERR
    [[ -f "$rollback_state" && -f "$rollback_image" ]]
    current=$(awk -F= '$1=="KB_FRONTEND_VERSION" {print $2}' "$state")
    [[ "$current" == "$version" ]] || { echo 'Refusing stale rollback.' >&2; exit 1; }
    old_version=$(awk -F= '$1=="KB_FRONTEND_VERSION" {print $2}' "$rollback_state")
    if [[ -z "$old_version" ]]; then old_version=$(awk -F= '$1=="KB_VERSION" {print $2}' "$rollback_state"); fi
    old_image=$(cat "$rollback_image")
    [[ "$old_version" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$ && "$old_image" =~ ^sha256:[a-f0-9]{64}$ ]]
    cp "$rollback_state" "$state"
    if [[ -f "$incoming/previous-manifest.json" ]]; then
        cp "$incoming/previous-manifest.json" "$root/deploy/frontend-manifest.json"
    else
        rm -f "$root/deploy/frontend-manifest.json"
    fi
    docker tag "$old_image" "knowledge-company-frontend:$old_version"
    "${compose[@]}" up -d --no-deps --wait --wait-timeout 120 web
    echo "Frontend rolled back to $old_version" >&2
}
if [[ "$mode" == rollback ]]; then rollback; exit 0; fi
existing=$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null || true)
[[ -z "$existing" || "$existing" == "$image_id" ]]
sha256sum -c SHA256SUMS
docker load -i images.tar
[[ "$(docker image inspect --format '{{.Id}}' "$image")" == "$image_id" ]]
[[ "$(docker image inspect --format '{{.Architecture}}' "$image")" == amd64 ]]
current=$(awk -F= '$1=="KB_FRONTEND_VERSION" {print $2}' "$state")
if [[ "$current" != "$version" ]]; then
    cp "$state" "$rollback_state"
    if [[ -f "$root/deploy/frontend-manifest.json" ]]; then
        cp "$root/deploy/frontend-manifest.json" "$incoming/previous-manifest.json"
    fi
    old_version=$(awk -F= '$1=="KB_FRONTEND_VERSION" {print $2}' "$state")
    if [[ -z "$old_version" ]]; then old_version=$(awk -F= '$1=="KB_VERSION" {print $2}' "$state"); fi
    [[ "$old_version" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$ ]]
    docker image inspect --format '{{.Id}}' "knowledge-company-frontend:$old_version" > "$rollback_image"
fi
[[ -f "$rollback_state" && -f "$rollback_image" ]]
old_container=$("${compose[@]}" ps -q web)
[[ -n "$old_container" ]]
assets="$root/data/frontend-assets"
mkdir -p "$assets"
chmod 755 "$assets"
docker cp "$old_container:/srv/assets/." "$assets"
asset_container=$(docker create "$image")
cleanup() { docker rm "$asset_container" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker cp "$asset_container:/srv/assets/." "$assets"
on_failure() {
    trap - ERR
    echo 'Frontend verification failed; restoring previous web image.' >&2
    rollback
    exit 1
}
trap on_failure ERR
awk -F= '$1 != "KB_FRONTEND_VERSION"' "$rollback_state" > "$state.tmp"
printf 'KB_FRONTEND_VERSION=%s\n' "$version" >> "$state.tmp"
mv "$state.tmp" "$state"
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 web
bash "$incoming/check-frontend.sh" http://127.0.0.1:18080 "$version"
bash "$incoming/check-frontend.sh" "$public_url" "$version"
cp manifest.json "$root/deploy/frontend-manifest.json"
rm -f images.tar
trap - ERR
echo "Frontend deployment complete: $version"
