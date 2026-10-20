"""Sweeps SIGFM parameters with sigfm_tune on a goodix53xd dataset.

usage: tune.py <dataset dir> <config>...
A config is "scale,contrast,ratio,min_match,length_tol,angle_tol[,bug]",
"bug" reproducing the libsigfm row deduplication bug.

The images are the ones built by the driver (*-image.pgm). For each config,
the threshold is the lowest one rejecting every impostor press against all
genuine presses, and the genuine acceptance is measured for random sets of
15 and 25 enrolled presses, like libfprint verify (best score over the
enrolled images).
"""

import glob
import os
import subprocess
import sys

import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
GENUINE = "index"


def load(root):
    paths, labels = [], []
    for label in sorted(os.listdir(root)):
        for path in sorted(glob.glob(os.path.join(root, label, "*-image.pgm"))):
            paths.append(path)
            labels.append(label)
    return paths, labels


def run(config, paths):
    fields = config.split(",")
    env = dict(os.environ)
    env.pop("SIGFM_ROW_BUG", None)
    if len(fields) > 6 and fields[6] == "bug":
        env["SIGFM_ROW_BUG"] = "1"
    out = subprocess.run([os.path.join(TOOLS, "sigfm_tune")] + fields[:6] + paths,
                         check=True, capture_output=True, text=True, env=env).stdout
    rows = [list(map(int, line.split(","))) for line in out.strip().splitlines()]
    return np.array([r[0] for r in rows]), np.array([r[1:] for r in rows])


def acceptance(scores, genuine, threshold, count, rng, draws=300):
    accepted = []
    for _ in range(draws):
        probe = rng.choice(genuine)
        others = [g for g in genuine if g != probe]
        templates = rng.choice(others, size=count, replace=False)
        accepted.append(scores[probe, templates].max() >= threshold)
    return np.mean(accepted)


def main():
    paths, labels = load(sys.argv[1])
    genuine = [i for i, label in enumerate(labels) if label == GENUINE]
    impostors = [i for i, label in enumerate(labels) if label != GENUINE]
    print(f"{len(genuine)} genuine, {len(impostors)} impostor presses")
    print(f"{'config':40s} {'kp med':>6s} {'thr':>5s} {'imp>0':>5s} "
          f"{'K=15':>5s} {'K=25':>5s}")
    for config in sys.argv[2:]:
        keypoints, scores = run(config, paths)
        imp_best = [scores[i, genuine].max() for i in impostors]
        threshold = max(max(imp_best) + 1, 1)
        nonzero = sum(b > 0 for b in imp_best)
        rng = np.random.default_rng(0)
        k15 = acceptance(scores, genuine, threshold, 15, rng)
        k25 = acceptance(scores, genuine, threshold, 25, rng)
        print(f"{config:40s} {int(np.median(keypoints)):6d} {threshold:5d} "
              f"{nonzero:5d} {k15:5.0%} {k25:5.0%}", flush=True)


if __name__ == "__main__":
    main()
