"""Tests for src/services/scanner/grading.py using purely synthetic images.

IMPORTANT: these only prove the maths behaves sensibly on hand-made images.
They say nothing about accuracy on real photographs of cards.
"""
import os
import sys
import unittest

import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.scanner import grading

W, H = 600, 875
NAME = (30, 25, 480, 50)
ART = (50, 110, 500, 490)


def bgr(r, g, b):
    return (b, g, r)


def make_card(frame=(200, 150, 60), name_text=None, art=(90, 110, 130)):
    """Synthetic card: black outer border, coloured frame, optional name text bars."""
    img = np.zeros((H, W, 3), np.uint8)
    img[:, :] = bgr(0, 0, 0)
    img[10:H - 10, 10:W - 10] = bgr(*frame)
    x, y, w, h = ART
    img[y:y + h, x:x + w] = bgr(*art)
    if name_text is not None:
        nx, ny, nw, nh = NAME
        # text = vertical bars so ~35% of the ROI is text
        for i in range(0, nw, 12):
            img[ny + 10:ny + nh - 10, nx + i:nx + i + 5] = name_text
    return img


def rainbow_bars():
    cols = [bgr(255, 0, 0), bgr(255, 255, 0), bgr(0, 255, 0),
            bgr(0, 255, 255), bgr(0, 0, 255), bgr(255, 0, 255)]
    return cols


def make_rainbow_name_card():
    img = make_card(frame=(60, 60, 60))
    nx, ny, nw, nh = NAME
    cols = rainbow_bars()
    k = 0
    for i in range(0, nw, 12):
        img[ny + 10:ny + nh - 10, nx + i:nx + i + 5] = cols[k % 6]
        k += 1
    return img


class TestConditionMapping(unittest.TestCase):
    def test_cardtrader_to_app(self):
        self.assertEqual(grading.cardtrader_to_app("NM"), "Near Mint")
        self.assertEqual(grading.cardtrader_to_app("PO"), "Poor")
        self.assertIsNone(grading.cardtrader_to_app("XX"))

    def test_every_mapped_literal_is_valid_in_app(self):
        from src.core.constants import CARD_CONDITIONS
        for lbl in ("NM", "SP", "MP", "PL", "PO"):
            self.assertIn(grading.cardtrader_to_app(lbl), CARD_CONDITIONS)

    def test_app_to_cardtrader_covers_all_literals(self):
        from src.core.constants import CARD_CONDITIONS
        for c in CARD_CONDITIONS:
            self.assertIn(grading.app_to_cardtrader(c), ("NM", "SP", "MP", "PL", "PO"))
        self.assertEqual(grading.app_to_cardtrader("Mint"), "NM")


class TestConditionEstimate(unittest.TestCase):
    def test_none_image_gives_no_suggestion(self):
        est = grading.estimate_condition(None)
        self.assertIsNone(est.label)
        self.assertEqual(est.confidence, 0.0)
        self.assertIsNone(grading.suggest_condition(est))

    def test_tiny_image_gives_no_suggestion(self):
        est = grading.estimate_condition(np.zeros((40, 30, 3), np.uint8))
        self.assertIsNone(est.label)

    def test_clean_card_is_near_mint(self):
        est = grading.estimate_condition(make_card())
        self.assertEqual(est.label, "NM")
        self.assertLessEqual(est.confidence, 0.8)  # never claims near-certainty

    def test_whitened_edges_worse_than_clean(self):
        clean = make_card()
        worn = make_card()
        # whiten ~35% of the outer edge pixels on all 4 sides, deterministic
        rng = np.random.default_rng(0)
        for side in range(4):
            n = W if side < 2 else H
            mask = rng.random(n) < 0.35
            for i in np.nonzero(mask)[0]:
                if side == 0: worn[0:6, i] = 235
                elif side == 1: worn[H - 6:H, i] = 235
                elif side == 2: worn[i, 0:6] = 235
                else: worn[i, W - 6:W] = 235
        e_clean = grading.estimate_condition(clean)
        e_worn = grading.estimate_condition(worn)
        self.assertGreater(e_worn.damage, e_clean.damage)
        self.assertNotEqual(e_worn.label, "NM")

    def test_heavily_damaged_is_poor_or_played(self):
        img = make_card()
        rng = np.random.default_rng(1)
        for i in np.nonzero(rng.random(W) < 0.7)[0]:
            img[0:6, i] = 235
            img[H - 6:H, i] = 235
        for i in np.nonzero(rng.random(H) < 0.7)[0]:
            img[i, 0:6] = 235
            img[i, W - 6:W] = 235
        noise = rng.integers(0, 255, (H, 18, 3), dtype=np.uint8)
        img[:, 10:28] = noise
        img[:, W - 28:W - 10] = rng.integers(0, 255, (H, 18, 3), dtype=np.uint8)
        est = grading.estimate_condition(img)
        self.assertIn(est.label, ("PL", "PO"))

    def test_whole_side_bright_means_bad_crop_no_suggestion(self):
        img = make_card()
        img[0:12, :] = 240  # whole top strip bright: background bleed, not wear
        est = grading.estimate_condition(img)
        self.assertIsNone(est.label)
        self.assertEqual(est.confidence, 0.0)

    def test_glare_lowers_confidence(self):
        clean = grading.estimate_condition(make_card())
        glare = make_card()
        glare[200:600, 100:500] = 255
        e = grading.estimate_condition(glare)
        self.assertLess(e.confidence, clean.confidence)

    def test_suggest_condition_threshold(self):
        low = grading.ConditionEstimate("MP", 0.3, 0.2, {})
        high = grading.ConditionEstimate("MP", 0.7, 0.2, {})
        self.assertIsNone(grading.suggest_condition(low))
        self.assertEqual(grading.suggest_condition(high), "Good")
        self.assertIsNone(grading.suggest_condition(grading.ConditionEstimate(None, 0.9, 0, {})))


