"""Run real CPU inference without changing model files or source photos."""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torch.nn.functional as F
from PIL import Image, ImageOps
from torchvision import transforms
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]


def timed(call, repeats=3):
    with torch.inference_mode():
        call()  # Warm-up is measured separately from steady-state inference.
        measurements = []
        for _ in range(repeats):
            start = time.perf_counter()
            result = call()
            measurements.append((time.perf_counter() - start) * 1000)
    return result, {"median_ms": round(float(np.median(measurements)), 2), "runs_ms": [round(x, 2) for x in measurements]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, default=ROOT / 'samples/coco-cats.png')
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    torch.manual_seed(0)
    out = ROOT / 'reports/smoke'
    out.mkdir(parents=True, exist_ok=True)
    with Image.open(args.image) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
    report = {
        'scope': 'Public-sample CPU runtime smoke test; not a pet identity accuracy evaluation.',
        'image': str(args.image), 'image_size': image.size,
        'environment': {'python': platform.python_version(), 'torch': torch.__version__, 'onnxruntime': ort.__version__, 'device': 'cpu', 'threads': args.threads},
    }
    cpuinfo = Path('/proc/cpuinfo')
    report['environment']['cpu'] = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')), platform.processor()) if cpuinfo.exists() else platform.processor()
    detector = YOLO(str(ROOT / 'models/yolo11n.pt'))
    results, timing = timed(lambda: detector.predict(image, device='cpu', imgsz=640, conf=0.25, verbose=False))
    result = results[0]
    result.save(filename=str(out / 'detections.jpg'))
    detections = []
    cats = []
    for box in result.boxes:
        category = result.names[int(box.cls.item())]
        bounds = [int(round(x)) for x in box.xyxy[0].tolist()]
        detections.append({'class': category, 'confidence': round(box.conf.item(), 4), 'xyxy': bounds})
        if category == 'cat':
            crop = image.crop(tuple(bounds))
            crop.save(out / f'cat-{len(cats)+1}.jpg')
            cats.append(crop)
    assert len(cats) >= 2, f'Two-cat public sample expected; detected {len(cats)} cats. Check --image and detections.jpg.'
    report['yolo11n'] = {'timing': timing, 'detections': detections, 'passed': True}
    print('YOLO11n:', json.dumps(report['yolo11n']), flush=True)

    preprocess = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    # Duplicate input tests determinism; another animal tests the comparison pipeline.
    batch = torch.stack([preprocess(cats[0]), preprocess(cats[0]), preprocess(cats[1])])
    sys.path.insert(0, str(ROOT / '.cache/dinov2'))
    from dinov2.hub.backbones import dinov2_vits14
    dino = dinov2_vits14(pretrained=False).eval()
    dino.load_state_dict(torch.load(ROOT / 'models/dinov2_vits14_pretrain.pth', map_location='cpu', weights_only=True), strict=True)
    features, timing = timed(lambda: F.normalize(dino(batch), dim=1))
    assert features.shape == (3, 384) and torch.isfinite(features).all()
    similarities = (features @ features.T).tolist()
    assert similarities[0][1] > 0.9999
    np.save(out / 'dinov2-features.npy', features.numpy())
    report['dinov2_small'] = {'shape': list(features.shape), 'timing_batch_3': timing, 'cosine_similarity': similarities, 'passed': True}
    print('DINOv2 Small:', json.dumps(report['dinov2_small']), flush=True)

    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(ROOT / 'models/pet-recognition-base/model.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
    name = session.get_inputs()[0].name
    outputs, timing = timed(lambda: session.run(None, {name: batch.numpy()}))
    embeddings = outputs[0]
    assert embeddings.shape == (3, 512) and np.isfinite(embeddings).all()
    norms = np.linalg.norm(embeddings, axis=1)
    assert np.allclose(norms, 1, atol=1e-3), norms
    similarities = embeddings @ embeddings.T
    assert similarities[0, 1] > 0.9999
    np.save(out / 'pet-recognition-features.npy', embeddings)
    report['pet_recognition_base'] = {'shape': list(embeddings.shape), 'timing_batch_3': timing, 'cosine_similarity': similarities.tolist(), 'embedding_norms': norms.tolist(), 'passed': True}
    print('Pet recognition:', json.dumps(report['pet_recognition_base']), flush=True)
    report['interpretation'] = 'Same input agreement only verifies determinism. Different-cat similarity is diagnostic and cannot establish identity accuracy or a decision threshold.'
    try:
        report['dinov2_code_commit'] = (ROOT / '.cache/dinov2/.git/refs/heads/main').read_text().strip()
    except OSError:
        report['dinov2_code_commit'] = 'see .cache/dinov2 checkout'
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('PASS: all three models completed CPU inference. Report:', out / 'report.json')


if __name__ == '__main__':
    main()
