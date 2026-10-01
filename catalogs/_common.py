"""Ferramentas comuns de catálogo: só lê páginas/FTP oficiais, nunca executa."""

from __future__ import annotations

import re
import io
import zipfile
import ssl
import unicodedata
from datetime import date
from ftplib import FTP, Error as FTPError
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

USER_AGENT = "PortalDownloadsDATASUS/1.0"
_HTTP_INDEX_FALLBACK_HOSTS = frozenset({"sia.datasus.gov.br"})
_DATE_PATTERN = re.compile(
    r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}[-/][A-Za-zÀ-ÿ.]{3,9}[-/]\d{4})(?!\d)"
)
_MONTHS = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4,
    "mai": 5, "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
    "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}


class LinkParser(HTMLParser):
    """Coleta pares (texto do link, href) de uma página de listagem simples."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = next((value for key, value in attrs if key.lower() == "href"), None)
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append(("".join(self._text).strip(), self._href))
        self._href = None
        self._text = []


class CatalogTableParser(HTMLParser):
    """Collect download links and their official file date from table rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[dict[str, object]] = []
        self._row: list[dict[str, object]] | None = None
        self._cell: dict[str, object] | None = None
        self._anchor: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": [], "links": []}
        elif tag == "a" and self._cell is not None:
            href = next((value for key, value in attrs if key.lower() == "href"), None)
            if href:
                self._anchor = {"href": href, "text": []}

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._anchor is not None:
            if self._cell is not None:
                self._cell["links"].append(self._anchor)
            self._anchor = None
        elif tag in {"td", "th"} and self._cell is not None:
            if self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            cells = self._row
            date_value = next(
                (release_date for cell in cells if (release_date := parse_release_date(" ".join(cell["text"])))),
                None,
            )
            for cell in cells:
                for link in cell["links"]:
                    name = " ".join(link["text"]).strip() or str(link["href"]).rsplit("/", 1)[-1]
                    entry = {"name": name, "url": link["href"], "size": None}
                    if date_value:
                        entry["release_date"] = date_value
                    self.entries.append(entry)
            self._row = None


def parse_release_date(value: str) -> str | None:
    """Normalize common date formats from official file listings to YYYY-MM-DD."""
    match = _DATE_PATTERN.search(str(value))
    if not match:
        return None
    candidate = match.group(0).strip().replace(".", "")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            return date.fromisoformat(candidate).isoformat()
        if "/" in candidate and candidate.split("/")[1].isdigit():
            day, month, year = (int(part) for part in candidate.split("/"))
            return date(year, month, day).isoformat()
        day_text, month_text, year_text = re.split(r"[-/]", candidate)
        month_key = unicodedata.normalize("NFKD", month_text).encode("ascii", "ignore").decode().lower()[:3]
        return date(int(year_text), _MONTHS[month_key], int(day_text)).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def fetch_index_links(url: str, *, timeout: int = 15, max_bytes: int = 2_000_000) -> list[tuple[str, str]]:
    """Baixa uma página de listagem e devolve os links encontrados nela."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        document = response.read(max_bytes + 1)
    if len(document) > max_bytes:
        raise ValueError(f"A página {url} excedeu o tamanho esperado.")
    parser = LinkParser()
    parser.feed(document.decode("utf-8", "replace"))
    return parser.links


def fetch_index_entries(url: str, *, timeout: int = 15, max_bytes: int = 2_000_000) -> list[dict[str, object]]:
    """Read file rows, retaining a publication date when the official page lists one."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response:
            document = response.read(max_bytes + 1)
    except URLError as exc:
        parsed = urlsplit(url)
        if not (
            isinstance(exc.reason, ssl.SSLCertVerificationError)
            and parsed.scheme == "https"
            and parsed.hostname in _HTTP_INDEX_FALLBACK_HOSTS
        ):
            raise
        # The official SIA portal currently has a certificate validation problem.
        # Retry only its read-only index over HTTP; file URLs remain separately validated.
        fallback_url = parsed._replace(scheme="http").geturl()
        fallback_request = Request(fallback_url, headers={"User-Agent": USER_AGENT})
        with urlopen(fallback_request, timeout=timeout) as response:
            document = response.read(max_bytes + 1)
    if len(document) > max_bytes:
        raise ValueError(f"A página {url} excedeu o tamanho esperado.")
    source = document.decode("utf-8", "replace")
    parser = CatalogTableParser()
    parser.feed(source)
    if parser.entries:
        return parser.entries
    links = LinkParser()
    links.feed(source)
    return [
        {"name": name or href.rsplit("/", 1)[-1], "url": href, "size": None}
        for name, href in links.links
    ]


