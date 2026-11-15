# Contributing to lazy-hsa

Thank you for your interest in contributing to lazy-hsa! This document provides guidelines for contributing.

## Adding New Provider Skills

Provider skills are the heart of lazy-hsa - they enable accurate extraction from specific healthcare providers and retailers.

### Step 1: Identify the Provider Format

Collect sample documents (redact personal info) and identify:
- Key fields: patient name, service date, amount, etc.
- Field locations and labels
- Any unique identifiers or patterns

### Step 2: Add the Skill

Edit `src/processors/llm_extractor.py`:

```python
PROVIDER_SKILLS = {
    # ... existing skills ...

    "your_provider": """
YOUR PROVIDER-SPECIFIC RULES:
- Document type: receipt/EOB/statement
- Look for "Field Name" for patient_responsibility
- Look for "Date of Service" for service_date
- provider_name should be "Your Provider Name"
- category should be "medical/dental/vision/pharmacy"

FIELD MAPPING:
- patient_responsibility: [describe where to find it]
- billed_amount: [describe where to find it]
- insurance_paid: [describe where to find it]
""",
}
```

### Step 3: Add Detection Pattern

In `detect_provider_skill()`, add a pattern:

```python
provider_patterns = [
    # ... existing patterns ...
    (["your_provider", "alternate_name"], "your_provider"),
]
```

### Step 4: Test

```bash
# Dry-run with a sample file
lazy-hsa process --file sample.pdf --dry-run

# Run tests
uv run pytest tests/test_llm_extractor.py -v
```

### Step 5: Submit PR

- Include the provider skill
- Add detection patterns
- Add tests if possible
- Redact any personal info from examples

## Development Setup

```bash
# Clone and install
git clone https://github.com/yourusername/lazy-hsa.git
cd lazy-hsa
uv sync --dev

# Run linting
uv run ruff check src/
uv run ruff format src/

# Run tests
uv run pytest
```

## Code Style

- Follow PEP 8 (enforced by ruff)
- Type hints for function signatures
- Docstrings for public methods
- Keep functions focused and small

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/new-provider`)
3. Make your changes
4. Run tests and linting
5. Commit with descriptive message
6. Push and create PR

## Reporting Issues

When reporting issues, please include:
- lazy-hsa version
- Python version
- Ollama model being used
- Relevant error messages
- Sample document format (redacted)

## Questions?

Open a [Discussion](https://github.com/yourusername/lazy-hsa/discussions) for questions or ideas.
