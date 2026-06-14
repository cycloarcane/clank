#!/usr/bin/env python3
"""Live terminal dashboard for Clank — plug energy use + LED channel levels.

A read-only `rich` TUI that watches the same MQTT broker Clank uses and polls
WLED's HTTP API, so it shows what the room is actually doing right now:

  * each OpenBeken smart plug: on/off, voltage, current, power (W), energy, and
    a TOTAL power + total energy across all plugs;
  * the WLED strip: master brightness and the effective R/G/B channel levels
    (col x bri / 255), as colored bars.

It reads the device list from config/devices.yaml (so it picks up whatever plugs
are enrolled) and needs no changes to Clank. Plug metric topics are
auto-detected — OpenBeken's energy driver names vary by build, so anything that
looks like voltage/current/power/energy is captured and shown.

Run from the repo root (uses the venv's paho/rich/requests/PyYAML):

    .venv/bin/python scripts/dashboard.py
    .venv/bin/python scripts/dashboard.py --wled-host clank-rgb.local

MQTT creds come from MQTT_USER / MQTT_PASS (auto-loaded from .env). Ctrl+C quits.
"""

import argparse
import os
import sys
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))


def _load_dotenv():
    """Load KEY=VALUE from the repo .env into os.environ (don't override)."""
    try:
        with open(os.path.join(REPO_ROOT, ".env")) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(),
                                      val.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def _f(v):
    """Best-effort float from an MQTT payload; None if it isn't numeric."""
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


class State:
    """Shared, lock-guarded snapshot the MQTT/WLED threads write and the UI reads."""

    def __init__(self, plugs):
        self.lock = threading.Lock()
        # base -> {"name", "relay": 0/1/None, "metrics": {suffix: (val, ts)}}
        self.plugs = {
            base: {"name": info["name"], "channel": info["channel"],
                   "relay": None, "metrics": {}}
            for base, info in plugs.items()
        }
        self.wled = {"on": None, "bri": 0, "col": [0, 0, 0],
                     "ts": 0.0, "error": None}

    def on_mqtt(self, topic, payload):
        parts = topic.split("/")
        if len(parts) < 2:
            return
        base, metric = parts[0], parts[1]
        with self.lock:
            plug = self.plugs.get(base)
            if plug is None:
                return
            # Relay state lives on <base>/<channel>/get for THIS plug's channel
            # (from its command topic, e.g. plug2/1/set -> "1"). Other numeric
            # channels OpenBeken emits (e.g. .../138/get) are ignored.
            if metric.isdigit():
                if metric == plug["channel"]:
                    v = _f(payload)
                    if v is not None:
                        plug["relay"] = int(v)
                return
            v = _f(payload)
            if v is not None:
                plug["metrics"][metric] = (v, time.time())

    def set_wled(self, data, error=None):
        with self.lock:
            # A failed poll only records the error — it keeps the last-known
            # values and the last-success timestamp, so a transient timeout
            # doesn't blank the panel. render() decides "offline" from the age.
            if data is None:
                self.wled["error"] = error
                return
            seg = (data.get("seg") or [{}])[0]
            col = (seg.get("col") or [[0, 0, 0]])[0]
            col = [int(c) for c in (list(col) + [0, 0, 0])[:3]]
            self.wled.update(error=None, on=bool(data.get("on")),
                             bri=int(data.get("bri", 0)), col=col,
                             ts=time.time())


# --- metric lookup: tolerate OpenBeken's varied energy/power topic names -----
def _pick(metrics, *keywords, exclude=()):
    """Return (value, ts) for the first metric whose name contains a keyword
    (and none of `exclude`), else None."""
    for kw in keywords:
        for name, (val, ts) in metrics.items():
            low = name.lower()
            if kw in low and not any(x in low for x in exclude):
                return val, ts
    return None


def plug_view(metrics):
    """Extract the headline numbers from whatever a plug published.

    OpenBeken energy topics: voltage/current/power (active), power_apparent,
    power_reactive, power_factor, and a cumulative `energycounter` (Wh) plus
    time-bucketed counters (energycounter_today/_yesterday/...). We show active
    power and the lifetime `energycounter` total."""
    def val(*kw, exclude=()):
        got = _pick(metrics, *kw, exclude=exclude)
        return got[0] if got else None

    def exact(*names):
        for n in names:
            if n in metrics:
                return metrics[n][0]
        return None

    return {
        "voltage": val("voltage"),
        "current": val("current"),
        # active power, not apparent/reactive/factor
        "power": val("power", exclude=("apparent", "reactive", "factor")),
        "pf": exact("power_factor"),
        # cumulative total only — NOT the _today/_yesterday/_N_days_ago buckets
        "energy_wh": exact("energycounter", "energytotal", "energy_total"),
    }


