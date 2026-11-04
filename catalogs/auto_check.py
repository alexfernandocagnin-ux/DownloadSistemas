"""Consulta das fontes disparada pelo próprio portal quando o agendamento atrasa.

O GitHub só executa parte dos agendamentos, então o portal confere a data da
última consulta a cada visita e, se ela passou do prazo, consulta as fontes em
segundo plano. Uma única consulta roda por vez para todos os visitantes, e
uma nova tentativa só sai depois de um intervalo mínimo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock, Thread

STALE_AFTER = timedelta(hours=2, minutes=10)
RETRY_AFTER = timedelta(minutes=20)


def last_checked_at(snapshot):
    value = (snapshot.get("last_check") or {}).get("completed_at") or snapshot.get("updated_at")
    try:
        checked_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return checked_at if checked_at.tzinfo else checked_at.replace(tzinfo=timezone.utc)


def is_stale(snapshot, now=None):
    checked_at = last_checked_at(snapshot)
    return checked_at is None or (now or datetime.now(timezone.utc)) - checked_at > STALE_AFTER


class BackgroundCheck:
    def __init__(self):
        self._lock = Lock()
        self.running = False
        self.started_at = None

    def try_start(self, run, now=None):
        """Inicia `run` numa thread, a menos que uma consulta esteja em curso ou tenha começado há pouco."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self.running or (self.started_at and now - self.started_at < RETRY_AFTER):
                return False
            self.running, self.started_at = True, now

        def target():
            try:
                run()
            except Exception:
                pass  # A próxima visita depois do intervalo tenta de novo.
            finally:
                self.running = False

        Thread(target=target, name="consulta-automatica-portal", daemon=True).start()
        return True
