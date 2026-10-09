#!/bin/sh
# 服务器每日备份：MySQL 一致性快照 + 上传原件；加密主密钥独立保管。
set -eu
umask 077
cd /opt/knowledge-base
# 镜像版本发布启用后，从当前正式版本备份，避免访问已停用的旧 Compose 容器。
if [ -f releases/state.json ]; then
  python3 deploy/release.py backup
  exit 0
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="data/backups/mysql-${stamp}"
mkdir -p "$backup_dir"
# 容器以 UID 10001 运行，需要在新备份目录内写 SQLite 快照。
chown 10001:10001 "$backup_dir"
docker compose -p knowledge-base -f deploy/compose.ecs.yaml exec -T \
  -e APP_DATABASE_MODE=mysql backend python scripts/snapshot_mysql.py \
  --output "/data/backups/mysql-${stamp}/knowledge_base.db"
# 原件不可变；先快照数据库，再归档文件，避免已引用文件尚未进入备份。
tar -czf "${backup_dir}/uploads.tar.gz" -C data storage/uploads
sha256sum "${backup_dir}/knowledge_base.db" "${backup_dir}/uploads.tar.gz" > "${backup_dir}/SHA256SUMS"
echo "Backup completed: ${backup_dir}"
# 不自动删除历史备份；管理员确认异地备份后再按容量清理。
