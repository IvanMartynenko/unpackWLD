#!/usr/bin/env python3
# nmf_tool.py
# One-file CLI: unpack .nmf → .json, repack .nmf → .nmf, or pack .json → .nmf

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# === import project libs ===
THIS_DIR = Path(__file__).resolve().parent
BIN_LIB = (THIS_DIR / "../python_lib/binary").resolve()
THREED_LIB = (THIS_DIR / "../python_lib/3d").resolve()

for lib in (BIN_LIB, THREED_LIB):
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))

# --- core NMF IO ---
try:
    from unpack_nmf import Nmf  # expects .unpack(path) -> dict
except Exception as e:
    print(f"Error: cannot import Nmf from {BIN_LIB}: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from pack_nmf import NMFWriter  # expects .pack(model: dict) -> bytes
except Exception as e:
    print(f"Error: cannot import NMFWriter from {BIN_LIB}: {e}", file=sys.stderr)
    sys.exit(1)

# --- optional animation normalizer ---
try:
    from animation_normalizer import AnimationNormalizer  # from ../python_lib/3d/
except Exception:
    AnimationNormalizer = None  # type: ignore

try:
    # expects: PivotBaker(model, rotation_order="XYZ").bake(inplace=False) -> dict or mutates model
    from pivot_baker import PivotBaker  # from ../python_lib/3d/
except Exception:
    PivotBaker = None  # type: ignore

# === helper functions ===
def apply_normalizer(model: Dict[str, Any], verbose: bool = True) -> Dict[str, Any]:
    """Run AnimationNormalizer on model if available. Tries common entrypoints."""
    if AnimationNormalizer is None:
        if verbose:
            print("Warn: AnimationNormalizer not found; skipping normalization.", file=sys.stderr)
        return model

    normalizer = AnimationNormalizer()
    for attr in ("normalize", "process", "run", "__call__"):
        func = getattr(normalizer, attr, None)
        if callable(func):
            if verbose:
                print(f"Info: Applying AnimationNormalizer via '{attr}'...", file=sys.stderr)
            result = func(model)  # type: ignore
            return result

    if verbose:
        print("Warn: AnimationNormalizer has no known callable (normalize/process/run). Skipping.", file=sys.stderr)
    return model

def apply_pivot_baker(
    model: Dict[str, Any],
    rotation_order: str = "XYZ",
    inplace: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Run PivotBaker if available.
    Usage equivalent: PivotBaker(model, rotation_order=...).bake(inplace=...)
    """
    if PivotBaker is None:
        if verbose:
            print("Warn: PivotBaker not found; skipping pivot baking.", file=sys.stderr)
        return model
    if verbose:
        print(f"Info: Baking pivots (rotation_order={rotation_order}, inplace={inplace})...", file=sys.stderr)
    baked = PivotBaker(model, rotation_order=rotation_order).bake(inplace=inplace)
    return baked if not inplace else model


def infer_mode(in_path: Path, out_path: Optional[Path]) -> str:
    """Return: unpack (.nmf→.json), repack (.nmf→.nmf), pack (.json→.nmf)."""
    in_suf = in_path.suffix.lower()
    out_suf = (out_path.suffix.lower() if out_path else None)

    if in_suf == ".nmf":
        if out_suf == ".json":
            return "unpack"
        if out_suf == ".nmf":
            return "repack"
        return "unpack"
    elif in_suf == ".json":
        return "pack"
    else:
        raise ValueError(f"Unsupported input extension '{in_suf}'")


def default_out_path(in_path: Path, mode: str) -> Path:
    if mode == "unpack":
        return in_path.with_suffix(".json")
    elif mode == "repack":
        return in_path.with_name(in_path.stem + ".repacked.nmf")
    elif mode == "pack":
        return in_path.with_suffix(".nmf")
    raise ValueError(f"Unknown mode '{mode}'")


def read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"OK: wrote JSON → {path.resolve()}")


def write_nmf(path: Path, blob: bytes) -> None:
    with path.open("wb") as f:
        f.write(blob)
    print(f"OK: wrote NMF → {path.resolve()}")


# === CLI parser ===
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NMF tool: unpack .nmf to .json, repack .nmf, or pack .json to .nmf"
    )
    p.add_argument("input", help="Path to input file (.nmf or .json)")
    p.add_argument("output", nargs="?", help="Optional output path (.json or .nmf)")
    p.add_argument(
        "--mode",
        choices=["unpack", "repack", "pack"],
        help="Force operation mode (otherwise inferred by file extension)."
    )
    p.add_argument(
        "--normalize",
        action="store_true",
        help="Apply AnimationNormalizer from ../python_lib/3d/ (if available)."
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout instead of writing a file (unpack only)."
    )
    p.add_argument(
        "--bake-pivots",
        action="store_true",
        help="Apply PivotBaker from ../python_lib/3d/ (if available)."
    )
    p.add_argument(
        "--rot-order",
        default="XYZ",
        choices=["XYZ","XZY","YXZ","YZX","ZXY","ZYX"],
        help="Rotation order to use with PivotBaker (default: XYZ)."
    )
    p.add_argument(
        "--bake-inplace",
        action="store_true",
        help="Run PivotBaker with inplace=True (mutates the model). Default is False."
    )
    return p.parse_args()


# === main logic ===
def main() -> None:
    args = parse_args()
    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Error: input file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output).resolve() if args.output else None
    mode = args.mode or infer_mode(in_path, out_path)
    if out_path is None and not args.pretty:
        out_path = default_out_path(in_path, mode)

    if mode == "unpack":
        try:
            model = Nmf().unpack(str(in_path))
        except Exception as e:
            print(f"Error during NMF unpack: {e}", file=sys.stderr)
            sys.exit(1)
        if args.normalize:
            model = apply_normalizer(model)
        if args.bake_pivots:
           model = apply_pivot_baker(model, rotation_order=args.rot_order, inplace=args.bake_inplace)
        if args.pretty:
            print(json.dumps(model, ensure_ascii=False, indent=2))
            return
        write_json(out_path, model)

    elif mode == "repack":
        try:
            model = Nmf().unpack(str(in_path))
        except Exception as e:
            print(f"Error during NMF unpack: {e}", file=sys.stderr)
            sys.exit(1)
        if args.normalize:
            model = apply_normalizer(model)
        if args.bake_pivots:
           model = apply_pivot_baker(model, rotation_order=args.rot_order, inplace=args.bake_inplace)
        try:
            blob = NMFWriter().pack(model)
            if not isinstance(blob, (bytes, bytearray)):
                raise TypeError("NMFWriter.pack() must return bytes/bytearray.")
        except Exception as e:
            print(f"Error during NMF repack: {e}", file=sys.stderr)
            sys.exit(1)
        write_nmf(out_path, bytes(blob))

    elif mode == "pack":
        model = read_json(in_path)
        if args.normalize:
            model = apply_normalizer(model)
        if args.bake_pivots:
           model = apply_pivot_baker(model, rotation_order=args.rot_order, inplace=args.bake_inplace)
        try:
            blob = NMFWriter().pack(model)
            if not isinstance(blob, (bytes, bytearray)):
                raise TypeError("NMFWriter.pack() must return bytes/bytearray.")
        except Exception as e:
            print(f"Error during NMF pack: {e}", file=sys.stderr)
            sys.exit(1)
        write_nmf(out_path, bytes(blob))

    else:
        print(f"Error: unknown mode '{mode}'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
