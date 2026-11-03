"""Decide se uma execução agendada deve consultar as fontes.

O GitHub descarta boa parte dos agendamentos quando está sobrecarregado, então
o workflow é agendado a cada 30 minutos e esta conferência pula as execuções
que chegam pouco depois da última consulta. Assim as fontes continuam sendo
consultadas cerca de uma vez a cada duas horas. Execuções manuais e por push
sempre consultam.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"
MIN_INTERVAL = timedelta(minutes=100)


def should_run(catalog, event, now=None):
    if event != "schedule":
        return True
    now = now or datetime.now(timezone.utc)
    completed = str((catalog.get("last_check") or {}).get("completed_at") or "")
    try:
        checked_at = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    except ValueError:
        return True
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return now - checked_at >= MIN_INTERVAL


def main():
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        catalog = {}  # Sem catálogo legível, consultar é o caminho seguro.
    run = should_run(catalog if isinstance(catalog, dict) else {}, os.environ.get("GITHUB_EVENT_NAME", ""))
    completed = (catalog.get("last_check") or {}).get("completed_at") if isinstance(catalog, dict) else None
    print(f"Última consulta: {completed or 'nenhuma'}. {'Consultando agora.' if run else 'Recente; esta execução foi pulada.'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"run={'true' if run else 'false'}\n")


if __name__ == "__main__":
    main()
