"""Tests for the compact Rune Seed HUD and its potential-mote tracker."""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))
SPEC = importlib.util.spec_from_file_location(
    "loremaster_hud_test_app", LOREMASTER_DIR / "loremaster.py")
LOREMASTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LOREMASTER
SPEC.loader.exec_module(LOREMASTER)


class MoteTrackerTests(unittest.TestCase):
    GRADES = ("Infinitesimal", "Minor", "Lesser", None, "Major", "Greater",
              "Superior", "Grand", "Ascendant", "Infinite")
    EXP = (1, 1, 2, 4, 5, 6, 7, 8, 9, 10)

    def name(self, grade, plural=False):
        stem = "Motes" if plural else "Mote"
        return f"{stem} of Potential" if grade is None else (
            f"{stem} of {grade} Potential")

    def test_all_ten_in_game_grades_bucket_in_tier_order(self):
        # The client names these items in the plural, but a loot line reads
        # "You have looted a <name>", so both spellings reach the ledger.
        for plural in (False, True):
            with self.subTest(plural=plural):
                loot = {self.name(g, plural): i + 1
                        for i, g in enumerate(self.GRADES)}
                self.assertEqual(
                    LOREMASTER.mote_tier_counts(loot), list(range(1, 11)))

    def test_infinite_and_infinitesimal_never_merge(self):
        # They share a prefix, so a prefix match would silently fold the rarest
        # grade into the most common one.
        self.assertEqual(
            LOREMASTER.mote_tier_counts(
                {"Mote of Infinitesimal Potential": 4})[0], 4)
        self.assertEqual(
            LOREMASTER.mote_tier_counts(
                {"Mote of Infinite Potential": 4})[9], 4)

    def test_exp_total_uses_each_grade_own_value(self):
        self.assertEqual(LOREMASTER.MOTE_TIER_EXP, self.EXP)
        self.assertEqual(LOREMASTER.mote_exp_total([1] * 10), sum(self.EXP))
        self.assertEqual(LOREMASTER.mote_exp_total([0] * 10), 0)
        self.assertEqual(LOREMASTER.mote_exp_total([2] + [0] * 9), 2)
        self.assertEqual(LOREMASTER.mote_exp_total([0] * 9 + [3]), 30)

    def test_casing_and_spacing_do_not_split_a_tier(self):
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "motes of MINOR potential": 2,
                "  Mote  of  Minor  Potential  ": 3,
            }),
            [0, 5] + [0] * 8,
        )

    def test_unrelated_and_near_miss_loot_is_never_counted(self):
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Froglok Fine Mesh": 9,
                "Mote of Potential Greatness": 9,
                "Shard of Minor Potential": 9,
                "Motes of Major Potentials": 9,
                "Mote of Supreme Potential": 9,
                "Mote of Infinites Potential": 9,
            }),
            [0] * 10,
        )
    def test_malformed_ledger_entries_cannot_crash_the_compact_readout(self):
        for loot in (None, [], "loot", 7):
            with self.subTest(loot=loot):
                self.assertEqual(
                    LOREMASTER.mote_tier_counts(loot), [0] * 10)
        self.assertEqual(
            LOREMASTER.mote_tier_counts({
                "Mote of Minor Potential": None,
                "Mote of Major Potential": "many",
                "Mote of Lesser Potential": -4,
                "Mote of Potential": 3,
            }),
            [0, 0, 0, 3] + [0] * 6,
        )

    def test_readout_stops_at_the_highest_grade_that_dropped(self):
        # Printing all ten grades would be a twenty-character cell; the cell
        # has to stay slim until a rare grade earns the space.
        self.assertEqual(
            LOREMASTER.fmt_mote_tiers([27, 32, 3, 2, 1] + [0] * 5),
            "27/32/3/2/1")
        self.assertEqual(LOREMASTER.fmt_mote_tiers([5] + [0] * 9), "5")
        self.assertEqual(
            LOREMASTER.fmt_mote_tiers([0] * 9 + [1]), "0/0/0/0/0/0/0/0/0/1")

    def test_readout_is_a_dash_when_nothing_has_dropped(self):
        for counts in ([0] * 10, [], None):
            with self.subTest(counts=counts):
                self.assertEqual(LOREMASTER.fmt_mote_tiers(counts), "\u2014")

    def test_tracker_is_a_first_class_card_with_a_seed_label(self):
        self.assertEqual(LOREMASTER.MINI_CARD_LABELS["motes"], "MOTES")
        self.assertEqual(len(LOREMASTER.MOTE_TIERS), 10)
        self.assertEqual(len(LOREMASTER.MOTE_TIER_LABELS), 10)
        self.assertEqual(len(LOREMASTER.MOTE_GRADES), 10)
        # Exactly one grade carries no grade word: the unqualified fourth.
        self.assertEqual(
            [i for i, g in enumerate(LOREMASTER.MOTE_GRADES) if not g], [3])


