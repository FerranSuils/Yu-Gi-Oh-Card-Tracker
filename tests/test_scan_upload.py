import re

from src.services.scanner.upload import MAX_UPLOAD_BYTES, image_extension, safe_upload_name

JPEG = b'\xff\xd8\xff\xe0' + b'0' * 20
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20
WEBP = b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'0' * 20


def test_image_extension_detects_real_images():
    assert image_extension(JPEG) == 'jpg'
    assert image_extension(PNG) == 'png'
    assert image_extension(WEBP) == 'webp'


def test_image_extension_rejects_non_images_and_oversize():
    assert image_extension(b'<html>not an image</html>') is None
    assert image_extension(b'') is None
    assert image_extension(JPEG + b'0' * MAX_UPLOAD_BYTES) is None


def test_safe_upload_name_never_keeps_the_client_path():
    name = safe_upload_name('../../evil.jpg', 'png')
    assert '/' not in name and '\\' not in name and '..' not in name
    assert re.fullmatch(r'upload_\d+_[0-9a-f]{6}\.png', name)
    assert safe_upload_name('a.jpg', 'jpg') != safe_upload_name('a.jpg', 'jpg')


def test_submit_scan_strips_directories_from_filename(tmp_path, monkeypatch):
    from src.services.scanner import manager as manager_module

    fake = type('M', (), {})()
    fake.queue_dir = str(tmp_path / 'queue')
    (tmp_path / 'queue').mkdir()
    fake.notification_queue = type('Q', (), {'put': lambda self, item: None})()
    fake.queue_lock = __import__('threading').Lock()
    fake.scan_queue = []
    fake._log_debug = lambda *a: None
    fake._emit = lambda *a: None
    monkeypatch.setattr(manager_module, 'SCANNER_AVAILABLE', False, raising=False)
    manager_module.ScannerManager.submit_scan(fake, JPEG, {}, filename='../outside.jpg')
    assert not (tmp_path / 'outside.jpg').exists()
    assert (tmp_path / 'queue' / 'outside.jpg').exists()


def test_finished_notice_warns_when_no_card_was_detected():
    from src.services.scanner.upload import finished_notice

    kind, text = finished_notice({'success': True, 'detected': False})
    assert kind == 'warning' and 'ninguna carta' in text
    assert finished_notice({'success': True, 'detected': True}) is None
    assert finished_notice({'success': True}) is None
    kind, text = finished_notice({'success': False, 'error': 'Frame read failed'})
    assert kind == 'negative' and 'Frame read failed' in text


# --- PDFs from a document scanner: one card per page ---------------------

import io
import os

import pytest

SCANNER_PDF = os.path.join(os.path.dirname(os.path.dirname(__file__)), '20261112174639.pdf')


def _pdf(sizes, mode='RGB'):
    from PIL import Image
    pages = [Image.new(mode, size, 'white' if mode != 'RGB' else (40 * (i + 1), 90, 160))
             for i, size in enumerate(sizes)]
    buffer = io.BytesIO()
    pages[0].save(buffer, 'PDF', save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def _sizes(images):
    from PIL import Image
    return [Image.open(io.BytesIO(data)).size for data in images]


def test_is_pdf_looks_at_the_bytes():
    from src.services.scanner.upload import is_pdf
    assert is_pdf(_pdf([(300, 420)]))
    assert not is_pdf(JPEG)
    assert not is_pdf(b'')


def test_pdf_page_images_gives_one_image_per_page_in_order():
    from src.services.scanner.upload import pdf_page_images
    images = pdf_page_images(_pdf([(300, 420), (310, 430), (320, 440)]))
    assert _sizes(images) == [(300, 420), (310, 430), (320, 440)]
    assert all(image_extension(data) for data in images)


def test_pdf_page_images_reencodes_what_the_scanner_cannot_read():
    from src.services.scanner.upload import pdf_page_images
    images = pdf_page_images(_pdf([(300, 420)], mode='1'))
    assert len(images) == 1 and image_extension(images[0])


def test_pdf_page_images_skips_pages_without_a_picture():
    from pypdf import PdfReader, PdfWriter
    from src.services.scanner.upload import pdf_page_images
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    for page in PdfReader(io.BytesIO(_pdf([(300, 420)]))).pages:
        writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    assert _sizes(pdf_page_images(buffer.getvalue())) == [(300, 420)]


def test_pdf_page_images_rejects_bad_files(monkeypatch):
    from src.services.scanner import upload
    with pytest.raises(ValueError, match='PDF'):
        upload.pdf_page_images(b'%PDF-1.7 this is not really a pdf')
    with pytest.raises(ValueError, match='PDF'):
        upload.pdf_page_images(JPEG)
    monkeypatch.setattr(upload, 'MAX_PDF_PAGES', 2)
    with pytest.raises(ValueError, match='2 páginas'):
        upload.pdf_page_images(_pdf([(300, 420)] * 3))
    monkeypatch.setattr(upload, 'MAX_PDF_BYTES', 10)
    with pytest.raises(ValueError, match='MB'):
        upload.pdf_page_images(_pdf([(300, 420)]))


def test_pdf_page_images_without_any_picture_is_an_error():
    from pypdf import PdfWriter
    from src.services.scanner.upload import pdf_page_images
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match='ninguna imagen'):
        pdf_page_images(buffer.getvalue())


@pytest.mark.skipif(not os.path.exists(SCANNER_PDF), reason='example scanner PDF not present')
def test_pdf_page_images_reads_the_example_document_scanner_pdf():
    from src.services.scanner.upload import pdf_page_images
    with open(SCANNER_PDF, 'rb') as file:
        images = pdf_page_images(file.read())
    assert len(images) == 9
    assert all(image_extension(data) == 'jpg' for data in images)
    assert all(600 < width < 800 and 900 < height < 1100 for width, height in _sizes(images))


def test_upload_images_takes_a_single_picture_or_every_page_of_a_pdf():
    from src.services.scanner.upload import upload_images
    assert upload_images(JPEG) == [(JPEG, 'jpg')]
    pages = upload_images(_pdf([(300, 420), (310, 430)]))
    assert [extension for _, extension in pages] == ['jpg', 'jpg']
    with pytest.raises(ValueError, match='JPG, PNG, WebP o PDF'):
        upload_images(b'hello')
