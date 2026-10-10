"""Data Gatekeeper — decide whether a dataset is fit to analyze, before it is.

Philosophy, shared with the funnel auditor:
- Diagnosis is read-only. The profiler never changes a byte.
- Dirt and structure are different things. Missing deal attributes for lost
  MQLs is *correct*, not dirty — the profiler proves which is which instead of
  guessing.
- Every fix is proposed with its reasoning and applied only on explicit
  human approval. The originals are never overwritten; every change is logged.
"""
__version__ = "0.1.0"
