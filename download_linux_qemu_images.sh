#!/usr/bin/env bash
# Download Linux QEMU images for GNS3.
#
# Sources:
#   - md5/size from ../gns3-registry/appliances/*.gns3a
#   - sha256 for corrected (stale-registry) entries from vendor checksum files:
#       Kali : https://cdimage.kali.org/kali-2026.3/SHA256SUMS
#       Rocky: .../Rocky-10-GenericCloud-Base-10.2-20260525.0.x86_64.qcow2.CHECKSUM
#
# Features: resume (.part), retries, checksum verify, archive extraction.
#
# Usage:
#   ./download_linux_qemu_images.sh [--dest DIR] [--only PATTERN]
#                                   [--no-extract] [--keep-archives] [--dry-run]
#
set -uo pipefail

DEST="${GNS3_QEMU_IMAGES:-/home/yueguobin/GNS3/images/QEMU}"
EXTRACT=1
KEEP_ARCHIVES=0
DRY=0
ONLY=""

usage() {
    cat <<EOF
Usage: $0 [options]
  --dest DIR        Image directory (default: $DEST)
  --only PATTERN    Only entries whose name matches PATTERN (case-insensitive grep)
  --no-extract      Keep archives as downloaded (.7z/.gz/.xz not unpacked)
  --keep-archives   Keep archives after successful extraction
  --dry-run         Print plan only, no download
  -h, --help        This help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dest)          DEST="$2"; shift 2 ;;
        --only)          ONLY="$2"; shift 2 ;;
        --no-extract)    EXTRACT=0; shift ;;
        --keep-archives) KEEP_ARCHIVES=1; shift ;;
        --dry-run)       DRY=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
    esac
done

mkdir -p "$DEST" || { echo "Cannot create $DEST" >&2; exit 1; }