def mqtt_thread(state, host, port, user, password, bases):
    import paho.mqtt.client as mqtt

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id="clank-dashboard")
    except (AttributeError, TypeError):  # paho 1.x fallback
        client = mqtt.Client(client_id="clank-dashboard")
    if user:
        client.username_pw_set(user, password)

    def on_connect(c, *_):
        for base in bases:
            c.subscribe(f"{base}/#")

    client.on_connect = on_connect
    client.on_message = lambda c, u, msg: state.on_mqtt(
        msg.topic, msg.payload.decode("utf-8", "replace"))
    client.connect_async(host, port, keepalive=60)
    client.loop_forever(retry_first_connection=True)


def discover_wled():
    """Scan the local neighbour table for a device whose /json/info says it's
    WLED. Returns its IP, or None — so you never have to hunt for the address."""
    import subprocess
    import requests

    try:
        out = subprocess.run(["ip", "-4", "neigh"], capture_output=True,
                             text=True, timeout=3).stdout
    except Exception:
        return None
    for line in out.splitlines():
        ip = line.split(" ", 1)[0]
        if ip.count(".") != 3:
            continue
        try:
            r = requests.get(f"http://{ip}/json/info", timeout=0.8)
            if r.ok and r.json().get("brand") == "WLED":
                return ip
        except Exception:
            continue
    return None


def wled_thread(state, host, interval, stop):
    import requests

    url = f"http://{host}/json/state"
    while not stop.is_set():
        try:
            r = requests.get(url, timeout=3)
            if r.ok:
                state.set_wled(r.json())
            else:
                state.set_wled(None, f"HTTP {r.status_code}")
        except Exception as e:
            state.set_wled(None, type(e).__name__)
        stop.wait(interval)


# --- rendering --------------------------------------------------------------
def _bar(value, vmax, width, color):
    n = 0 if vmax <= 0 else max(0, min(width, round(value / vmax * width)))
    return f"[{color}]{'█' * n}[/][grey37]{'─' * (width - n)}[/]"


