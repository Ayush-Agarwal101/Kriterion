#!/bin/sh
# Kriterion Firecracker guest init — runs as PID 1 inside the VM.
#
# Drive layout (set by kriterion/firecracker_runner.py):
#   /dev/vda  — runner rootfs (this filesystem, is_root_device=True, registered first)
#   /dev/vdb  — payload ext4 (registered second, read-write, contains payload.py)
#
# On exit the kernel will panic (panic=1 in boot_args) and Firecracker will
# detect the halt.  The host-side runner polls debugfs for result.json on
# /dev/vdb and does not wait for the Firecracker process to exit.
#
# NEVER add network interfaces here — the manifest specifies network=forbidden.

set -e

# ---- essential mounts -------------------------------------------------------
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts
mount -t devpts devpts /dev/pts 2>/dev/null || true

# Enable SysRq so we can request a clean power-off after writing result.json
echo 1 > /proc/sys/kernel/sysrq 2>/dev/null || true

# ---- wait for the payload block device --------------------------------------
# Firecracker virtio-blk devices appear as /dev/vdX in registration order.
# runner_rootfs = /dev/vda  (registered first, is_root_device)
# payload       = /dev/vdb  (registered second)

PAYLOAD_DEV=/dev/vdb
TRIES=30
while [ "${TRIES}" -gt 0 ] && [ ! -b "${PAYLOAD_DEV}" ]; do
    sleep 1
    TRIES=$((TRIES - 1))
done

if [ ! -b "${PAYLOAD_DEV}" ]; then
    # Emit on ttyS0 (captured by Firecracker stdout/stderr logging)
    echo "kriterion-guest: ERROR payload device ${PAYLOAD_DEV} did not appear" >&2
    echo o > /proc/sysrq-trigger
    sleep 10
    exit 1
fi

# ---- mount the payload ext4 drive -------------------------------------------
PAYLOAD_MOUNT=/mnt/payload
mkdir -p "${PAYLOAD_MOUNT}"
mount "${PAYLOAD_DEV}" "${PAYLOAD_MOUNT}"

# ---- run the Python payload runner ------------------------------------------
# payload_runner.py is installed at /sbin/payload_runner.py by build_rootfs.sh.
# It runs payload.py and writes result.json, both on the mounted payload drive.
python3 /sbin/payload_runner.py "${PAYLOAD_MOUNT}"
RUNNER_EXIT=$?

# ---- flush and unmount ------------------------------------------------------
sync
umount "${PAYLOAD_MOUNT}" 2>/dev/null || true

# ---- power off the guest ----------------------------------------------------
# The host-side runner polls for result.json via debugfs; it does NOT wait for
# the Firecracker process.  A clean power-off here prevents the 30 s wall-clock
# timeout from being consumed unnecessarily.
echo o > /proc/sysrq-trigger

# Fallback if SysRq poweroff is not honoured (should not happen with 5.10 kernel)
sleep 10
exit "${RUNNER_EXIT}"