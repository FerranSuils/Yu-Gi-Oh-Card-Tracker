import re

from src.services.scanner import upload


def test_a_150_mb_scanner_pdf_with_about_300_pages_is_accepted():
    assert upload.MAX_PDF_BYTES >= 300 * 1024 * 1024
    assert upload.MAX_PDF_PAGES >= 500


def test_the_web_server_lets_through_what_the_app_accepts():
    # IIS drops bigger bodies before the app sees them and the upload just sits at 0%.
    config = open('deploy/iis/web.config', encoding='utf-8').read()
    limit = int(re.search(r'maxAllowedContentLength="(\d+)"', config).group(1))
    assert limit >= upload.MAX_PDF_BYTES
