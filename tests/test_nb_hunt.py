#!/usr/bin/env python3
"""Tests for nb_hunt: the vectorised CRC engine must agree with zlib exactly,
each search must find a planted name, and the budget must refuse searches
whose expected chance matches are too high."""
import contextlib
import io
import random
import sys
import unittest
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import nb_hunt
from nb_reconstruct import unappend


def crc(s):
    return zlib.crc32(s.lower().encode())


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        nb_hunt.main(argv)
    return out.getvalue()


class Engine(unittest.TestCase):
    def setUp(self):
        rnd = random.Random(7)
        alpha = "abcdefghijklmnopqrstuvwxyz_0123456789"
        self.words = ["".join(rnd.choice(alpha) for _ in range(rnd.randint(0, 12))) for _ in range(300)]

    def test_feed_each_matches_zlib(self):
        start = nb_hunt.reg("st_")
        got = nb_hunt.hashes_of(nb_hunt.feed_each(start, self.words))
        self.assertEqual(got.tolist(), [crc("st_" + w) for w in self.words])

    def test_feed_matches_zlib(self):
        regs = [nb_hunt.reg(w) for w in self.words]
        got = nb_hunt.hashes_of(nb_hunt.feed(regs, "_out"))
        self.assertEqual(got.tolist(), [crc(w + "_out") for w in self.words])

    def test_unappend_many_matches_scalar(self):
        hs = [crc(w + "left") for w in self.words]
        got = nb_hunt.unappend_many(hs, "left").tolist()
        self.assertEqual(got, [unappend(h, "left") for h in hs])
        self.assertEqual(got, [crc(w) for w in self.words])

    def test_unappend_each_peels_every_word(self):
        h = crc("ST_CScaredLiquid")
        got = nb_hunt.unappend_each(h, ["liquid", "Liquid", "x"]).tolist()
        self.assertEqual(got[:2], [crc("st_cscared")] * 2)
        self.assertEqual(got[2], unappend(h, "x"))


class Searches(unittest.TestCase):
    def test_brute_finds_planted_name(self):
        out = run(["brute", "st_cscared", f"{crc('ST_CScaredFire'):08x}", "--len", "4", "--jobs", "1"])
        self.assertIn("st_cscaredfire", out)

    def test_brute_with_suffix(self):
        out = run(["brute", "st_scam", f"{crc('ST_SCam02'):08x}", "--len", "2", "--alphabet",
                   "0123456789", "--jobs", "1"])
        self.assertIn("st_scam02", out)
        out = run(["brute", "st_", f"{crc('ST_SCam02'):08x}", "--suffix", "02", "--len", "4", "--jobs", "1"])
        self.assertIn("st_scam02", out)

    def test_words_meet_in_the_middle(self):
        name = "demo_fearevent_cakewalk_finsihing_second"
        out = run(["words", "demo_fearevent_", f"{crc(name):08x}", "--depth", "3", "--seps", "_",
                   "--tokens", "cakewalk,finsihing,finishing,second,third,dancing"])
        self.assertIn(name, out)

    def test_typos_find_developer_typo(self):
        name = "npc_names_pirate_midhip"
        out = run(["typos", f"{crc(name):08x}", "npc_names_pirate_midship"])
        self.assertIn(name, out)

    def test_sibling_candidates(self):
        c = nb_hunt.sibling_candidates("CloseWindowIn")
        self.assertIn("closewindowout", c)
        c = nb_hunt.sibling_candidates("ST_SprintFootL")
        self.assertIn("st_sprintfootr", c)
        c = nb_hunt.sibling_candidates("multiplayer_badge_accomodating_effect2")
        self.assertIn("multiplayer_badge_accomodating_effect3", c)
        c = nb_hunt.sibling_candidates("costume_names_hat_elite")
        self.assertIn("costume_names_hat_elite_desc", c)

    def test_affix_candidates_transfer_endings(self):
        known = {1: "ST_OpenFridge", 2: "ST_CloseFridge_Panic", 3: "ST_Idle_Panic",
                 4: "tutorial_details_tutorialprompt03", 5: "costume_x_02"}
        c = nb_hunt.affix_candidates(known)
        self.assertIn("st_openfridge_panic", c)
        self.assertIn("tutorial_details_tutorialprompt03_02", c)

    def test_learned_swaps(self):
        known = {1: "ST_RunFootL", 2: "ST_SprintFootL", 3: "ST_RunFootR", 4: "ST_SprintFootR",
                 5: "ST_NinjaRunFootL"}
        c = nb_hunt.learned_swap_candidates(known, least=2)
        self.assertIn("st_ninjasprintfootl", c)

    def test_camel_follows_nearest_known_name(self):
        known = {1: "ST_SinkIdle", 2: "ST_OpenFridge", 3: "costume_names_hat_elite", 4: "CloseWindowIn",
                 5: "ST_CScaredFire"}
        self.assertEqual(nb_hunt.camel("st_sinkidleout", known), "ST_SinkIdleOut")
        self.assertEqual(nb_hunt.camel("costume_names_hat_elite_desc", known), "costume_names_hat_elite_desc")
        self.assertEqual(nb_hunt.camel("closewindowout", known), "CloseWindowOut")

    def test_budget_refuses_wide_search(self):
        targets = ",".join(f"{crc(str(i)):08x}" for i in range(200))
        with self.assertRaises(SystemExit):
            run(["brute", "st_", targets, "--len", "7", "--jobs", "1"])

    def test_cache_inside_repo_refused(self):
        with self.assertRaises(SystemExit):
            run(["index", "where", "--hashes", "00000001", "--cache", str(TOOLS / "cache")])


class Plausibility(unittest.TestCase):
    def test_junk_scores_above_real_names(self):
        s = nb_hunt.Scorer(known={1: "ST_RunFootR", 2: "ST_WalkFootL", 3: "ST_CheckFireIn", 4: "demo_fearevent_cakewalk_finishing_first"},
                           tiers={1: "found", 2: "found", 3: "found", 4: "found"})
        real, _ = s.score("ST_CheckFireOut")
        junk, _ = s.score("st_runninglf4eho")
        self.assertLess(real, nb_hunt.JUNK)
        self.assertGreaterEqual(junk, nb_hunt.JUNK)


if __name__ == "__main__":
    unittest.main()
