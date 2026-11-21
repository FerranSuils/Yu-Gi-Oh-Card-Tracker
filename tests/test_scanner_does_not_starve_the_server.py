"""A 300-page scan must not take the web server down (2026-11-21: 159,379 threads, 21 GB, 504s)."""
import os
import sys
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

for name in ('langdetect', 'easyocr', 'keras_ocr', 'doctr', 'doctr.io', 'doctr.models', 'mmocr', 'mmocr.apis'):
    sys.modules.setdefault(name, MagicMock())

from src.services.scanner.manager import ScannerManager
from src.services.scanner.models import OCRResult


def test_doctr_does_not_open_a_thread_pool_per_batch():
    # On Windows every pool thread that touches torch leaves ~13 native threads behind for good.
    import src.services.scanner  # noqa: F401
    assert os.environ.get('DOCTR_MULTIPROCESSING_DISABLE') == 'TRUE'


@pytest.mark.asyncio
async def test_matching_against_the_card_database_runs_off_the_event_loop():
    manager = ScannerManager()
    manager.scanner = MagicMock()
    seen = set()

    def normalize(text):
        seen.add(threading.get_ident())
        return text.lower() if text else ''

    manager.scanner._normalize_card_name = normalize
    variant = MagicMock(set_code='TEST-EN001', set_rarity='Common', image_id=1, variant_id='v1')
    card = MagicMock(id=1, type='Monster', card_sets=[variant], card_images=[MagicMock(id=1)], atk=None, def_=None)
    card.name = 'Test Card'
    ocr = OCRResult(engine='test', raw_text='Test Card', card_name='Test Card', set_id='TEST-EN001', set_id_conf=90.0)

    with patch('src.services.scanner.manager.ygo_service') as ygo:
        ygo.load_card_database = AsyncMock(return_value=[card])
        result = await manager.find_best_match(ocr, None)

    assert result['candidates'][0]['set_code'] == 'TEST-EN001'
    assert seen and threading.get_ident() not in seen
