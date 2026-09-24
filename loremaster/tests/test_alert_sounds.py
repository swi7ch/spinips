import io
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

import alert_sounds  # noqa: E402


def _which_factory(available):
    def which(name):
        if name in available:
            return f"/usr/bin/{name}"
        return None
    return which


class DummyProcess:
    def __init__(self):
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class SoundProfileTests(unittest.TestCase):
    def test_missing_profiles_use_the_studio_defaults(self):
        profiles = alert_sounds.normalize_sound_profiles(None)
        self.assertEqual(set(profiles), set(alert_sounds.SOUND_KINDS))
        self.assertEqual(profiles["default"]["preset"], "rune")
        self.assertEqual(profiles["charmBreak"]["preset"], "ember")
        self.assertEqual(profiles["tell"]["preset"], "crystal")
        self.assertEqual(profiles["summon"]["preset"], "ember")
        self.assertEqual(profiles["death"]["preset"], "ember")
        self.assertEqual(profiles["bigHit"]["preset"], "rune")
        self.assertEqual(profiles["nameCalled"]["preset"], "crystal")
        self.assertEqual(profiles["mez"]["preset"], "rune")
        self.assertEqual(profiles["lull"]["preset"], "bell")
        self.assertTrue(all(row["custom_path"] == "" for row in profiles.values()))

    def test_invalid_entries_fall_back_without_dropping_real_choices(self):
        profiles = alert_sounds.normalize_sound_profiles({
            "lull": {"preset": "silent", "custom_path": "/tmp/lull.wav"},
            "tell": {"preset": "nope", "custom_path": 12},
            "death": {"preset": "custom", "custom_path": "x" * 4097},
            "debuff": {"preset": "bell", "custom_path": "/tmp/debuff.wav"},
            "mez": "rune",
        })
        self.assertEqual(profiles["lull"], {
            "preset": "silent", "custom_path": "/tmp/lull.wav"})
        self.assertEqual(profiles["tell"]["preset"], "crystal")
        self.assertEqual(profiles["tell"]["custom_path"], "")
        self.assertEqual(profiles["death"]["preset"], "custom")
        self.assertEqual(profiles["death"]["custom_path"], "")
        self.assertNotIn("debuff", profiles)
        self.assertEqual(profiles["mez"]["preset"], "rune")

    def test_sound_kind_follows_the_banner_heading_then_the_log_kind(self):
        cases = [
            ("spell_fade", "CHARM BROKE \u2014 A ROCK GOLEM", "charmBreak"),
            ("", "BOB CALLED YOU \u2014 heal", "nameCalled"),
            ("tell_in", "TELL \u2014 Foo: CALLED YOU later", "tell"),
            ("tell_in", "TELL \u2014 Foo: hi", "tell"),
            ("summoned", "YOU HAVE BEEN SUMMONED", "summon"),
            ("death_you", "YOU DIED \u2014 a dragon", "death"),
            ("melee_in", "BIG HIT \u2014 900", "bigHit"),
            ("nuke_in", "BIG HIT \u2014 1", "bigHit"),
            ("dot_in", "BIG HIT \u2014 1", "bigHit"),
            ("nonmelee_in", "BIG HIT \u2014 1", "bigHit"),
            ("mez", "", "mez"),
            ("lull", "", "lull"),
            ("", "CLICK-THROUGH ON \u2014 restore mouse", "default"),
            ("zone", "Entered the arena", "default"),
        ]
        for log_kind, text, expected in cases:
            with self.subTest(log_kind=log_kind, text=text):
                self.assertEqual(
                    alert_sounds.sound_kind_for_alert(log_kind, text), expected)

    def test_custom_rule_sound_accepts_a_preset_a_label_or_a_path(self):
        self.assertIsNone(alert_sounds.profile_for_custom_sound(None))
        self.assertIsNone(alert_sounds.profile_for_custom_sound("  "))
        self.assertIsNone(alert_sounds.profile_for_custom_sound("nope"))
        self.assertEqual(
            alert_sounds.profile_for_custom_sound(" EMBER "),
            {"preset": "ember", "custom_path": ""})
        self.assertEqual(
            alert_sounds.profile_for_custom_sound("Temple Bell"),
            {"preset": "bell", "custom_path": ""})
        self.assertEqual(
            alert_sounds.profile_for_custom_sound("silent"),
            {"preset": "silent", "custom_path": ""})
        self.assertEqual(
            alert_sounds.profile_for_custom_sound("/home/you/sounds/rampage.wav"),
            {"preset": "custom", "custom_path": "/home/you/sounds/rampage.wav"})
        self.assertEqual(
            alert_sounds.profile_for_custom_sound("rampage.ogg"),
            {"preset": "custom", "custom_path": "rampage.ogg"})

    def test_preview_severity_matches_the_studio_rows(self):
        self.assertEqual(alert_sounds.preview_severity("tell"), "info")
        self.assertEqual(alert_sounds.preview_severity("nameCalled"), "info")
        self.assertEqual(alert_sounds.preview_severity("bigHit"), "warn")
        self.assertEqual(alert_sounds.preview_severity("mez"), "warn")
        self.assertEqual(alert_sounds.preview_severity("lull"), "warn")
        self.assertEqual(alert_sounds.preview_severity("charmBreak"), "danger")
        self.assertEqual(alert_sounds.preview_severity("default"), "danger")


