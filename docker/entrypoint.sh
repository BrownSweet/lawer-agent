#!/bin/sh
set -eu

mkdir -p "${DATA_DIR:-/app/.local/files}"
cd /app/law_backend
# 迁移失败时退出，避免启动一个数据库结构不兼容的工作台。
alembic upgrade head
exec "$@"
