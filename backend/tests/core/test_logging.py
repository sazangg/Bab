import logging

from app.core.logging import configure_logging


def test_configure_logging_uses_json_renderer_in_production() -> None:
    configure_logging(environment="production")

    processors = logging.getLogger().handlers[0].formatter.processors
    formatter = processors[-1]

    assert formatter.__class__.__name__ == "JSONRenderer"


def test_configure_logging_uses_console_renderer_in_development() -> None:
    configure_logging(environment="development")

    processors = logging.getLogger().handlers[0].formatter.processors
    formatter = processors[-1]

    assert formatter.__class__.__name__ == "ConsoleRenderer"
