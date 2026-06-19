# VendorVigil — Hackathon Submission Draft

## Team: OlengSquad
## Track: 1 — Internal Enterprise
## Partners: AI/ML API, Featherless AI

---

## Short Description (≤ 300 chars)

VendorVigil is a Band-native multi-agent system for enterprise vendor risk triage. Seven specialized AI agents collaborate via Band Chat Room to assess security, privacy, and financial risks with deterministic scoring, fail-closed rules, and immutable audit trail. Built for governance officers who need fast, auditable decisions — not chatbot chitchat.

---

## Long Description

### The Problem

Enterprise governance teams board 50+ third-party vendors every quarter. Each vendor processes customer data, payments, or accesses internal systems. The manual review process takes weeks of compliance officers sifting through spreadsheets, questionnaires, and evidence docs. The result? Bottlenecked procurement, inconsistent risk decisions, and no audit trail.

### Our Solution

**VendorVigil** automates the initial triage of vendor risk assessments using seven specialized AI agents coordinated through Band's Chat Room. It is NOT a certification tool, NOT an auditor, and NOT a human replacement. It is a decision support engine for governance teams — fast, auditable, and fail-closed by design.

### Architecture — 7 Remote Agents, Multi-Model

| Agent | Model | Provider | Role |
|-------|-------|----------|------|
| @vendor_coordinator | `google/gemini-3-flash-preview` | AI/ML API | Reads vendor profile, routes to specialists |
| @security_reviewer | `openai/gpt-5-2` | AI/ML API | Security posture + SOC 2/ISO 27001 check |
| @privacy_reviewer | `openai/gpt-5-nano-2025-08-07` | AI/ML API | Data privacy + DPA + retention policy |
| @financial_reviewer | `Qwen/Qwen3.6-27B` | Featherless | Financial stability + operational risk |
| @risk_scorer | `Qwen/Qwen3.5-27B` | Featherless | Deterministic score + fail-closed rules |
| @audit_logger | `openai/gpt-5-2` | AI/ML API | Immutable audit trail + agent trace |
| @report_compiler | `openai/gpt-5-1` | AI/ML API | Executive summary + recommendations |

### How It Works

1. **User** @mentions @vendor_coordinator in Band Chat Room with a vendor name
2. **Coordinator** reads vendor profile and @mentions specialists for parallel assessment
3. **Three specialists** analyze security, privacy, and financial domains concurrently
4. **Risk scorer** computes weighted total score (deterministic Python — NOT LLM hallucination)
5. **Fail-closed rules** escalate decisions that would otherwise pass (e.g., data + no DPA = automatic ESCALATED)
6. **Audit agent** creates immutable log with unique ID (VV-YYYY-NNN), full agent trace, and mandatory disclaimer
7. **Report agent** synthesizes findings into a Streamlit dashboard with executive summary and recommendations

### Scoring Engine (Deterministic)

- Security 35% | Privacy 30% | Financial 20% | Evidence 15%
- APPROVED (80-100): Proceed to contract
- NEEDS_REVISION (65-79): Complete missing evidence
- ESCALATED (45-64): Mandatory human review
- TEMPORARILY_REJECTED (0-44): Not eligible

### 7 Fail-Closed Rules

1. Personal data + no DPA → ESCALATED
2. Payment + no SOC 2 → ESCALATED
3. No ISO 27001 + no encryption → ESCALATED
4. Two sub-scores below 50 → ESCALATED
5. Total score below 45 → TEMPORARILY_REJECTED
6. Agent confidence below 0.75 → ESCALATED
7. Incomplete input → never APPROVED

### Technology Classification (Critical)

- **Band** = coordination layer (NOT a framework)
- **Pydantic AI** = agent framework for all 7 agents (unified, clean adapter)
- **LangGraph** = orchestration framework (available, not used in current adapter)
- **AI/ML API** = provider/gateway for frontier models (Gemini 3 Flash, GPT-5-2, GPT-5-nano, GPT-5-1)
- **Featherless** = provider/gateway for open-source models (Qwen3.5-27B, Qwen3.6-27B)

### What Makes Us Different

1. **Deterministic scoring**: The final risk score is computed by Python math, not by an LLM. We use LLMs for extraction, reasoning, and explanation — never for the final decision.
2. **Fail-closed by design**: The system can only escalate decisions, never approve risky vendors. Personal data without DPA is always ESCALATED, regardless of numeric score.
3. **True multi-agent**: 7 distinct agents with different models (7 unique) and providers (AI/ML API + Featherless). Pydantic AI as unified agent framework. No single agent pretending to be many.
4. **Complete audit trail**: Every run generates a unique audit ID with the full agent trace and immutable log.
5. **Band-native**: All coordination happens through @mention in Band Chat Room. The demo shows the full conversation transcript.

### Demo

Three fictional vendor scenarios showcase the full spectrum:
- **SafeDocsID**: Document storage, full compliance → APPROVED (100/100)
- **CloudPayX**: Payment processing, missing SOC 2 + DPA → ESCALATED (52/100) — GOLDEN PATH
- **QuickLeadPro**: Marketing enrichment, zero evidence → TEMPORARILY_REJECTED (20/100)

### Safe Position

VendorVigil is a decision support tool for initial vendor risk triage. This system is not an official auditor, not a compliance certification, and not a replacement for human judgment.

---

## Tags

`vendor-risk` `governance` `multi-agent` `band-native` `fail-closed` `audit-trail` `enterprise` `decision-support` `pydantic-ai` `langgraph` `aiml-api` `featherless` `streamlit` `compliance`

---

## Partner Credits

- **AI/ML API**: $10 credit via lablab.ai partner program — used for frontier model reasoning (Gemini 3 Flash, GPT-5-2, GPT-5-nano, GPT-5-1)
- **Featherless AI**: $25 credit via lablab.ai, promo BOA26 — used for open-source reasoning (Qwen3.5-27B, Qwen3.6-27B)

---

## Repository

The full project is structured for immediate execution:
- `agents/` — 7 agent implementations
- `utils/` — scoring engine, schemas, partner clients, audit log
- `app/streamlit_app.py` — interactive demo dashboard
- `config/` — model policy and scoring rules YAML
- `run_pipeline.py` — single-command end-to-end pipeline
- `tests/` — unit tests for scoring, fail-closed rules, golden path
