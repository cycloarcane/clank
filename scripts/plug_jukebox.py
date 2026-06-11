#!/usr/bin/env python3
"""Play a looping rhythm on the OpenBeken smart plugs until stopped (Ctrl+C).

The plugs have mechanical relays, so each toggle makes an audible *click* — this
turns the three of them into a tiny three-voice drum machine. There's no pitch,
only rhythm. Press Ctrl+C to stop; the plugs are switched off and left quiet.

Connects to the same MQTT broker Clank uses; credentials come from the
environment (MQTT_USER / MQTT_PASS), exactly like the rest of Clank. Run it
from a shell that has sourced .env, e.g.:

    set -a; source .env; set +a
    python3 scripts/plug_jukebox.py            # default groove at 120 BPM
    python3 scripts/plug_jukebox.py --bpm 150 --pattern backbeat
    python3 scripts/plug_jukebox.py --plugs plug1,plug2 --bpm 90

NOTE ON WEAR: a relay is a mechanical part with a finite number of operations
(typically tens of thousands+). A few minutes of this is harmless fun; don't
leave it grinding for hours. The tempo is capped so the relays can keep up.
"""

import os
import sys
import time
import argparse
import signal

# 16-step patterns (one bar of sixteenth notes). Each plug is a "voice"; an "x"
# means click that plug on that step, "." means rest. Add your own here.
PATTERNS = {
    # kick on every beat, snare on 2 & 4, hat on the off-beats
    "groove": {
        "plug1": "x...x...x...x...",
        "plug2": "....x.......x...",
        "plug3": "..x...x...x...x.",
    },
    # straight rock backbeat
    "backbeat": {
        "plug1": "x.......x.......",
        "plug2": "....x.......x...",
        "plug3": "x.x.x.x.x.x.x.x.",
    },
    # busy little fill that moves around the three plugs
    "rolling": {
        "plug1": "x..x..x..x..x...",
        "plug2": "..x..x..x..x..x.",
        "plug3": ".x..x..x..x..x..",
    },
    # sparse heartbeat — gentle on the relays
    "heartbeat": {
        "plug1": "x.x.............",
        "plug2": "........x.x.....",
        "plug3": "................",
    },
}

MIN_STEP_MS = 80          # relays follow cleanly down to ~80 ms; don't go faster
running = True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.getenv("MQTT_BROKER", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    ap.add_argument("--bpm", type=float, default=120.0, help="tempo (beats/min)")
    ap.add_argument("--pattern", choices=sorted(PATTERNS), default="groove")
    ap.add_argument("--plugs", default="plug1,plug2,plug3",
                    help="comma-separated plug base topics in voice order")
    ap.add_argument("--channel", default="1", help="relay channel index (OpenBeken)")
    args = ap.parse_args()

    import paho.mqtt.client as mqtt

    user = os.getenv("MQTT_USER")
    password = os.getenv("MQTT_PASS")
    if not password:
        print("MQTT_PASS not set — run:  set -a; source .env; set +a", file=sys.stderr)
        return 1

    # Sixteenth-note duration. Guard the tempo so the relays can keep up.
    step_ms = (60_000.0 / args.bpm) / 4.0
    if step_ms < MIN_STEP_MS:
        capped = (60_000.0 / 4.0) / MIN_STEP_MS
        print(f"Tempo too fast for the relays; capping to {capped:.0f} BPM.")
        step_ms = MIN_STEP_MS
    step_s = step_ms / 1000.0

    # Map the three pattern voices onto the requested plug base topics.
    bases = [b.strip() for b in args.plugs.split(",") if b.strip()]
    pattern = PATTERNS[args.pattern]
    voices = list(pattern.items())  # [(plug1, "x..."), ...]
    rows = []
    for i, base in enumerate(bases):
        if i < len(voices):
            rows.append((base, voices[i][1]))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="plug-jukebox")
    if password:
        client.username_pw_set(user or "clank", password)
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()

    def topic(base):
        return f"{base}/{args.channel}/set"

    def all_off():
        for base, _ in rows:
            client.publish(topic(base), "0")

    # Clean stop on Ctrl+C / SIGTERM: stop the loop, then silence the plugs.
    def stop(_sig, _frm):
        global running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    all_off()
    time.sleep(0.3)
    state = {base: 0 for base, _ in rows}

    print(f"♪ {args.pattern} @ {60_000.0/(step_ms*4):.0f} BPM on "
          f"{', '.join(b for b, _ in rows)} — Ctrl+C to stop ♪")

    bar_len = len(next(iter(pattern.values())))
    next_t = time.monotonic()
    step = 0
    try:
        while running:
            for base, row in rows:
                if row[step % len(row)] == "x":
                    state[base] ^= 1                # each flip = one click
                    client.publish(topic(base), state[base])
            step = (step + 1) % bar_len
            next_t += step_s
            # Sleep until the next step, but wake often enough to react to Ctrl+C.
            while running and time.monotonic() < next_t:
                time.sleep(min(0.02, max(0.0, next_t - time.monotonic())))
    finally:
        all_off()
        time.sleep(0.3)
        client.loop_stop()
        client.disconnect()
        print("\nstopped — plugs off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
