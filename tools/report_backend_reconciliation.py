"""Compatibility shim for the renamed backend-comparison report.

Use tools.report_backend_comparison in new code.
"""
from tools.report_backend_comparison import build_report, render_md, main, _mage_structural_build, _mage_level, _mage_policy_signature

if __name__ == "__main__":
    raise SystemExit(main())
