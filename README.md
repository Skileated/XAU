# XAUUSD Quantitative Strategy Discovery and Decision Platform

A real, production-oriented quantitative research and trading infrastructure project for XAUUSD (Gold vs. US Dollar).

> **Engineering Rule**: This repository operates under strict quantitative research discipline: no synthetic market data, zero look-ahead bias, strict reproducibility, and an explicit Git Approval Gate.

---

## Phase Roadmap

- [x] **Phase 0**: Engineering Foundation
- [ ] **Phase 1**: Real XAUUSD data acquisition, validation, and storage
- [ ] **Phase 2**: Market feature engine
- [ ] **Phase 3**: Market state and regime engine
- [ ] **Phase 4**: Strategy DSL and compiler
- [ ] **Phase 5**: Strategy discovery engine
- [ ] **Phase 6**: Realistic backtesting engine
- [ ] **Phase 7**: Robustness and validation engine
- [ ] **Phase 8**: Strategy intelligence, clustering, and health
- [ ] **Phase 9**: Live XAUUSD market engine
- [ ] **Phase 10**: Strategy selector and adaptive playbook engine
- [ ] **Phase 11**: Risk engine and paper trading
- [ ] **Phase 12**: Broker execution layer
- [ ] **Phase 13**: Final product UI

---

## Phase 0: Engineering Foundation

Phase 0 provides the foundational architecture for the platform:
- Project layout and repository discipline
- Isolated Python 3.12 virtual environment
- Type-safe configuration subsystem (`xau_quant.config`) with environment variable substitution and provenance tracking
- Deterministic project-local path resolution (`xau_quant.common.paths`)
- Structured console and rotating file logging (`xau_quant.common.logging`)
- System and environment health verification CLI (`xau-health` and `scripts/health_check.py`)
- Full unit and integration test suite (`pytest`)
- Pre-installed analytical foundation (`duckdb`) without placeholder or fabricated data

---

## Setup Instructions

### Prerequisites
- Python `3.12.x` (Compatible with `>=3.12, <3.13`)
- Git

### 1. Create and Activate Virtual Environment
```powershell
# In project root:
python -m venv .venv

# Activate on Windows PowerShell:
.\.venv\Scripts\Activate.ps1
```

### 2. Install Package and Dependencies
Install in editable mode with development dependencies:
```powershell
pip install --upgrade pip
pip install -e ".[dev]"
```

### 3. Configure Environment Variables
Copy the template file to `.env` (optional, for local overrides):
```powershell
cp .env.example .env
```
*(Note: `.env` is ignored by Git and must never be committed).*

### 4. Run System Health Check
Verify the environment, directories, configuration, dependencies, logging, and Git state:
```powershell
# Using the installed CLI entrypoint:
xau-health

# Or using the standalone script:
python scripts/health_check.py
```

### 5. Run Unit and Integration Tests
```powershell
pytest
```

---

## Repository Structure

```
xau-quant-platform/
├── README.md
├── LICENSE
├── pyproject.toml
├── .gitignore
├── .env.example
├── configs/               # Environment configurations (development, research, paper)
├── src/xau_quant/         # Core application package
│   ├── common/            # Paths, structured logging, base exceptions
│   └── config/            # Pydantic schemas, YAML loader, provenance tracking
├── tests/                 # Unit, integration tests, and fixtures
├── research/              # Experiments, notebooks, and research reports
├── scripts/               # Maintenance and diagnostic scripts
├── data/                  # raw, interim, processed, features, metadata
├── artifacts/             # datasets, backtests, validation, models, reports
├── logs/                  # development, research, paper log sinks
└── apps/dev_ui/           # Minimal dev UI (reserved for future phases)
```

---

## Git Approval Gate

All Git commits and pushes are strictly gated:
Antigravity does not commit or push to version control without explicit approval from Nishant for that specific phase.
