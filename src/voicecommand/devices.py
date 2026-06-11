"""Device registry — the single source of truth for what Clank can control.

Each controllable thing (the WLED RGB strip, an on/off smart plug, ...) is one
entry in ``config/devices.yaml``. Adding hardware is therefore a config edit +
restart: no code change, and no central firmware "sketch" to touch (WLED and
OpenBeken/Tasmota are independent MQTT devices; Clank just needs each one's
spoken name, type, and MQTT topic).

The registry does three jobs:
  * resolve a spoken/garbled target name to a device (alias + fuzzy match),
  * describe the available devices for the LLM system prompt at runtime, and
  * carry the metadata the dispatcher needs to render an MQTT payload.

Payload *rendering* deliberately stays in the control layer (it's device-type
specific and, for WLED, needs the colour/effect tables and persist settings);
the registry only resolves and describes.
"""

import os
import difflib
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Iterable

import yaml

logger = logging.getLogger(__name__)

# Device types.
TYPE_WLED = "wled"      # colour / brightness / effects, controlled via WLED JSON
TYPE_SWITCH = "switch"  # plain on/off plug (OpenBeken / Tasmota), raw payload

# Which device types each action may target.
ACTION_TYPES = {
    "set_rgb": {TYPE_WLED},
    "set_switch": {TYPE_SWITCH},
}


@dataclass
class Device:
    """One controllable device, loaded from a ``devices.yaml`` entry."""

    name: str                         # canonical spoken name ("strip", "desk lamp")
    type: str                         # TYPE_WLED | TYPE_SWITCH
    topic: str                        # MQTT topic commands are published to
    aliases: List[str] = field(default_factory=list)
    # switch (OpenBeken/Tasmota) payloads — what to send for on / off.
    on_payload: str = "ON"
    off_payload: str = "OFF"
    # WLED only: snapshot the look into this preset slot after each command so a
    # mains power-cycle restores it. None = fall back to the global
    # mqtt.persist_preset; 0 disables.
    persist_preset: Optional[int] = None

    def labels(self) -> List[str]:
        """All names this device answers to (canonical + aliases), lowercased."""
        return [self.name.lower()] + [a.lower() for a in self.aliases]


class DeviceRegistry:
    """Loads devices.yaml and resolves spoken names to :class:`Device` objects."""

    def __init__(self, devices: List[Device]):
        self.devices = devices
        names = [d.name for d in devices]
        if len(names) != len(set(n.lower() for n in names)):
            raise ValueError(f"Duplicate device name in registry: {names}")

    # ----- loading ---------------------------------------------------------
    @classmethod
    def from_file(cls, path: str) -> "DeviceRegistry":
        """Load a registry from a YAML file. A missing/empty file yields an
        empty registry (Clank still runs; it just controls nothing)."""
        if not path or not os.path.exists(path):
            logger.warning("Device registry not found at %s; no devices loaded", path)
            return cls([])
        with open(path, "r") as fh:
            data = yaml.safe_load(fh) or {}
        entries = data.get("devices") or []
        devices: List[Device] = []
        for i, entry in enumerate(entries):
            try:
                devices.append(cls._device_from_entry(entry))
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"Invalid device entry #{i + 1} in {path}: {e}")
        logger.info(
            "Device registry: %d device(s) [%s]",
            len(devices), ", ".join(d.name for d in devices),
        )
        return cls(devices)

    @staticmethod
    def _device_from_entry(entry: dict) -> Device:
        if not isinstance(entry, dict):
            raise TypeError("device entry must be a mapping")
        name = entry["name"]
        dtype = entry["type"]
        topic = entry["topic"]
        if dtype not in (TYPE_WLED, TYPE_SWITCH):
            raise ValueError(f"unknown type {dtype!r} (use {TYPE_WLED} or {TYPE_SWITCH})")
        if not isinstance(name, str) or not isinstance(topic, str):
            raise ValueError("name and topic must be strings")
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError("aliases must be a list")
        return Device(
            name=name.strip(),
            type=dtype,
            topic=topic.strip(),
            aliases=[str(a).strip() for a in aliases],
            on_payload=str(entry.get("on_payload", "ON")),
            off_payload=str(entry.get("off_payload", "OFF")),
            persist_preset=entry.get("persist_preset"),
        )

    # ----- resolution ------------------------------------------------------
    def resolve(self, name: Optional[str], kind: Optional[Iterable[str]] = None) -> Optional[Device]:
        """Resolve a (possibly garbled or absent) target name to a device.

        ``kind`` restricts candidates to those device types (e.g. an action's
        allowed types). When ``name`` is empty and exactly one candidate of the
        right kind exists, that device is returned — so a single-strip setup
        with no explicit target keeps working. Returns None if nothing matches
        or the choice is ambiguous.
        """
        candidates = self.devices
        if kind:
            kind = set(kind)
            typed = [d for d in candidates if d.type in kind]
            # Only narrow when the kind is actually present; otherwise leave the
            # full list so a clearly-named target can still be found and the
            # caller can report the type mismatch.
            if typed:
                candidates = typed

        if not name or not name.strip():
            return candidates[0] if len(candidates) == 1 else None

        n = name.lower().strip()
        # 1. exact name/alias hit.
        for d in candidates:
            if n in d.labels():
                return d
        # 2. substring or fuzzy match (handles STT mishearings / partial names).
        best, best_score = None, 0.0
        for d in candidates:
            for label in d.labels():
                score = difflib.SequenceMatcher(None, n, label).ratio()
                if label in n or n in label:
                    score = max(score, 0.9)
                if score > best_score:
                    best, best_score = d, score
        return best if best_score >= 0.6 else None

    def get(self, name: Optional[str]) -> Optional[Device]:
        """Look up a device by its exact canonical name (as returned by
        validation after a target is resolved). Returns None if absent."""
        if not name:
            return None
        n = name.lower().strip()
        for d in self.devices:
            if d.name.lower() == n:
                return d
        return None

    def has_type(self, dtype: str) -> bool:
        return any(d.type == dtype for d in self.devices)

    # ----- prompt ----------------------------------------------------------
    def prompt_block(self) -> str:
        """A human-readable device list to inject into the LLM system prompt."""
        if not self.devices:
            return "(no devices are currently configured)"
        lines = []
        for d in self.devices:
            alias_str = ", ".join(d.aliases) if d.aliases else "—"
            if d.type == TYPE_WLED:
                kind = 'RGB light strip; action "set_rgb"; supports colour, brightness, effects, on/off'
            else:
                kind = 'on/off smart plug; action "set_switch"; supports on/off only'
            lines.append(f'- "{d.name}" ({kind}). Also called: {alias_str}.')
        return "\n".join(lines)