class DetailActionRowTests(unittest.TestCase):
    """A detail row can carry an action, following the meter row's encoding.

    Detail rows are plain ``(kind, left, right)`` data with no channel for a
    callback, so the action name rides in the kind the way a meter's fill
    percentage already does. A malformed or unknown kind must read as "no
    action" rather than building a button that does nothing when clicked.
    """

    def test_an_action_row_names_its_action(self):
        self.assertEqual(
            LOREMASTER.detail_action_name("action:reset-motes"), "reset-motes")

    def test_an_ordinary_row_names_no_action(self):
        for kind in ("row", "head", "line", "meter:0.5", "", None):
            with self.subTest(kind=kind):
                self.assertEqual(LOREMASTER.detail_action_name(kind), "")

    def test_an_action_without_a_name_is_not_an_action(self):
        for kind in ("action:", "action:   "):
            with self.subTest(kind=kind):
                self.assertEqual(LOREMASTER.detail_action_name(kind), "")

    def test_the_mote_card_offers_a_reset(self):
        self.assertEqual(LOREMASTER.MOTE_RESET_ACTION, "reset-motes")


class SecondaryWindowPlacementTests(unittest.TestCase):
    def test_tall_settings_surface_stays_inside_owners_monitor(self):
        position = LOREMASTER.adjacent_window_position(
            (3334, 1106, 94, 50), (877, 1049), (0, 0, 3440, 1400))
        self.assertEqual(position, (2441, 343))

    def test_surface_falls_right_when_left_side_is_unavailable(self):
        position = LOREMASTER.adjacent_window_position(
            (10, 100, 94, 50), (300, 400), (0, 0, 1920, 1040))
        self.assertEqual(position, (120, 100))


class MoteAcquisitionTests(unittest.TestCase):
    """A mote has to be counted however the client announces it.

    The tracker first derived its counts from the loot ledger, and the ledger
    understood exactly two sentences - both requiring the article "a"/"an".
    A stacked drop or a plain "You receive ..." system line therefore never
    reached it at all, which is why a looted Mote of Major Potential could go
    unreported.
    """

    def feed(self, *messages):
        stats = LOREMASTER.SessionStats("Spin")
        for index, message in enumerate(messages):
            parsed = LOREMASTER.parse_line(
                f"[Wed Jul 30 01:00:{index:02d} 2026] {message}")
            if parsed:
                stats.apply(*parsed)
        return stats.motes

    def test_corpse_loot_line_counts(self):
        self.assertEqual(
            self.feed("--You have looted a Mote of Major Potential.--"),
            [0, 0, 0, 0, 1] + [0] * 5)
        self.assertEqual(
            self.feed("--You have looted a Mote of Major Potential from a "
                      "gnoll pup's corpse.--"),
            [0, 0, 0, 0, 1] + [0] * 5)

    def test_a_stack_counts_its_whole_stack(self):
        self.assertEqual(
            self.feed("--You have looted 5 Motes of Minor Potential.--"),
            [0, 5] + [0] * 8)

    def test_system_lines_without_dashes_or_an_article_count(self):
        for message in (
            "You receive a Mote of Major Potential.",
            "You have received a Mote of Major Potential.",
            "You gain a Mote of Major Potential!",
            "You have gained a Mote of Major Potential.",
            "You acquired a Mote of Major Potential.",
            "You found a Mote of Major Potential",
            "You looted Mote of Major Potential.",
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    self.feed(message), [0, 0, 0, 0, 1] + [0] * 5)

    def test_quantity_is_honoured_on_a_system_line(self):
        self.assertEqual(
            self.feed("You have gained 3 Motes of Greater Potential."),
            [0] * 5 + [3] + [0] * 4)

    def test_a_single_line_is_never_counted_twice(self):
        # A corpse-loot line matches the loot pattern; the last-resort mote
        # pattern must not also claim it.
        self.assertEqual(
            self.feed("--You have looted a Mote of Infinite Potential.--"),
            [0] * 9 + [1])

    def test_chat_naming_the_item_is_not_a_mote_you_looted(self):
        for message in (
            "Aria tells you, 'You looted a Mote of Major Potential'",
            "You tell the guild, 'you receive a mote of major potential'",
            "Aria says, 'I found a Mote of Infinite Potential'",
        ):
            with self.subTest(message=message):
                self.assertEqual(self.feed(message), [0] * 10)

    def test_ordinary_loot_still_reaches_the_ledger_untouched(self):
        stats = LOREMASTER.SessionStats("Spin")
        parsed = LOREMASTER.parse_line(
            "[Wed Jul 30 01:00:00 2026] --You have looted a Froglok Fine "
            "Mesh from a froglok shin knight's corpse.--")
        stats.apply(*parsed)
        self.assertEqual(stats.loot["Froglok Fine Mesh"], 1)
        self.assertEqual(stats.motes, [0] * 10)


