# Contributing to FastPanel

Thanks for your interest in contributing! FastPanel is an open-source project
and welcomes contributions of all kinds — bug reports, feature requests, documentation
improvements, and code.

## Local Development Setup

**Prerequisites**: Python 3.11+, [Poetry](https://python-poetry.org/)

```bash
# Clone the repo
git clone https://github.com/officialalkenes/fastpanel.git
cd fastpanel

# Install all dependencies including dev extras
poetry install --with dev

# Activate the virtual environment
poetry shell
```

### Running the Example App

```bash
cd fastpanel/
FASTPANEL_ENABLED=true uvicorn example.main:app --reload
```

Visit `http://localhost:8000/` — the FastPanel toolbar should appear in the
bottom-right corner.

### Running the Tests

```bash
# Run the full test suite
pytest

# Run with coverage (must stay ≥ 85%)
pytest --cov=fastpanel --cov-report=term-missing

# Run a specific test file
pytest tests/test_sql_panel.py -v
```

### Code Style

We use [black](https://black.readthedocs.io/) for formatting and
[ruff](https://docs.astral.sh/ruff/) for linting.

```bash
# Format code
black fastpanel/ tests/

# Run linter
ruff check fastpanel/ tests/

# Fix auto-fixable lint issues
ruff check --fix fastpanel/ tests/
```

### Pre-commit Hooks

Install pre-commit hooks to run black + ruff automatically before every commit:

```bash
pre-commit install
```

## Branch Naming Convention

| Prefix  | Use for                                      |
|---------|----------------------------------------------|
| `feat/` | New features (`feat/cache-redis-backend`)    |
| `fix/`  | Bug fixes (`fix/sql-location-async`)         |
| `docs/` | Documentation only (`docs/cache-panel-guide`) |
| `chore/`| Build, CI, dependency updates                |

## Pull Request Checklist

Before submitting a PR, please verify:

- [ ] All tests pass: `pytest`
- [ ] Coverage remains ≥ 85%: `pytest --cov=fastpanel`
- [ ] Code is formatted: `black fastpanel/ tests/`
- [ ] No lint errors: `ruff check fastpanel/ tests/`
- [ ] New features have tests in `tests/`
- [ ] Public API changes are reflected in docstrings
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]`

## Writing a Custom Panel

Subclass `AbstractPanel` to build a new panel:

```python
from fastpanel.panels.base import AbstractPanel
from starlette.requests import Request
from starlette.responses import Response
from typing import Any

class MyPanel(AbstractPanel):
    panel_id = "my_panel"
    title = "My Panel"

    def __init__(self) -> None:
        super().__init__()
        self._value: str = ""

    def reset(self) -> None:
        self._value = ""

    async def process_request(self, request: Request) -> None:
        self._value = request.headers.get("x-my-header", "not set")

    def get_stats(self) -> str:
        return self._value[:10]

    def get_data(self) -> dict[str, Any]:
        return {"header_value": self._value}
```

Register it:

```python
from fastpanel import FastPanel
FastPanel(app, enabled=True, extra_panels=[MyPanel])
```

## Reporting Bugs

Please open an issue at https://github.com/officialalkenes/fastpanel/issues with:
- Python version
- FastAPI + SQLAlchemy versions (if relevant)
- Minimal reproduction case
- Expected vs actual behaviour

## License

By contributing, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).
