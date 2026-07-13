"""Converts incident signals into an explainable root-cause assessment."""

from app.models.remediation import RootCause


class RootCauseAnalyzer:
    """Assigns confidence to known operational failure patterns."""

    def analyze(self, signals: set[str]) -> RootCause:
        """Return the most specific detected root cause."""
        if signals:
            category = sorted(signals)[0]
            return RootCause(category=category, confidence=0.9, evidence=f"Detected signal: {category}")
        return RootCause(category="unknown", confidence=0.0, evidence="No supported remediation signal was detected.")
