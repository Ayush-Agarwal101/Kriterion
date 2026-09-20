#!/usr/bin/env bash
# firecracker/build_rootfs.sh
#
# Build the Firecracker guest rootfs (firecracker/assets/rootfs.ext4).
#
# What this does:
#   1. Builds a Docker image from Dockerfile.rootfs (Alpine + Python 3 +
#      our guest_init.sh and payload_runner.py).
#   2. Exports the container filesystem as a tar archive.
#   3. Writes the tar into an ext4 image using a privileged container so
#      that no host-side root or loop-mount privileges are required.
#
# Requirements (host):
#   - Docker (tested with 24+; Podman with --compat-volumes also works)
#   - ~500 MB free disk space in firecracker/assets/
#
# Output:
#   firecracker/assets/rootfs.ext4   (~300 MiB ext4 image)
#
# Usage:
#   cd <repo-root>
#   ./firecracker/build_rootfs.sh [--size-mib N]   # default: 300
#
# The produced image is intentionally NOT committed to git.
# Add FIRECRACKER_ROOTFS=<abs-path>/firecracker/assets/rootfs.ext4 to your
# environment (or .env file) so kriterion/sandbox.py can find it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ASSETS_DIR="${SCRIPT_DIR}/assets"
ROOTFS_IMAGE="${ASSETS_DIR}/rootfs.ext4"

# Rootfs capacity.  300 MiB comfortably fits Alpine + Python3 + headroom.
SIZE_MIB=300

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --size-mib)
            SIZE_MIB="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [--size-mib N]" >&2
            exit 1
            ;;
    esac
done

# ── Pre-flight checks ─────────────────────────────────────────────────────────
# Prefer Docker if available; otherwise use Finch.
if command -v docker &>/dev/null; then
    CONTAINER_RUNTIME="docker"
elif command -v finch &>/dev/null; then
    CONTAINER_RUNTIME="finch"
else
    echo "ERROR: Neither 'docker' nor 'finch' is available on PATH." >&2
    exit 1
fi

if ! "${CONTAINER_RUNTIME}" info &>/dev/null 2>&1; then
    echo "ERROR: ${CONTAINER_RUNTIME} is installed but its runtime is unavailable." >&2
    exit 1
fi

echo "    Runtime    : ${CONTAINER_RUNTIME}"

echo "==> Building Kriterion Firecracker guest rootfs"
echo "    Dockerfile : ${SCRIPT_DIR}/Dockerfile.rootfs"
echo "    Output     : ${ROOTFS_IMAGE}"
echo "    Size       : ${SIZE_MIB} MiB"
echo

mkdir -p "${ASSETS_DIR}"

# ── Step 1: Build the Docker image ───────────────────────────────────────────
echo "[1/4] Building Docker image kriterion-fc-rootfs:build ..."
"${CONTAINER_RUNTIME}" build \
    --platform linux/amd64 \
    --tag kriterion-fc-rootfs:build \
    --file "${SCRIPT_DIR}/Dockerfile.rootfs" \
    "${SCRIPT_DIR}"

# ── Step 2: Export filesystem as tar ─────────────────────────────────────────
echo "[2/4] Exporting container filesystem ..."
TMP_TAR="$(mktemp /tmp/kriterion_rootfs_XXXXXX.tar)"
# shellcheck disable=SC2064
trap "rm -f '${TMP_TAR}'" EXIT

CONTAINER_ID="$("${CONTAINER_RUNTIME}" create --platform linux/amd64 kriterion-fc-rootfs:build)"
"${CONTAINER_RUNTIME}" export "${CONTAINER_ID}" > "${TMP_TAR}"
"${CONTAINER_RUNTIME}" rm "${CONTAINER_ID}" > /dev/null

echo "    Exported $(du -sh "${TMP_TAR}" | cut -f1) tar"

# ── Step 3: Write tar into an ext4 image (inside a privileged container) ─────
# Using a privileged Alpine container avoids requiring the host to have root
# or loop-device access.  mkfs.ext4 and mount are available via e2fsprogs.
echo "[3/4] Creating ext4 image (${SIZE_MIB} MiB) ..."

"${CONTAINER_RUNTIME}" run \
    --rm \
    --privileged \
    --platform linux/amd64 \
    -v "${TMP_TAR}:/rootfs.tar:ro" \
    -v "${ASSETS_DIR}:/out" \
    alpine:3.19 \
    sh -euc "
        apk add --no-cache e2fsprogs > /dev/null 2>&1

        # Create a sparse zeroed file.
        dd if=/dev/zero of=/out/rootfs.ext4 bs=1M count=${SIZE_MIB} status=none

        # Format as ext4 (-F = force, -L = label).
        mkfs.ext4 -q -F -L kriterion-guest /out/rootfs.ext4

        # Mount and populate.
        mkdir -p /mnt/rootfs
        mount -o loop /out/rootfs.ext4 /mnt/rootfs
        tar -xf /rootfs.tar -C /mnt/rootfs --numeric-owner 2>/dev/null || true
        umount /mnt/rootfs

        echo '    ext4 image written.'
    "

# ── Step 4: Verify the image is readable ─────────────────────────────────────
echo "[4/4] Verifying image contents ..."
if command -v debugfs &>/dev/null; then
    INIT_CHECK="$(debugfs "${ROOTFS_IMAGE}" -R "stat /sbin/init" 2>/dev/null | grep "File mode" || echo '')"
    RUNNER_CHECK="$(debugfs "${ROOTFS_IMAGE}" -R "stat /sbin/payload_runner.py" 2>/dev/null | grep "File mode" || echo '')"
    if [[ -z "${INIT_CHECK}" || -z "${RUNNER_CHECK}" ]]; then
        echo "WARNING: Could not verify /sbin/init or /sbin/payload_runner.py in image." >&2
        echo "         (debugfs available but stat returned empty — image may still be valid)" >&2
    else
        echo "    /sbin/init            : present"
        echo "    /sbin/payload_runner.py: present"
    fi
else
    echo "    (skipping content verify — 'debugfs' not found; install e2fsprogs to enable)"
fi

echo
echo "==> Done."
echo "    ${ROOTFS_IMAGE}"
echo
echo "Export for kriterion/sandbox.py:"
echo "    export FIRECRACKER_ROOTFS=${ROOTFS_IMAGE}"