class MoteSessionResetTests(unittest.TestCase):
    """A mote count answers "this session", so a login has to start it over.

    The count is a farming readout, not a lifetime total. Logging back in is
    the one boundary the log states outright, and it must not disturb the rest
    of the ledger: damage, kills and loot deliberately survive a relog.
    """

    LOGIN = "Welcome to EverQuest Legends!"
    MOTE = "--You have looted a Mote of Major Potential.--"

    def feed(self, *messages):
        stats = LOREMASTER.SessionStats("Spin")
        for index, message in enumerate(messages):
            parsed = LOREMASTER.parse_line(
                f"[Wed Jul 30 01:00:{index:02d} 2026] {message}")
            if parsed:
                stats.apply(*parsed)
        return stats

    def test_a_login_clears_motes_gathered_before_it(self):
        self.assertEqual(self.feed(self.MOTE, self.LOGIN).motes, [0] * 10)

    def test_motes_looted_after_a_login_are_counted(self):
        stats = self.feed(self.MOTE, self.LOGIN, self.MOTE, self.MOTE)
        self.assertEqual(stats.motes, [0, 0, 0, 0, 2] + [0] * 5)

    def test_the_plain_everquest_login_line_also_starts_a_session(self):
        self.assertEqual(
            self.feed(self.MOTE, "Welcome to EverQuest!").motes, [0] * 10)

    def test_a_login_leaves_the_rest_of_the_ledger_alone(self):
        stats = self.feed(
            "You slash a rat for 5 points of damage.",
            "--You have looted a Rusty Dagger from a rat's corpse.--",
            self.MOTE,
            self.LOGIN)
        self.assertEqual(stats.motes, [0] * 10)
        self.assertEqual(stats.snapshot()["melee_dealt"], 5)
        self.assertEqual(stats.loot["Rusty Dagger"], 1)

    def test_someone_saying_the_login_line_in_chat_is_not_a_login(self):
        for message in (
            "Aria tells you, 'Welcome to EverQuest Legends!'",
            "You say, 'Welcome to EverQuest Legends!'",
        ):
            with self.subTest(message=message):
                self.assertEqual(
                    self.feed(self.MOTE, message).motes,
                    [0, 0, 0, 0, 1] + [0] * 5)

    def test_a_manual_reset_clears_only_the_motes(self):
        stats = self.feed("You slash a rat for 5 points of damage.", self.MOTE)
        stats.reset_motes()
        self.assertEqual(stats.motes, [0] * 10)
        self.assertEqual(stats.snapshot()["melee_dealt"], 5)

    def test_the_mote_session_stamp_moves_to_the_login(self):
        stats = self.feed(self.MOTE, self.LOGIN)
        self.assertEqual(
            stats.snapshot()["motes_started_at"],
            datetime(2026, 7, 30, 1, 0, 1))

    def test_the_snapshot_describes_the_deck_it_carries(self):
        """A renderer must not need a second copy of the grade table."""
        snap = self.feed(self.MOTE, self.MOTE).snapshot()
        self.assertEqual(snap["mote_labels"], LOREMASTER.MOTE_TIER_LABELS)
        self.assertEqual(snap["mote_potential"], 10)

    def test_the_mote_session_stamp_starts_with_the_session(self):
        stats = self.feed(self.MOTE)
        self.assertEqual(
            stats.snapshot()["motes_started_at"],
            stats.snapshot()["session_start"])


