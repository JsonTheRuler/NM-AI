"""
Package run.py + model weights into a submission ZIP.

Usage:
    python package.py                           # Uses runs/*/weights/best.pt
    python package.py --weights path/to/best.pt # Custom weights path
"""

import argparse
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", default=None, help="Path to .pt weights file")
    parser.add_argument("--output", default="submission.zip", help="Output zip path")
    args = parser.parse_args()

    # Find weights
    if args.weights:
        weights_path = Path(args.weights)
    else:
        # Auto-find latest best.pt
        runs_dir = Path("runs")
        candidates = sorted(runs_dir.glob("*/weights/best.pt"))
        if not candidates:
            print("No best.pt found in runs/. Train a model first or specify --weights.")
            return
        weights_path = candidates[-1]

    if not weights_path.exists():
        print(f"Weights not found: {weights_path}")
        return

    weights_mb = weights_path.stat().st_size / (1024 * 1024)
    print(f"Weights: {weights_path} ({weights_mb:.1f} MB)")

    if weights_mb > 420:
        print(f"WARNING: Weights exceed 420 MB limit! Consider FP16 quantization.")

    # Create zip
    output_path = Path(args.output)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # run.py must be at the root
        zf.write("run.py", "run.py")
        # Model weights
        zf.write(weights_path, "best.pt")

    zip_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Created {output_path} ({zip_mb:.1f} MB)")

    # Verify structure
    with zipfile.ZipFile(output_path, "r") as zf:
        names = zf.namelist()
        print(f"Contents: {names}")
        if "run.py" not in names:
            print("ERROR: run.py not at zip root!")
        else:
            print("OK: run.py is at zip root")


if __name__ == "__main__":
    main()
