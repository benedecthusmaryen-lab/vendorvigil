# VendorVigil — Demo Script (3-Minute Video)

## 🎥 Video Structure: 180 seconds

---

### [0:00-0:20] — OPENING: The Problem

**Narrator:**

"Every enterprise onboards dozens of third-party vendors every quarter. Each vendor handles customer data, processes payments, or accesses internal systems. But vendor security questionnaires take compliance teams weeks. Governance officers drown in spreadsheets. How do you know which vendor to approve, which to escalate, and which to reject — at speed?"

---

### [0:20-0:50] — INTRODUCING VENDORVIGIL

**Narrator:**

"We built VendorVigil — a Band-native multi-agent system for vendor risk triage. Seven specialized AI agents collaborate via Band Chat Room, with a Streamlit dashboard. Scoring is deterministic. Decisions are fail-closed. Every action is auditable. And we never claim to replace humans."

**[SCREEN: Show Streamlit dashboard with vendor selector]**

---

### [0:50-1:40] — GOLDEN PATH DEMO: CloudPayX → ESCALATED

**Narrator:**

"Let me show you the golden path. CloudPayX processes payments and stores customer personal data — a high-stakes vendor. I select CloudPayX from the dashboard and click 'Run Vendor Assessment'."

**[SCREEN: Click button, show loading]**

"@vendor_coordinator reads the profile, determines this vendor needs security, privacy, and financial assessment, and @mentions three parallel specialists in the Band Chat Room."

**[SCREEN: Show Band Chat transcript]**

"@security_reviewer (Pydantic AI + gpt-5-2) finds ISO 27001 certified, but SOC 2 is missing. Score: 58/100."

"@privacy_reviewer (Pydantic AI + gpt-5-nano) discovers the vendor processes personal data without a Data Processing Agreement. Score: 52/100."

"@financial_reviewer (Pydantic AI + Qwen3.6-27B) confirms the company is Series A funded and operationally active. Score: 74/100."

**[SCREEN: Show score cards]**

"@risk_scorer (Pydantic AI + Qwen3.5-27B) computes the weighted total: 52/100 — ESCALATED. Two fail-closed rules fired: personal data with no DPA, and payment processing with no SOC 2. Human review is now required."

**[SCREEN: Show the ESCALATED banner in orange with human review flag]**

"@audit_logger (Pydantic AI + Qwen3.6-35B) creates an immutable audit log — VV-2026-001 — with the complete agent trace."

**[SCREEN: Show audit details]**

"@report_compiler (Pydantic AI + gpt-5-1) generates the final report with executive summary, recommendations, and the mandatory disclaimer."

---

### [1:40-2:10] — THREE SCENARIOS SHOWCASED

**Narrator:**

"VendorVigil handles the full spectrum. SafeDocsID — a document storage vendor with ISO 27001 and DPA. Score: 100/100 — APPROVED."

**[SCREEN: Run SafeDocsID → green APPROVED]**

"QuickLeadPro — a marketing enrichment vendor with zero compliance evidence. Score: 20 — TEMPORARILY REJECTED."

**[SCREEN: Run QuickLeadPro → red TEMPORARILY REJECTED]**

"All three scenarios demonstrate the scoring engine, fail-closed rules, and audit trail in action. No decision is made without traceability."

---

### [2:10-2:50] — KEY DIFFERENTIATORS

**Narrator:**

"Three things make VendorVigil different. First: **deterministic scoring**. LLMs provide reasoning and extraction, but the final numeric score comes from pure Python. The system cannot hallucinate a risk score."

"Second: **fail-closed by design**. Seven override rules can only escalate decisions. A vendor can never be approved if it processes personal data without a DPA — period."

"Third: **true multi-agent architecture**. Seven distinct agents, each with its own model and provider. Pydantic AI as the unified agent framework. AI/ML API for frontier reasoning with four different models including Gemini 3 Flash and GPT-5. Featherless for two open-source models including Qwen3.5-27B and Qwen3.6. And Band as the coordination layer — NOT as a framework."

---

### [2:50-3:00] — CLOSING + DISCLAIMER

**Narrator:**

"VendorVigil is a decision support tool. It is not a legal certification, not an auditor, and not a human replacement. It helps compliance officers triage faster so they can focus on what matters: making the final call."

"Built by OlengSquad for the Band of Agents Hackathon 2026. Track 1: Internal Enterprise. Thank you."

**[SCREEN: Logo + "OlengSquad — VendorVigil" + disclaimer text + link]**
