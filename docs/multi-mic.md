# Listening to two microphones at once (multi-room)

This is a **niche, Linux/PipeWire-specific** setup. The default Clank install
listens to a single microphone (your OS default input) and needs none of this.

Use this if you want Clank to hear from **two mics simultaneously** — e.g. an
internal mic downstairs and a USB mic upstairs — by mixing both into one virtual
capture source. Whichever mic picks up "hey clank" triggers it.

> Alternative: if your second mic is on a **different machine**, don't combine
> audio — run a second Clank instance on that machine pointed at the same MQTT
> broker. Each node handles its own room. This page is only for two mics on
> **one** machine.

## How it works

PipeWire (via its PulseAudio compatibility layer) creates a **null sink** called
`combined_mics`, loops both microphones into it, and exposes its monitor
(`combined_mics.monitor`) as a source carrying both mics mixed together. Clank
then captures from that monitor.

Three pieces are needed:

1. a PipeWire drop-in that builds the combined source on login;
2. `audio.input_device: "pulse"` so Clank captures through PipeWire (not raw ALSA);
3. `PULSE_SOURCE=combined_mics.monitor` so libpulse opens the combined source.

## 1. Create the combined source

Find your two microphones' source names:

```fish
pactl list sources short
```

Look for the `alsa_input.*` entries (ignore `*.monitor` — those are output
monitors). Then create the drop-in file
`~/.config/pipewire/pipewire-pulse.conf.d/combine-mics.conf` with **your** two
source names substituted:

```
# Combines two mics into one virtual source (combined_mics.monitor)
# so Clank can hear from both at once.
pulse.cmd = [
    { cmd = "load-module" args = "module-null-sink sink_name=combined_mics sink_properties='node.description=Combined Microphones'" }
    { cmd = "load-module" args = "module-loopback source=alsa_input.pci-0000_00_1f.3.analog-stereo sink=combined_mics latency_msec=1" }
    { cmd = "load-module" args = "module-loopback source=alsa_input.usb-Generic_USB_AUDIO_20230714100308-00.analog-stereo sink=combined_mics latency_msec=1" }
]
```

Replace the two `source=alsa_input....` names with yours. Restart PipeWire's
pulse layer to load it (or just log out and back in):

```fish
systemctl --user restart pipewire-pulse
```

Verify the combined source now exists:

```fish
pactl list sources short | grep combined_mics
```

This auto-loads on every login — no service or cron job needed. If a mic isn't
plugged in when PipeWire starts, that one loopback fails silently and Clank
still hears the other mic.

## 2. Point Clank at PipeWire and select the combined source

Add these two lines to your `.env` (it is gitignored, so this stays
machine-specific and does not affect other installs):

```sh
CLANK_INPUT_DEVICE=pulse
PULSE_SOURCE=combined_mics.monitor
```

`CLANK_INPUT_DEVICE=pulse` overrides `audio.input_device` from `default.yaml`
and tells Clank to open the PulseAudio/PipeWire device instead of raw ALSA —
the raw ALSA `"default"` device ignores `PULSE_SOURCE`, so the combined virtual
source would never be selected without it.

`PULSE_SOURCE` is read by libpulse and tells PipeWire which source to open.
`start_clank.sh` already exports everything in `.env` with `set -a`, so no
changes to the script are needed.

Restart Clank. Use `--oww-debug` (or watch the logs) to confirm the wake score
spikes when you speak into *either* mic.

## Why `combined_mics` shows up as an *output* device

Expected. A null sink is technically an output — both mics "play into" it. Clank
reads from its **monitor**, which is the passthrough of everything routed in.
The sink itself is just internal plumbing; nothing actually plays through it.

## Tuning the noise floor

Mixing two mics at 100% each **sums both rooms' background noise** continuously,
which can hurt wake-word recall. Balance the levels — turn the noisier room's mic
down so its ambient noise doesn't drown the wake word:

```fish
pactl list sink-inputs short                 # find each loopback's index
pactl set-sink-input-volume <index> 50%      # e.g. quiet the AC-noisy room
```

You may also need a slightly lower `audio.oww_threshold` to catch borderline
hits on the mixed signal (the bundled config already runs sensitive).