# name|url|archive|final|algo|checksum|size_bytes|checksum_target(archive|final)
ENTRIES=(
"AlmaLinux 10|https://vault.almalinux.org/10.0/cloud/x86_64/images/AlmaLinux-10-GenericCloud-10.0-20250528.0.x86_64.qcow2|AlmaLinux-10-GenericCloud-10.0-20250528.0.x86_64.qcow2|AlmaLinux-10-GenericCloud-10.0-20250528.0.x86_64.qcow2|md5|e5099e33f16014b6cc851482d865720d|460062720|final"
"Alpine Cloud 3.21|https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/cloud/generic_alpine-3.21.2-x86_64-bios-cloudinit-r0.qcow2|generic_alpine-3.21.2-x86_64-bios-cloudinit-r0.qcow2|generic_alpine-3.21.2-x86_64-bios-cloudinit-r0.qcow2|md5|b40825dff2867e0ffaffbc4c87674462|189726720|final"
"Alpine Virt 3.18.4|https://sourceforge.net/projects/gns-3/files/Qemu%20Appliances/alpine-virt-3.18.4.qcow2/download|alpine-virt-3.18.4.qcow2|alpine-virt-3.18.4.qcow2|md5|99d393c16c870e12c4215aadd82ca998|51066880|final"
"Debian 12.6|https://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/debian-12.6.qcow2|debian-12.6.qcow2|debian-12.6.qcow2|md5|04753ba14295c6414d49bffe27b676ae|280907776|final"
"Fedora Cloud 44|https://fedora.mirrorservice.org/fedora/linux/releases/44/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2|Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2|Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2|md5|49784011eb752291bfead24d3be8163f|583729152|final"
"FRR 8.2.2|http://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/frr-8.2.2.qcow2|frr-8.2.2.qcow2|frr-8.2.2.qcow2|md5|ea0ace3cd791d49fa4661660238eb48d|58064896|final"
"NixOS 24.11|http://ob7.us/nixos-24-11.qcow2|nixos-24-11.qcow2|nixos-24-11.qcow2|md5|2459f05136836dd430402d75cba0f205|1749483520|final"
"Oracle Linux 10.1|https://yum.oracle.com/templates/OracleLinux/OL10/u1/x86_64/OL10U1_x86_64-kvm-b270.qcow2|OL10U1_x86_64-kvm-b270.qcow2|OL10U1_x86_64-kvm-b270.qcow2|md5|c3ed48965110e0cbbd75734d3c23a2ce|1044119552|final"
"Ubuntu 24.10 Cloud|https://cloud-images.ubuntu.com/releases/oracular/release-20241009/ubuntu-24.10-server-cloudimg-amd64.img|ubuntu-24.10-server-cloudimg-amd64.img|ubuntu-24.10-server-cloudimg-amd64.img|md5|f2960f8743efedd0a4968bfcd9451782|627360256|final"
"Tiny Core 17|http://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/linux-tinycore-17.0.qcow2|linux-tinycore-17.0.qcow2|linux-tinycore-17.0.qcow2|md5|6434d4da25dd0277cc90b000bb4ac8f1|35061760|final"
"Micro Core 6.4|http://downloads.sourceforge.net/project/gns-3/Qemu%20Appliances/linux-microcore-6.4.img|linux-microcore-6.4.img|linux-microcore-6.4.img|md5|877419f975c4891c019947ceead5c696|16580608|final"
"Cumulus VX 5.4|https://d2cd9e7ca6hntp.cloudfront.net/public/CumulusLinux-5.4.0/cumulus-linux-5.4.0-vx-amd64-qemu.qcow2|cumulus-linux-5.4.0-vx-amd64-qemu.qcow2|cumulus-linux-5.4.0-vx-amd64-qemu.qcow2|md5|b36d781a168e381e0db5b1d85a2f970d|6254493696|final"
"OpenWrt 25.12|https://downloads.openwrt.org/releases/25.12.0/targets/x86/64/openwrt-25.12.0-x86-64-generic-ext4-combined.img.gz|openwrt-25.12.0-x86-64-generic-ext4-combined.img.gz|openwrt-25.12.0-x86-64-generic-ext4-combined.img|md5|8c0e01307fc47c1f862a5d0c9a51c2c5|126353408|final"
"CentOS Stream 10|https://cloud.centos.org/centos/10-stream/x86_64/images/CentOS-Stream-GenericCloud-10-20260504.0.x86_64.qcow2|CentOS-Stream-GenericCloud-10-20260504.0.x86_64.qcow2|CentOS-Stream-GenericCloud-10-20260504.0.x86_64.qcow2|md5|932b0bcc7e5c7404f91432979dc95314|2173501440|final"
"Kali 2026.3 (registry 2025.4 stale)|https://cdimage.kali.org/kali-2026.3/kali-linux-2026.3-qemu-amd64.7z|kali-linux-2026.3-qemu-amd64.7z|kali-linux-2026.3-qemu-amd64.qcow2|sha256|6a73c8496064cc5e6b26a82084b7a7e6d0aea92047e555af34a9208fd430bae8|3900428588|archive"
"RockyLinux 10.2 (registry 10.1 stale)|https://download.rockylinux.org/pub/rocky/10/images/x86_64/Rocky-10-GenericCloud-Base-10.2-20260525.0.x86_64.qcow2|Rocky-10-GenericCloud-Base-10.2-20260525.0.x86_64.qcow2|Rocky-10-GenericCloud-Base-10.2-20260525.0.x86_64.qcow2|sha256|9fc9e9ff16888bb68ac39b0392e25c9c92684d50c85f1cce6ab549363bbc4b48|544997376|final"
)

human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "$1 B"; }

verify_sum() { # file algo sum
    local f="$1" algo="$2" sum="$3"
    [ -z "$sum" ] && return 0
    case "$algo" in
        md5)    printf '%s  %s\n' "$sum" "$f" | md5sum -c --status - ;;
        sha256) printf '%s  %s\n' "$sum" "$f" | sha256sum -c --status - ;;
        *)      return 2 ;;
    esac
}

fetch() { # url outfile
    local url="$1" out="$2" resume=()
    [ -f "$out" ] && resume=(-C -)
    curl -fL --retry 5 --retry-delay 5 --retry-all-errors \
         --connect-timeout 20 --progress-bar ${resume[@]+"${resume[@]}"} -o "$out" "$url"
}

