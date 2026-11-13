"""Checks for card images people upload to the scanner."""

from __future__ import annotations

import time
import uuid

MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def image_extension(content: bytes) -> str | None:
    """Extension for a JPEG, PNG or WebP image judged by its bytes, or None."""
    if not content or len(content) > MAX_UPLOAD_BYTES:
        return None
    if content.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'webp'
    return None


def safe_upload_name(original: str | None, extension: str) -> str:
    """A generated name: the client's file name never reaches the disk."""
    return f'upload_{int(time.time())}_{uuid.uuid4().hex[:6]}.{extension}'


def finished_notice(data: dict) -> tuple[str, str] | None:
    """Toast for a finished scan, or None when the result itself will show."""
    if not data.get('success'):
        return 'negative', f"Escaneo fallido: {data.get('error', 'error desconocido')}"
    if data.get('detected') is False:
        return 'warning', ('No se ha detectado ninguna carta en la imagen. Prueba con una foto '
                           'nítida, de frente y con el código de set visible.')
    return None


# --- PDFs from a document scanner: one card per page ---------------------

MAX_PDF_BYTES = 80 * 1024 * 1024
MAX_PDF_PAGES = 300
MIN_PAGE_IMAGE_SIDE = 120  # smaller pictures are logos or stamps, not a scanned card


def is_pdf(content: bytes) -> bool:
    return bool(content) and content[:1024].lstrip().startswith(b'%PDF')


def _as_scannable(image) -> bytes | None:
    """The embedded picture as JPEG, PNG or WebP bytes the scanner accepts."""
    import io
    data = image.data
    if image_extension(data):
        return data
    buffer = io.BytesIO()
    image.image.convert('RGB').save(buffer, 'JPEG', quality=92)
    return buffer.getvalue() if image_extension(buffer.getvalue()) else None


def pdf_page_images(content: bytes) -> list[bytes]:
    """The scanned picture of every page of a PDF, in page order.

    A document scanner stores one picture per page; pages without one are skipped.
    Raises ValueError with a message for the person when the file cannot be used.
    """
    import io

    from pypdf import PdfReader

    if len(content) > MAX_PDF_BYTES:
        raise ValueError(f'El PDF supera los {MAX_PDF_BYTES // (1024 * 1024)} MB')
    if not is_pdf(content):
        raise ValueError('El archivo no es un PDF')
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            # Many scanners only restrict printing or copying: those open with an empty password.
            try:
                opened = reader.decrypt('')
            except Exception:
                opened = 0
            if not opened:
                raise ValueError('El PDF está protegido con contraseña')
        pages = list(reader.pages)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'No se ha podido leer el PDF: {exc}') from exc
    if len(pages) > MAX_PDF_PAGES:
        raise ValueError(f'El PDF tiene {len(pages)} páginas; el máximo es {MAX_PDF_PAGES} páginas')

    images: list[bytes] = []
    for page in pages:
        best, best_area = None, 0
        try:
            for image in page.images:
                width, height = image.image.size
                if min(width, height) >= MIN_PAGE_IMAGE_SIDE and width * height > best_area:
                    best, best_area = image, width * height
            data = _as_scannable(best) if best is not None else None
        except Exception:
            data = None  # a damaged page must not lose the rest of the document
        if data:
            images.append(data)
    if not images:
        raise ValueError('El PDF no contiene ninguna imagen escaneada')
    return images


def upload_images(content: bytes) -> list[tuple[bytes, str]]:
    """What to scan from one uploaded file: the picture itself, or each page of a PDF."""
    if is_pdf(content):
        return [(data, image_extension(data)) for data in pdf_page_images(content)]
    extension = image_extension(content)
    if not extension:
        raise ValueError('no es una imagen JPG, PNG, WebP o PDF válido (imágenes hasta 15 MB, PDF hasta '
                         f'{MAX_PDF_BYTES // (1024 * 1024)} MB)')
    return [(content, extension)]


def queued_notice(queued: int, total: int, original: str | None, from_pdf: bool) -> tuple[str, str]:
    """(message, kind) for the toast after an upload: it only claims what really got queued."""
    name = original or ('PDF' if from_pdf else 'imagen')
    if queued <= 0:
        return f'No se ha podido poner en cola {name}.', 'negative'
    if queued < total:
        return f'En cola: {queued} de {total} cartas de {name}. El resto no se ha podido guardar.', 'warning'
    if from_pdf:
        return f'En cola: {queued} cartas de {name}', 'positive'
    return f'En cola: {name}', 'positive'
