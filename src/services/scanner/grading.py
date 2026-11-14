"""Condition and rarity *hints* for scanned cards (CardTrader guides).

Pure numpy, no cv2: the input is the already rectified card image (BGR uint8,
600x875 like ``CardScanner.warped``; other sizes are scaled).

Design rules
------------
* Everything here only SUGGESTS. Callers must keep the existing default when
  a function returns ``None``.
* Condition: a coarse wear estimate (whitening of the border, corner wear,
  noise in the frame margins). Confidence is capped well below certainty and
  collapses on glare, tiny images, or crops that look wrong.
* Rarity: cues are only used to RANK rarities that are already known for the
  identified set code (DB candidates), never to guess blindly.
* The thresholds are heuristics validated ONLY on synthetic images. They have
  not been calibrated against real photographs.

CardTrader condition guide -> app literal (``src.core.constants.CARD_CONDITIONS``)
----------------------------------------------------------------------------------
    NM  Near Mint        -> "Near Mint"
    SP  Slightly Played  -> "Excellent"     (minimal wear, good appearance)
    MP  Moderately Played-> "Good"          (noticeable light wear, good overall)
    PL  Played           -> "Played"        (heavy wear, cosmetic damage)
    PO  Poor             -> "Poor"          (very damaged)
The app's "Mint" folds into NM and "Light Played" into MP when going back to
CardTrader labels, "Damaged" into PO. The estimator never emits "Mint".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

# ----------------------------------------------------------------------------
# Condition label mapping
# ----------------------------------------------------------------------------

CARDTRADER_TO_APP: Dict[str, str] = {
    "NM": "Near Mint",
    "SP": "Excellent",
    "MP": "Good",
    "PL": "Played",
    "PO": "Poor",
}

APP_TO_CARDTRADER: Dict[str, str] = {
    "Mint": "NM",
    "Near Mint": "NM",
    "Excellent": "SP",
    "Good": "MP",
    "Light Played": "MP",
    "Played": "PL",
    "Poor": "PO",
    "Damaged": "PO",
}

# Minimum confidence for a condition to be proposed at all.
MIN_CONDITION_CONFIDENCE = 0.6
# Hard ceilings: a webcam photo never justifies more.
MAX_CONDITION_CONFIDENCE = 0.8
MAX_NM_CONFIDENCE = 0.7  # absence of visible wear is weak evidence

# damage-score bands: label -> (low, high)
_BANDS: List[Tuple[str, float, float]] = [
    ("NM", float("-inf"), 0.10),
    ("SP", 0.10, 0.30),
    ("MP", 0.30, 0.60),
    ("PL", 0.60, 1.00),
    ("PO", 1.00, float("inf")),
]

REF_W, REF_H = 600, 875
REF_NAME_ROI = (30, 25, 480, 50)
REF_ART_ROI = (50, 110, 500, 490)
REF_DESC_ROI = (35, 650, 530, 180)


def cardtrader_to_app(label: Optional[str]) -> Optional[str]:
    return CARDTRADER_TO_APP.get((label or "").upper())


def app_to_cardtrader(condition: Optional[str]) -> Optional[str]:
    return APP_TO_CARDTRADER.get(condition or "")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _np():
    import numpy as np
    return np


def _valid_image(img, min_w: int = 150, min_h: int = 200) -> bool:
    if img is None:
        return False
    shape = getattr(img, "shape", None)
    if not shape or len(shape) != 3 or shape[2] < 3:
        return False
    return shape[0] >= min_h and shape[1] >= min_w


def _gray(img):
    np = _np()
    f = img[:, :, :3].astype(np.float32)
    return f.mean(axis=2)


def _scaled_roi(img, roi):
    x, y, w, h = roi
    sx = img.shape[1] / REF_W
    sy = img.shape[0] / REF_H
    x0, y0 = int(round(x * sx)), int(round(y * sy))
    x1, y1 = int(round((x + w) * sx)), int(round((y + h) * sy))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    return img[y0:y1, x0:x1]


def _bgr_to_hsv(crop):
    """Return h (0-360), s (0-1), v (0-1) float arrays for a BGR crop."""
    np = _np()
    f = crop[:, :, :3].astype(np.float32) / 255.0
    b, g, r = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    mx = f.max(axis=2)
    mn = f.min(axis=2)
    d = mx - mn
    safe = np.where(d == 0, 1.0, d)
    h = np.zeros_like(mx)
    h = np.where(mx == r, ((g - b) / safe) % 6.0, h)
    h = np.where((mx == g) & (mx != r), (b - r) / safe + 2.0, h)
    h = np.where((mx == b) & (mx != r) & (mx != g), (r - g) / safe + 4.0, h)
    h = np.where(d == 0, 0.0, h) * 60.0
    s = np.where(mx == 0, 0.0, d / np.where(mx == 0, 1.0, mx))
    return h % 360.0, s, mx


def _box_blur(gray, k: int = 5):
    np = _np()
    pad = k // 2
    p = np.pad(gray, pad, mode="edge")
    c = p.cumsum(axis=0).cumsum(axis=1)
    c = np.pad(c, ((1, 0), (1, 0)))
    hh, ww = gray.shape
    s = c[k:k + hh, k:k + ww] - c[0:hh, k:k + ww] - c[k:k + hh, 0:ww] + c[0:hh, 0:ww]
    return s / float(k * k)


# ----------------------------------------------------------------------------
# Condition estimation
# ----------------------------------------------------------------------------

@dataclass
class ConditionEstimate:
    label: Optional[str]          # NM/SP/MP/PL/PO or None when it cannot tell
    confidence: float             # 0..MAX_CONDITION_CONFIDENCE
    damage: float                 # raw damage score (0 = pristine)
    metrics: Dict[str, float] = field(default_factory=dict)
    reason: str = ""


def _no_estimate(reason: str, metrics=None) -> ConditionEstimate:
    return ConditionEstimate(None, 0.0, 0.0, metrics or {}, reason)


def estimate_condition(img) -> ConditionEstimate:
    """Conservative wear estimate from a rectified card image.

    Looks only at: whitening of the dark outer border (edges and corners) and
    noise (scratch/stain-like outliers) in the frame margins. Surface
    scratches on the art/foil are NOT assessed.
    """
    if not _valid_image(img):
        return _no_estimate("imagen no valida o demasiado pequena")
    np = _np()
    gray = _gray(img)
    h, w = gray.shape

    t = max(2, int(round(0.01 * w)))      # edge strip thickness (inside black border)
    c = max(3, int(round(0.0135 * w)))    # corner patch size
    bright = gray > 150.0

    top = bright[0:t, c:w - c]
    bottom = bright[h - t:h, c:w - c]
    left = bright[c:h - c, 0:t]
    right = bright[c:h - c, w - t:w]
    sides = [float(s.mean()) for s in (top, bottom, left, right)]

    if max(sides) > 0.85:
        return _no_estimate("un borde completo es claro: recorte dudoso (fondo), no es desgaste",
                            {"edge_sides": max(sides)})

    edge_white = sum(sides) / 4.0
    corners = [bright[0:c, 0:c], bright[0:c, w - c:w], bright[h - c:h, 0:c], bright[h - c:h, w - c:w]]
    corner_white = sum(float(k.mean()) for k in corners) / 4.0

    # frame margin noise: outliers vs the median of each band
    m0 = max(t + 2, int(round(0.02 * w)))
    m1 = max(m0 + 2, int(round(0.045 * w)))
    bands = [gray[c:h - c, m0:m1], gray[c:h - c, w - m1:w - m0]]
    tb0 = max(t + 2, int(round(0.015 * h)))
    tb1 = max(tb0 + 2, int(round(0.026 * h)))
    bands += [gray[tb0:tb1, m1:w - m1], gray[h - tb1:h - tb0, m1:w - m1]]
    outl = []
    for b in bands:
        if b.size == 0:
            continue
        outl.append(float((np.abs(b - np.median(b)) > 35.0).mean()))
    margin_noise = sum(outl) / len(outl) if outl else 0.0

    damage = 2.0 * edge_white + 2.0 * corner_white + 1.5 * margin_noise

    label = "PO"
    lo = hi = 0.0
    for name, a, b in _BANDS:
        if a <= damage < b:
            label, lo, hi = name, a, b
            break
    margin = min(damage - lo if lo != float("-inf") else 1e9,
                 hi - damage if hi != float("inf") else 1e9)
    margin = max(0.0, min(margin, 0.15))
    conf = 0.4 + 0.4 * (margin / 0.15)

    glare = float((gray >= 250.0).mean())
    if glare > 0.03:
        conf *= 0.5
    if float(gray.std()) < 8.0:
        conf *= 0.5
    if w < 400:
        conf *= 0.8
    conf = min(conf, MAX_NM_CONFIDENCE if label == "NM" else MAX_CONDITION_CONFIDENCE)

    metrics = {"edge_white": edge_white, "corner_white": corner_white,
               "margin_noise": margin_noise, "glare": glare}
    return ConditionEstimate(label, round(conf, 3), round(damage, 4), metrics,
                             "estimacion aproximada (bordes, esquinas, margenes)")


def suggest_condition(est: Optional[ConditionEstimate],
                      min_confidence: float = MIN_CONDITION_CONFIDENCE) -> Optional[str]:
    """App condition literal to preselect, or None to keep the default."""
    if est is None or est.label is None or est.confidence < min_confidence:
        return None
    return cardtrader_to_app(est.label)


# ----------------------------------------------------------------------------
# Rarity cues
# ----------------------------------------------------------------------------

NAME_COLORS = ("black", "white", "silver", "gold", "red", "rainbow")


@dataclass
class RarityCues:
    name_color_scores: Dict[str, float] = field(default_factory=dict)
    text_fraction: float = 0.0
    art_foil_prob: Optional[float] = None
    art_pale_prob: Optional[float] = None
    card_foil_prob: Optional[float] = None
    metrics: Dict[str, float] = field(default_factory=dict)

    def top_name_color(self, min_score: float = 0.4) -> Optional[str]:
        best, best_s = None, 0.0
        for k, v in self.name_color_scores.items():
            if k in NAME_COLORS and v > best_s:
                best, best_s = k, v
        return best if best_s >= min_score else None


def _name_color_scores(img) -> Tuple[Dict[str, float], float]:
    np = _np()
    crop = _scaled_roi(img, REF_NAME_ROI)
    if crop.size == 0:
        return {}, 0.0
    f = crop[:, :, :3].astype(np.float32)
    bg = np.median(f.reshape(-1, 3), axis=0)
    dist = np.sqrt(((f - bg) ** 2).sum(axis=2))
    mask = dist > 70.0
    frac = float(mask.mean())
    if frac < 0.03 or frac > 0.6:
        return {}, frac
    hch, sat, val = _bgr_to_hsv(crop)
    hh, ss, vv = hch[mask], sat[mask], val[mask]
    n = float(hh.size)

    dark = vv < 0.25
    white = (~dark) & (ss < 0.2) & (vv > 0.88)
    silver = (~dark) & (~white) & (ss < 0.25) & (vv >= 0.4)
    colored = (~dark) & (~white) & (~silver) & (ss >= 0.3) & (vv >= 0.35)

    scores = {k: 0.0 for k in NAME_COLORS}
    scores["other"] = 0.0
    scores["black"] = float(dark.sum()) / n
    scores["white"] = float(white.sum()) / n
    scores["silver"] = float(silver.sum()) / n

    ncol = int(colored.sum())
    if ncol:
        bins = (np.floor(hh[colored] / 60.0).astype(int)) % 6
        counts = np.bincount(bins, minlength=6) / float(ncol)
        n_bins = int((counts >= 0.08).sum())
        col_frac = ncol / n
        if n_bins >= 4:
            scores["rainbow"] = col_frac
        else:
            hc = hh[colored]
            scores["gold"] = float(((hc >= 35) & (hc < 65)).sum()) / n
            scores["red"] = float(((hc < 15) | (hc >= 345)).sum()) / n
            scores["other"] = col_frac - scores["gold"] - scores["red"]
    scores["other"] = max(0.0, scores["other"])
    return scores, frac


def _art_cues(img) -> Tuple[Optional[float], Optional[float], Dict[str, float]]:
    np = _np()
    crop = _scaled_roi(img, REF_ART_ROI)
    if crop.shape[0] < 20 or crop.shape[1] < 20:
        return None, None, {}
    hch, sat, val = _bgr_to_hsv(crop)
    glint = float(((val > 0.94) & (sat < 0.15)).mean())
    gray = _gray(crop)
    sparkle = float((np.abs(gray - _box_blur(gray, 5)) > 25.0).mean())
    score = glint * 8.0 + sparkle * 2.0
    # Deliberately weak: evidence is bounded to 0.2..0.8.
    foil_prob = float(min(0.8, max(0.2, 0.5 + 2.0 * (score - 0.12))))
    mean_sat = float(sat.mean())
    pale = 0.75 if mean_sat < 0.12 else (0.25 if mean_sat > 0.3 else 0.5)
    return foil_prob, pale, {"art_glint": glint, "art_sparkle": sparkle, "art_mean_sat": mean_sat}


def _card_foil_prob(img) -> Tuple[Optional[float], Dict[str, float]]:
    np = _np()
    crop = _scaled_roi(img, REF_DESC_ROI)
    if crop.shape[0] < 20 or crop.shape[1] < 20:
        return None, {}
    hch, sat, val = _bgr_to_hsv(crop)
    colored = (sat > 0.35) & (val > 0.4)
    col_frac = float(colored.mean())
    if colored.sum() < 50:
        return 0.35, {"desc_hue_bins": 0.0, "desc_colored": col_frac}
    bins = (np.floor(hch[colored] / 60.0).astype(int)) % 6
    counts = np.bincount(bins, minlength=6) / float(colored.sum())
    n_bins = int((counts >= 0.05).sum())
    if n_bins >= 4 and col_frac > 0.15:
        p = 0.8
    elif n_bins <= 1:
        p = 0.3
    else:
        p = 0.5
    return p, {"desc_hue_bins": float(n_bins), "desc_colored": col_frac}


def analyze_rarity_cues(img) -> RarityCues:
    """Extract visual rarity cues from a rectified card image."""
    if not _valid_image(img):
        return RarityCues()
    scores, frac = _name_color_scores(img)
    art_prob, art_pale, m1 = _art_cues(img)
    card_prob, m2 = _card_foil_prob(img)
    metrics = {}
    metrics.update(m1)
    metrics.update(m2)
    return RarityCues(scores, frac, art_prob, art_pale, card_prob, metrics)


# ----------------------------------------------------------------------------
# Rarity signatures (CardTrader print guide)
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class _Sig:
    name: Optional[frozenset] = None   # expected name colours
    art_foil: Optional[bool] = None
    art_pale: Optional[bool] = None
    card_foil: Optional[bool] = None


def _fs(*a):
    return frozenset(a)


SIGNATURES: Dict[str, _Sig] = {
    "common": _Sig(_fs("black", "white"), False, None, False),
    "rare": _Sig(_fs("silver"), False, None, False),
    "super": _Sig(_fs("black", "white"), True),
    "ultra": _Sig(_fs("gold"), True),
    "ultimate": _Sig(_fs("gold"), True),
    "ghost": _Sig(_fs("silver"), None, True),
    "holographic": _Sig(_fs("silver"), None, True),
    "platinum": _Sig(_fs("silver"), True),
    "starlight": _Sig(_fs("white"), True),
    "secret": _Sig(_fs("rainbow"), True),
    "prismatic secret": _Sig(_fs("rainbow"), True),
    "extra secret": _Sig(_fs("rainbow"), None, None, True),
    "platinum secret": _Sig(None, True),
    "ultra secret": _Sig(_fs("rainbow"), True),
    "20th secret": _Sig(_fs("red"), True),
    "secret ultra": _Sig(_fs("gold"), True),
    "10000 secret": _Sig(_fs("black"), True),
    "gold": _Sig(_fs("gold"), True),
    "gold secret": _Sig(None, True),
    "ghost/gold": _Sig(None, None, True),
    "premium gold": _Sig(),
    "parallel": _Sig(None, None, None, True),
    "starfoil": _Sig(None, None, None, True),
    "mosaic": _Sig(None, None, None, True),
    "shatterfoil": _Sig(None, None, None, True),
    "collectors": _Sig(None, None, None, True),
    "millennium": _Sig(None, None, None, True),
}

_ABBR = {
    "c": "common", "r": "rare", "sr": "super", "ur": "ultra", "utr": "ultimate",
    "gr": "ghost", "hgr": "holographic", "plr": "platinum", "scr": "secret",
    "pscr": "prismatic secret", "escr": "extra secret", "plscr": "platinum secret",
    "uscr": "ultra secret", "20scr": "20th secret", "scur": "secret ultra",
    "gur": "gold", "gscr": "gold secret", "ggr": "ghost/gold", "pgr": "premium gold",
    "sfr": "starfoil", "msr": "mosaic", "shr": "shatterfoil", "cr": "collectors",
    "mr": "millennium",
}


def normalize_rarity(name: Optional[str]) -> Optional[str]:
    """Map a DB/CardTrader rarity name or abbreviation to a signature key."""
    if not name:
        return None
    s = name.strip().lower().replace("'", "").replace("’", "")
    if s in _ABBR:
        return _ABBR[s]
    if s.endswith(" rare"):
        s = s[:-5].strip()
    if s == "alternate":
        s = "starlight"
    if s == "collector":
        s = "collectors"
    return s if s in SIGNATURES else None


@dataclass
class RarityRanking:
    rarity: str
    score: float
    reasons: List[str] = field(default_factory=list)


@dataclass
class RaritySuggestion:
    rarity: str
    confidence: float
    reasons: List[str] = field(default_factory=list)


_W_NAME, _W_ART, _W_PALE, _W_CARD = 2.0, 0.8, 0.5, 1.0


def rank_rarities(cues: RarityCues, candidates: Iterable[str]) -> List[RarityRanking]:
    """Order the given candidate rarities by agreement with the visual cues.

    Rarities without a known signature score 0 (neutral). Ties keep input order.
    """
    cands = list(candidates)
    have_name = bool(cues.name_color_scores)
    total_w = 0.0
    if have_name:
        total_w += _W_NAME
    if cues.art_foil_prob is not None:
        total_w += _W_ART
    if cues.art_pale_prob is not None:
        total_w += _W_PALE
    if cues.card_foil_prob is not None:
        total_w += _W_CARD

    out: List[RarityRanking] = []
    for cand in cands:
        key = normalize_rarity(cand)
        sig = SIGNATURES.get(key) if key else None
        total = 0.0
        reasons: List[str] = []
        if sig is not None and total_w > 0:
            if have_name and sig.name:
                s = sum(cues.name_color_scores.get(c, 0.0) for c in sig.name)
                total += _W_NAME * (2 * s - 1)
                reasons.append(f"nombre {'/'.join(sorted(sig.name))}: {s:.2f}")
            if cues.art_foil_prob is not None and sig.art_foil is not None:
                p = cues.art_foil_prob
                total += _W_ART * ((2 * p - 1) if sig.art_foil else -(2 * p - 1))
                reasons.append(f"foil ilustracion esperado={sig.art_foil} (p={p:.2f})")
            if cues.art_pale_prob is not None and sig.art_pale is not None:
                p = cues.art_pale_prob
                total += _W_PALE * ((2 * p - 1) if sig.art_pale else -(2 * p - 1))
                reasons.append(f"ilustracion palida esperada={sig.art_pale} (p={p:.2f})")
            if cues.card_foil_prob is not None and sig.card_foil is not None:
                p = cues.card_foil_prob
                total += _W_CARD * ((2 * p - 1) if sig.card_foil else -(2 * p - 1))
                reasons.append(f"foil carta completa esperado={sig.card_foil} (p={p:.2f})")
        score = total / total_w if total_w > 0 else 0.0
        out.append(RarityRanking(cand, score, reasons))
    out.sort(key=lambda r: -r.score)  # stable
    return out


def suggest_rarity(cues: RarityCues, candidates: Iterable[str],
                   min_score: float = 0.25, min_margin: float = 0.2) -> Optional[RaritySuggestion]:
    """Return a rarity to preselect, or None when the cues are not decisive.

    Needs at least two candidates, a clearly positive best score and a clear
    margin over the runner-up (identical signatures such as Ultra/Ultimate
    never produce a suggestion).
    """
    cands = list(dict.fromkeys(candidates))
    if len(cands) < 2:
        return None
    ranking = rank_rarities(cues, cands)
    top, second = ranking[0], ranking[1]
    margin = top.score - second.score
    if top.score < min_score or margin < min_margin:
        return None
    conf = min(0.85, max(0.0, 0.4 + 0.3 * top.score + 0.3 * margin))
    return RaritySuggestion(top.rarity, round(conf, 3), top.reasons)


# ----------------------------------------------------------------------------
# Glue used by the UI (kept here so no logic lives in src/ui)
# ----------------------------------------------------------------------------

def pick_condition(result: dict, default: str) -> str:
    """Condition for a confirmed scan: valid suggestion, else the user default."""
    try:
        from src.core.constants import CARD_CONDITIONS
    except Exception:  # pragma: no cover
        CARD_CONDITIONS = list(APP_TO_CARDTRADER)
    sug = (result or {}).get("suggested_condition")
    return sug if sug in CARD_CONDITIONS else default


def pick_rarity(suggested: Optional[str], current: Optional[str],
                candidates: Iterable[str]) -> Optional[str]:
    """Preselect the suggested rarity only if it is one of the real candidates."""
    if suggested and suggested in set(candidates):
        return suggested
    return current
