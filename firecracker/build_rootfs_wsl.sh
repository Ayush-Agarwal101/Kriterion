#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ASSETS="$SCRIPT_DIR/assets"

ALPINE_VERSION="3.19.9"
ALPINE_URL="https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-minirootfs-${ALPINE_VERSION}-x86_64.tar.gz"

# IMPORTANT:
# Build staging lives on WSL's Linux filesystem, NOT /mnt/d,
# so Unix permissions, symlinks, ownership, etc. are preserved.
WORK="/tmp/kriterion-firecracker-rootfs"
ROOTFS="$ASSETS/rootfs.ext4"
TARBALL="$WORK/alpine-minirootfs.tar.gz"
STAGING="$WORK/rootfs"

echo "==> Preparing workspace..."
rm -rf "$WORK"
mkdir -p "$STAGING"
mkdir -p "$ASSETS"

echo "==> Downloading Alpine ${ALPINE_VERSION} minirootfs..."
curl -fL "$ALPINE_URL" -o "$TARBALL"

echo "==> Extracting Alpine rootfs..."
tar -xzf "$TARBALL" -C "$STAGING"

echo "==> Installing Python3 into rootfs..."

# Alpine minirootfs has apk but isn't fully configured as a running system.
# Prepare DNS and apk repositories.
cp /etc/resolv.conf "$STAGING/etc/resolv.conf"

cat > "$STAGING/etc/apk/repositories" <<EOF
https://dl-cdn.alpinelinux.org/alpine/v3.19/main
https://dl-cdn.alpinelinux.org/alpine/v3.19/community
EOF

# Install packages inside the rootfs without requiring root/mounts.
# proot provides the chroot-like environment in userspace.
proot -0 -R "$STAGING" /sbin/apk add --no-cache python3

echo "==> Installing Kriterion guest init..."
cp "$SCRIPT_DIR/runner/guest_init.sh" "$STAGING/sbin/kriterion-init"
chmod 755 "$STAGING/sbin/kriterion-init"

# Alpine's /sbin/init is a symlink. Replace it cleanly.
rm -f "$STAGING/sbin/init"
ln -s /sbin/kriterion-init "$STAGING/sbin/init"

echo "==> Installing Kriterion payload runner..."
cp "$SCRIPT_DIR/runner/payload_runner.py" "$STAGING/sbin/payload_runner.py"
chmod 755 "$STAGING/sbin/payload_runner.py"

echo "==> Creating required mount points..."
mkdir -p \
    "$STAGING/proc" \
    "$STAGING/sys" \
    "$STAGING/dev" \
    "$STAGING/dev/pts" \
    "$STAGING/mnt/payload" \
    "$STAGING/run"

echo "==> Verifying guest files..."

test -x "$STAGING/sbin/kriterion-init"
test -L "$STAGING/sbin/init"
test -x "$STAGING/sbin/payload_runner.py"
test -x "$STAGING/usr/bin/python3"

echo "    OK: /sbin/init"
echo "    OK: /sbin/payload_runner.py"
echo "    OK: /usr/bin/python3"

echo "==> Removing old rootfs image..."
rm -f "$ROOTFS"

echo "==> Creating 300 MiB ext4 rootfs..."
truncate -s 300M "$ROOTFS"

mkfs.ext4 -F -L kriterion-rootfs -d "$STAGING" "$ROOTFS"

echo "==> Verifying ext4 image..."

debugfs -R "stat /sbin/init" "$ROOTFS" 2>/dev/null | grep -q "File type: symbolic link"
debugfs -R "stat /sbin/payload_runner.py" "$ROOTFS" >/dev/null 2>&1
debugfs -R "stat /usr/bin/python3" "$ROOTFS" >/dev/null 2>&1

echo ""
echo "============================================"
echo " Firecracker rootfs created successfully"
echo "============================================"
echo ""
echo "Rootfs:"
echo "  $ROOTFS"
echo ""
ls -lh "$ROOTFS"
echo ""
echo "Kernel:"
ls -lh "$ASSETS/vmlinux"
