"""Allow ``python -m arciv.scripts`` to invoke the CLI."""

import sys

from .cli import main

sys.exit(main())
