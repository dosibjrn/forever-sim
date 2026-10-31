# CLI and maintenance tools

This directory contains 286 Python programs, currently kept flat for compatibility. They include source capture, data ingestion, audits, validator/acceptance commands and benchmarking utilities.

**Stable documented gate entry point:**
```bash
python tools/wf_gate.py --class druid --level 60 --gate P7.1
```
Its default evidence target is `<repo>/gate_evidence`; this is a real current runtime interface, **not** an alias for `docs/evidence`.

Future categories could be `tools/gates/`, `tools/capture/`, `tools/ingest/`, `tools/audit/`, `tools/analysis/` and `tools/legacy/`, but first audit imports, documentation and `python tools/<name>.py` callers. Moving these 286 entry points wholesale would be an API break.

[Repository structure guide](../docs/REPOSITORY_STRUCTURE.md).
