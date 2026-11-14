from src.services.scanner import autocapture


def test_the_choices_are_a_few_calm_intervals_with_the_default_among_them():
    assert autocapture.INTERVALS == (2, 3, 5, 10)
    assert autocapture.DEFAULT_INTERVAL in autocapture.INTERVALS


def test_it_captures_only_when_the_scanner_has_finished_the_last_card():
    assert autocapture.should_capture(scanner_idle=True) is True
    assert autocapture.should_capture(scanner_idle=False) is False


def test_the_label_says_how_often_it_looks():
    assert autocapture.interval_label(2) == 'Cada 2 s'
    assert autocapture.interval_label(10) == 'Cada 10 s'


def test_an_unknown_interval_falls_back_to_the_default():
    assert autocapture.clean_interval(7) == autocapture.DEFAULT_INTERVAL
    assert autocapture.clean_interval('5') == 5
    assert autocapture.clean_interval(None) == autocapture.DEFAULT_INTERVAL
