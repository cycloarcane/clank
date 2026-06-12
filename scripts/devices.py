#!/usr/bin/env python3
"""Show and manage Clank's device registry (config/devices.yaml).

This is the friendly front-end to the registry: see what Clank can currently
control, add a new device without hand-editing YAML, and physically test a
switch by toggling it (handy for working out which plug is which).

    python3 scripts/devices.py                 # list enrolled devices
    python3 scripts/devices.py list
    python3 scripts/devices.py add             # interactive add
    python3 scripts/devices.py add --name "desk lamp" --type switch \
            --topic plug1/1/set --aliases "lamp,reading lamp"
    python3 scripts/devices.py test plug1/1/set   # toggle a switch on, then off

Adding appends a tidy block to config/devices.yaml and leaves every existing
comment intact (it does NOT round-trip the file through a YAML dumper). After
adding, restart Clank so it reloads the registry.

MQTT creds for `test` come from the environment (MQTT_USER / MQTT_PASS); the
.env in the repo root is auto-loaded if they aren't already set, so it works the
same in fish, bash, or anywhere — no `source` dance.
"""

import os
import sys
import time
import argparse

# Make voicecommand.* importable (src/ on the path), mirroring the app.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from voicecommand.devices import (  # noqa: E402
    DeviceRegistry, Device, TYPE_WLED, TYPE_SWITCH,
)


def devices_path():
    """Same resolution the app uses: $CLANK_DEVICES else repo config/devices.yaml."""
    return os.getenv("CLANK_DEVICES") or os.path.join(REPO_ROOT, "config", "devices.yaml")


def _load_dotenv():
    """Load KEY=VALUE from the repo .env into os.environ without overriding what's
    already set, so `test` finds MQTT creds in any shell."""
    path = os.path.join(REPO_ROOT, ".env")
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


# ----- list -----------------------------------------------------------------
def cmd_list(args):
    reg = DeviceRegistry.from_file(devices_path())
    if not reg.devices:
        print(f"No devices enrolled. Add one:  python3 {sys.argv[0]} add")
        return 0
    print(f"Clank controls {len(reg.devices)} device(s) — from {devices_path()}\n")
    for d in reg.devices:
        if d.type == TYPE_WLED:
            kind = "WLED strip (colour / brightness / effects)"
            extra = f"persist preset: {d.persist_preset}" if d.persist_preset is not None else ""
        else:
            kind = "on/off switch"
            extra = f"on={d.on_payload!r} off={d.off_payload!r}"
        aliases = ", ".join(d.aliases) if d.aliases else "—"
        print(f"  ● {d.name}")
        print(f"      type    : {kind}")
        print(f"      topic   : {d.topic}")
        print(f"      aliases : {aliases}")
        if extra:
            print(f"      {extra}")
        print()
    return 0


# ----- add ------------------------------------------------------------------
def _ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or (default or "")


def _yaml_str(s):
    """Quote a scalar only when YAML would otherwise misread it."""
    if s == "" or s[0] in "[]{}#&*!|>'\"%@`,:" or s != s.strip() or s.lower() in (
        "true", "false", "null", "yes", "no", "on", "off"
    ):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def _format_entry(dev: Device) -> str:
    lines = [
        f"  - name: {_yaml_str(dev.name)}",
        f"    type: {dev.type}",
        f"    topic: {_yaml_str(dev.topic)}",
    ]
    if dev.aliases:
        lines.append("    aliases: [" + ", ".join(_yaml_str(a) for a in dev.aliases) + "]")
    if dev.type == TYPE_SWITCH:
        lines.append(f'    on_payload: "{dev.on_payload}"')
        lines.append(f'    off_payload: "{dev.off_payload}"')
    elif dev.type == TYPE_WLED and dev.persist_preset is not None:
        lines.append(f"    persist_preset: {dev.persist_preset}")
    return "\n".join(lines)


