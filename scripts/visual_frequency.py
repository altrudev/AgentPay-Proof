#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat


def fit(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def mae_similarity(a: Image.Image, b: Image.Image, size: tuple[int, int]) -> float:
    diff = ImageChops.difference(fit(a, size), fit(b, size))
    mean = sum(ImageStat.Stat(diff).mean) / 3.0
    return max(0.0, 1.0 - mean / 255.0)


def edge_similarity(a: Image.Image, b: Image.Image) -> float:
    def mask(img: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(fit(img, (320, 180))).filter(ImageFilter.FIND_EDGES)
        return gray.point(lambda x: 255 if x > 28 else 0)
    ea, eb = mask(a), mask(b)
    inter = ImageChops.multiply(ea, eb)
    sa = sum(ImageStat.Stat(ea).sum) / 255.0
    sb = sum(ImageStat.Stat(eb).sum) / 255.0
    si = sum(ImageStat.Stat(inter).sum) / 255.0
    return 1.0 if sa + sb == 0 else max(0.0, min(1.0, 2.0 * si / (sa + sb)))


def spatial_coverage(a: Image.Image, b: Image.Image, cols: int = 4, rows: int = 4) -> float:
    def cells(img: Image.Image) -> list[float]:
        gray = ImageOps.grayscale(fit(img, (320, 180)))
        cw, ch = 80, 45
        out = []
        for y in range(rows):
            for x in range(cols):
                crop = gray.crop((x*cw, y*ch, (x+1)*cw, (y+1)*ch))
                hist = crop.histogram()
                out.append(sum(hist[20:]) / float(cw*ch))
        return out
    aa, bb = cells(a), cells(b)
    sims = []
    for x, y in zip(aa, bb):
        if x < .01:
            sims.append(1.0 if y < .01 else max(0.0, 1.0-y))
        else:
            sims.append(max(0.0, 1.0-min(1.0, abs(x-y)/x)))
    return sum(sims)/len(sims)


def compare(reference: Image.Image, candidate: Image.Image) -> dict:
    coarse = mae_similarity(reference, candidate, (80, 45))
    medium = mae_similarity(reference, candidate, (320, 180))
    edges = edge_similarity(reference, candidate)
    spatial = spatial_coverage(reference, candidate)
    aspect = 1.0 - min(1.0, abs((reference.width/reference.height)-(candidate.width/candidate.height))/(reference.width/reference.height))
    score = .31*coarse + .31*medium + .18*edges + .14*spatial + .06*aspect
    return {
        "score": round(score, 6),
        "metrics": {
            "coarse_similarity": round(coarse, 6),
            "medium_similarity": round(medium, 6),
            "edge_similarity": round(edges, 6),
            "spatial_coverage_similarity": round(spatial, 6),
            "aspect_similarity": round(aspect, 6),
        },
        "reference": [reference.width, reference.height],
        "candidate": [candidate.width, candidate.height],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("reference", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("--threshold", type=float, default=.80)
    p.add_argument("--diff", type=Path)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    ref, cand = Image.open(a.reference), Image.open(a.candidate)
    result = compare(ref, cand)
    result["threshold"] = a.threshold
    result["verdict"] = "PASS" if result["score"] >= a.threshold else "FAIL"
    if a.diff:
        d = ImageChops.difference(fit(ref, ref.size), fit(cand, ref.size)).point(lambda x:min(255,x*3))
        a.diff.parent.mkdir(parents=True, exist_ok=True)
        d.save(a.diff)
        result["diff"] = str(a.diff)
    print(json.dumps(result, indent=2) if a.json else f"Visual Frequency {result['verdict']} score={result['score']:.3f}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
