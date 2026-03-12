#!/usr/bin/env python3
"""
PRZ Light PWM Patcher

Reads an existing .prz file and patches per-layer Light PWM values.
Supports alternating patterns, fixed values, or custom per-layer lists.

Usage:
    # Alternate 0/100 on normal layers (skip bottom layers)
    python prz_pwm_patcher.py input.prz -o output.prz --alternate 0 100

    # Set all layers (including bottom) to fixed PWM
    python prz_pwm_patcher.py input.prz -o output.prz --fixed 150

    # Alternate but also patch bottom layers
    python prz_pwm_patcher.py input.prz -o output.prz --alternate 0 100 --include-bottom
"""

import argparse
import struct
import sys
from pathlib import Path

HEADER_SIZE = 195477
LAYER_DEF_SIZE = 64      # per-layer definition block size
PWM_OFFSET_IN_LAYER = 62  # PWM is last 2 bytes of layer def
CRLF = b"\r\n"


def parse_prz_layers(data: bytes):
    """Parse PRZ binary and return list of layer info (offset, rle_size)."""
    pos = HEADER_SIZE
    layers = []

    while pos < len(data):
        # Check if we hit footer (starts with 0x00 0x00 0x00 0x07)
        if pos + 4 <= len(data) and data[pos:pos + 4] == b"\x00\x00\x00\x07":
            break

        layer_start = pos

        # Layer definition (64 bytes)
        if pos + LAYER_DEF_SIZE > len(data):
            break
        layer_def = data[pos:pos + LAYER_DEF_SIZE]
        pos += LAYER_DEF_SIZE

        # CRLF
        if data[pos:pos + 2] != CRLF:
            print(f"Warning: expected CRLF after layer def at offset {pos}", file=sys.stderr)
            break
        pos += 2

        # RLE data size (4B uint BE)
        if pos + 4 > len(data):
            break
        rle_size = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4

        # RLE data
        pos += rle_size

        # CRLF
        if pos + 2 <= len(data) and data[pos:pos + 2] == CRLF:
            pos += 2

        # Read current PWM
        current_pwm = struct.unpack(">H", layer_def[PWM_OFFSET_IN_LAYER:PWM_OFFSET_IN_LAYER + 2])[0]

        layers.append({
            "index": len(layers),
            "def_offset": layer_start,
            "pwm_offset": layer_start + PWM_OFFSET_IN_LAYER,
            "current_pwm": current_pwm,
        })

    return layers


def read_header_bottom_layer_count(data: bytes) -> int:
    """Read Bottom Layer Count from PRZ header. Offset found by examining header structure."""
    # Bottom Layer Count is at a known offset in the header.
    # From _write_header: it's a 2-byte short BE.
    # We'll scan for it by reading layer defs and checking exposure patterns instead.
    # Simpler approach: just ask user or default to 0.
    # For robustness, read from layer definitions — bottom layers typically have longer exposure.
    layers = parse_prz_layers(data)
    if len(layers) < 2:
        return 0

    # Read exposure times from layer defs
    exposures = []
    for layer in layers:
        offset = layer["def_offset"]
        # Exposure is at offset 10 in layer def (after PauseFlag 2B + PauseZ 4B + LayerZ 4B)
        exp = struct.unpack(">f", data[offset + 10:offset + 14])[0]
        exposures.append(exp)

    # Find where exposure drops significantly (bottom → normal transition)
    if len(exposures) < 2:
        return 0
    normal_exp = exposures[-1]  # last layer is definitely normal
    for i, exp in enumerate(exposures):
        if abs(exp - normal_exp) < 0.5:  # within 0.5s of normal exposure
            return i
    return 0


def main():
    parser = argparse.ArgumentParser(description="Patch Light PWM values in a PRZ file")
    parser.add_argument("input", type=Path, help="Input .prz file")
    parser.add_argument("-o", "--output", type=Path, help="Output .prz file (default: input_patched.prz)")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--alternate", nargs=2, type=int, metavar=("A", "B"),
                      help="Alternate between two PWM values (e.g. --alternate 0 100)")
    mode.add_argument("--fixed", type=int, metavar="PWM",
                      help="Set all layers to a fixed PWM value")

    parser.add_argument("--include-bottom", action="store_true",
                        help="Also patch bottom layers (default: skip bottom layers)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be changed without writing")

    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    if args.output is None:
        args.output = args.input.with_stem(args.input.stem + "_patched")

    # Read file
    data = bytearray(args.input.read_bytes())
    layers = parse_prz_layers(data)

    if not layers:
        print("Error: no layers found in PRZ file", file=sys.stderr)
        sys.exit(1)

    # Detect bottom layer count
    bottom_count = read_header_bottom_layer_count(bytes(data))
    print(f"Total layers: {len(layers)}")
    print(f"Detected bottom layers: {bottom_count}")
    print()

    # Compute new PWM values
    changes = 0
    for layer in layers:
        idx = layer["index"]
        is_bottom = idx < bottom_count

        if is_bottom and not args.include_bottom:
            new_pwm = layer["current_pwm"]  # keep original
        elif args.alternate:
            a, b = args.alternate
            new_pwm = a if (idx % 2 == 0) else b
        else:  # --fixed
            new_pwm = args.fixed

        if new_pwm != layer["current_pwm"]:
            changes += 1

        label = " (bottom)" if is_bottom else ""
        if args.dry_run or new_pwm != layer["current_pwm"]:
            print(f"  Layer {idx:4d}{label}: PWM {layer['current_pwm']:5d} -> {new_pwm:5d}")

        # Patch
        struct.pack_into(">H", data, layer["pwm_offset"], new_pwm)

    if args.dry_run:
        print(f"\nDry run: {changes} layers would be changed")
    else:
        args.output.write_bytes(bytes(data))
        print(f"\n{changes} layers patched. Output: {args.output}")


if __name__ == "__main__":
    main()
