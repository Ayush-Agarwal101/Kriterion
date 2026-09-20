#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSETS="$ROOT/assets"
mkdir -p "$ASSETS"

S3="https://s3.amazonaws.com/spec.ccfc.min"
ARCH="$(uname -m)"

if [[ "$ARCH" != "x86_64" ]]; then
    echo "ERROR: This script currently supports x86_64 only."
    exit 1
fi

echo "==> Discovering latest Firecracker CI kernel..."

PREFIX="$(
    curl -fsSL "$S3?list-type=2&prefix=firecracker-ci/&delimiter=/" |
    grep -oP '(?<=<Prefix>)firecracker-ci/[0-9]{8}-[^/]+/(?=</Prefix>)' |
    sort |
    tail -1
)"

if [[ -z "$PREFIX" ]]; then
    echo "ERROR: Could not discover Firecracker CI artifact."
    exit 1
fi

KERNEL_KEY="$(
    curl -fsSL "$S3?list-type=2&prefix=${PREFIX}${ARCH}/vmlinux-" |
    grep -oP "(?<=<Key>)(${PREFIX}${ARCH}/vmlinux-[0-9]+\.[0-9]+\.[0-9]{1,3})(?=</Key>)" |
    sort -V |
    tail -1
)"

if [[ -z "$KERNEL_KEY" ]]; then
    echo "ERROR: Could not discover a Firecracker CI kernel."
    exit 1
fi

URL="$S3/$KERNEL_KEY"
DEST="$ASSETS/vmlinux"

echo "    URL: $URL"
echo "    Destination: $DEST"

curl -fL --retry 3 "$URL" -o "$DEST"

if ! file "$DEST" | grep -q ELF; then
    echo "ERROR: Downloaded file is not an ELF kernel."
    rm -f "$DEST"
    exit 1
fi

SHA256="$(sha256sum "$DEST" | awk '{print $1}')"

echo
echo "Kernel downloaded successfully."
echo "SHA-256: $SHA256"
echo "Path: $DEST"