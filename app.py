from io import BytesIO
from pathlib import Path
from typing import Annotated

import torch
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from torchvision.models import ResNet18_Weights, resnet18
from torchvision.transforms import Compose, Resize, ToTensor, Normalize

ROOT = Path(__file__).parent
app = FastAPI(title="쑥쑥 사물 학습")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

LABELS = {
    "cup": "컵", "coffee mug": "컵", "water bottle": "물병", "bottle": "물병",
    "chair": "의자", "ball": "공", "soccer ball": "공", "shoe": "신발",
    "running shoe": "신발", "sandal": "신발", "backpack": "가방", "purse": "가방",
    "umbrella": "우산", "banana": "바나나", "apple": "사과", "orange": "오렌지",
    "book jacket": "책", "book": "책", "pencil": "연필", "pen": "펜",
    "cellular telephone": "휴대전화", "laptop": "노트북", "keyboard": "키보드",
    "mouse": "마우스", "clock": "시계", "digital clock": "시계", "watch": "손목시계",
    "sunglasses": "선글라스", "hat": "모자", "jean": "청바지", "jersey": "티셔츠",
    "teddy": "인형", "toy poodle": "강아지", "dog": "강아지", "cat": "고양이",
    "bicycle-built-for-two": "자전거", "miniskirt": "치마", "television": "텔레비전",
    "remote control": "리모컨", "toilet tissue": "휴지", "fork": "포크", "spatula": "주걱",
}
weights = ResNet18_Weights.DEFAULT
model = resnet18(weights=weights).eval()
MODEL_VERSION = "resnet18-full-frame-v1"
preprocess = Compose([Resize((224, 224), antialias=True), ToTensor(),
                      Normalize(weights.transforms().mean, weights.transforms().std)])
imagenet = weights.meta["categories"]

def predict(image: Image.Image):
    with torch.inference_mode():
        probs = model(preprocess(image.convert("RGB")).unsqueeze(0)).softmax(1)[0]
    values, indices = torch.topk(probs, 5)
    for value, index in zip(values.tolist(), indices.tolist()):
        raw = imagenet[index].lower()
        if raw in LABELS and value >= 0.20:
            return {"name": LABELS[raw], "confidence": round(value, 3), "raw": raw}
    return {"name": None, "confidence": round(values[0].item(), 3), "raw": imagenet[indices[0]].lower()}

@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/api/health")
def health():
    return {"ok": True, "model": "ResNet-18 ImageNet (CPU)", "model_version": MODEL_VERSION,
            "items": len(set(LABELS.values()))}

@app.post("/api/identify")
async def identify(file: Annotated[UploadFile, File()]):
    result = predict(Image.open(BytesIO(await file.read())))
    return {"ok": True, "model_version": MODEL_VERSION, **result}

@app.post("/api/quiz")
async def quiz(target: str, file: Annotated[UploadFile, File()]):
    result = predict(Image.open(BytesIO(await file.read())))
    correct = result["name"] == target if result["name"] else False
    return {"ok": True, "model_version": MODEL_VERSION, "correct": correct, **result, "target": target}
