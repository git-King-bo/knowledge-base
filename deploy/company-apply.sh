#!/bin/bash
set -euo pipefail
umask 077
version=${1:?version required}
target=${2:-all}
[[ "$target" =~ ^(all|frontend|backend)$ ]]
[[ "$version" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$ ]]
root=/opt/knowledge-base
incoming=$PWD
mkdir -p "$root/deploy" "$root/data" "$root/backups"
chmod 700 "$root/backups"
exec 9>"$root/deploy.lock"
flock -n 9
if [ -f "$incoming/images.tar" ]; then
    docker load -i "$incoming/images.tar"
else
    for role in backend frontend; do
        [[ "$target" == all || "$target" == "$role" ]] || continue
        docker image inspect "knowledge-company-$role:$version" >/dev/null
    done
fi
compose=(docker compose -p knowledge-company --env-file "$root/deploy/company-version.env" -f "$root/deploy/compose.company.yaml")
if [[ "$target" != all && ! -f "$root/deploy/company-version.env" ]]; then
    echo '首次部署必须发布前后端。' >&2
    exit 1
fi
backend_version=$version
frontend_version=$version
if [[ "$target" != all ]]; then
    state="$root/deploy/company-version.env"
    old=$(awk -F= '$1=="KB_VERSION" {print $2}' "$state")
    if [[ "$target" == frontend ]]; then
        backend_version=$(awk -F= '$1=="KB_BACKEND_VERSION" {print $2}' "$state")
        backend_version=${backend_version:-$old}
    else
        frontend_version=$(awk -F= '$1=="KB_FRONTEND_VERSION" {print $2}' "$state")
        frontend_version=${frontend_version:-$old}
    fi
fi
[[ "$backend_version" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$ ]]
[[ "$frontend_version" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$ ]]
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$root/backups/$stamp"
mkdir -p "$backup"
had_previous=false
if [ -f "$root/deploy/company-version.env" ]; then
    had_previous=true
    cp "$root/deploy/company-version.env" "$backup/"
    cp "$root/deploy/compose.company.yaml" "$backup/"
    if [[ "$target" != frontend ]]; then
        "${compose[@]}" stop backend
        if ! tar -C "$root" -czf "$backup/data.tgz" data; then
            "${compose[@]}" start backend
            exit 1
        fi
    fi
fi
site=/etc/nginx/sites-available/knowledge-base
[ ! -e "$site" ] || cp "$site" "$backup/nginx.conf"
rollback() {
    echo 'Deployment failed; restoring previous configuration.' >&2
    if $had_previous; then
        cp "$backup/company-version.env" "$root/deploy/"
        cp "$backup/compose.company.yaml" "$root/deploy/"
        "${compose[@]}" up -d || true
    else
        "${compose[@]}" down || true
    fi
    if [ -f "$backup/nginx.conf" ]; then
        cp "$backup/nginx.conf" "$site"
    else
        rm -f /etc/nginx/sites-enabled/knowledge-base "$site"
    fi
    nginx -t && systemctl reload nginx
}
trap rollback ERR
if [[ "$target" != backend ]]; then
    # Keep content-hashed assets from old pages, including the pre-upgrade deployment.
    assets="$root/data/frontend-assets"
    mkdir -p "$assets"
    chmod 755 "$assets"
    if docker inspect knowledge-company-web-1 >/dev/null 2>&1; then
        docker cp knowledge-company-web-1:/srv/assets/. "$assets"
    fi
    asset_container="knowledge-assets-$version"
    docker create --name "$asset_container" "knowledge-company-frontend:$frontend_version" >/dev/null
    if ! docker cp "$asset_container:/srv/assets/." "$assets"; then
        docker rm "$asset_container" >/dev/null
        false
    fi
    docker rm "$asset_container" >/dev/null
fi
install -m 644 "$incoming/compose.company.yaml" "$root/deploy/compose.company.yaml"
if [ ! -f "$root/deploy/company.env" ]; then
    install -m 600 "$incoming/company.env.example" "$root/deploy/company.env"
fi
mkdir -p "$root/data/uploads"
chown 10001:10001 "$root/data" "$root/data/uploads"
chmod 700 "$root/data"
printf 'KB_VERSION=%s\nKB_BACKEND_VERSION=%s\nKB_FRONTEND_VERSION=%s\n' "$version" "$backend_version" "$frontend_version" > "$root/deploy/company-version.env"
if [[ "$target" == frontend ]]; then
    "${compose[@]}" up -d --no-deps --wait --wait-timeout 240 web
elif [[ "$target" == backend ]]; then
    "${compose[@]}" up -d --no-deps --wait --wait-timeout 240 backend
else
    "${compose[@]}" up -d --wait --wait-timeout 240
fi
curl --fail --max-time 15 http://127.0.0.1:18080/ready
install -m 644 "$incoming/nginx.company.conf" "$site"
ln -sfn "$site" /etc/nginx/sites-enabled/knowledge-base
nginx -t
systemctl reload nginx
ready=false
for attempt in {1..10}; do
    if curl --fail --silent --max-time 15 -H 'Host: future.ops.originhub.tech' http://127.0.0.1/ready | grep -q '"status":"ready"'; then
        ready=true
        break
    fi
    sleep 1
done
$ready
"${compose[@]}" ps
trap - ERR
# Images have been loaded; keep the small configuration, not transfer archives.
rm -f "$incoming/images.tar" "$incoming/bundle.tgz"
echo "Deployment complete: $version"
