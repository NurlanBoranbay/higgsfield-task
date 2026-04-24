"""Allow running the eval framework as ``python -m eval``."""

import sys

from eval.cli import main

sys.exit(main())
