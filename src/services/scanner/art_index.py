"""Keeps the cached art index in step with the images on disk."""

from __future__ import annotations

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png')


def plan_index_update(cached: dict | None, files: list[str]) -> tuple[dict, list[str]]:
    """Cached features still backed by an image, and the images not indexed yet.

    The cache used to be trusted forever, so an index built while the model was
    still downloading (or before more card images arrived) never grew again.
    """
    images = [f for f in files if f.lower().endswith(IMAGE_EXTENSIONS)]
    cached = cached or {}
    keep = {f: cached[f] for f in images if f in cached}
    missing = [f for f in images if f not in cached]
    return keep, missing


def running_classifier_head(yolo):
    """The classifier head of the network that actually runs.

    After the first prediction ultralytics runs a fused copy inside its predictor
    (AutoBackend), so a hook on ``yolo.model`` only fires once per process.
    """
    predictor = getattr(yolo, 'predictor', None)
    backend = getattr(predictor, 'model', None) if predictor is not None else None
    network = getattr(backend, 'model', None) if backend is not None else None
    if network is not None and hasattr(network, 'model'):
        return network.model[-1]
    return yolo.model.model[-1]