def cmd_add(args):
    path = devices_path()
    reg = DeviceRegistry.from_file(path)
    existing = {d.name.lower() for d in reg.devices}

    name = args.name or _ask("Name (what you'll say)")
    if not name:
        print("A name is required.", file=sys.stderr)
        return 1
    if name.lower() in existing:
        print(f"A device called {name!r} already exists.", file=sys.stderr)
        return 1

    dtype = args.type or _ask("Type — switch or wled", "switch")
    if dtype not in (TYPE_WLED, TYPE_SWITCH):
        print(f"Type must be '{TYPE_SWITCH}' or '{TYPE_WLED}'.", file=sys.stderr)
        return 1

    topic = args.topic or _ask(
        "MQTT topic",
        "plugN/1/set" if dtype == TYPE_SWITCH else "wled/NAME/api",
    )
    if not topic or "N/1/set" in topic or "wled/NAME/api" == topic:
        print("A real MQTT topic is required.", file=sys.stderr)
        return 1

    if args.aliases is not None:
        aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    else:
        raw = _ask("Aliases (comma-separated, optional)")
        aliases = [a.strip() for a in raw.split(",") if a.strip()]

    dev = Device(
        name=name, type=dtype, topic=topic, aliases=aliases,
        on_payload=args.on or "1", off_payload=args.off or "0",
        persist_preset=args.persist,
    )
    block = _format_entry(dev)

    print("\nAbout to append this entry:\n")
    print(block + "\n")
    if not args.yes:
        if input("Write it to devices.yaml? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted; nothing written.")
            return 1

    with open(path, "r") as fh:
        content = fh.read()
    sep = "" if content.endswith("\n") else "\n"
    with open(path, "a") as fh:
        fh.write(f"{sep}\n{block}\n")

    # Re-load to validate (duplicate names, bad type, etc. raise here).
    DeviceRegistry.from_file(path)
    print(f"\nAdded '{name}'. Restart Clank to pick it up.")
    return 0


# ----- test -----------------------------------------------------------------
def cmd_test(args):
    _load_dotenv()
    import paho.mqtt.client as mqtt

    # Accept a raw topic or a registered device name.
    topic = args.target
    on, off = "1", "0"
    reg = DeviceRegistry.from_file(devices_path())
    dev = reg.get(args.target)
    if dev is None and "/" not in args.target:
        dev = reg.resolve(args.target, kind=[TYPE_SWITCH])
    if dev is not None:
        if dev.type != TYPE_SWITCH:
            print("test only toggles switch devices.", file=sys.stderr)
            return 1
        topic, on, off = dev.topic, dev.on_payload, dev.off_payload
        print(f"Testing '{dev.name}' on {topic}")
    else:
        print(f"Testing raw topic {topic}")

    user = os.getenv("MQTT_USER")
    password = os.getenv("MQTT_PASS")
    if not password:
        print("MQTT_PASS not set (and no .env found).", file=sys.stderr)
        return 1

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="clank-devtest")
    client.username_pw_set(user or "clank", password)
    client.connect(args.host, args.port, keepalive=30)
    client.loop_start()
    print(f"  -> ON  ({on})")
    client.publish(topic, on)
    time.sleep(args.seconds)
    print(f"  -> OFF ({off})")
    client.publish(topic, off)
    time.sleep(0.3)
    client.loop_stop()
    client.disconnect()
    print("done.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list", help="show enrolled devices (default)")

    a = sub.add_parser("add", help="add a device to the registry")
    a.add_argument("--name")
    a.add_argument("--type", choices=[TYPE_SWITCH, TYPE_WLED])
    a.add_argument("--topic")
    a.add_argument("--aliases", help="comma-separated")
    a.add_argument("--on", help="switch on payload (default 1)")
    a.add_argument("--off", help="switch off payload (default 0)")
    a.add_argument("--persist", type=int, help="WLED persist preset slot")
    a.add_argument("-y", "--yes", action="store_true", help="don't ask to confirm")

    t = sub.add_parser("test", help="toggle a switch on then off to identify it")
    t.add_argument("target", help="a registered switch name or a raw MQTT topic")
    t.add_argument("--host", default=os.getenv("MQTT_BROKER", "127.0.0.1"))
    t.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    t.add_argument("--seconds", type=float, default=2.0, help="how long to stay on")

    args = ap.parse_args()
    if args.cmd == "add":
        return cmd_add(args)
    if args.cmd == "test":
        return cmd_test(args)
    return cmd_list(args)


if __name__ == "__main__":
    sys.exit(main())
