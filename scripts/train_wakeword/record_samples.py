#!/usr/bin/env python3
"""Record wake-word training clips from the Clank mic.

The single biggest lever on "hey clank" recall is training on audio from the
*same microphone and room* Clank actually listens through. The openWakeWord
pipeline trains mostly on synthetic (TTS) speech; folding in a few dozen real
recordings from this mic closes the gap that shows up as "it scores 0.8 on a
headset but 0.1 on the built-in mic".

Records fixed-length 16 kHz mono WAV clips — the format the trainer expects.

Examples (run from the repo root, in the Clank venv):

    # 50 positive "hey clank" clips
    .venv/bin/python scripts/train_wakeword/record_samples.py \
        --label positive --count 50

    # 30 "hard negative" clips: talk, but never say the wake word. These teach
    # the model what NOT to fire on (TV, conversation, similar-sounding words).
    .venv/bin/python scripts/train_wakeword/record_samples.py \
        --label negative --count 30 --seconds 3

Clips land in   data/wakeword/<label>/<label>_NNN.wav   by default.
Press ENTER to record each clip; after each you can (k)eep, (r)edo, or (q)uit.
"""

import argparse
import os
import sys
import time

SAMPLE_RATE = 16000  # openWakeWord operates at 16 kHz mono.


def _check_deps():
    try:
        import sounddevice  # noqa: F401
        import soundfile  # noqa: F401
    except ImportError as e:
        sys.exit(
            f"Missing audio dependency ({e.name}). These ship with Clank's "
            "runtime venv — run this with .venv/bin/python from the repo root."
        )


def _countdown(prompt):
    print(f"\n{prompt}")
    for n in ("3", "2", "1", "GO"):
        print(f"  {n}", end="\r" if n != "GO" else "\n", flush=True)
        time.sleep(0.5)


def record_one(seconds):
    import sounddevice as sd

    frames = int(seconds * SAMPLE_RATE)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return audio.reshape(-1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="positive",
                    help="Clip class / subfolder name (e.g. positive, negative).")
    ap.add_argument("--count", type=int, default=50,
                    help="How many clips to record this session.")
    ap.add_argument("--seconds", type=float, default=2.0,
                    help="Length of each clip in seconds (2.0 suits 'hey clank').")
    ap.add_argument("--out", default="data/wakeword",
                    help="Base output directory (subfolder per --label).")
    ap.add_argument("--phrase", default="hey clank",
                    help="What to say (shown as the prompt for positives).")
    args = ap.parse_args()

    _check_deps()
    import sounddevice as sd
    import soundfile as sf

    out_dir = os.path.join(args.out, args.label)
    os.makedirs(out_dir, exist_ok=True)

    # Continue numbering after any existing clips so repeated sessions accrue.
    existing = [f for f in os.listdir(out_dir)
                if f.startswith(args.label + "_") and f.endswith(".wav")]
    start_idx = len(existing)

    try:
        dev = sd.query_devices(kind="input")
        print(f"Input device: {dev['name']}")
    except Exception:
        print("Input device: (default)")

    say = (f"Say: \"{args.phrase}\"" if args.label == "positive"
           else f"Make a NON-wake sound/speech for ~{args.seconds:.0f}s "
                "(talk, TV, similar words — anything but the wake word)")
    print(f"\nRecording {args.count} '{args.label}' clips of "
          f"{args.seconds:.1f}s into {out_dir}/")
    print("ENTER = record • after each: [k]eep / [r]edo / [q]uit\n")

    saved = 0
    idx = start_idx
    while saved < args.count:
        try:
            input(f"[{saved + 1}/{args.count}] ENTER to record… ")
        except (EOFError, KeyboardInterrupt):
            print("\nStopping.")
            break

        while True:
            _countdown(say)
            audio = record_one(args.seconds)
            peak = float(abs(audio).max()) if audio.size else 0.0
            warn = "  ⚠ very quiet — move closer / raise mic gain" if peak < 0.02 else ""
            warn = "  ⚠ clipping — lower mic gain" if peak > 0.99 else warn
            print(f"  peak level: {peak:.3f}{warn}")
            sd.play(audio, SAMPLE_RATE)
            sd.wait()
            choice = input("  [k]eep / [r]edo / [q]uit: ").strip().lower()
            if choice == "r":
                continue
            if choice == "q":
                print(f"\nDone. Saved {saved} clip(s) to {out_dir}/")
                return
            # default / 'k' -> keep
            path = os.path.join(out_dir, f"{args.label}_{idx:03d}.wav")
            sf.write(path, audio, SAMPLE_RATE, subtype="PCM_16")
            print(f"  saved {path}")
            saved += 1
            idx += 1
            break

    print(f"\nDone. Saved {saved} clip(s) to {out_dir}/")
    print("Next: feed these into the trainer — see docs/training-wakeword.md")


if __name__ == "__main__":
    main()