class RuneSeedGeometryTests(unittest.TestCase):
    def test_seed_matches_the_approved_compact_footprint(self):
        self.assertEqual(LOREMASTER.RUNE_SEED_WIDTH, 92)
        self.assertEqual(LOREMASTER.RUNE_SEED_HEIGHT, 48)
        self.assertEqual(LOREMASTER.RUNE_SEED_COMBAT_LABEL, "DPS")
        # The one-pixel Vellum frame is outside the seed canvas.
        self.assertEqual(LOREMASTER.MINI_BASE_WIDTH, 94)
        self.assertEqual(LOREMASTER.MINI_BASE_HEIGHT, 50)
        self.assertEqual(LOREMASTER.MINI_MIN_WIDTH, 94)

    def test_generated_cog_is_a_tiny_transparent_rgba_asset(self):
        path = LOREMASTER.bundled_resource_path(
            "assets", LOREMASTER.BRAND_COG_FILE)
        self.assertTrue(path.is_file())
        self.assertEqual(LOREMASTER.png_asset_identity(path), (32, 32, 6))

    def test_cog_and_metric_lanes_never_overlap(self):
        for scale in (1.0, 1.15, 1.4):
            with self.subTest(scale=scale):
                layout = LOREMASTER.rune_seed_content_layout(
                    LOREMASTER.RUNE_SEED_WIDTH * scale,
                    LOREMASTER.RUNE_SEED_HEIGHT * scale)
                self.assertLess(layout["icon"][2], layout["text"][0])
                self.assertGreaterEqual(
                    layout["text"][0] - layout["icon"][2], 5.0)

    def test_seed_capsule_points_are_bounded_and_reach_every_edge(self):
        points = LOREMASTER.rounded_rectangle_points(1, 2, 79, 46, 13)
        xs, ys = points[::2], points[1::2]
        self.assertEqual((min(xs), max(xs)), (1.0, 79.0))
        self.assertEqual((min(ys), max(ys)), (2.0, 46.0))
        self.assertGreater(len(set(zip(xs, ys))), 8)

    def test_alpha_free_color_blend_is_clamped_and_deterministic(self):
        self.assertEqual(
            LOREMASTER.blend_hex_color("#000000", "#ffffff", 0.5),
            "#808080")
        self.assertEqual(
            LOREMASTER.blend_hex_color("#123456", "#abcdef", -1),
            "#123456")
        self.assertEqual(
            LOREMASTER.blend_hex_color("#123456", "#abcdef", 2),
            "#abcdef")

    def test_seed_carousel_retains_four_starred_metrics(self):
        self.assertEqual(LOREMASTER.MINI_MAX_CELLS, 4)
        self.assertEqual(
            LOREMASTER.rune_seed_keys(
                ["combat", "kills", "money", "motes", "loot"]),
            ["combat", "kills", "money", "motes"],
        )
        self.assertEqual(LOREMASTER.rune_seed_keys("combat"), ["combat"])
        self.assertEqual(
            LOREMASTER.rune_seed_keys(
                ["combat", "combat", "kills", "money", "motes", "loot"]),
            ["combat", "kills", "money", "motes"],
        )

    def test_selecting_a_fifth_metric_replaces_the_oldest(self):
        starred = ["combat", "kills", "money", "motes"]
        self.assertEqual(
            LOREMASTER.toggle_rune_seed_star(starred, "progress"),
            ["kills", "money", "motes", "progress"],
        )
        self.assertEqual(
            LOREMASTER.toggle_rune_seed_star(starred, "kills"),
            ["combat", "money", "motes"],
        )
        self.assertEqual(
            LOREMASTER.toggle_rune_seed_star(["combat"], "combat"),
            ["combat"],
        )

    def test_metric_carousel_wraps_in_both_directions(self):
        self.assertEqual(LOREMASTER.cycle_rune_seed_index(3, 1, 4), 0)
        self.assertEqual(LOREMASTER.cycle_rune_seed_index(0, -1, 4), 3)
        self.assertEqual(LOREMASTER.cycle_rune_seed_index("bad", 1, 4), 0)

    def test_large_values_stay_glanceable(self):
        self.assertEqual(LOREMASTER.compact_hud_number(946), "946")
        self.assertEqual(LOREMASTER.compact_hud_number(1284), "1.28k")
        self.assertEqual(LOREMASTER.compact_hud_number(48800), "48.8k")
        self.assertEqual(LOREMASTER.compact_hud_number(2_105_000), "2.1m")

    def test_morph_has_cached_bounded_frames_and_exact_endpoints(self):
        start = (58, 46, 1400, 800)
        end = (550, 820, 900, 180)
        frames = LOREMASTER.geometry_morph_frames(start, end)
        self.assertEqual(len(frames), LOREMASTER.HUD_MORPH_STEPS)
        self.assertEqual(frames[0], start)
        self.assertEqual(frames[-1], end)
        self.assertTrue(all(a[0] <= b[0] for a, b in zip(frames, frames[1:])))
        self.assertTrue(all(a[1] <= b[1] for a, b in zip(frames, frames[1:])))

    def test_wall_clock_morph_clamps_and_skips_to_elapsed_progress(self):
        start = (94, 50, 1500, 800)
        end = (550, 820, 900, 180)
        self.assertEqual(LOREMASTER.geometry_morph_at(start, end, -1), start)
        self.assertEqual(LOREMASTER.geometry_morph_at(start, end, 2), end)
        late = LOREMASTER.geometry_morph_at(start, end, 0.75)
        early = LOREMASTER.geometry_morph_at(start, end, 0.25)
        self.assertGreater(late[0], early[0])
        self.assertGreater(late[1], early[1])
        self.assertLess(late[2], early[2])

    def test_expanded_panel_fits_short_work_areas_at_large_text_scale(self):
        width, height = LOREMASTER.fit_panel_size_to_bounds(
            LOREMASTER.FULL_DEFAULT_SIZE, 1.40, (0, 0, 1366, 728))
        self.assertLessEqual(width, 1350)
        self.assertLessEqual(height, 712)
        self.assertEqual((width, height), (616, 712))

    def test_resize_floor_keeps_the_footer_grip_reachable(self):
        width, height = LOREMASTER.expanded_panel_minimum(653, 339, 1.0)
        self.assertEqual(width, LOREMASTER.FULL_MIN_WIDTH)
        self.assertEqual(height, 653)
        wide, tall = LOREMASTER.expanded_panel_minimum(751, 700, 1.4)
        self.assertEqual(wide, 700)
        self.assertEqual(tall, 751)
        self.assertGreaterEqual(
            LOREMASTER.clamp_panel_resize(400, 653, 500), 653)
        self.assertEqual(LOREMASTER.clamp_panel_resize(900, 653, 820), 820)
        self.assertEqual(LOREMASTER.clamp_panel_resize(700, 653, 1000), 700)

    def test_expanded_panel_keeps_its_design_size_when_space_allows(self):
        self.assertEqual(
            LOREMASTER.fit_panel_size_to_bounds(
                LOREMASTER.FULL_DEFAULT_SIZE, 1.0, (0, 0, 1920, 1040)),
            LOREMASTER.FULL_DEFAULT_SIZE,
        )

    def test_settings_stays_off_the_glance_seed(self):
        source = (LOREMASTER_DIR / "loremaster.py").read_text(encoding="utf-8")
        self.assertNotIn("mini_settings", source)
        # It remains in the expanded footer and on the seed's right click.
        self.assertIn('widgets["settings"] = tk.Label', source)
        self.assertIn('seed.bind("<Button-3>", open_settings)', source)


