"""Pytest fixtures for lazy-hsa tests."""

import pytest


@pytest.fixture
def family_members():
    """Default family members list."""
    return ["Alice", "Bob", "Charlie"]


@pytest.fixture
def mock_extractor():
    """Create a mock extractor for testing without LLM calls."""
    from src.processors.llm_extractor import MockVisionExtractor

    return MockVisionExtractor()
