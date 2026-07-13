"""Run a manual Kubernetes investigation against the configured current cluster."""

import asyncio
import json
import sys

from app.config.settings import get_settings
from app.connectors.kubernetes import KubernetesConnector
from app.services.investigation_service import InvestigationService
from app.models.investigation import InvestigationRequest


async def main() -> None:
    """Investigate the requested default pod and write a formatted JSON report."""
    settings = get_settings()
    connector = KubernetesConnector(settings.kubectl_path, settings.kubectl_timeout_seconds)
    service = InvestigationService(connector)
    result = await service.investigate(InvestigationRequest(namespace="default", pod="stress-app-77dfc6569f-g7t9k"))
    sys.stdout.write(json.dumps(result.model_dump(mode="json"), indent=2, default=str) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
