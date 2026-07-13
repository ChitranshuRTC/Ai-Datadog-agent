"""AI engine facade for prompt construction and incident signal analysis."""

from app.ai.incident_analyzer import IncidentAnalyzer
from app.ai.prompt_builder import PromptBuilder
from app.models.incident import Incident


class AIEngine:
    """Provides deterministic, auditable analysis input to the decision engine."""

    def __init__(self, prompt_builder: PromptBuilder, incident_analyzer: IncidentAnalyzer) -> None:
        self._prompt_builder = prompt_builder
        self._incident_analyzer = incident_analyzer

    def analyze(self, incident: Incident) -> set[str]:
        """Build incident context and derive normalized operational signals."""
        prompt = self._prompt_builder.build(incident)
        return self._incident_analyzer.analyze(incident, prompt)
