"""Allow running microrag as a module: python -m microrag."""

import sys

from microrag.cli import main

if __name__ == "__main__":
    sys.exit(main())
