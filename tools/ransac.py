"""SIFT + RANSAC matching prototype for goodix53xd images.

usage: ransac.py <dataset dir>

For each pair, SIFT descriptors are matched with Lowe's ratio test, then a
rotation + translation (+ uniform scale close to 1) is estimated with RANSAC.
The pair score is the number of inliers. Probe scores against a set of
enrolled images are combined either as the best pair score (like libfprint)
or as the sum of the pair scores.
"""

import glob
import os
import sys

import cv2
import numpy as np

GENUINE = "index"
RATIO = 0.8
RANSAC_PIXELS = 3.0
MAX_SCALE_ERROR = 0.15


def load(root):
    images, labels = [], []
    for label in sorted(os.listdir(root)):
        for path in sorted(glob.glob(os.path.join(root, label, "*-image.pgm"))):
            images.append(cv2.imread(path, cv2.IMREAD_GRAYSCALE))
            labels.append(label)
    return images, labels


def features(images):
    sift = cv2.SIFT_create()
    return [sift.detectAndCompute(img, None) for img in images]


def pair_score(probe, enrolled):
    (kp1, d1), (kp2, d2) = probe, enrolled
    if d1 is None or d2 is None or len(kp1) < 2 or len(kp2) < 2:
        return 0
    good = [m for m, n in cv2.BFMatcher().knnMatch(d1, d2, k=2)
            if m.distance < RATIO * n.distance]
    if len(good) < 3:
        return 0
    src = np.float32([kp1[m.queryIdx].pt for m in good])
    dst = np.float32([kp2[m.trainIdx].pt for m in good])
    model, inliers = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_PIXELS,
        maxIters=2000, confidence=0.99)
    if model is None:
        return 0
    scale = np.hypot(model[0, 0], model[1, 0])
    if abs(scale - 1) > MAX_SCALE_ERROR:
        return 0
    return int(inliers.sum())


def main():
    images, labels = load(sys.argv[1])
    feats = features(images)
    n = len(images)
    scores = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(n):
            if i != j:
                scores[i, j] = pair_score(feats[i], feats[j])

    genuine = [i for i, l in enumerate(labels) if l == GENUINE]
    impostors = [i for i, l in enumerate(labels) if l != GENUINE]
    rng = np.random.default_rng(0)

    for combine in ("max", "sum"):
        reduce = np.max if combine == "max" else np.sum
        imp = [reduce(scores[i, genuine]) for i in impostors]
        print(f"\n== combine {combine}: impostor scores vs all genuine: "
              f"max {max(imp)}, sorted top {sorted(imp)[-5:]}")
        for threshold in sorted({max(imp) + 1, max(imp) + 3, max(imp) * 2 + 1}):
            line = []
            for count in (10, 15, 20, 25):
                accepted = []
                for _ in range(300):
                    probe = rng.choice(genuine)
                    others = [g for g in genuine if g != probe]
                    templates = rng.choice(others, size=count, replace=False)
                    accepted.append(reduce(scores[probe, templates]) >= threshold)
                line.append(f"K={count}:{np.mean(accepted):4.0%}")
            print(f"  threshold {threshold:3d}: " + "  ".join(line))


if __name__ == "__main__":
    main()
