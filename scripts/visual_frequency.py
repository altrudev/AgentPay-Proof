#!/usr/bin/env python3
"""Visual Frequency: perceptual regression gate for approved UI references.

This intentionally checks rendered evidence, not CSS declarations. It compares
an approved reference screenshot with a candidate render at multiple scales and
fails closed when the visual result drifts materially.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat


DEFAULT_THRESHOLD = 0.80


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def _mae_similarity(reference: Image.Image, candidate: Image.Image, size: tuple[int, int]) -> float:
    a = _fit(reference, size)
    b = _fit(candidate, size)
    diff = ImageChops.difference(a, b)
    mean = sum(ImageStat.Stat(diff).mean) / 3.0
    return max(0.0, 1.0 - (mean / 255.0))


def _edge_mask(image: Image.Image, size: tuple[int, int] = (256, 144)) -> Image.Image:
    gray = ImageOps.grayscale(_fit(image, size))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return edges.point(lambda value: 255 if value > 28 else 0)


def _edge_similarity(reference: Image.Image, candidate: Image.Image) -> float:
    a = _edge_mask(reference)
    b = _edge_mask(candidate)
    intersection = ImageChops.multiply(a, b)
    a_count = sum(ImageStat.Stat(a).sum) / 255.0
    b_count = sum(ImageStat.Stat(b).sum) / 255.0
    i_count = sum(ImageStat.Stat(intersection).sum) / 255.0
    total = a_count + b_count
    return 1.0 if total == 0 else max(0.0, min(1.0, (2.0 * i_count) / total))


def _coverage(image: Image.Image, size: tuple[int, int] = (256, 144)) -> float:
    gray = ImageOps.grayscale(_fit(image, size))
    histogram = gray.histogram()
    active = sum(histogram[19:])
    return active / float(size[0] * size[1])


def _coverage_similarity(reference: Image.Image, candidate: Image.Image) -> tuple[float, float, float]:
    ref = _coverage(reference)
    cand = _coverage(candidate)
    if ref <= 0:
        return 1.0 if cand <= 0 else 0.0, ref, cand
    delta = abs(ref - cand) / ref
    return max(0.0, 1.0 - min(1.0, delta)), ref, cand


def _spatial_coverage_similarity(
    reference: Image.Image,
    candidate: Image.Image,
    *,
    cols: int = 4,
    rows: int = 4,
    size: tuple[int, int] = (256, 144),
) -> float:
    def cells(image: Image.Image) -> list[float]:
        gray = ImageOps.grayscale(_fit(image, size))
        values = []
        cell_w = size[0] // cols
        cell_h = size[1] // rows
        for row in range(rows):
            for col in range(cols):
                box = (
                    col * cell_w,
                    row * cell_h,
                    size[0] if col == cols - 1 else (col + 1) * cell_w,
                    size[1] if row == rows - 1 else (row + 1) * cell_h,
                )
                hist = gray.crop(box).histogram()
                pixels = (box[2] - box[0]) * (box[3] - box[1])
                values.append(sum(hist[19:]) / float(pixels))
        return values

    ref = cells(reference)
    cand = cells(candidate)
    similarities = []
    for r, c in zip(ref, cand):
        if r <= 0.01:
            similarities.append(1.0 if c <= 0.01 else max(0.0, 1.0 - c))
        else:
            similarities.append(max(0.0, 1.0 - min(1.0, abs(r - c) / r)))
    return sum(similarities) / len(similarities)


def _aspect_similarity(reference: Image.Image, candidate: Image.Image) -> float:
    ra = reference.width / reference.height
    ca = candidate.width / candidate.height
    return max(0.0, 1.0 - min(1.0, abs(ra - ca) / ra))


def compare(reference: Image.Image, candidate: Image.Image) -> dict:
    coarse = _mae_similarity(reference, candidate, (64, 36))
    medium = _mae_similarity(reference, candidate, (256, 144))
    edge = _edge_similarity(reference, candidate)
    coverage, ref_coverage, candidate_coverage = _coverage_similarity(reference, candidate)
    spatial = _spatial_coverage_similarity(reference, candidate)
    aspect = _aspect_similarity(reference, candidate)

    score = (
        0.27 * coarse
        + 0.25 * medium
        + 0.17 * edge
        + 0.13 * coverage
        + 0.12 * spatial
        + 0.06 * aspect
    )

    return {
        "score": round(score, 6),
        "metrics": {
            "coarse_similarity": round(coarse, 6),
            "medium_similarity": round(medium, 6),
            "edge_similarity": round(edge, 6),
            "coverage_similarity": round(coverage, 6),
            "spatial_coverage_similarity": round(spatial, 6),
            "aspect_similarity": round(aspect, 6),
            "reference_coverage": round(ref_coverage, 6),
            "candidate_coverage": round(candidate_coverage, 6),
        },
        "reference": {"width": reference.width, "height": reference.height},
        "candidate": {"width": candidate.width, "height": candidate.height},
    }


def write_diff(reference: Image.Image, candidate: Image.Image, output: Path) -> None:
    size = reference.size
    a = _fit(reference, size)
    b = _fit(candidate, size)
    diff = ImageChops.difference(a, b)
    # Amplify differences so a reviewer can immediately see drift.
    diff = diff.point(lambda value: min(255, value * 3))
    output.parent.mkdir(parents=True, exist_ok=True)
    diff.save(output)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a candidate UI screenshot to an approved reference.")
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--diff", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    reference = Image.open(args.reference)
    candidate = Image.open(args.candidate)
    result = compare(reference, candidate)
    result["threshold"] = args.threshold
    result["verdict"] = "PASS" if result["score"] >= args.threshold else "FAIL"

    if args.diff:
        write_diff(reference, candidate, args.diff)
        result["diff"] = str(args.diff)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"Visual Frequency {result['verdict']} "
            f"score={result['score']:.3f} threshold={args.threshold:.3f}"
        )
        for key, value in result["metrics"].items():
            print(f"  {key}: {value}")

    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