class FullPanelSummaryTests(unittest.TestCase):
    class Packable:
        def __init__(self, managed=True):
            self.managed = managed
            self.pack_calls = []
            self.forget_calls = 0

        def winfo_manager(self):
            return "pack" if self.managed else ""

        def pack_forget(self):
            self.managed = False
            self.forget_calls += 1

        def pack(self, **kwargs):
            self.managed = True
            self.pack_calls.append(kwargs)

    def test_title_toggle_label_matches_the_available_action(self):
        self.assertEqual(LOREMASTER.summary_toggle_label(False), "TOP ▴")
        self.assertEqual(LOREMASTER.summary_toggle_label(True), "SHOW TOP ▾")

    def test_collapsing_reclaims_space_without_repacking_the_ledger(self):
        summary = self.Packable(managed=True)
        restore = self.Packable(managed=False)
        ledger = object()
        LOREMASTER.apply_summary_visibility(summary, restore, ledger, True)
        self.assertFalse(summary.managed)
        self.assertTrue(restore.managed)
        self.assertEqual(summary.forget_calls, 1)
        self.assertEqual(summary.pack_calls, [])
        self.assertEqual(restore.pack_calls, [{"fill": "x", "before": ledger}])

    def test_expanding_restores_summary_immediately_before_ledger(self):
        summary = self.Packable(managed=False)
        restore = self.Packable(managed=True)
        ledger = object()
        LOREMASTER.apply_summary_visibility(summary, restore, ledger, False)
        self.assertTrue(summary.managed)
        self.assertFalse(restore.managed)
        self.assertEqual(summary.pack_calls, [{"fill": "x", "before": ledger}])
        self.assertEqual(restore.forget_calls, 1)


