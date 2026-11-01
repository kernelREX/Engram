"""Entry point for the frozen build.

PyInstaller runs its entry script as a top level module, so `engram/__main__.py` and its
relative imports cannot serve. This imports the package properly and hands straight over.
"""

import sys

from engram.cli import main

if __name__ == "__main__":
    sys.exit(main())
