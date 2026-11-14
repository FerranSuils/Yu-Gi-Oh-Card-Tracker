import re
from types import SimpleNamespace as NS

from src.ui.components.ambiguity_dialog import preview_url
from src.ui.theme import GLOBAL_CSS

SOURCE = open('src/ui/components/ambiguity_dialog.py', encoding='utf-8').read()


def test_the_preview_uses_the_downloaded_picture_when_there_is_one():
    assert preview_url(123, [], exists=lambda i: True) == '/images/123.jpg'


def test_the_preview_falls_back_to_the_online_picture_instead_of_a_black_box():
    images = [NS(id=1, image_url_small='https://images.ygoprodeck.com/images/cards_small/1.jpg',
                 image_url='https://images.ygoprodeck.com/images/cards/1.jpg')]
    assert preview_url(1, images, exists=lambda i: False) == 'https://images.ygoprodeck.com/images/cards/1.jpg'
    assert preview_url(77, images, exists=lambda i: False) == 'https://images.ygoprodeck.com/images/cards/77.jpg'
    assert preview_url(None, images, exists=lambda i: False) is None


def test_the_dialog_floats_over_the_page_with_a_see_through_blurred_overlay_and_fits_small_screens():
    assert 'oy-modal' in SOURCE and 'backdrop-filter' in SOURCE
    assert re.search(r'\.oy-modal \.q-dialog__backdrop\s*\{[^}]*rgba\(', GLOBAL_CSS)
    assert 'max-w-[95vw]' in SOURCE and 'max-h-[92vh]' in SOURCE
    assert 'bg-black' not in SOURCE