def render(state, broker, wled_host, grace=10.0):
    from rich.table import Table
    from rich.panel import Panel
    from rich.console import Group
    from rich.text import Text

    with state.lock:
        plugs = {b: dict(p, metrics=dict(p["metrics"]))
                 for b, p in state.plugs.items()}
        wled = dict(state.wled)

    # --- plugs table ---
    tbl = Table(expand=True, title="Smart plugs")
    for c, just in (("Plug", "left"), ("State", "center"), ("V", "right"),
                    ("A", "right"), ("Power", "right"), ("Energy", "right")):
        tbl.add_column(c, justify=just)

    total_power = 0.0
    total_energy = 0.0  # Wh
    now = time.time()
    for base, p in plugs.items():
        view = plug_view(p["metrics"])
        last = max((ts for _, ts in p["metrics"].values()), default=0)
        stale = p["metrics"] and (now - last) > 30
        dim = " [grey37](stale)[/]" if stale else ""
        relay = p["relay"]
        st = ("[green]ON[/]" if relay == 1 else
              "[grey50]off[/]" if relay == 0 else "[grey37]?[/]")
        if view["power"] is not None:
            total_power += view["power"]
        if view["energy_wh"] is not None:
            total_energy += view["energy_wh"]

        def cell(v, unit, fmt="{:.1f}"):
            return f"{fmt.format(v)}{unit}" if v is not None else "[grey37]—[/]"

        energy_cell = (f"{view['energy_wh'] / 1000:.3f} kWh"
                       if view["energy_wh"] is not None else "[grey37]—[/]")
        tbl.add_row(
            f"{p['name']}{dim}", st,
            cell(view["voltage"], " V", "{:.0f}"),
            cell(view["current"], " A", "{:.3f}"),
            cell(view["power"], " W"),
            energy_cell,
        )
    tbl.add_section()
    tbl.add_row("[bold]Total[/]", "", "", "",
                f"[bold]{total_power:.1f} W[/]",
                f"[bold]{total_energy / 1000:.3f} kWh[/]")

    # --- WLED panel ---
    # Tolerate transient timeouts: only declare offline once we've had no
    # successful poll for `grace` seconds; until then keep showing last values.
    age = time.time() - wled["ts"]
    fresh = wled["ts"] > 0 and age <= grace
    if not fresh:
        reason = wled.get("error") or "no response yet"
        seen = f", last seen {int(age)}s ago" if wled["ts"] > 0 else ""
        wled_body = Text(f"offline ({reason}{seen}) — "
                         f"http://{wled_host}/json/state", style="red")
    else:
        bri = wled["bri"]
        on = wled["on"]
        col = wled["col"]
        eff = [round(c * bri / 255) if on else 0 for c in col]
        recon = "   [yellow]reconnecting…[/]" if wled.get("error") else ""
        head = (f"power: {'[green]on[/]' if on else '[grey50]off[/]'}    "
                f"master bri: {bri}/255    raw col: {tuple(col)}{recon}")
        rows = []
        for label, color, c, e in (("R", "red", col[0], eff[0]),
                                    ("G", "green3", col[1], eff[1]),
                                    ("B", "blue", col[2], eff[2])):
            rows.append(f"{label}  {_bar(e, 255, 28, color)}  "
                        f"[{color}]{e:>3}[/] [grey37](of {c})[/]")
        wled_body = Group(Text.from_markup(head), Text(""),
                          *[Text.from_markup(r) for r in rows],
                          Text(""),
                          Text.from_markup("[grey37]effective = col x bri / 255 "
                                           "(before WLED gamma)[/]"))
    wled_panel = Panel(wled_body, title="LED channels", border_style="cyan")

    footer = Text(f"broker {broker}  ·  wled {wled_host}  ·  "
                  f"{time.strftime('%H:%M:%S')}  ·  Ctrl+C to quit",
                  style="grey37", justify="center")
    return Group(wled_panel, tbl, footer)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wled-host", default=os.getenv("CLANK_WLED_HOST", "auto"),
                    help="WLED hostname/IP for /json/state. 'auto' (default) "
                         "scans the local neighbours for a WLED device.")
    ap.add_argument("--broker", help="MQTT broker host (default: from config).")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="WLED poll / UI refresh interval (s).")
    ap.add_argument("--wled-grace", type=float, default=10.0,
                    help="Seconds with no successful WLED poll before the panel "
                         "shows offline (transient timeouts are tolerated).")
    args = ap.parse_args()

    _load_dotenv()
    from voicecommand.config import ClankConfig
    from voicecommand.devices import DeviceRegistry, TYPE_SWITCH

    cfg_path = os.path.join(REPO_ROOT, "config", "default.yaml")
    cfg = ClankConfig(cfg_path if os.path.exists(cfg_path) else None)
    reg_path = os.getenv("CLANK_DEVICES") or os.path.join(
        REPO_ROOT, "config", "devices.yaml")
    reg = DeviceRegistry.from_file(reg_path)

    # base topic (plug1, plug2, ...) -> friendly name + relay channel, from the
    # enrolled switches (channel comes from the command topic, e.g. plug2/1/set).
    plugs = {}
    for d in reg.devices:
        if d.type != TYPE_SWITCH:
            continue
        parts = d.topic.split("/")
        plugs[parts[0]] = {"name": d.name,
                           "channel": parts[1] if len(parts) > 1 else "1"}
    if not plugs:
        print("No switch devices enrolled — nothing to meter.", file=sys.stderr)
        return 1

    broker = args.broker or cfg.mqtt.broker_host
    wled_host = args.wled_host
    if wled_host == "auto":
        print("Discovering WLED on the local network…", file=sys.stderr)
        wled_host = discover_wled() or "clank-rgb.local"
    wled_host = wled_host.replace("https://", "").replace("http://", "").rstrip("/")
    state = State(plugs)
    stop = threading.Event()

    t_mqtt = threading.Thread(
        target=mqtt_thread, daemon=True,
        args=(state, broker, cfg.mqtt.broker_port,
              os.getenv("MQTT_USER"), os.getenv("MQTT_PASS"), list(plugs)))
    t_wled = threading.Thread(
        target=wled_thread, daemon=True,
        args=(state, wled_host, args.interval, stop))
    t_mqtt.start()
    t_wled.start()

    from rich.live import Live
    try:
        with Live(render(state, broker, wled_host, args.wled_grace),
                  refresh_per_second=max(1, round(1 / args.interval)),
                  screen=True) as live:
            while True:
                time.sleep(args.interval)
                live.update(render(state, broker, wled_host, args.wled_grace))
    except KeyboardInterrupt:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
