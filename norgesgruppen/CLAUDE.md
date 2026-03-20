# NorgesGruppen — Grocery Object Detection

## Your Mission
Detect and classify grocery products on store shelf images. Train a YOLOv8 model on COCO-format training data, package as ZIP, upload for evaluation.

## Key Files
- `train.py` — Training script (COCO→YOLO conversion + ultralytics training)
- `run.py` — Inference script (submitted in ZIP, runs in sandbox)
- `package.py` — Create submission ZIP from run.py + weights

## Workflow
```bash
# 1. Download data from app.ainm.no submit page
# 2. Extract to norgesgruppen/data/ (images/ + annotations.json)

pip install ultralytics==8.1.0   # EXACT version match required

# 3. Train
python train.py --model yolov8l --imgsz 640 --epochs 100

# 4. Package
python package.py --weights runs/yolov8l_640/weights/best.pt

# 5. Upload submission.zip at app.ainm.no
```

## Training Data
- 248 shelf images, ~22,700 annotations, 357 categories (0-356)
- COCO format: annotations.json with bbox [x, y, width, height]
- Product reference images available too (~60 MB, multi-angle photos)

## Scoring
- **70% detection mAP** — did you find the products? (IoU ≥ 0.5, category ignored)
- **30% classification mAP** — did you identify the right product? (IoU ≥ 0.5 AND correct category)
- Detection-only (all category_id=0) caps at 0.70

## Sandbox Environment
- Python 3.11, PyTorch 2.6.0+cu124, ultralytics 8.1.0
- GPU: NVIDIA L4 (24GB VRAM), CUDA 12.4
- Timeout: 300 seconds, Memory: 8 GB RAM
- NO NETWORK ACCESS

## CRITICAL CONSTRAINTS
- `ultralytics==8.1.0` — EXACT version. 8.2+ weights WILL FAIL.
- NO `os`, `sys`, `subprocess`, `socket` imports — use `pathlib`
- NO `yaml` — use `json` for config
- Max zip: 420 MB uncompressed, max 3 weight files
- run.py MUST be at ZIP root (not in a subfolder)
- Max 3 submissions per day

## Progressive Strategy
1. First: get detection working (up to 70% score)
2. Then: fine-tune for classification (remaining 30%)
3. Scale up: YOLOv8m → YOLOv8l → YOLOv8x
4. Try imgsz=1280 for small product detection
5. Consider ensemble or TTA for final submission
