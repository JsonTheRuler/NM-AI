"""
NorgesGruppen Object Detection — Inference Script (runs in sandbox)
This is the file submitted in the ZIP. It runs on the competition server.

IMPORTANT sandbox constraints:
- No os, sys, subprocess, socket imports (use pathlib)
- Pre-installed: ultralytics==8.1.0, torch 2.6.0, CUDA 12.4
- GPU: NVIDIA L4 (24GB VRAM), always available
- Timeout: 300 seconds
- Memory: 8 GB RAM
"""

import argparse
import json
from pathlib import Path

import torch
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Load fine-tuned model
    model = YOLO("best.pt")

    predictions = []

    input_dir = Path(args.input)
    for img_path in sorted(input_dir.iterdir()):
        if img_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue

        image_id = int(img_path.stem.split("_")[-1])

        results = model(str(img_path), device=device, verbose=False,
                        conf=0.25, iou=0.45)

        for r in results:
            if r.boxes is None:
                continue
            for i in range(len(r.boxes)):
                x1, y1, x2, y2 = r.boxes.xyxy[i].tolist()
                predictions.append({
                    "image_id": image_id,
                    "category_id": int(r.boxes.cls[i].item()),
                    "bbox": [
                        round(x1, 1),
                        round(y1, 1),
                        round(x2 - x1, 1),
                        round(y2 - y1, 1),
                    ],
                    "score": round(float(r.boxes.conf[i].item()), 3),
                })

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(predictions, f)

    print(f"Wrote {len(predictions)} predictions for "
          f"{sum(1 for _ in input_dir.iterdir() if _.suffix.lower() in ('.jpg','.jpeg','.png'))} images")


if __name__ == "__main__":
    main()
