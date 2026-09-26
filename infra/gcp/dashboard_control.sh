#!/usr/bin/env bash
# Root-owned fixed command bridge for the loopback-only paper dashboard.
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
[[ $# -eq 1 ]] || exit 64
case "$1" in
  start) systemctl start bitget-bot.service ;;
  stop) systemctl stop bitget-bot.service ;;
  restart) systemctl restart bitget-bot.service ;;
  verify) python3 /opt/bitget/current/infra/gcp/runtime_ops.py verify ;;
  *) exit 64 ;;
esac