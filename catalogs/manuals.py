"""Biblioteca de documentação oficial com cópias locais verificadas."""

from __future__ import annotations

import json
import hashlib
import unicodedata
from pathlib import Path

from catalogs._common import looks_like_zip

MANUALS_PATH = Path(__file__).parent.parent / "data" / "manuals.json"
SYSTEMS = {
    "bpa": ("BPA Magnético", "🧾"),
    "apac": ("APAC Magnético", "📝"),
    "sia": ("SIA / BDSIA", "🏥"),
    "fpo": ("FPO Magnético", "🧮"),
    "sihd2": ("SIHD2", "🏨"),
    "cnes": ("CNES / SCNES", "🗂️"),
    "ciha02": ("CIHA02", "🏛️"),
    "sigtap": ("SIGTAP", "💊"),
}
MAX_MANUAL_SIZE = 50_000_000
MANUALS_DIR = Path(__file__).parent.parent / "static" / "manuals"


def load_manuals():
    return json.loads(MANUALS_PATH.read_text(encoding="utf-8"))


def search_text(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(char))


def filter_manuals(query="", system="", category=""):
    words = search_text(query).split()
    return [manual for manual in load_manuals()
            if (not system or manual["system"] == system)
            and (not category or manual["category"] == category)
            and all(word in search_text(" ".join((manual["title"], manual["description"],
                                                 SYSTEMS[manual["system"]][0], manual["category"])))
                    for word in words)]


def download_manual(manual_id: str) -> bytes:
    manual = next((item for item in load_manuals() if item["id"] == manual_id), None)
    if not manual:
        raise ValueError("Manual não encontrado.")
    filename = manual.get("file", "")
    if not filename or Path(filename).name != filename or "/" in filename or "\\" in filename:
        raise ValueError("Cópia de manual inválida.")
    target = MANUALS_DIR / filename
    if target.stat().st_size > MAX_MANUAL_SIZE:
        raise ValueError("O documento excedeu o limite de tamanho.")
    package = target.read_bytes()
    if len(package) != manual["size"] or hashlib.sha256(package).hexdigest() != manual["sha256"]:
        raise ValueError("A integridade da cópia do manual não foi confirmada.")
    if manual["format"] == "PDF":
        valid = package.startswith(b"%PDF-") and b"%%EOF" in package[-1024:]
    else:
        valid = looks_like_zip(package, min_size=20)
    if not valid:
        raise ValueError("A fonte não entregou um documento válido. Tente novamente mais tarde.")
    return package
