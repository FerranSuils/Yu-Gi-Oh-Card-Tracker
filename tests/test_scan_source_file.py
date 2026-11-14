import asyncio
from unittest.mock import MagicMock, patch

from src.services.scanner.models import OCRResult, ScanResult
from tests.mock_imports import import_with_module_mocks

manager_module = import_with_module_mocks(
    'src.services.scanner.manager',
    {'cv2': MagicMock(), 'src.services.scanner.pipeline': MagicMock()},
)


def _lookup(filename):
    return {"ocr_result": {"engine": "test", "raw_text": "x", "language": "EN"}, "art_match": None,
            "filename": filename, "owner": "ana"}


def test_a_finished_match_remembers_which_uploaded_file_it_came_from():
    manager = manager_module.ScannerManager()

    async def match(*args, **kwargs):
        return {"ambiguity": False, "candidates": [{"name": "A", "card_id": 1, "set_code": "X-EN001", "score": 90.0}]}

    manager.find_best_match = match

    async def run():
        # the models are only imported when the scanner libraries are installed
        with patch.object(manager_module, 'ygo_service') as ygo, \
                patch.object(manager_module, 'OCRResult', OCRResult, create=True), \
                patch.object(manager_module, 'ScanResult', ScanResult, create=True):
            ygo.get_card.return_value = None
            manager.lookup_queue.put(_lookup('upload_1.jpg'))
            await manager.process_pending_lookups()

    asyncio.run(run())
    assert manager.get_latest_result('ana')['source_file'] == 'upload_1.jpg'


def test_the_finished_event_names_the_file_so_the_page_can_tell_which_one_failed():
    source = open(manager_module.__file__, encoding='utf-8').read()
    assert source.count('"filename": filename') >= 3
