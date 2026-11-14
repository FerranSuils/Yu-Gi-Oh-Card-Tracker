from src.services.scanner.batches import UploadBatch


def _batch(pages=4):
    batch = UploadBatch('mazo.pdf')
    for number in range(1, pages + 1):
        batch.add(number, f'img{number}'.encode(), 'jpg')
        batch.queued(number, f'file{number}.jpg')
    return batch


def test_a_new_batch_has_every_page_waiting():
    batch = _batch()
    assert batch.counts() == {'found': 0, 'missing': 0, 'waiting': 4, 'total': 4}


def test_a_page_is_found_by_the_file_name_the_scanner_reports():
    batch = _batch()
    batch.found('file2.jpg')
    assert batch.counts()['found'] == 1
    assert batch.counts()['waiting'] == 3


def test_a_page_that_was_not_read_is_missing_with_its_reason():
    batch = _batch()
    batch.lost('file3.jpg', 'No se detectó ninguna carta')
    assert batch.missing() == [3]
    assert batch.reasons() == {3: 'No se detectó ninguna carta'}


def test_an_unknown_file_name_changes_nothing():
    batch = _batch()
    batch.found('other.jpg')
    batch.lost('other.jpg', 'x')
    assert batch.counts() == {'found': 0, 'missing': 0, 'waiting': 4, 'total': 4}


def test_when_the_scanner_is_idle_every_page_not_found_counts_as_missing():
    batch = _batch()
    batch.found('file1.jpg')
    batch.found('file4.jpg')
    batch.settle()
    assert batch.missing() == [2, 3]
    assert batch.counts() == {'found': 2, 'missing': 2, 'waiting': 0, 'total': 4}


def test_a_found_page_gives_its_picture_back_to_memory():
    batch = _batch()
    batch.found('file1.jpg')
    assert batch.retry_items() == []
    assert batch.pages[1].image is None


def test_retrying_hands_out_only_the_missing_pages_under_new_names():
    batch = _batch()
    batch.found('file1.jpg')
    batch.found('file4.jpg')
    batch.settle()
    items = batch.retry_items()
    assert [(number, image, extension) for number, image, extension in items] == [(2, b'img2', 'jpg'), (3, b'img3', 'jpg')]
    assert batch.counts() == {'found': 2, 'missing': 0, 'waiting': 2, 'total': 4}
    batch.queued(2, 'again2.jpg')
    batch.found('again2.jpg')
    assert batch.counts()['found'] == 3
    assert batch.pages[2].attempts == 1


def test_the_old_name_of_a_retried_page_no_longer_counts():
    batch = _batch()
    batch.lost('file2.jpg', 'x')
    batch.retry_items()
    batch.queued(2, 'again2.jpg')
    batch.found('file2.jpg')
    assert batch.counts()['found'] == 0


def test_the_summary_says_how_many_are_left():
    batch = _batch(57)
    for number in range(1, 28):
        batch.found(f'file{number}.jpg')
    batch.settle()
    assert batch.summary() == '27 de 57 cartas de mazo.pdf leídas. Faltan 30.'
    batch.retry_items()
    assert batch.summary() == '27 de 57 cartas de mazo.pdf leídas. Leyendo 30…'
    for number in range(28, 58):
        batch.queued(number, f'again{number}.jpg')
        batch.found(f'again{number}.jpg')
    assert batch.summary() == 'Las 57 cartas de mazo.pdf están leídas.'


def test_the_scan_page_does_not_send_you_away_while_the_scanner_still_has_work():
    # A long PDF takes over an hour; the idle redirect to the home page used to cut it off halfway.
    from pathlib import Path
    source = Path('src/ui/scan.py').read_text(encoding='utf-8')
    assert 'window.resetScannerIdle = resetTimer' in source
    consumer = source[source.index('async def event_consumer'):]
    assert "ui.run_javascript('window.resetScannerIdle && window.resetScannerIdle()')" in consumer
    assert 'is_idle(self.owner)' in consumer


def test_the_retry_button_speaks_in_singular_and_plural():
    from src.services.scanner.batches import retry_label
    assert retry_label(1) == 'Reintentar la que falta'
    assert retry_label(30) == 'Reintentar las 30 que faltan'


def test_a_single_page_is_not_called_cartas():
    batch = _batch(1)
    batch.found('file1.jpg')
    assert batch.summary() == 'La carta de mazo.pdf está leída.'
