"""
NorgesGruppen Object Detection — Training Script
Train YOLOv8 on the competition COCO dataset.

Prerequisites:
1. Download NM_NGD_coco_dataset.zip from app.ainm.no
2. Extract to norgesgruppen/data/
3. pip install ultralytics==8.1.0

Usage:
    python train.py                    # YOLOv8m, imgsz=640
    python train.py --model yolov8l    # YOLOv8l
    python train.py --imgsz 1280       # Higher resolution (needs more VRAM)
"""

import argparse
import json
from pathlib import Path


def create_data_yaml(data_dir: Path, output_path: Path):
    """Create data.yaml for ultralytics from COCO annotations."""
    annotations_path = data_dir / "annotations.json"
    if not annotations_path.exists():
        raise FileNotFoundError(f"annotations.json not found at {annotations_path}")

    with open(annotations_path) as f:
        coco = json.load(f)

    # Extract category names
    categories = {cat["id"]: cat["name"] for cat in coco["categories"]}
    nc = len(categories)

    # Build names dict
    names = {i: categories.get(i, f"class_{i}") for i in range(nc)}

    # Create data.yaml content
    yaml_content = f"""# NorgesGruppen Object Detection Dataset
# Auto-generated from COCO annotations

path: {data_dir.resolve()}
train: images
val: images

nc: {nc}
names: {names}
"""
    output_path.write_text(yaml_content)
    print(f"Created {output_path} with {nc} classes")
    return nc


def convert_coco_to_yolo(data_dir: Path):
    """Convert COCO annotations to YOLO format (one .txt per image)."""
    annotations_path = data_dir / "annotations.json"
    with open(annotations_path) as f:
        coco = json.load(f)

    # Build image lookup
    images = {img["id"]: img for img in coco["images"]}

    # Create labels directory
    labels_dir = data_dir / "labels"
    labels_dir.mkdir(exist_ok=True)

    # Group annotations by image
    img_annotations = {}
    for ann in coco["annotations"]:
        img_id = ann["image_id"]
        if img_id not in img_annotations:
            img_annotations[img_id] = []
        img_annotations[img_id].append(ann)

    # Write YOLO format labels
    for img_id, anns in img_annotations.items():
        img_info = images[img_id]
        img_w, img_h = img_info["width"], img_info["height"]
        filename = Path(img_info["file_name"]).stem + ".txt"

        lines = []
        for ann in anns:
            cat_id = ann["category_id"]
            x, y, w, h = ann["bbox"]  # COCO: x, y, width, height (pixels)

            # Convert to YOLO: center_x, center_y, width, height (normalized)
            cx = (x + w / 2) / img_w
            cy = (y + h / 2) / img_h
            nw = w / img_w
            nh = h / img_h

            # Clamp to [0, 1]
            cx = max(0, min(1, cx))
            cy = max(0, min(1, cy))
            nw = max(0, min(1, nw))
            nh = max(0, min(1, nh))

            lines.append(f"{cat_id} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")

        (labels_dir / filename).write_text("\n".join(lines))

    # Also create empty label files for images without annotations
    images_dir = data_dir / "images"
    if images_dir.exists():
        for img_path in images_dir.iterdir():
            if img_path.suffix.lower() in (".jpg", ".jpeg", ".png"):
                label_path = labels_dir / (img_path.stem + ".txt")
                if not label_path.exists():
                    label_path.write_text("")

    print(f"Converted {len(img_annotations)} images to YOLO format in {labels_dir}")


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8 for NorgesGruppen")
    parser.add_argument("--model", default="yolov8m", help="Model variant (yolov8n/s/m/l/x)")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--batch", type=int, default=16, help="Batch size")
    parser.add_argument("--data-dir", default="data", help="Path to extracted dataset")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Data directory {data_dir} not found!")
        print("Download and extract NM_NGD_coco_dataset.zip first.")
        return

    # Step 1: Convert COCO to YOLO format
    print("Converting COCO annotations to YOLO format...")
    convert_coco_to_yolo(data_dir)

    # Step 2: Create data.yaml
    data_yaml = Path("data.yaml")
    nc = create_data_yaml(data_dir, data_yaml)

    # Step 3: Train
    print(f"\nTraining {args.model}.pt — {nc} classes, imgsz={args.imgsz}, "
          f"batch={args.batch}, epochs={args.epochs}")

    from ultralytics import YOLO

    model = YOLO(f"{args.model}.pt")
    model.train(
        data=str(data_yaml.resolve()),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device="0",  # GPU
        workers=4,
        project="runs",
        name=f"{args.model}_{args.imgsz}",
        exist_ok=True,
        # Augmentation
        mosaic=1.0,
        mixup=0.1,
        copy_paste=0.1,
        # Save best
        save=True,
        save_period=10,
    )

    print(f"\nTraining complete! Best weights at: runs/{args.model}_{args.imgsz}/weights/best.pt")
    print("Next: python package.py to create submission zip")


if __name__ == "__main__":
    main()
