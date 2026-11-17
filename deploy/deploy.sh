#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(dirname "$script_dir")"
if [[ "${1:-}" == "--help" ]]; then
    echo '用法：bash deploy/deploy.sh [all|frontend|backend]（默认发布前后端）'
    exit 0
fi
target=${1:-all}
if [[ $# -gt 1 || ! "$target" =~ ^(all|frontend|backend)$ ]]; then
    echo '用法：bash deploy/deploy.sh [all|frontend|backend]' >&2
    exit 1
fi
cd "$root_dir"
version=$(date -u +%Y%m%dT%H%M%SZ)-$$
mkdir -p logs
log="$root_dir/logs/deploy-$version.log"
touch "$log"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
trap 'echo "发布失败，详细日志：$log" >&2' ERR

images=()
build() {
    local role image
    for role in backend frontend; do
        [[ "$target" == all || "$target" == "$role" ]] || continue
        image="knowledge-company-$role:$version"
        images+=("$image")
        if [[ "$role" == backend ]] &&
           [[ "$(docker image inspect --format '{{.Architecture}}' knowledge-base-release-test:backend 2>/dev/null || true)" == amd64 ]] &&
           docker run --rm --platform linux/amd64 --entrypoint cat knowledge-base-release-test:backend /app/requirements.lock > "$work/requirements.lock" &&
           cmp -s backend/requirements.lock "$work/requirements.lock"; then
            printf 'FROM knowledge-base-release-test:backend\nCOPY backend /app\n' > "$work/Dockerfile"
            docker build --platform linux/amd64 -f "$work/Dockerfile" -t "$image" . || return
        elif [[ "$role" == frontend ]] && command -v pnpm >/dev/null &&
             [[ "$(docker image inspect --format '{{.Architecture}}' knowledge-base-release-test:frontend 2>/dev/null || true)" == amd64 ]]; then
            VITE_APP_VERSION="$version" pnpm --dir frontend build || return
            cp -R frontend/dist "$work/dist" || return
            cp deploy/Caddyfile "$work/Caddyfile" || return
            printf 'FROM knowledge-base-release-test:frontend\nCOPY dist /srv\nCOPY Caddyfile /etc/caddy/Caddyfile\n' > "$work/Dockerfile"
            docker build --platform linux/amd64 -t "$image" "$work" || return
        else
            docker build --platform linux/amd64 --build-arg "VITE_APP_VERSION=$version" -f "deploy/Dockerfile.$role" -t "$image" . || return
        fi
        [[ "$(docker image inspect --format '{{.Architecture}}' "$image")" == amd64 ]] || return 1
    done
}

echo '[1/3] 构建镜像…'
build >> "$log" 2>&1
echo '[2/3] 打包并上传…'
docker save -o "$work/images.tar" "${images[@]}" >> "$log" 2>&1
for file in compose.company.yaml nginx.company.conf company.env.example company-apply.sh; do
    cp "$script_dir/$file" "$work/$file"
done
tar -czf "$work/bundle.tgz" -C "$work" images.tar compose.company.yaml nginx.company.conf company.env.example company-apply.sh >> "$log" 2>&1
checksum=$(openssl dgst -sha256 "$work/bundle.tgz" | awk '{print $NF}')
[[ "$checksum" =~ ^[a-f0-9]{64}$ ]]
remote="/opt/knowledge-base/incoming/$version"
ssh companyOps "mkdir -p $remote; chmod 700 /opt/knowledge-base/incoming $remote" >> "$log" 2>&1
ssh companyOps "cat > $remote/bundle.tgz" < "$work/bundle.tgz" >> "$log" 2>&1
echo '[3/3] 备份数据并更新服务…'
ssh companyOps "cd $remote && echo '$checksum  bundle.tgz' | sha256sum -c - && tar -xzf bundle.tgz && bash company-apply.sh $version $target" >> "$log" 2>&1
echo "发布成功：$target / $version"
echo '访问：http://future.ops.originhub.tech'
echo "详细日志：$log"
