"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.api.router import api_router
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.config.settings import get_settings
from app.logging.configuration import configure_logging
from app.connectors.slack import SlackConnector
from app.services.incident_service import IncidentService
from app.services.thread_store import InMemoryThreadStore
from app.services.slack_thread_manager import SlackThreadManager
from app.services.remediation_service import RemediationService
from app.ai.engine import AIEngine
from app.ai.incident_analyzer import IncidentAnalyzer
from app.ai.prompt_builder import PromptBuilder
from app.action_engine.engine import KubernetesActionEngine
from app.action_engine.kubernetes import KubernetesConnector
from app.connectors.github import GitHubConnector
from app.connectors.github_ai import GitHubAIConnector
from app.decision_engine.engine import DecisionEngine
from app.decision_engine.root_cause_analyzer import RootCauseAnalyzer
from app.decision_engine.rule_engine import RuleEngine
from app.verification.engine import VerificationEngine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and gracefully shut down application resources."""
    configure_logging()
    slack_connector = SlackConnector.from_settings(get_settings())
    app.state.incident_service = IncidentService(SlackThreadManager(slack_connector, InMemoryThreadStore()))
    github = None
    github_ai = None
    if settings.github_token and settings.github_repository:
        github = GitHubConnector(settings.github_token.get_secret_value(), settings.github_repository, settings.github_base_branch)
        github_ai = GitHubAIConnector(settings.github_token.get_secret_value(), settings.github_repository, settings.github_base_branch)
    kubernetes = KubernetesConnector(settings.kubernetes_in_cluster)
    decision_engine = DecisionEngine(AIEngine(PromptBuilder(), IncidentAnalyzer()), RootCauseAnalyzer(), RuleEngine())
    app.state.remediation_service = RemediationService(
        decision_engine,
        KubernetesActionEngine(kubernetes, github),
        VerificationEngine(kubernetes, slack_connector, settings.remediation_wait_seconds),
        github_ai=github_ai,
        slack=slack_connector,
    )
    yield
    await app.state.incident_service.aclose()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered AIOps platform that receives Datadog incidents and coordinates Slack, GitHub, and Kubernetes remediation.",
    debug=settings.app_debug,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_origins != ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID", "X-Correlation-ID", "X-Incident-ID", "X-Datadog-Webhook-Token", "X-Datadog-Signature"],
)
app.add_middleware(RequestContextMiddleware)
register_exception_handlers(app)
app.include_router(api_router)
