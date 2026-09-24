"""Per-event alert cues for the Tk Loremaster.

Presets follow the desktop Alert Sound Studio note list and are rendered
here as short WAV files. Playback uses a Linux audio player already on
the machine. Custom files stay where the player chose them.
"""

from __future__ import annotations

import io
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path


SAMPLE_RATE = 44100
# Web Audio renders these cues very quietly. Scale the finished mix so a
# desktop speaker playing the WAV is clearly audible without clipping.
TARGET_PEAK = 0.45
MASTER_GAIN = 0.72
CUSTOM_SOUND_EXTENSIONS = frozenset({".wav", ".mp3", ".ogg", ".m4a"})
CUSTOM_SOUND_MAX_BYTES = 8 * 1024 * 1024

SOUND_KIND_ROWS = (
    ("default", "General alerts", "Raid toasts, the test banner, and other notices"),
    ("charmBreak", "Charm breaks", "Urgent recharm warning"),
    ("tell", "Incoming tells", "Direct player messages"),
    ("summon", "Summoned", "Boss summon warning"),
    ("death", "Death", "Character death"),
    ("bigHit", "Big hits", "Damage threshold warning"),
    ("nameCalled", "Name called", "Group, raid, or guild mention"),
    ("mez", "Mez urgent", "Safe window closing"),
    ("lull", "Lull urgent", "Safe window closing"),
)
SOUND_KINDS = tuple(kind for kind, _label, _detail in SOUND_KIND_ROWS)

PRESET_CHOICES = (
    ("rune", "Rune Pulse"),
    ("crystal", "Crystal Chime"),
    ("ember", "Ember Alarm"),
    ("bell", "Temple Bell"),
    ("custom", "Custom File"),
    ("silent", "Silent"),
)
PRESET_LABELS = {preset_id: label for preset_id, label in PRESET_CHOICES}
SOUND_PRESETS = tuple(PRESET_LABELS)
SYNTH_PRESETS = frozenset({"rune", "crystal", "ember", "bell"})

_DEFAULT_PRESETS = {
    "default": "rune",
    "charmBreak": "ember",
    "tell": "crystal",
    "summon": "ember",
    "death": "ember",
    "bigHit": "rune",
    "nameCalled": "crystal",
    "mez": "rune",
    "lull": "bell",
}
_SYNTH_CACHE: dict[tuple[str, str], bytes] = {}


def default_sound_profiles() -> dict[str, dict[str, str]]:
    """Return a fresh copy of the studio defaults."""
    return {
        kind: {"preset": preset, "custom_path": ""}
        for kind, preset in _DEFAULT_PRESETS.items()
    }


def normalize_sound_profiles(value) -> dict[str, dict[str, str]]:
    """Keep one valid preset and path for every studio row."""
    source = value if isinstance(value, dict) else {}
    profiles = default_sound_profiles()
    for kind, profile in profiles.items():
        candidate = source.get(kind)
        if not isinstance(candidate, dict):
            continue
        preset = candidate.get("preset")
        if preset in SOUND_PRESETS:
            profile["preset"] = preset
        custom_path = candidate.get("custom_path")
        if isinstance(custom_path, str) and len(custom_path) <= 4096:
            profile["custom_path"] = custom_path
    return profiles


def sound_kind_for_alert(log_kind: str, text: str = "") -> str:
    """Pick the studio row for one banner.

    Charm breaks and name calls are read from the banner heading because
    the log kind alone does not name them. Other rows follow the parsed kind.
    """
    heading, _, _rest = (text or "").partition(" \u2014 ")
    if log_kind == "charmBreak" or heading.startswith("CHARM BROKE"):
        return "charmBreak"
    if "CALLED YOU" in heading:
        return "nameCalled"
    kind = log_kind or ""
    if kind == "tell_in" or kind.startswith("tell"):
        return "tell"
    if kind == "summoned":
        return "summon"
    if kind == "death_you":
        return "death"
    if kind in ("melee_in", "nuke_in", "dot_in", "nonmelee_in"):
        return "bigHit"
    if kind in ("mez", "lull"):
        return kind
    return "default"


def preview_severity(kind: str) -> str:
    """Severity used when the settings row previews itself."""
    if kind in ("tell", "nameCalled"):
        return "info"
    if kind in ("bigHit", "mez", "lull"):
        return "warn"
    return "danger"


def fallback_preset(severity: str) -> str:
    """Preset used when a custom file cannot be played."""
    if severity == "danger":
        return "ember"
    if severity == "warn":
        return "rune"
    return "crystal"


_PRESET_BY_NAME = {}
for _preset_id, _label in PRESET_CHOICES:
    if _preset_id == "custom":
        continue
    _PRESET_BY_NAME[_preset_id.casefold()] = _preset_id
    _PRESET_BY_NAME[_label.casefold()] = _preset_id


