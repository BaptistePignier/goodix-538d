"""Do failed matches come from bad images? Offline check on a dataset.

usage: quality.py <dataset dir>

Replays the "usage" presses with template learning (see learning.py), then
computes image quality indicators for each press and how well each one
separates matched from failed presses (ROC AUC, 0.5 = no information).
For the best indicators, shows what a "retry" threshold would catch.
"""

import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import learning  # noqa: E402

BORDER = 2


def raw_signal(image_path):
    """Background minus the average of the press frames, border cropped."""
    prefix = image_path[: -len("image.pgm")]
    frames = [cv2.imread(f, cv2.IMREAD_UNCHANGED).astype(np.float64)
              for f in sorted(glob.glob(prefix + "frame*.pgm"))]
    background = cv2.imread(prefix + "background.pgm",
                            cv2.IMREAD_UNCHANGED).astype(np.float64)
    signal = background - np.mean(frames, axis=0)
    return signal[BORDER:-BORDER, BORDER:-BORDER]


def contact(image_path):
    with open(image_path[: -len("image.pgm")] + "info.txt") as f:
        info = f.read()
    return int(info.split("delta=")[1].split()[0])


def coherence_map(img):
    f = img.astype(np.float64)
    gx = cv2.Sobel(f, cv2.CV_64F, 1, 0)
    gy = cv2.Sobel(f, cv2.CV_64F, 0, 1)
    gxx = cv2.GaussianBlur(gx * gx, (0, 0), 4)
    gyy = cv2.GaussianBlur(gy * gy, (0, 0), 4)
    gxy = cv2.GaussianBlur(gx * gy, (0, 0), 4)
    return np.sqrt((gxx - gyy) ** 2 + 4 * gxy ** 2) / (gxx + gyy + 1e-9)


def ridge_strength(img):
    """Spectral energy at ridge frequencies over the total (DC excluded)."""
    f = img.astype(np.float64)
    f -= f.mean()
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(f))) ** 2
    h, w = f.shape
    y, x = np.mgrid[:h, :w]
    # Normalized radial frequency, ridge period of 6 to 14 pixels
    r = np.hypot((x - w / 2) / w, (y - h / 2) / h)
    band = (r > 1 / 14) & (r < 1 / 6)
    total = spectrum[r > 1 / 40].sum()
    return spectrum[band].sum() / total


def indicators(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    coh = coherence_map(img)
    return {
        "keypoints": len(cv2.SIFT_create().detect(img, None)),
        "coherence": float(coh.mean()),
        "ridge_strength": ridge_strength(img),
        "coverage": float((coh > 0.6).mean()),
        "contrast": float(raw_signal(image_path).std()),
        "contact": contact(image_path),
    }


def auc(values, positive):
    """Probability that a matched press scores higher than a failed one."""
    values = np.asarray(values)
    pos, neg = values[positive], values[~positive]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    greater = (pos[:, None] > neg[None, :]).mean()
    ties = (pos[:, None] == neg[None, :]).mean()
    return greater + ties / 2


def main():
    paths, labels = learning.load(sys.argv[1])
    enrolled = [i for i, label in enumerate(labels) if label == "enrol"]
    usage = [i for i, label in enumerate(labels) if label == "usage"]
    scores = learning.scores_of(paths)
    matched, _ = learning.replay(scores, enrolled, usage,
                                 learning.MATCH_THRESHOLD)
    print(f"{len(usage)} usage presses, {matched.sum()} matched, "
          f"{(~matched).sum()} failed\n")

    values = [indicators(paths[i]) for i in usage]
    names = list(values[0])
    print(f"{'indicator':15s} {'AUC':>5s} {'matched median':>15s} "
          f"{'failed median':>14s}")
    for name in names:
        v = np.array([x[name] for x in values])
        print(f"{name:15s} {auc(v, matched):5.2f} {np.median(v[matched]):15.3f} "
              f"{np.median(v[~matched]):14.3f}")

    print("\nretry below a threshold: failures caught / matches asked again")
    for name in names:
        v = np.array([x[name] for x in values])
        line = []
        for q in (10, 20, 30):
            threshold = np.percentile(v, q)
            low = v < threshold
            line.append(f"p{q}: {(low & ~matched).sum()}/{(~matched).sum()} "
                        f"vs {(low & matched).sum()}/{matched.sum()}")
        print(f"{name:15s} " + "  ".join(line))


if __name__ == "__main__":
    main()
