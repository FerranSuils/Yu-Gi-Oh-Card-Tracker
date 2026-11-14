"""What became of every picture of one upload: which cards were read, which are missing, and the way to retry.

A PDF from a document scanner brings one card per page. The scanner works through them one at a time and a page
can be lost on the way (no card found, a failed read, the page closed). The batch remembers each page's picture
until its card is read, so the missing ones can be sent again without uploading the file again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

WAITING, FOUND, MISSING = 'waiting', 'found', 'missing'
NOT_READ = 'No se llegó a leer'


@dataclass
class Page:
    number: int
    image: Optional[bytes]
    extension: str
    status: str = WAITING
    filename: Optional[str] = None
    reason: str = ''
    attempts: int = 0


class UploadBatch:
    def __init__(self, source: str):
        self.source = source
        self.pages: Dict[int, Page] = {}
        self._by_file: Dict[str, int] = {}

    def add(self, number: int, image: bytes, extension: str) -> None:
        self.pages[number] = Page(number, image, extension)

    def queued(self, number: int, filename: str) -> None:
        """The page went to the scanner under this file name (a retry gets a new one)."""
        page = self.pages[number]
        for old, owner in list(self._by_file.items()):
            if owner == number:
                del self._by_file[old]
        page.filename = filename
        page.status = WAITING
        self._by_file[filename] = number

    def found(self, filename: str) -> None:
        page = self._page_of(filename)
        if page is not None:
            page.status, page.image, page.reason = FOUND, None, ''

    def lost(self, filename: str, reason: str) -> None:
        page = self._page_of(filename)
        if page is not None and page.status != FOUND:
            page.status, page.reason = MISSING, reason

    def settle(self) -> None:
        """The scanner has nothing left to do: whatever is not read yet never will be."""
        for page in self.pages.values():
            if page.status == WAITING:
                page.status, page.reason = MISSING, page.reason or NOT_READ

    def missing(self) -> List[int]:
        return sorted(number for number, page in self.pages.items() if page.status == MISSING)

    def reasons(self) -> Dict[int, str]:
        return {number: self.pages[number].reason for number in self.missing()}

    def counts(self) -> Dict[str, int]:
        states = [page.status for page in self.pages.values()]
        return {'found': states.count(FOUND), 'missing': states.count(MISSING), 'waiting': states.count(WAITING),
                'total': len(states)}

    def retry_items(self) -> List[Tuple[int, bytes, str]]:
        """The missing pages, ready to send again. They go back to waiting until the scanner answers."""
        items = []
        for number in self.missing():
            page = self.pages[number]
            if page.image is None:
                continue
            page.status, page.reason = WAITING, ''
            page.attempts += 1
            items.append((number, page.image, page.extension))
        return items

    def finished(self) -> bool:
        counts = self.counts()
        return counts['waiting'] == 0 and counts['missing'] == 0

    def summary(self) -> str:
        counts = self.counts()
        total, found = counts['total'], counts['found']
        if self.finished():
            if total == 1:
                return f'La carta de {self.source} está leída.'
            return f'Las {total} cartas de {self.source} están leídas.'
        head = f'{found} de {total} cartas de {self.source} leídas.'
        if counts['waiting']:
            return f'{head} Leyendo {counts["waiting"]}…'
        return f'{head} Faltan {counts["missing"]}.'

    def _page_of(self, filename: str) -> Optional[Page]:
        number = self._by_file.get(filename)
        return self.pages.get(number) if number is not None else None


def retry_label(missing: int) -> str:
    return 'Reintentar la que falta' if missing == 1 else f'Reintentar las {missing} que faltan'
