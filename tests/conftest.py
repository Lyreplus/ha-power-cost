"""Fixture comuni."""

import pytest


@pytest.fixture(autouse=True)
def mock_recorder_before_hass(async_test_recorder):
    """Prepara il database del recorder prima di creare hass."""


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Carica custom_components/ nei test."""
    yield
