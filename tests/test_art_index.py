from src.services.scanner.art_index import plan_index_update


def test_plan_reuses_cached_features_and_lists_missing_images():
    cached = {'a.jpg': [1], 'gone.jpg': [2]}
    keep, missing = plan_index_update(cached, ['a.jpg', 'b.png', 'notes.txt', 'c.JPEG'])
    assert keep == {'a.jpg': [1]}
    assert missing == ['b.png', 'c.JPEG']


def test_plan_with_no_cache_indexes_every_image():
    keep, missing = plan_index_update(None, ['x.jpg', 'y.jpg'])
    assert keep == {} and missing == ['x.jpg', 'y.jpg']


def test_plan_with_complete_cache_has_nothing_to_do():
    keep, missing = plan_index_update({'x.jpg': [1]}, ['x.jpg'])
    assert keep == {'x.jpg': [1]} and missing == []


def test_running_head_follows_the_predictor_copy_after_first_inference():
    from types import SimpleNamespace as NS

    from src.services.scanner.art_index import running_classifier_head

    original_head, predictor_head = object(), object()
    yolo = NS(model=NS(model=[None, original_head]), predictor=None)
    assert running_classifier_head(yolo) is original_head
    yolo.predictor = NS(model=NS(model=NS(model=[None, predictor_head])))
    assert running_classifier_head(yolo) is predictor_head
