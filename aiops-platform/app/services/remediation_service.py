"""End-to-end automated remediation orchestration."""

import logging

from app.action_engine.engine import KubernetesActionEngine
from app.decision_engine.engine import DecisionEngine
from app.models.incident import Incident
from app.verification.engine import VerificationEngine, VerificationStatus

logger = logging.getLogger(__name__)


class RemediationService:
    """Decides, executes, verifies, and reports a remediation lifecycle."""

    def __init__(self, decision_engine: DecisionEngine, action_engine: KubernetesActionEngine, verification_engine: VerificationEngine) -> None:
        self._decision_engine = decision_engine
        self._action_engine = action_engine
        self._verification_engine = verification_engine

    async def remediate(self, incident: Incident, slack_thread_id: str) -> VerificationStatus:
        """Run the complete remediation lifecycle and report unexpected failures."""
        decision = self._decision_engine.decide(incident)
        try:
            result = await self._action_engine.execute(incident, decision, incident.pod_name)
            return await self._verification_engine.verify(incident, slack_thread_id, result)
        except Exception:
            logger.exception("Remediation execution failed for incident %s", incident.identifier)
            await self._verification_engine.report_failure(slack_thread_id)
            return VerificationStatus.FAILED
