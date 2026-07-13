"""Tests for Datadog incident parsing."""

from app.connectors.datadog import DatadogConnector


def test_parse_incident_extracts_datadog_monitor_fields() -> None:
    incident = DatadogConnector().parse_incident(
        b'{"id":"123","title":"CPU high","alert_status":"Alert","date":1710000000,"text":"Host CPU is saturated","tags":["namespace:payments","service:checkout","cluster_name:prod-eu"]}'
    )

    assert incident.identifier == "123"
    assert incident.severity == "critical"
    assert incident.namespace == "payments"
    assert incident.service == "checkout"
    assert incident.cluster == "prod-eu"