def profile_for_custom_sound(value):
    """Turn one custom_alerts ``sound`` value into a studio profile.

    A blank value means the rule uses the general alert cue. A preset id
    or its label (``ember``, ``Temple Bell``, ``silent``) selects that cue.
    A path, or any name with an audio extension, plays that file.
    """
    if not isinstance(value, str):
        return None
    sound = value.strip()
    if not sound:
        return None
    preset = _PRESET_BY_NAME.get(sound.casefold())
    if preset is not None:
        return {"preset": preset, "custom_path": ""}
    suffix = Path(sound).suffix.lower()
    if (suffix in CUSTOM_SOUND_EXTENSIONS or "/" in sound or "\\" in sound
            or sound.startswith("~")):
        return {"preset": "custom", "custom_path": sound}
    return None


class AlertNotice(tuple):
    """A ``(severity, text)`` banner with an optional per-rule sound.

    The pair stays a two-item tuple so existing alert checks keep working.
    ``sound`` is the raw custom_alerts value, or None when the rule does
    not name one.
    """

    def __new__(cls, severity, text, sound=None):
        notice = tuple.__new__(cls, (severity, text))
        if isinstance(sound, str):
            sound = sound.strip() or None
        else:
            sound = None
        notice.sound = sound
        return notice


def validated_custom_path(value) -> Path | None:
    """Return a regular audio file inside the studio's size and type limits."""
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    try:
        candidate = Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if candidate.suffix.lower() not in CUSTOM_SOUND_EXTENSIONS:
        return None
    try:
        info = candidate.stat()
    except OSError:
        return None
    if (not candidate.is_file() or info.st_size <= 0
            or info.st_size > CUSTOM_SOUND_MAX_BYTES):
        return None
    return candidate


def _oscillator(wave_name: str, phase: float) -> float:
    if wave_name == "sine":
        return math.sin(2.0 * math.pi * phase)
    if wave_name == "square":
        return 1.0 if phase < 0.5 else -1.0
    if wave_name == "sawtooth":
        return 2.0 * phase - 1.0
    if phase < 0.5:
        return -1.0 + 4.0 * phase
    return 3.0 - 4.0 * phase


def _notes_for(preset: str, severity: str) -> tuple[dict, ...]:
    # Same schedule as the desktop studio's playPresetSignal.
    if preset == "crystal":
        return (
            {"at": 0.0, "hz": 880.0, "length": 0.32, "wave": "triangle", "volume": 0.11},
            {"at": 0.08, "hz": 1320.0, "length": 0.44, "wave": "sine", "volume": 0.08},
        )
    if preset == "ember":
        return (
            {"at": 0.0, "hz": 760.0, "length": 0.18, "wave": "sawtooth", "volume": 0.12},
            {"at": 0.19, "hz": 520.0, "length": 0.24, "wave": "square", "volume": 0.08},
        )
    if preset == "bell":
        return (
            {"at": 0.0, "hz": 523.25, "length": 0.7, "wave": "sine", "volume": 0.11},
            {"at": 0.0, "hz": 1046.5, "length": 0.5, "wave": "sine", "volume": 0.05},
        )
    danger = severity == "danger"
    return (
        {"at": 0.0, "hz": 620.0 if danger else 440.0, "length": 0.25,
         "wave": "sine", "volume": 0.12},
        {"at": 0.13, "hz": 820.0 if danger else 660.0, "length": 0.30,
         "wave": "triangle", "volume": 0.09},
    )


def _render_note(note: dict) -> list[float]:
    count = max(1, int(round(note["length"] * SAMPLE_RATE)))
    attack = min(count, int(round(0.012 * SAMPLE_RATE)))
    samples = [0.0] * count
    step = note["hz"] / SAMPLE_RATE
    phase = 0.0
    volume = note["volume"]
    for index in range(count):
        if index < attack:
            slope = index / attack if attack else 1.0
            envelope = 0.0001 * (volume / 0.0001) ** slope
        else:
            span = count - attack
            slope = (index - attack) / span if span else 1.0
            envelope = volume * (0.0001 / volume) ** slope
        samples[index] = _oscillator(note["wave"], phase) * envelope * MASTER_GAIN
        phase = (phase + step) % 1.0
    return samples


def _wav_bytes(samples: list[float]) -> bytes:
    frames = array("h", (
        int(round(max(-1.0, min(1.0, sample)) * 32767)) for sample in samples
    ))
    if sys.byteorder != "little":
        frames.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames.tobytes())
    return buffer.getvalue()