def safe_official_url(
    url: str,
    name: str,
    *,
    https_hosts: frozenset[str] = frozenset(),
    ftp_hosts: frozenset[str] = frozenset(),
    ftp_path_prefix: str = "",
) -> bool:
    """Confere se um link aponta mesmo para o arquivo esperado, num host oficial conhecido."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if unquote(Path(parsed.path).name).lower() != name.lower():
        return False
    if parsed.scheme == "ftp":
        return bool(ftp_hosts) and parsed.hostname in ftp_hosts and parsed.path.lower().startswith(ftp_path_prefix.lower())
    return parsed.scheme == "https" and parsed.hostname in https_hosts


def fetch_ftp_names(host: str, directory: str, *, timeout: int = 15) -> list[str]:
    """Lista os nomes de arquivo de um diretório FTP público, sem baixar nada."""
    try:
        with FTP(host, timeout=timeout) as server:
            server.login()
            server.cwd(directory)
            return [Path(raw_name).name for raw_name in server.nlst()]
    except FTPError as exc:
        raise OSError("Não foi possível listar o diretório FTP oficial.") from exc


def download_via_http(url: str, name: str, *, max_size: int, timeout: int = 45) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        declared = response.headers.get("Content-Length")
        expected = int(declared) if isinstance(declared, str) and declared.isdigit() else None
        if expected is not None and expected > max_size:
            raise ValueError(f"O download de {name} excedeu o limite de tamanho.")
        chunks: list[bytes] = []
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > max_size:
                raise ValueError(f"O download de {name} excedeu o limite de tamanho.")
            chunks.append(block)
        if expected is not None and total != expected:
            raise ValueError(f"O download de {name} foi interrompido ou está incompleto.")
    return b"".join(chunks)


def download_via_ftp(host: str, directory: str, name: str, *, max_size: int, timeout: int = 45) -> bytes:
    chunks: list[bytes] = []
    total = 0

    def collect(block: bytes) -> None:
        nonlocal total
        total += len(block)
        if total > max_size:
            raise ValueError(f"O download de {name} excedeu o limite de tamanho.")
        chunks.append(block)

    try:
        with FTP(host, timeout=timeout) as server:
            server.login()
            server.cwd(directory)
            expected = None
            try:
                server.voidcmd("TYPE I")
                size = server.size(name)
                expected = size if isinstance(size, int) and size >= 0 else None
            except FTPError:
                pass
            if expected is not None and expected > max_size:
                raise ValueError(f"O download de {name} excedeu o limite de tamanho.")
            server.retrbinary(f"RETR {name}", collect, blocksize=1024 * 1024)
    except FTPError as exc:
        raise OSError(f"O servidor FTP não conseguiu entregar {name}.") from exc
    if expected is not None and total != expected:
        raise ValueError(f"O download de {name} foi interrompido ou está incompleto.")
    return b"".join(chunks)


def resolve_href(base_url: str, href: str) -> str:
    return urljoin(base_url, href)


def looks_like_windows_executable(package: bytes, *, min_size: int = 1_000_000) -> bool:
    return len(package) >= min_size and package[:2] == b"MZ"


def looks_like_zip(package: bytes, *, min_size: int = 1_000_000) -> bool:
    return len(package) >= min_size and package[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(package))


def download_release(
    url: str,
    name: str,
    *,
    safe_url_fn,
    max_size: int,
    min_size: int = 1_000_000,
    looks_valid_fn=looks_like_windows_executable,
    ftp_hosts: frozenset[str] = frozenset(),
) -> bytes:
    """Baixa um pacote já catalogado, sem executá-lo, revalidando o link antes."""
    if not safe_url_fn(url, name):
        raise ValueError(f"Link de download não permitido para {name}.")
    parsed = urlsplit(url)
    if parsed.scheme == "ftp":
        directory, _, filename = unquote(parsed.path).rpartition("/")
        hosts = list(dict.fromkeys([parsed.hostname or "", *sorted(ftp_hosts)]))
        last_error = None
        for host in hosts:
            candidate = parsed._replace(netloc=host).geturl()
            if not safe_url_fn(candidate, name):
                continue
            try:
                package = download_via_ftp(host, directory, filename, max_size=max_size)
                if not looks_valid_fn(package, min_size=min_size):
                    raise ValueError(f"O download de {name} não parece ser um pacote válido.")
                break
            except (OSError, ValueError) as exc:
                last_error = exc
        else:
            raise OSError(f"Nenhum servidor FTP conseguiu entregar {name}.") from last_error
    else:
        package = download_via_http(url, name, max_size=max_size)
    if not looks_valid_fn(package, min_size=min_size):
        raise ValueError(f"O download de {name} não parece ser um pacote válido.")
    return package
