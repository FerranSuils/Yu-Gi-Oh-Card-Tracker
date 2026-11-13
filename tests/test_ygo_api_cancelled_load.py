import asyncio
import json
from unittest.mock import AsyncMock, patch

from src.services.ygo_api import YugiohService


def _db(tmp_path):
    path = tmp_path / 'card_db.json'
    path.write_text(json.dumps([{'id': 1, 'name': 'Kuriboh', 'type': 'Effect Monster', 'frameType': 'effect',
                                 'desc': 'x'}]), encoding='utf-8')
    return str(path)


def test_cancelled_load_does_not_poison_the_cache(tmp_path):
    """NiceGUI's run.io_bound returns None when the page's task is cancelled."""
    service = YugiohService()
    path = _db(tmp_path)
    with patch.object(service, '_get_db_file', return_value=path):
        with patch('src.services.ygo_api.run.io_bound', new_callable=AsyncMock, return_value=None):
            assert asyncio.run(service.load_card_database('en')) == []
        assert 'en' not in service._cards_cache

        async def direct(callback, *args, **kwargs):
            return callback(*args, **kwargs)

        with patch('src.services.ygo_api.run.io_bound', new=direct):
            cards = asyncio.run(service.load_card_database('en'))
    assert [card.name for card in cards] == ['Kuriboh']