def synthesize_preset(preset: str, severity: str = "info") -> bytes:
    """Render one built-in cue to a mono 16-bit WAV."""
    if preset not in SYNTH_PRESETS:
        raise ValueError(f"unknown preset cue: {preset}")
    cache_key = (preset, "danger" if preset == "rune" and severity == "danger" else "")
    cached = _SYNTH_CACHE.get(cache_key)
    if cached is not None:
        return cached
    notes = _notes_for(preset, severity)
    total = max(note["at"] + note["length"] for note in notes)
    count = max(1, int(round(total * SAMPLE_RATE)))
    mix = [0.0] * count
    for note in notes:
        start = int(round(note["at"] * SAMPLE_RATE))
        for offset, sample in enumerate(_render_note(note)):
            index = start + offset
            if index < count:
                mix[index] += sample
    peak = max(abs(sample) for sample in mix) or 1.0
    scale = TARGET_PEAK / peak
    rendered = _wav_bytes([sample * scale for sample in mix])
    _SYNTH_CACHE[cache_key] = rendered
    return rendered


def player_argv(path: Path, which=shutil.which) -> list[str] | None:
    """Choose a non-blocking player command for this file, or None."""
    location = str(path)
    if path.suffix.lower() == ".wav":
        candidates = (
            ("paplay", lambda binary: [binary, location]),
            ("pw-play", lambda binary: [binary, location]),
            ("aplay", lambda binary: [binary, "-q", location]),
        )
    else:
        candidates = (
            ("ffplay", lambda binary: [
                binary, "-nodisp", "-autoexit", "-loglevel", "quiet", location]),
            ("mpv", lambda binary: [binary, "--no-video", "--really-quiet", location]),
            ("gst-play-1.0", lambda binary: [
                binary, "-q", "--no-interactive", location]),
            ("paplay", lambda binary: [binary, location]),
        )
    for name, build in candidates:
        binary = which(name)
        if binary:
            return build(binary)
    return None


def _default_runner(argv, **kwargs):
    return subprocess.Popen(argv, **kwargs)


class AlertSoundPlayer:
    """Play one cue at a time. A new cue replaces whatever is still sounding."""

    def __init__(self, runner=None, which=None, temp_dir=None):
        self._runner = runner or _default_runner
        self._which = which or shutil.which
        self._temp_dir = (Path(temp_dir) if temp_dir is not None
                          else Path(tempfile.gettempdir()) / "loremaster-sounds")
        self._child = None
        self._owned_path = None
        self._seq = 0

    def play(self, profile, severity: str = "info", bell=None) -> bool:
        """Play a profile. Ring ``bell`` only when no player can start."""
        if not isinstance(profile, dict):
            profile = {}
        preset = profile.get("preset")
        if preset not in SOUND_PRESETS:
            preset = "rune"
        if preset == "silent":
            self.stop()
            return True
        if preset == "custom":
            custom = validated_custom_path(profile.get("custom_path", ""))
            if custom is not None and self._play_path(custom, owned=False):
                return True
            preset = fallback_preset(severity)
        path = self._write_preset(preset, severity)
        if path is not None and self._play_path(path, owned=True):
            return True
        self._ring(bell)
        return False

    def stop(self) -> None:
        self._release_previous()

    def _write_preset(self, preset: str, severity: str) -> Path | None:
        try:
            payload = synthesize_preset(preset, severity)
            self._temp_dir.mkdir(parents=True, exist_ok=True)
            self._seq += 1
            path = self._temp_dir / f"{preset}-{self._seq}.wav"
            path.write_bytes(payload)
        except (OSError, ValueError):
            return None
        return path

    def _play_path(self, path: Path, *, owned: bool) -> bool:
        argv = player_argv(path, self._which)
        if not argv:
            if owned:
                self._unlink(path)
            return False
        self._release_previous()
        try:
            self._child = self._runner(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            self._child = None
            if owned:
                self._unlink(path)
            return False
        self._owned_path = path if owned else None
        return True

    def _release_previous(self) -> None:
        child = self._child
        owned = self._owned_path
        self._child = None
        self._owned_path = None
        if child is not None and child.poll() is None:
            try:
                child.kill()
            except OSError:
                pass
            child.poll()
        if owned is not None:
            self._unlink(owned)

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _ring(bell) -> None:
        if bell is None:
            return
        try:
            bell()
        except Exception:
            pass


_PLAYER = AlertSoundPlayer()


def play_alert_sound(profile, severity: str = "info", bell=None) -> bool:
    """Play through the process-wide player."""
    return _PLAYER.play(profile, severity, bell=bell)


def stop_alert_playback() -> None:
    """Stop the cue started by :func:`play_alert_sound`, if it is still going."""
    _PLAYER.stop()