class StarredCardMigrationTests(unittest.TestCase):
    def load_payload(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loremaster_config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            original = LOREMASTER.CONFIG_PATH
            LOREMASTER.CONFIG_PATH = path
            try:
                return LOREMASTER.load_config()
            finally:
                LOREMASTER.CONFIG_PATH = original

    def test_untouched_legacy_default_migrates_to_dps_only(self):
        config = self.load_payload({
            "starred_cards": ["combat", "kills", "money", "progress"],
            "mini_stat_index": 2,
        })
        self.assertEqual(config["starred_cards"], ["combat"])
        self.assertEqual(config["mini_stat_index"], 0)
        self.assertEqual(
            config["hud_cards_version"],
            LOREMASTER.RUNE_SEED_CONFIG_VERSION)

    def test_a_config_that_already_saw_v1_still_drops_progression(self):
        config = self.load_payload({
            "starred_cards": ["combat", "progress", "motes"],
            "hud_cards_version": 1,
        })
        self.assertEqual(config["starred_cards"], ["combat", "motes"])
        self.assertEqual(
            config["hud_cards_version"],
            LOREMASTER.RUNE_SEED_CONFIG_VERSION)

    def test_a_deliberate_choice_is_not_undone_on_the_next_launch(self):
        config = self.load_payload({
            "starred_cards": ["combat", "kills", "progress"],
            "hud_cards_version": 2,
        })
        self.assertEqual(
            config["starred_cards"], ["combat", "kills", "progress"])
        self.assertEqual(
            config["hud_cards_version"],
            LOREMASTER.RUNE_SEED_CONFIG_VERSION)

    def test_default_seed_is_dps_only(self):
        config = self.load_payload({})
        self.assertEqual(config["starred_cards"], ["combat"])
        self.assertEqual(config["mini_stat_index"], 0)
        self.assertEqual(
            config["hud_cards_version"],
            LOREMASTER.RUNE_SEED_CONFIG_VERSION)
        keys = LOREMASTER.rune_seed_keys(config["starred_cards"])
        self.assertEqual(keys, ["combat"])

    def test_exact_v2_default_resets_selection_to_dps(self):
        config = self.load_payload({
            "starred_cards": ["combat", "kills", "money", "motes"],
            "mini_stat_index": 3,
            "hud_cards_version": 2,
        })
        self.assertEqual(config["starred_cards"], ["combat"])
        self.assertEqual(config["mini_stat_index"], 0)

    def test_v3_user_can_deliberately_rebuild_the_old_four_item_wheel(self):
        config = self.load_payload({
            "starred_cards": ["combat", "kills", "money", "motes"],
            "mini_stat_index": 3,
            "hud_cards_version": LOREMASTER.RUNE_SEED_CONFIG_VERSION,
        })
        self.assertEqual(
            config["starred_cards"], ["combat", "kills", "money", "motes"])
        self.assertEqual(config["mini_stat_index"], 3)

    def test_loaded_wheel_order_and_selection_are_not_reset(self):
        config = self.load_payload({
            "starred_cards": ["kills", "combat", "motes"],
            "mini_stat_index": 2,
            "hud_cards_version": 2,
        })
        self.assertEqual(
            config["starred_cards"], ["kills", "combat", "motes"])
        self.assertEqual(config["mini_stat_index"], 2)
        self.assertEqual(
            config["hud_cards_version"],
            LOREMASTER.RUNE_SEED_CONFIG_VERSION)
        self.assertEqual(
            config["starred_cards"][config["mini_stat_index"]], "motes")

    def test_malformed_starred_cards_do_not_break_the_migration(self):
        config = self.load_payload({"starred_cards": "combat"})
        self.assertEqual(
            config["hud_cards_version"],
            LOREMASTER.RUNE_SEED_CONFIG_VERSION)
        self.assertEqual(config["starred_cards"], ["combat"])

    def test_legacy_hidden_stars_are_normalized_to_the_wheel_budget(self):
        config = self.load_payload({
            "starred_cards": [
                "combat", "combat", "kills", "money", "motes", "loot"],
            "hud_cards_version": 2,
        })
        self.assertEqual(
            config["starred_cards"], ["combat", "kills", "money", "motes"])


if __name__ == "__main__":
    unittest.main()
