from src.services.scanner.ambiguity_queue import AmbiguityQueue


def _res(name):
    return {'candidates': [{'name': name}], 'ambiguity_flag': True}


def test_ambiguous_scans_wait_in_order_and_come_out_one_after_another():
    queue = AmbiguityQueue()
    for name in ('a', 'b', 'c'):
        queue.push(_res(name))
    assert len(queue) == 3
    order = []
    while (item := queue.next_to_show(scanner_idle=True)):
        order.append(item['candidates'][0]['name'])
        queue.closed()
    assert order == ['a', 'b', 'c'] and len(queue) == 0


def test_nothing_opens_while_the_scanner_is_still_working():
    queue = AmbiguityQueue()
    queue.push(_res('a'))
    assert queue.next_to_show(scanner_idle=False) is None
    assert len(queue) == 1
    assert queue.next_to_show(scanner_idle=True) is not None


def test_a_second_dialog_never_replaces_the_one_that_is_open():
    queue = AmbiguityQueue()
    queue.push(_res('a'))
    queue.push(_res('b'))
    assert queue.next_to_show(scanner_idle=True) is not None
    assert queue.next_to_show(scanner_idle=True) is None  # 'a' is still open
    queue.closed()
    assert queue.next_to_show(scanner_idle=True)['candidates'][0]['name'] == 'b'


def test_it_reports_what_is_pending_for_the_notice():
    queue = AmbiguityQueue()
    assert queue.pending() == 0 and not queue.busy()
    queue.push(_res('a'))
    queue.push(_res('b'))
    queue.next_to_show(scanner_idle=True)
    assert queue.pending() == 2 and queue.busy()  # one open, one waiting
    queue.closed()
    assert queue.pending() == 1 and not queue.busy()


def test_the_scan_page_queues_ambiguities_and_opens_the_next_when_one_closes():
    source = open('src/ui/scan.py', encoding='utf-8').read()
    assert 'self.ambiguities.push(res)' in source
    assert "dialog.on('hide', self.ambiguity_closed)" in source
    assert source.count('AmbiguityDialog(res') == 1  # only the queue opens dialogs


def test_pending_ambiguities_survive_leaving_the_scan_page():
    from src.services.scanner.ambiguity_queue import queue_for

    first_visit = queue_for('ana-survive')
    first_visit.push(_res('a'))
    first_visit.push(_res('b'))
    first_visit.next_to_show(scanner_idle=True)  # 'a' is on screen when the connection drops

    second_visit = queue_for('ana-survive')
    second_visit.reattach()
    assert second_visit.pending() == 2  # the one that was on screen is not lost either
    assert second_visit.next_to_show(scanner_idle=True)['candidates'][0]['name'] == 'a'
    assert queue_for('bea-survive').pending() == 0  # each account has its own


def test_the_scan_page_uses_the_accounts_own_lasting_queue():
    source = open('src/ui/scan.py', encoding='utf-8').read()
    assert 'self.ambiguities = queue_for(self.owner)' in source
    assert 'self.ambiguities.reattach()' in source
