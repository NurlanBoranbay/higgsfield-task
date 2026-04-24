#!/usr/bin/env python3
"""Entry point for the evaluation framework.

Usage:
    python run_eval.py                           # Run full suite
    python run_eval.py --case voyager_heliopause  # Run single case
    python run_eval.py --repeats 3                # Flakiness detection
    python run_eval.py --rescore --run-id abc123  # Re-score cached traces
    python run_eval.py --diff abc123              # Diff against previous
"""

import sys
from eval.cli import main

if __name__ == "__main__":
    sys.exit(main())
