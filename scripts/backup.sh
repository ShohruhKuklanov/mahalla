#!/bin/sh
# Kunlik zaxira: crontab -e →  15 3 * * * /path/to/mahalla/scripts/backup.sh
# docker compose ichidagi bazadan siqilgan nusxa oladi, 30 kundan eskilarini o'chiradi.
set -e
DIR="${BACKUP_DIR:-$HOME/mahalla-backups}"
mkdir -p "$DIR"
cd "$(dirname "$0")/.."
docker compose exec -T db pg_dump -U mahalla -Fc mahalla > "$DIR/mahalla-$(date +%F).dump"
find "$DIR" -name 'mahalla-*.dump' -mtime +30 -delete
echo "Zaxira: $DIR/mahalla-$(date +%F).dump"
# Tiklash:  docker compose exec -T db pg_restore -U mahalla -d mahalla --clean < fayl.dump
