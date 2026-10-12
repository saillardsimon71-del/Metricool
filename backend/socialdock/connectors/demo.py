"""Connecteur de démonstration — strictement local, jamais connecté au réseau.

Il permet :
* d'explorer l'application sans identifiants API ;
* de tester les scénarios difficiles (échec, timeout ambigu, publication privée,
  action humaine) de façon **déterministe**.

Le scénario est choisi explicitement (``payload.demo_scenario`` ou
``account.extra.demo_scenario``) — aucun comportement n'est simulé à l'insu de
l'utilisateur : les comptes de démonstration sont marqués ``mode="demo"``.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from ..models import Account
from .base import Capabilities, PublishContext, PublishResult, SocialConnector, StatusResult

SCENARIOS = ("success", "failure", "uncertain", "published_private", "waiting_for_user")


class DemoConnector(SocialConnector):
    platform = "demo"
    label = "Démonstration locale"

    def get_capabilities(self, account: Account | None = None) -> Capabilities:
        return Capabilities(
            platform=self.platform,
            label=self.label,
            auth_available=False,
            publish_video=True,
            publish_public=True,
            scheduling=True,
            upload=True,
            analytics=True,
            requires_review=False,
            restrictions=[
                "Plateforme simulée : rien n'est envoyé sur Internet.",
                "Les statistiques affichées sont générées localement et ne reflètent aucune audience réelle.",
            ],
            permissions_required=[],
            permissions_missing=[],
        )

    @staticmethod
    def scenario_for(context: PublishContext) -> str:
        explicit = (context.target.payload or {}).get("demo_scenario") or (context.account.extra or {}).get("demo_scenario")
        if explicit in SCENARIOS:
            return str(explicit)
        # Scénario déterministe dérivé de la clé d'idempotence (reproductible).
        digest = int(hashlib.sha256(context.target.idempotency_key.encode()).hexdigest(), 16)
        return SCENARIOS[digest % len(SCENARIOS)]

    def publish(self, context: PublishContext) -> PublishResult:
        scenario = self.scenario_for(context)
        for percent in (10, 40, 70, 95):
            context.report(percent, f"Démonstration : étape {percent} %")
            time.sleep(0.01)
        account_label = context.account.display_name or "compte démo"
        remote_id = f"demo-{context.target.id[:12]}"
        remote_url = f"https://demo.socialdock.local/{context.account.platform}/{remote_id}"
        if scenario == "success":
            return PublishResult(
                outcome="success",
                status="published",
                remote_id=remote_id,
                remote_url=remote_url,
                data={"scenario": scenario, "note": f"Publication simulée vers {account_label}"},
            )
        if scenario == "failure":
            return PublishResult(
                outcome="failure",
                status="failed",
                remote_id=remote_id,
                error_code="demo_rejected",
                error_message="Démonstration : la plateforme simulée a refusé la publication.",
                http_status=403,
                data={"scenario": scenario},
            )
        if scenario == "uncertain":
            return PublishResult(
                outcome="uncertain",
                status="uncertain",
                remote_id=remote_id,
                error_code="demo_ambiguous",
                error_message="Démonstration : réponse perdue après envoi (statut incertain).",
                requires_user_action=True,
                user_action_hint="Résolvez manuellement : marquer comme publiée, comme échouée, ou relancer.",
                data={"scenario": scenario},
            )
        if scenario == "published_private":
            return PublishResult(
                outcome="success",
                status="published_private",
                remote_id=remote_id,
                remote_url=remote_url,
                requires_user_action=True,
                user_action_hint="Démonstration : publiée en privé — passage en public à confirmer.",
                data={"scenario": scenario},
            )
        return PublishResult(
            outcome="success",
            status="waiting_for_user",
            remote_id=remote_id,
            requires_user_action=True,
            user_action_hint="Démonstration : terminez la publication manuellement puis enregistrez le lien.",
            data={"scenario": scenario},
        )

    def get_publish_status(self, context: PublishContext) -> StatusResult:
        if context.target.status == "published":
            return StatusResult(status="published", remote_url=context.target.remote_url, remote_id=context.target.remote_id)
        return StatusResult(status=context.target.status, detail="Statut simulé (aucun service distant).")

    def get_analytics(self, context: PublishContext) -> dict[str, Any]:
        """Métriques pseudo-aléatoires mais stables, explicitement étiquetées démo."""
        seed = int(hashlib.sha256(f"{context.target.id}-metrics".encode()).hexdigest(), 16)
        views = seed % 5000
        return {
            "metrics": {
                "views": views,
                "likes": views // 12,
                "comments": views // 90,
                "shares": views // 140,
            },
            "source": "demo.local",
            "note": "Données simulées : aucune audience réelle.",
        }