class CustomPathTests(unittest.TestCase):
    def test_accepts_a_small_audio_file_and_rejects_the_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "Chime.WAV"
            good.write_bytes(b"RIFFnot-really-a-wav")
            spaced = root / "my cue.ogg"
            spaced.write_bytes(b"OggS")
            empty = root / "empty.mp3"
            empty.write_bytes(b"")
            huge = root / "huge.m4a"
            with huge.open("wb") as handle:
                handle.truncate(alert_sounds.CUSTOM_SOUND_MAX_BYTES + 1)
            text = root / "notes.txt"
            text.write_bytes(b"hello")
            folder = root / "folder.wav"
            folder.mkdir()

            self.assertEqual(
                alert_sounds.validated_custom_path(str(good)), good.resolve())
            self.assertEqual(
                alert_sounds.validated_custom_path(str(spaced)), spaced.resolve())
            self.assertIsNone(alert_sounds.validated_custom_path(str(empty)))
            self.assertIsNone(alert_sounds.validated_custom_path(str(huge)))
            self.assertIsNone(alert_sounds.validated_custom_path(str(text)))
            self.assertIsNone(alert_sounds.validated_custom_path(str(folder)))
            self.assertIsNone(alert_sounds.validated_custom_path(str(root / "missing.wav")))
            self.assertIsNone(alert_sounds.validated_custom_path(""))
            self.assertIsNone(alert_sounds.validated_custom_path("x" * 4097))
            self.assertIsNone(alert_sounds.validated_custom_path(None))