class TestNameColour(unittest.TestCase):
    def cues(self, img):
        return grading.analyze_rarity_cues(img)

    def test_gold_name(self):
        c = self.cues(make_card(frame=(60, 60, 60), name_text=bgr(230, 190, 40)))
        self.assertEqual(c.top_name_color(), "gold")

    def test_black_name_on_colored_frame(self):
        c = self.cues(make_card(frame=(230, 190, 60), name_text=bgr(5, 5, 5)))
        self.assertEqual(c.top_name_color(), "black")

    def test_white_name(self):
        c = self.cues(make_card(frame=(40, 120, 70), name_text=bgr(250, 250, 250)))
        self.assertEqual(c.top_name_color(), "white")

    def test_silver_name(self):
        c = self.cues(make_card(frame=(60, 60, 60), name_text=bgr(170, 170, 175)))
        self.assertEqual(c.top_name_color(), "silver")

    def test_rainbow_name(self):
        c = self.cues(make_rainbow_name_card())
        self.assertEqual(c.top_name_color(), "rainbow")

    def test_red_name(self):
        c = self.cues(make_card(frame=(60, 60, 60), name_text=bgr(220, 20, 20)))
        self.assertEqual(c.top_name_color(), "red")

    def test_gold_name_on_orange_frame_still_found(self):
        # frame colour must not be mistaken for the text colour
        c = self.cues(make_card(frame=(200, 100, 30), name_text=bgr(235, 195, 45)))
        self.assertEqual(c.top_name_color(), "gold")

    def test_no_text_unknown(self):
        c = self.cues(make_card(frame=(200, 100, 30)))
        self.assertIsNone(c.top_name_color())


class TestRarityRanking(unittest.TestCase):
    def test_normalize_rarity(self):
        n = grading.normalize_rarity
        self.assertEqual(n("Ultra Rare"), "ultra")
        self.assertEqual(n("UR"), "ultra")
        self.assertEqual(n("Secret Rare"), "secret")
        self.assertEqual(n("ScR"), "secret")
        self.assertEqual(n("Prismatic Secret Rare"), "prismatic secret")
        self.assertEqual(n("Common"), "common")
        self.assertEqual(n("Super Rare"), "super")
        self.assertEqual(n("Starlight Rare"), "starlight")
        self.assertIsNone(n("Totally Made Up"))

    def test_gold_name_prefers_ultra_over_secret(self):
        cues = grading.analyze_rarity_cues(make_card(frame=(60, 60, 60), name_text=bgr(230, 190, 40)))
        ranking = grading.rank_rarities(cues, ["Secret Rare", "Ultra Rare"])
        self.assertEqual(ranking[0].rarity, "Ultra Rare")

    def test_rainbow_name_prefers_secret_over_ultra(self):
        cues = grading.analyze_rarity_cues(make_rainbow_name_card())
        ranking = grading.rank_rarities(cues, ["Ultra Rare", "Secret Rare"])
        self.assertEqual(ranking[0].rarity, "Secret Rare")

    def test_suggest_rarity_when_clear(self):
        cues = grading.analyze_rarity_cues(make_rainbow_name_card())
        s = grading.suggest_rarity(cues, ["Ultra Rare", "Secret Rare"])
        self.assertIsNotNone(s)
        self.assertEqual(s.rarity, "Secret Rare")
        self.assertGreater(s.confidence, 0)

    def test_no_suggestion_without_cues(self):
        cues = grading.analyze_rarity_cues(make_card(frame=(200, 100, 30)))
        self.assertIsNone(grading.suggest_rarity(cues, ["Ultra Rare", "Secret Rare"]))

    def test_no_suggestion_for_indistinguishable_pair(self):
        # Ultra and Ultimate share name colour (gold): cannot be told apart by colour
        cues = grading.analyze_rarity_cues(make_card(frame=(60, 60, 60), name_text=bgr(230, 190, 40)))
        self.assertIsNone(grading.suggest_rarity(cues, ["Ultra Rare", "Ultimate Rare"]))

    def test_single_candidate_never_suggests(self):
        cues = grading.analyze_rarity_cues(make_rainbow_name_card())
        self.assertIsNone(grading.suggest_rarity(cues, ["Secret Rare"]))

    def test_unknown_rarity_names_are_kept_but_neutral(self):
        cues = grading.analyze_rarity_cues(make_rainbow_name_card())
        ranking = grading.rank_rarities(cues, ["Mystery Rare", "Secret Rare"])
        self.assertEqual({r.rarity for r in ranking}, {"Mystery Rare", "Secret Rare"})
        self.assertEqual(ranking[0].rarity, "Secret Rare")

    def test_whole_card_foil_cue_favours_parallel(self):
        img = make_card(frame=(60, 60, 60))  # no readable name text
        cues = grading.analyze_rarity_cues(img)
        cues.card_foil_prob = 0.9
        ranking = grading.rank_rarities(cues, ["Common", "Starfoil Rare"])
        self.assertEqual(ranking[0].rarity, "Starfoil Rare")


