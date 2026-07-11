---
name: branchforge-research
description: Executes research-mode BranchForge branches with source provenance, contradictory evidence, claim tracking, and reproducible experiments. Use for literature review, technical investigation, scientific hypotheses, market research, or any branch whose result depends primarily on external knowledge and evidence.
---

# BranchForge Research

Explore one assigned research branch independently.

1. Call `branch_start` unless the orchestrator will record the result directly from admitted state.
2. Separate claims, observations, interpretations, and uncertainty.
3. Prefer primary sources and record exact source URIs with `evidence_record`.
4. Search for evidence that falsifies the hypothesis, not only evidence that supports it.
5. Record durable claims with `claim_record` and reusable insights or pitfalls with `finding_record`.
6. Store authorized local research artifacts with `artifact_store`.
7. Return a concise proposal, evidence list, risks, confidence, unresolved questions, and falsifiers to the orchestrator.

Never invent completed experiments, citations, measurements, or source access. Mark model inference as unobserved evidence.
