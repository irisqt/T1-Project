#!/usr/bin/env bash
# Run only on the dedicated Ubuntu 24.04 Compute Engine VM.
set -Eeuo pipefail
umask 077
archive="${1:?archive path required}"
expected_sha="${2:?archive SHA256 required}"
backup_bucket="${3:-}"
[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "Invalid SHA256" >&2; exit 1; }
[[ -z "$backup_bucket" || "$backup_bucket" =~ ^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$ ]] || exit 1
[[ -f "$archive" && ! -L "$archive" ]] || { echo "Expected regular archive file" >&2; exit 1; }
actual_sha="$(sha256sum -- "$archive" | cut -d' ' -f1)"
[[ "$actual_sha" == "$expected_sha" ]] || { echo "Archive checksum mismatch" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install --yes --no-install-recommends python3 ca-certificates e2fsprogs util-linux
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
id -u bitget >/dev/null 2>&1 || useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin bitget
install -d -m 0755 /opt/bitget/releases
install -d -m 0750 -o root -g bitget /etc/bitget
install -d -m 0750 -o root -g bitget /var/lib/bitget

# Refuse unexpected/partitioned disks. Only the explicitly attached data disk can be initialized.
device=/dev/disk/by-id/google-bitget-data
[[ -b "$device" ]] || { echo "Named durable data disk is missing" >&2; exit 1; }
filesystem="$(blkid -s TYPE -o value "$device" || true)"
if [[ -z "$filesystem" ]]; then
    [[ "$(lsblk -nr -o NAME "$device" | wc -l)" -eq 1 ]] || { echo "Unexpected disk partitions" >&2; exit 1; }
    signatures="$(wipefs --no-act --noheadings --output TYPE "$device")"
    [[ -z "$signatures" ]] || { echo "Disk has unrecognized signatures" >&2; exit 1; }
    mkfs.ext4 -L bitget-state "$device"
elif [[ "$filesystem" != ext4 ]]; then
    echo "Refusing to overwrite non-ext4 disk" >&2
    exit 1
fi
disk_uuid="$(blkid -s UUID -o value "$device")"
if mountpoint --quiet /var/lib/bitget; then
    [[ "$(findmnt -n -o UUID /var/lib/bitget)" == "$disk_uuid" ]] || { echo "Wrong mounted data disk" >&2; exit 1; }
else
    [[ -z "$(find /var/lib/bitget -mindepth 1 -maxdepth 1 -print -quit)" ]] || { echo "Mountpoint is not empty" >&2; exit 1; }
    mount -o nodev,nosuid,noexec "$device" /var/lib/bitget
fi
if ! grep -q "^UUID=$disk_uuid " /etc/fstab; then
    printf 'UUID=%s /var/lib/bitget ext4 defaults,nofail,nodev,nosuid,noexec 0 2\n' "$disk_uuid" >> /etc/fstab
fi
install -d -m 0700 -o bitget -g bitget /var/lib/bitget/data /var/lib/bitget/backups

staging="$(mktemp -d /opt/bitget/releases/.staging-XXXXXXXX)"
trap 'if [[ -n "${staging:-}" && "$staging" == /opt/bitget/releases/.staging-* ]]; then rm -rf -- "$staging"; fi' EXIT
python3 - "$archive" "$staging" <<'PY'
import hashlib, json, pathlib, sys, tarfile, tomllib
archive, target = sys.argv[1], pathlib.Path(sys.argv[2])
with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()
    names = [m.name for m in members]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate archive member")
    for member in members:
        name = pathlib.PurePosixPath(member.name)
        allowed = (
            member.name == "BUILD_MANIFEST.json"
            or member.name == "config/paper.toml"
            or (name.parts[:2] == ("src", "bitget_bot") and name.suffix == ".py")
            or (name.parts[:2] == ("infra", "gcp") and name.suffix in {".py", ".sh", ".service", ".timer"})
        )
        if not allowed or not member.isfile() or name.is_absolute() or ".." in name.parts:
            raise ValueError("Unsafe archive member")
        if member.size > 10_000_000:
            raise ValueError("Unexpected deployment file size")
    handle.extractall(target, filter="data")
manifest = json.loads((target / "BUILD_MANIFEST.json").read_text())
expected = {row["path"] for row in manifest["files"]}
if set(names) != expected | {"BUILD_MANIFEST.json"}:
    raise ValueError("Archive manifest file list mismatch")
for row in manifest["files"]:
    data = (target / row["path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("Manifest checksum mismatch")
settings = tomllib.loads((target / "config/paper.toml").read_text())
mode = settings.get("mode", settings.get("app", {}).get("mode", settings.get("trading", {}).get("mode")))
if mode != "paper":
    raise ValueError("Only paper deployment is supported")
PY
ln -s /var/lib/bitget/data "$staging/data"
chmod -R a+rX "$staging"
release="/opt/bitget/releases/${expected_sha:0:16}"
if [[ -e "$release" ]]; then
    [[ -d "$release" && ! -L "$release" ]] || { echo "Invalid release path" >&2; exit 1; }
else
    mv -- "$staging" "$release"
    staging=""
fi

if [[ ! -f /etc/bitget/paper.toml ]]; then
    install -m 0640 -o root -g bitget "$release/config/paper.toml" /etc/bitget/paper.toml
fi
# Existing configuration is preserved, but must still be paper before restarting.
python3 - <<'PY'
import tomllib
with open("/etc/bitget/paper.toml", "rb") as source:
    settings = tomllib.load(source)
mode = settings.get("mode", settings.get("app", {}).get("mode", settings.get("trading", {}).get("mode")))
if mode != "paper":
    raise ValueError("Existing server configuration is not paper")
PY
printf 'BITGET_BACKUP_BUCKET=%s\n' "$backup_bucket" > /etc/bitget/backup.env
chown root:bitget /etc/bitget/backup.env
chmod 0640 /etc/bitget/backup.env
# Stop only after the new release is fully verified; the old directory remains for rollback.
for link in /opt/bitget/current /opt/bitget/current.next; do
    [[ ! -e "$link" || -L "$link" ]] || { echo "Unexpected non-symlink release pointer" >&2; exit 1; }
done
if systemctl cat bitget-bot.service >/dev/null 2>&1; then
    systemctl stop bitget-bot.service
fi
if systemctl cat bitget-dashboard.service >/dev/null 2>&1; then
    systemctl stop bitget-dashboard.service
fi
ln -sfn "$release" /opt/bitget/current.next
mv -Tf /opt/bitget/current.next /opt/bitget/current
for unit in bitget-bot.service bitget-dashboard.service bitget-health.service bitget-health.timer bitget-backup.service bitget-backup.timer; do
    install -m 0644 "$release/infra/gcp/$unit" "/etc/systemd/system/$unit"
done
install -m 0750 -o root -g bitget "$release/infra/gcp/dashboard_control.sh" /usr/local/sbin/bitget-dashboard-control
printf '%s
' 'bitget ALL=(root) NOPASSWD: /usr/local/sbin/bitget-dashboard-control start, /usr/local/sbin/bitget-dashboard-control stop, /usr/local/sbin/bitget-dashboard-control restart, /usr/local/sbin/bitget-dashboard-control verify' > /etc/sudoers.d/bitget-dashboard-control
chmod 0440 /etc/sudoers.d/bitget-dashboard-control
visudo -cf /etc/sudoers.d/bitget-dashboard-control
install -d -m 0755 /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\nMaxRetentionSec=14day\n' > /etc/systemd/journald.conf.d/bitget.conf
systemctl restart systemd-journald
systemctl daemon-reload
systemctl enable --now bitget-bot.service bitget-dashboard.service bitget-health.timer bitget-backup.timer
sleep 5
systemctl is-active --quiet bitget-bot.service
echo "Paper worker installed. Verify heartbeat, status, and backup before declaring deployment healthy."
