from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union

class OCRResult(BaseModel):
    engine: str
    scope: str = "full" # full or crop
    raw_text: str
    set_id: Optional[str] = None
    card_passcode: Optional[str] = None
    card_name: Optional[str] = None
    set_id_conf: float = 0.0
    language: str = "EN"
    atk: Optional[str] = None
    def_val: Optional[str] = Field(None, alias="def")
    card_type: Optional[str] = None # "Spell", "Trap", "Monster" (inferred)

class ScanStep(BaseModel):
    name: str
    status: str # SUCCESS, FAIL
    details: Optional[str] = None

class ScanRequest(BaseModel):
    id: str
    timestamp: float
    filepath: str
    options: Dict[str, Any]
    type: str = "Manual Scan"
    filename: str
    owner: str = ""  # account that queued it; only that account sees it

class ScanResult(BaseModel):
    """Final result for consumption by the UI/DB"""
    name: str = "Unknown Card"
    card_id: Optional[int] = None
    set_code: Optional[str] = None
    rarity: str = "Unknown"
    visual_rarity: str = "Common"
    language: str = "EN"
    first_edition: bool = False
    ocr_conf: float = 0.0
    image_path: Optional[str] = None
    image_id: Optional[int] = None
    variant_id: Optional[str] = None
    match_score: int = 0
    ambiguity_flag: bool = False
    candidates: List[Dict[str, Any]] = [] # List of potential matches
    scan_image_path: Optional[str] = None # Path to the temporary warped image
    raw_image_path: Optional[str] = None # Path to the temporary raw image
    source_file: Optional[str] = None # Name of the uploaded or captured file this card came from
    # For UI display
    raw_ocr: Optional[List[OCRResult]] = None
    # Visual suggestions (grading.py). Only hints: None / 0.0 means "could not decide".
    suggested_condition: Optional[str] = None   # app literal, e.g. "Near Mint"
    condition_label: Optional[str] = None       # CardTrader label NM/SP/MP/PL/PO
    condition_confidence: float = 0.0
    suggested_rarity: Optional[str] = None      # one of the candidate rarities
    rarity_confidence: float = 0.0
    rarity_hints: Optional[Dict[str, Any]] = None  # name colour scores etc. for debugging

class ScanDebugReport(BaseModel):
    """Comprehensive state for the Debug Lab"""
    owner: str = ""  # account whose scan this report describes
    logs: List[str] = []
    queue_len: int = 0
    paused: bool = True
    current_step: str = "Idle"

    captured_image_url: Optional[str] = None
    warped_image_url: Optional[str] = None
    roi_viz_url: Optional[str] = None

    # Intermediate OCR results
    t1_full: Optional[OCRResult] = None # EasyOCR
    t1_crop: Optional[OCRResult] = None
    t2_full: Optional[OCRResult] = None # DocTR
    t2_crop: Optional[OCRResult] = None

    # YOLO Art Match
    art_match_yolo: Optional[Dict[str, Any]] = None

    # Metadata
    preprocessing: str = "classic"
    active_tracks: List[str] = []

    visual_rarity: str = "Unknown"
    first_edition: bool = False
    card_type: Optional[str] = None # "Spell", "Trap"
    steps: List[ScanStep] = []

    # Final Match Candidates
    match_candidates: List[Dict[str, Any]] = []

class ScanEvent(BaseModel):
    type: str # 'status_update', 'scan_queued', 'scan_finished', 'error'
    data: Dict[str, Any] # Flexible payload
    snapshot: Optional[ScanDebugReport] = None # Include full state snapshot for UI consistency
