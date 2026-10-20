"""Correlation matching prototype for goodix53xd images.

usage: correlation.py <dataset dir> [variant]

For each pair of presses, the second image is rotated over a range of
angles, the translation is found by phase correlation, and the score is the
normalized cross-correlation over the overlapping area (when it is large
enough). Scores are evaluated like analyze.py: genuine finger "index",
every other finger is an impostor.
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze  # noqa: E402

ANGLES = np.arange(-20, 21, 4)  # degrees
MIN_OVERLAP = 0.4  # fraction of the image


def prepare(img):
    """Zero mean, band-passed float image and its validity mask."""
    f = img.astype(np.float32)
    f = cv2.GaussianBlur(f, (0, 0), 0.8) - cv2.GaussianBlur(f, (0, 0), 5)
    f -= f.mean()
    return f / (f.std() + 1e-6)


def ncc_overlap(a, b, mask_b, dx, dy):
    """Normalized cross-correlation of a and b shifted by (dx, dy)."""
    h, w = a.shape
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    b_shift = cv2.warpAffine(b, m, (w, h))
    mask = cv2.warpAffine(mask_b, m, (w, h)) > 0.99
    if mask.mean() < MIN_OVERLAP:
        return -1.0
    x, y = a[mask], b_shift[mask]
    x = x - x.mean()
    y = y - y.mean()
    return float((x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum() + 1e-9))


def score(a, b):
    h, w = a.shape
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    best = -1.0
    for angle in ANGLES:
        rot = cv2.getRotationMatrix2D((w / 2, h / 2), float(angle), 1.0)
        b_rot = cv2.warpAffine(b, rot, (w, h))
        mask = cv2.warpAffine(np.ones_like(b), rot, (w, h))
        (dx, dy), _ = cv2.phaseCorrelate(a * window, b_rot * window)
        # phaseCorrelate gives the shift of a relative to b
        best = max(best, ncc_overlap(a, b_rot, mask, dx, dy))
    return best


def main():
    root = sys.argv[1]
    variant = sys.argv[2] if len(sys.argv) > 2 else "rows"
    presses = analyze.load_dataset(root)
    images = [prepare(img) for img in analyze.VARIANTS[variant](presses)]
    n = len(images)
    scores = np.full((n, n), -1.0)
    for i in range(n):
        for j in range(n):
            if i != j:
                scores[i, j] = score(images[i], images[j])
    np.save(f"correlation-{variant}.npy", scores)

    genuine = [i for i, p in enumerate(presses) if p["label"] == analyze.GENUINE]
    impostors = [i for i, p in enumerate(presses) if p["label"] != analyze.GENUINE]
    pairs_g = [scores[i, j] for i in genuine for j in genuine if i != j]
    pairs_i = [scores[i, j] for i in impostors for j in genuine]
    print(f"pair scores: genuine median {np.median(pairs_g):.2f} p90 "
          f"{np.percentile(pairs_g, 90):.2f} | impostor median "
          f"{np.median(pairs_i):.2f} p99 {np.percentile(pairs_i, 99):.2f} "
          f"max {max(pairs_i):.2f}")

    rng = np.random.default_rng(0)
    imp_best = max(scores[i, genuine].max() for i in impostors)
    print(f"max impostor score against all genuine presses: {imp_best:.2f}")
    for threshold in (imp_best + 0.01, 0.5, 0.6, 0.7):
        line = []
        for count in (5, 10, 15, 20, 25, 29):
            accepted = []
            for _ in range(300):
                probe = rng.choice(genuine)
                others = [g for g in genuine if g != probe]
                templates = rng.choice(others, size=count, replace=False)
                accepted.append(scores[probe, templates].max() >= threshold)
            line.append(f"K={count}:{np.mean(accepted):4.0%}")
        far = np.mean([scores[i, genuine].max() >= threshold for i in impostors])
        print(f"  threshold {threshold:.2f} (impostors accepted vs all "
              f"{len(genuine)}: {far:.0%}): " + "  ".join(line))


if __name__ == "__main__":
    main()