class SynthesisTests(unittest.TestCase):
    def _wave(self, preset, severity="info"):
        payload = alert_sounds.synthesize_preset(preset, severity)
        with wave.open(io.BytesIO(payload), "rb") as handle:
            frames = handle.readframes(handle.getnframes())
            return handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), (
                handle.getnframes() / handle.getframerate()
            ), frames

    def test_each_preset_is_a_short_audible_mono_wav(self):
        expected = {"crystal": 0.52, "ember": 0.43, "bell": 0.70, "rune": 0.43}
        for preset, seconds in expected.items():
            with self.subTest(preset=preset):
                channels, width, rate, duration, frames = self._wave(preset)
                self.assertEqual((channels, width, rate), (1, 2, 44100))
                self.assertAlmostEqual(duration, seconds, delta=0.002)
                samples = struct.unpack("<" + "h" * (len(frames) // 2), frames)
                peak = max(abs(sample) for sample in samples) / 32767
                self.assertGreater(peak, 0.2)
                self.assertLess(peak, 0.46)

    def test_danger_rune_is_a_different_cue_from_the_quieter_one(self):
        self.assertNotEqual(
            alert_sounds.synthesize_preset("rune", "danger"),
            alert_sounds.synthesize_preset("rune", "info"))
        self.assertEqual(
            alert_sounds.synthesize_preset("rune", "warn"),
            alert_sounds.synthesize_preset("rune", "info"))


class PlayerSelectionTests(unittest.TestCase):
    def test_wav_prefers_paplay_and_compressed_audio_prefers_ffplay(self):
        which = _which_factory({"paplay", "ffplay", "aplay", "mpv"})
        wav = alert_sounds.player_argv(Path("/tmp/cue.wav"), which)
        mp3 = alert_sounds.player_argv(Path("/tmp/cue.mp3"), which)
        self.assertEqual(wav, ["/usr/bin/paplay", "/tmp/cue.wav"])
        self.assertEqual(mp3[0], "/usr/bin/ffplay")
        self.assertIn("/tmp/cue.mp3", mp3)
        self.assertIn("-nodisp", mp3)

    def test_wav_falls_through_to_aplay_and_compressed_to_paplay(self):
        wav = alert_sounds.player_argv(
            Path("/tmp/cue.wav"), _which_factory({"aplay"}))
        ogg = alert_sounds.player_argv(
            Path("/tmp/cue.ogg"), _which_factory({"paplay"}))
        self.assertEqual(wav, ["/usr/bin/aplay", "-q", "/tmp/cue.wav"])
        self.assertEqual(ogg, ["/usr/bin/paplay", "/tmp/cue.ogg"])
        self.assertIsNone(alert_sounds.player_argv(
            Path("/tmp/cue.wav"), _which_factory(())))

    def _player(self, tmp, which, calls):
        def runner(argv, **_kwargs):
            calls.append(argv)
            return DummyProcess()
        return alert_sounds.AlertSoundPlayer(
            runner=runner, which=which, temp_dir=tmp)

    def test_silent_plays_nothing_and_a_second_cue_stops_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            processes = []

            def runner(argv, **_kwargs):
                calls.append(argv)
                process = DummyProcess()
                processes.append(process)
                return process

            player = alert_sounds.AlertSoundPlayer(
                runner=runner, which=_which_factory({"paplay"}), temp_dir=tmp)
            rung = []
            self.assertTrue(player.play(
                {"preset": "silent", "custom_path": ""},
                bell=lambda: rung.append(1)))
            self.assertEqual(calls, [])
            self.assertEqual(rung, [])
            self.assertTrue(player.play(
                {"preset": "rune", "custom_path": ""}, "info"))
            self.assertTrue(player.play(
                {"preset": "bell", "custom_path": ""}, "info"))
            self.assertEqual(len(calls), 2)
            self.assertTrue(calls[0][0].endswith("paplay"))
            self.assertTrue(processes[0].killed)
            self.assertFalse(processes[1].killed)

    def test_missing_custom_file_falls_back_to_the_severity_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            player = self._player(
                tmp, _which_factory({"paplay"}), calls)
            self.assertTrue(player.play({
                "preset": "custom",
                "custom_path": str(Path(tmp) / "gone.wav"),
            }, "danger"))
            played = Path(calls[0][-1]).read_bytes()
            self.assertEqual(played, alert_sounds.synthesize_preset("ember", "danger"))
            self.assertNotEqual(
                played, alert_sounds.synthesize_preset("crystal", "info"))

    def test_custom_wav_is_passed_through_and_a_dead_player_rings_the_bell(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "my cue.wav"
            custom.write_bytes(b"RIFFfake-but-accepted")
            calls = []
            player = self._player(tmp, _which_factory({"paplay"}), calls)
            self.assertTrue(player.play(
                {"preset": "custom", "custom_path": str(custom)}, "info"))
            self.assertEqual(calls[0], ["/usr/bin/paplay", str(custom.resolve())])

            rung = []
            silent_player = self._player(tmp, _which_factory({}), calls)
            self.assertFalse(silent_player.play(
                {"preset": "rune", "custom_path": ""}, "warn",
                bell=lambda: rung.append("bell")))
            self.assertEqual(rung, ["bell"])

    def test_runner_failure_falls_through_to_the_bell(self):
        with tempfile.TemporaryDirectory() as tmp:
            def runner(_argv, **_kwargs):
                raise OSError("player missing")
            player = alert_sounds.AlertSoundPlayer(
                runner=runner, which=_which_factory({"paplay"}), temp_dir=tmp)
            rung = []
            self.assertFalse(player.play(
                {"preset": "crystal", "custom_path": ""},
                bell=lambda: rung.append(1)))
            self.assertEqual(rung, [1])


class ConfigIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "loremaster_alert_sound_config", LOREMASTER_DIR / "loremaster.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.loremaster = module

    def test_load_config_fills_studio_defaults_for_an_older_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loremaster_config.json"
            path.write_text('{"alert_sound": false}', encoding="utf-8")
            original = self.loremaster.CONFIG_PATH
            self.loremaster.CONFIG_PATH = path
            try:
                config = self.loremaster.load_config()
            finally:
                self.loremaster.CONFIG_PATH = original
        self.assertFalse(config["alert_sound"])
        self.assertEqual(
            config["sound_profiles"]["charmBreak"]["preset"], "ember")
        self.assertEqual(config["sound_profiles"]["lull"]["preset"], "bell")

    def test_charm_break_banner_text_selects_its_studio_row(self):
        event = self.loremaster.CharmBreakEvent(
            event_id=1, pet_name="a rock golem",
            charm_spell="Cajoling Whispers",
            occurred_at=self.loremaster.datetime.now())
        banners = self.loremaster.check_alerts(
            "spell_fade", {}, "", "Soandso",
            {"alerts_enabled": True}, (event,))
        self.assertEqual(
            alert_sounds.sound_kind_for_alert("spell_fade", banners[0][1]),
            "charmBreak")


if __name__ == "__main__":
    unittest.main()
