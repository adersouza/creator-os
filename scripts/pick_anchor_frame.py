#!/usr/bin/env python3
"""Pick the best anchor frame from a reference reel.

Nano Banana substitutes the creator's face only when the source frame gives it
a clear one. When the face is averted, occluded, motion-blurred, or too small,
it silently returns the SOURCE woman -- no error, just a plausible generation
of the wrong person (see the frame-selection section of the anchor findings).
Choosing that frame by eye is what burned credits on 2026-08-06/07, so choose
it by measurement instead.

Score = face sharpness (blur is fatal) + face size + both eyes visible.

    scripts/pick_anchor_frame.py REEL.mp4 [--out DIR] [--top N]

Prints a ranked table and, with --out, writes the top frames plus a face-crop
contact sheet so the choice can be eyeballed before spending.

ponytail: the Haar frontal cascade doubles as the "is she facing camera" test
-- it only fires near-frontal, so a hit IS the signal. No pose model needed.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - optional analysis dependency
    sys.exit("needs opencv-python + numpy (uv sync --package reel_factory --extra identity)")

# The face never sits in the bottom of a 9:16 reel frame, but KNEES do -- and
# the frontal cascade reads a knee as a face often enough to win the ranking.
# Searching only the top of the frame is what makes the score mean anything.
FACE_BAND = 0.45


def rank(path: pathlib.Path) -> tuple[list[dict], float]:
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    eyes = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    rows: list[dict] = []
    index = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        index += 1
        height = frame.shape[0]
        gray = cv2.cvtColor(frame[: int(height * FACE_BAND)], cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 7, minSize=(60, 60))
        if len(faces) == 0:
            continue
        x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
        roi = gray[y : y + h, x : x + w]
        rows.append(
            {
                "t": index / fps,
                "px": int(h),
                "frac": h / height,
                "sharp": float(cv2.Laplacian(roi, cv2.CV_64F).var()),
                "eyes": len(eyes.detectMultiScale(roi, 1.1, 6,
                                                  minSize=(int(w * 0.10), int(h * 0.10)))),
                "box": (int(x), int(y), int(w), int(h)),
                "frame": frame,
            }
        )
    cap.release()
    if not rows:
        return [], fps

    max_sharp = max(r["sharp"] for r in rows)
    max_px = max(r["px"] for r in rows)
    for r in rows:
        # sharpness dominates: a big blurry face animates into a smeared reel,
        # while a smaller crisp one still lands the swap
        r["score"] = (
            0.55 * (r["sharp"] / max_sharp)
            + 0.30 * (r["px"] / max_px)
            + 0.15 * min(r["eyes"], 2) / 2
        )
    rows.sort(key=lambda r: -r["score"])
    return rows, fps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reel", type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, help="write top frames + face sheet here")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    rows, _ = rank(args.reel)
    if not rows:
        print("no frontal face in any frame -- this reel has no usable anchor", file=sys.stderr)
        return 1

    print(f"{len(rows)} candidate frames\n")
    print(f"{'t':>7} {'facepx':>7} {'frac':>6} {'sharp':>9} {'eyes':>5} {'score':>6}")
    for r in rows[: args.top]:
        print(f"{r['t']:7.2f} {r['px']:7d} {r['frac']:6.3f} "
              f"{r['sharp']:9.1f} {r['eyes']:5d} {r['score']:6.3f}")
    print(f"\nbest: t={rows[0]['t']:.2f}")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        crops = []
        for r in rows[: args.top]:
            cv2.imwrite(str(args.out / f"anchor_t{r['t']:.2f}.png"), r["frame"])
            x, y, w, h = r["box"]
            pad = int(h * 0.5)
            crop = r["frame"][max(0, y - pad) : y + h + pad,
                              max(0, x - pad) : x + w + pad]
            crop = cv2.resize(crop, (340, 340))
            cv2.putText(crop, f"t={r['t']:.2f}", (6, 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            crops.append(crop)
        cv2.imwrite(str(args.out / "faces.jpg"), np.hstack(crops))
        print(f"wrote {args.top} frames + faces.jpg to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