class TestApplySuggestion(unittest.TestCase):
    def test_uses_default_without_suggestion(self):
        self.assertEqual(grading.pick_condition({}, "Near Mint"), "Near Mint")
        self.assertEqual(grading.pick_condition({"suggested_condition": None}, "Good"), "Good")

    def test_uses_valid_suggestion(self):
        self.assertEqual(grading.pick_condition({"suggested_condition": "Played"}, "Near Mint"), "Played")

    def test_ignores_invalid_suggestion(self):
        self.assertEqual(grading.pick_condition({"suggested_condition": "Banana"}, "Near Mint"), "Near Mint")

    def test_pick_rarity_only_among_candidates(self):
        self.assertEqual(grading.pick_rarity("Secret Rare", "Ultra Rare", ["Ultra Rare", "Secret Rare"]), "Secret Rare")
        self.assertEqual(grading.pick_rarity("Secret Rare", "Ultra Rare", ["Ultra Rare"]), "Ultra Rare")
        self.assertEqual(grading.pick_rarity(None, "Ultra Rare", ["Ultra Rare"]), "Ultra Rare")


class TestScanResultFields(unittest.TestCase):
    def test_defaults_do_not_break(self):
        from src.services.scanner.models import ScanResult
        r = ScanResult()
        self.assertIsNone(r.suggested_condition)
        self.assertIsNone(r.suggested_rarity)
        self.assertEqual(r.condition_confidence, 0.0)
        self.assertEqual(r.rarity_confidence, 0.0)


class TestManagerIntegration(unittest.TestCase):
    """_apply_visual_suggestions fills hints and never raises."""

    @classmethod
    def setUpClass(cls):
        from unittest.mock import MagicMock
        for mod in ('langdetect', 'easyocr', 'keras_ocr', 'doctr', 'doctr.io',
                    'doctr.models', 'mmocr', 'mmocr.apis'):
            sys.modules.setdefault(mod, MagicMock())
        from src.services.scanner.manager import ScannerManager
        from src.services.scanner.models import ScanResult
        cls.Manager, cls.ScanResult = ScannerManager, ScanResult

    def _result(self):
        r = self.ScanResult()
        r.set_code = "LOB-EN001"
        r.candidates = [
            {"set_code": "LOB-EN001", "rarity": "Ultra Rare"},
            {"set_code": "LOB-EN001", "rarity": "Secret Rare"},
        ]
        return r

    def test_suggests_rarity_among_candidates(self):
        m = self.Manager()
        r = self._result()
        m._apply_visual_suggestions(r, make_rainbow_name_card())
        self.assertEqual(r.suggested_rarity, "Secret Rare")
        self.assertIn(r.suggested_rarity, [c["rarity"] for c in r.candidates])
        self.assertEqual(r.rarity, "Unknown")  # existing field untouched

    def test_no_warped_image_changes_nothing(self):
        m = self.Manager()
        r = self._result()
        m._apply_visual_suggestions(r, None)
        self.assertIsNone(r.suggested_rarity)
        self.assertIsNone(r.suggested_condition)

    def test_garbage_image_does_not_raise(self):
        m = self.Manager()
        r = self._result()
        m._apply_visual_suggestions(r, "not an image")
        self.assertIsNone(r.suggested_rarity)


if __name__ == "__main__":
    unittest.main()
