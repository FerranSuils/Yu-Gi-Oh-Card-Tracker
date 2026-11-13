"""Each account only sees its own scans: queue, results, live report and recent scans."""
import os
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def manager(tmp_path, monkeypatch):
    """A manager with the real request and report models, without the vision libraries."""
    from src.services.scanner import manager as module
    from src.services.scanner import models

    monkeypatch.setattr(module, 'SCANNER_AVAILABLE', True)
    monkeypatch.setattr(module, 'CardScanner', MagicMock())
    for name in ('ScanRequest', 'ScanEvent', 'ScanDebugReport'):
        monkeypatch.setattr(module, name, getattr(models, name))
    made = module.ScannerManager()
    made.queue_dir = str(tmp_path)
    return made


def test_queue_only_lists_the_accounts_own_scans(manager):
    assert manager.submit_scan(b'a', {}, filename='ana.jpg', owner='ana')
    assert manager.submit_scan(b'b', {}, filename='bea.jpg', owner='bea')
    assert [item['filename'] for item in manager.get_queue_snapshot('ana')] == ['ana.jpg']
    assert [item['filename'] for item in manager.get_queue_snapshot('bea')] == ['bea.jpg']
    assert manager.get_queue_snapshot('otra') == []


def test_an_account_cannot_remove_another_accounts_scan(manager):
    manager.submit_scan(b'a', {}, filename='ana.jpg', owner='ana')
    request = manager.get_queue_snapshot('ana')[0]['id']
    assert manager.remove_scan_request(request, 'bea') is False
    assert len(manager.scan_queue) == 1 and os.path.exists(manager.scan_queue[0].filepath)
    assert manager.remove_scan_request(request, 'ana') is True
    assert manager.scan_queue == []
    assert manager.remove_scan_request(request, 'ana') is False


def test_results_reach_only_the_account_that_scanned(manager):
    manager._deliver({'set_code': 'LOB-EN005'}, 'ana')
    assert manager.is_idle('bea') and not manager.is_idle('ana')
    assert manager.get_latest_result('bea') is None
    assert manager.get_latest_result('ana') == {'set_code': 'LOB-EN005'}
    assert manager.get_latest_result('ana') is None and manager.is_idle('ana')


def test_queued_event_names_its_owner(manager):
    seen = []
    manager.register_listener(seen.append)
    manager.submit_scan(b'a', {}, filename='ana.jpg', owner='ana')
    assert [(event.type, event.data['owner']) for event in seen] == [('scan_queued', 'ana')]


def test_live_report_of_another_account_is_blank():
    from src.services.scanner.manager import report_for

    report = {'owner': 'ana', 'logs': ['Started: ana.jpg'], 'captured_image_url': '/x.jpg', 'paused': False,
              'queue_len': 3, 'current_step': 'OCR'}
    assert report_for(report, 'ana') is report
    hidden = report_for(report, 'bea')
    assert hidden['logs'] == [] and hidden['captured_image_url'] is None and hidden['current_step'] == 'Idle'
    assert hidden['paused'] is False
    assert report_for({'logs': ['x']}, 'bea') == {'logs': ['x']}  # nothing scanned yet: nobody's


def test_recent_scans_live_in_the_accounts_folder():
    from src.services.scanner.manager import recent_scans_path

    assert recent_scans_path('data').replace(os.sep, '/') == 'data/scans/scans_temp.json'
    assert recent_scans_path(os.path.join('data', 'users', 'bea')).replace(os.sep, '/') == \
        'data/users/bea/scans/scans_temp.json'


def test_a_new_scan_starts_with_a_clean_report(manager):
    state = manager.debug_state
    state.owner, state.logs, state.captured_image_url = 'ana', ['Started: ana.jpg'], '/debug/ana.jpg'
    state.match_candidates, state.paused, state.visual_rarity = [{'name': 'Carta de Ana'}], False, 'Secret Rare'
    manager._begin_report('bea')
    fresh = manager.debug_state
    assert (fresh.owner, fresh.logs, fresh.captured_image_url, fresh.match_candidates) == ('bea', [], None, [])
    assert fresh.visual_rarity == 'Unknown' and fresh.paused is False


def test_lookup_results_stay_out_of_another_accounts_live_report(manager):
    seen = []
    manager.register_listener(seen.append)
    manager._begin_report('bea')
    manager._publish_match([{'name': 'Carta de Ana'}], 'ana', {'set_code': 'ANA-001', 'ambiguous': False})
    assert manager.debug_state.match_candidates == []
    assert [(event.type, event.data['owner']) for event in seen] == [('step_complete', 'ana'), ('result_ready', 'ana')]
    manager._publish_match([{'name': 'Carta de Bea'}], 'bea', {'set_code': 'BEA-001', 'ambiguous': False})
    assert manager.debug_state.match_candidates == [{'name': 'Carta de Bea'}]