extract_archive() { # archive_path final_name
    local arc="$1" final_name="$2"
    case "$arc" in
        *.7z)
            command -v 7z >/dev/null || { echo "ERROR: 7z not installed"; return 1; }
            7z x -y -o"$DEST" "$arc" >/dev/null || return 1 ;;
        *.gz)  gunzip -c "$arc" > "$DEST/$final_name" || return 1 ;;
        *.xz)  xz -dc  "$arc" > "$DEST/$final_name" || return 1 ;;
        *.bz2) bzip2 -dc "$arc" > "$DEST/$final_name" || return 1 ;;
        *) return 1 ;;
    esac
}

ok=0; skipped=0; failed=0
failed_names=()

for entry in "${ENTRIES[@]}"; do
    IFS='|' read -r name url archive final algo sum size ctarget <<< "$entry"
    [ -n "$ONLY" ] && ! grep -qi -- "$ONLY" <<< "$name" && continue

    arc_path="$DEST/$archive"
    final_path="$DEST/$final"

    echo
    echo "=== $name"
    echo "    file : $final ($(human "$size"))"
    echo "    url  : $url"

    if [ "$DRY" -eq 1 ]; then
        if [ "$archive" != "$final" ] && [ "$EXTRACT" -eq 1 ]; then
            echo "    plan : download -> verify $algo -> extract"
        else
            echo "    plan : download -> verify $algo"
        fi
        continue
    fi

    # Already-usable final file?
    if [ "$archive" != "$final" ] && [ -f "$final_path" ]; then
        if [ "$ctarget" = "final" ] && verify_sum "$final_path" "$algo" "$sum"; then
            echo "    SKIP : final exists, $algo OK"
            skipped=$((skipped+1)); continue
        elif [ ! -f "$arc_path" ]; then
            echo "    SKIP : extracted file exists (archive gone, checksum not re-verified)"
            skipped=$((skipped+1)); continue
        fi
    fi

    # Archive present: verify, extract if needed.
    if [ -f "$arc_path" ]; then
        if verify_sum "$arc_path" "$algo" "$sum"; then
            echo "    OK   : existing archive checksum matches"
        else
            echo "    WARN : existing archive checksum mismatch -> re-download"
            rm -f "$arc_path"
        fi
    fi

    if [ ! -f "$arc_path" ]; then
        echo "    GET  : downloading..."
        part="$arc_path.part"
        if ! fetch "$url" "$part"; then
            echo "    FAIL : download failed (kept $part for resume)"
            failed=$((failed+1)); failed_names+=("$name"); continue
        fi
        mv -f "$part" "$arc_path"
        if ! verify_sum "$arc_path" "$algo" "$sum"; then
            echo "    FAIL : checksum mismatch after download"
            rm -f "$arc_path"
            failed=$((failed+1)); failed_names+=("$name"); continue
        fi
        echo "    OK   : download + $algo verified"
    fi

    # Same name = nothing to extract.
    if [ "$archive" = "$final" ]; then
        ok=$((ok+1)); continue
    fi

    if [ "$EXTRACT" -eq 0 ]; then
        echo "    OK   : archive kept (--no-extract)"
        ok=$((ok+1)); continue
    fi

    echo "    UNPACK: $archive -> $final"
    if ! extract_archive "$arc_path" "$final"; then
        echo "    FAIL : extraction failed"
        failed=$((failed+1)); failed_names+=("$name"); continue
    fi
    if [ ! -f "$final_path" ]; then
        echo "    FAIL : expected extracted file not found: $final"
        failed=$((failed+1)); failed_names+=("$name"); continue
    fi
    if [ "$ctarget" = "final" ] && ! verify_sum "$final_path" "$algo" "$sum"; then
        echo "    FAIL : extracted file checksum mismatch"
        failed=$((failed+1)); failed_names+=("$name"); continue
    fi
    if [ "$KEEP_ARCHIVES" -eq 0 ]; then rm -f "$arc_path"; fi
    echo "    OK   : extracted${KEEP_ARCHIVES:+}"
    ok=$((ok+1))
done

echo
echo "================ SUMMARY ================"
echo "dest    : $DEST"
echo "ok      : $ok"
echo "skipped : $skipped"
echo "failed  : $failed"
if [ "$failed" -gt 0 ]; then
    printf 'failed  : %s\n' "${failed_names[*]}"
    exit 1
fi
