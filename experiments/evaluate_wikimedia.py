"""Evaluate baseline and at most two inference improvements on the frozen split."""
from __future__ import annotations

import csv, json
from pathlib import Path
import torch
from PIL import Image
from torchvision.models import ResNet18_Weights, resnet18
from torchvision.transforms import Compose, Resize, ToTensor, Normalize

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "wikimedia_manifest.csv"
OUT = ROOT / "experiments" / "wikimedia_evaluation.json"
TARGET = {
    "cup":"컵", "bottle":"물병", "chair":"의자", "ball":"공", "shoe":"신발", "backpack":"가방", "umbrella":"우산",
    "banana":"바나나", "apple":"사과", "orange fruit":"오렌지", "book":"책", "pencil":"연필", "pen":"펜",
    "mobile phone":"휴대전화", "laptop":"노트북", "computer keyboard":"키보드", "computer mouse":"마우스", "clock":"시계",
    "wristwatch":"손목시계", "sunglasses":"선글라스", "hat":"모자", "jeans":"청바지", "t-shirt":"티셔츠",
    "teddy bear":"인형", "dog":"강아지", "cat":"고양이", "bicycle":"자전거", "television":"텔레비전",
    "remote control":"리모컨", "toilet paper":"휴지", "fork":"포크", "spatula":"주걱",
}

def load_rows():
    with MANIFEST.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def transform(kind, weights):
    if kind == "baseline": return weights.transforms()
    # Candidate 1: avoid center-cropping small thumbnails.
    if kind == "full_frame":
        return Compose([Resize((224, 224), antialias=True), ToTensor(), Normalize(weights.transforms().mean, weights.transforms().std)])
    return weights.transforms()

def evaluate(rows, model, categories, kind, threshold):
    tfm = transform(kind, weights)
    results = []
    for row in rows:
        image = Image.open(ROOT / row["path"]).convert("RGB")
        with torch.inference_mode():
            probs = model(tfm(image).unsqueeze(0)).softmax(1)[0]
        values, indices = torch.topk(probs, 5)
        name = None; raw = categories[int(indices[0])]; confidence = float(values[0])
        for value, index in zip(values.tolist(), indices.tolist()):
            candidate = categories[index].lower()
            if candidate in LABELS and value >= threshold:
                name = LABELS[candidate]; raw = candidate; confidence = value; break
        expected = TARGET.get(row["label"])
        correct_in = row["group"] == "in" and name == expected
        correct_out = row["group"] == "out" and name is None
        results.append({"path": row["path"], "split": row["split"], "group": row["group"], "expected": expected,
                        "name": name, "raw": raw, "confidence": round(confidence, 6),
                        "correct_in": correct_in, "correct_out": correct_out})
    ins = [r for r in results if r["group"] == "in"]
    outs = [r for r in results if r["group"] == "out"]
    return {"in_accuracy": sum(r["correct_in"] for r in ins) / len(ins) if ins else 0,
            "out_unknown_rate": sum(r["correct_out"] for r in outs) / len(outs) if outs else 0,
            "results": results}

LABELS = {
    "cup":"컵", "coffee mug":"컵", "water bottle":"물병", "bottle":"물병", "chair":"의자", "ball":"공", "soccer ball":"공",
    "shoe":"신발", "running shoe":"신발", "sandal":"신발", "backpack":"가방", "purse":"가방", "umbrella":"우산", "banana":"바나나",
    "apple":"사과", "orange":"오렌지", "book jacket":"책", "book":"책", "pencil":"연필", "pen":"펜", "cellular telephone":"휴대전화",
    "laptop":"노트북", "keyboard":"키보드", "mouse":"마우스", "clock":"시계", "digital clock":"시계", "watch":"손목시계",
    "sunglasses":"선글라스", "hat":"모자", "jean":"청바지", "jersey":"티셔츠", "teddy":"인형", "toy poodle":"강아지", "dog":"강아지",
    "cat":"고양이", "bicycle-built-for-two":"자전거", "miniskirt":"치마", "television":"텔레비전", "remote control":"리모컨",
    "toilet tissue":"휴지", "fork":"포크", "spatula":"주걱",
}

weights = ResNet18_Weights.DEFAULT
model = resnet18(weights=weights).eval()
rows = load_rows(); tuning = [r for r in rows if r["split"] == "tuning"]; final = [r for r in rows if r["split"] == "final"]
baseline_tune = evaluate(tuning, model, weights.meta["categories"], "baseline", .20)
attempts = [
    ("full_frame", .20),
    ("baseline_lower_unknown_threshold", .15),
]
candidate_tuning = []
for kind, threshold in attempts:
    candidate_tuning.append({"kind": kind, "threshold": threshold, **evaluate(tuning, model, weights.meta["categories"], kind, threshold)})
best = max(candidate_tuning, key=lambda x: (x["in_accuracy"] + x["out_unknown_rate"], x["out_unknown_rate"]))
baseline_final = evaluate(final, model, weights.meta["categories"], "baseline", .20)
selected_final = evaluate(final, model, weights.meta["categories"], best["kind"], best["threshold"])
payload = {"data": {"total": len(rows), "tuning": len(tuning), "final": len(final), "in_list": sum(r["group"] == "in" for r in rows), "out_of_list": sum(r["group"] == "out" for r in rows)},
           "baseline_tuning": {k:v for k,v in baseline_tune.items() if k != "results"},
           "candidate_tuning": [{k:v for k,v in x.items() if k != "results"} for x in candidate_tuning],
           "selected": {"kind": best["kind"], "threshold": best["threshold"]},
           "baseline_final": {k:v for k,v in baseline_final.items() if k != "results"},
           "selected_final": {k:v for k,v in selected_final.items() if k != "results"},
           "final_delta": {"in_accuracy": selected_final["in_accuracy"] - baseline_final["in_accuracy"], "out_unknown_rate": selected_final["out_unknown_rate"] - baseline_final["out_unknown_rate"]}}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
