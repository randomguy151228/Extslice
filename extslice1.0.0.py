#!/usr/bin/env python3
"""
extslice.py - Extract ext2/3/4 partitions and dump full directory trees using debugfs.
"""

import argparse
import os
import struct
import subprocess
import sys

EXT_SUPERBLOCK_MAGIC = b"\x53\xef"
SUPERBLOCK_OFFSET = 1024


def parse_superblock(data: bytes):
    if len(data) < 1024:
        return None

    if data[0x38:0x3A] != EXT_SUPERBLOCK_MAGIC:
        return None

    try:
        blocks_count = struct.unpack("<I", data[0x04:0x08])[0]
        log_block_size = struct.unpack("<I", data[0x18:0x1C])[0]
        block_size = 1024 << log_block_size

        if block_size < 1024 or block_size > 65536 or blocks_count == 0:
            return None

        return {
            "block_size": block_size,
            "blocks_count": blocks_count,
            "total_size": blocks_count * block_size,
        }
    except Exception:
        return None


def dump_with_debugfs(raw_image_path: str, target_dir: str):
    """Uses native Linux debugfs to extract all directories and files reliably."""
    os.makedirs(target_dir, exist_ok=True)
    print(f"    [*] Extracting directory structure via debugfs to '{target_dir}'...")

    cmd = ["debugfs", "-R", f"rdump / {target_dir}", raw_image_path]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.returncode == 0:
        print(f"    [+] Successfully extracted folder structure!")
    else:
        err = result.stderr.decode(errors="ignore").strip()
        print(f"    [!] debugfs reported errors/warnings:\n{err[:300]}")


def scan_and_extract(firmware_path: str, output_dir: str, align: int = 512):
    if not os.path.exists(firmware_path):
        print(f"Error: File '{firmware_path}' not found.", file=sys.stderr)
        sys.exit(1)

    file_size = os.path.getsize(firmware_path)
    print(f"[*] Scanning '{firmware_path}' ({file_size} bytes)...")

    found_count = 0

    with open(firmware_path, "rb") as f:
        offset = 0
        while offset < file_size - SUPERBLOCK_OFFSET:
            f.seek(offset + SUPERBLOCK_OFFSET)
            sb_candidate = f.read(2048)

            metadata = parse_superblock(sb_candidate)
            if metadata:
                partition_start = offset
                total_size = metadata["total_size"]

                print(f"\n[+] Found ext filesystem at offset 0x{partition_start:X}")
                print(
                    f"    - Block Size: {metadata['block_size']} | Total Size: {total_size} bytes"
                )

                if partition_start + total_size > file_size:
                    print("    [!] Partition boundary exceeds file size. Truncating to file end.")
                    total_size = file_size - partition_start

                temp_raw = f"/tmp/part_0x{partition_start:X}.raw"
                dump_folder = os.path.join(output_dir, f"ext_dir_0x{partition_start:X}")

                # Slice out partition image to temporary space
                f.seek(partition_start)
                bytes_copied = 0
                chunk_size = 1024 * 1024

                with open(temp_raw, "wb") as out_f:
                    while bytes_copied < total_size:
                        to_read = min(chunk_size, total_size - bytes_copied)
                        chunk = f.read(to_read)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        bytes_copied += len(chunk)

                # Dump directory contents using debugfs
                dump_with_debugfs(temp_raw, dump_folder)

                # Clean up temp file
                if os.path.exists(temp_raw):
                    os.remove(temp_raw)

                found_count += 1
                offset += total_size
                continue

            offset += align

    if found_count == 0:
        print("[-] No ext filesystem partitions detected.")
    else:
        print(f"\n[+] Done! All files and folders extracted under '{output_dir}'.")


def main():
    parser = argparse.ArgumentParser(
        description="extslice - Scan firmware and extract directory structures."
    )
    parser.add_argument("firmware", help="Path to input firmware binary")
    parser.add_argument("-o", "--output", default="extracted_dirs")
    parser.add_argument("-a", "--align", type=int, default=512)

    args = parser.parse_args()
    scan_and_extract(args.firmware, args.output, args.align)


if __name__ == "__main__":
    main()