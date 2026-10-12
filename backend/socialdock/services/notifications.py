"""Notifications locales (Windows) — sans dépendance externe obligatoire.

Sous Windows, on utilise PowerShell + ``System.Windows.Forms.NotifyIcon``
(ballon système), disponible sans installation supplémentaire. Ailleurs, ou en
cas d'échec, la notification est simplement journalisée.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Callable

log = logging.getLogger(__name__)

Notifier = Callable[[str, str, str], None]


def _windows_notify(title: str, message: str, level: str = "info") -> bool:
    script = (
        "[Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        "$n.Visible = $true;"
        f"$n.ShowBalloonTip(6000, [string]$args[0], [string]$args[1], [System.Windows.Forms.ToolTipIcon]::Info);"
        "Start-Sleep -Seconds 7;"
        "$n.Dispose()"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script, title[:120], message[:240]],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("Notification Windows indisponible : %s", exc)
        return False


class NotificationService:
    """Point d'entrée unique : le scheduler n'a pas à connaître la plateforme."""

    def __init__(self, *, enabled: bool = True, force_log: bool = False) -> None:
        self.enabled = enabled
        self.force_log = force_log
        self.sent: list[tuple[str, str, str]] = []

    def notify(self, title: str, message: str, level: str = "info") -> bool:
        self.sent.append((title, message, level))
        if not self.enabled:
            return False
        if not self.force_log and sys.platform.startswith("win") and os.environ.get("SOCIALDOCK_DISABLE_TOAST") != "1":
            if _windows_notify(title, message, level):
                return True
        log.info("[notification:%s] %s — %s", level, title, message)
        return True

    def __call__(self, title: str, message: str, level: str = "info") -> bool:
        return self.notify(title, message, level)
