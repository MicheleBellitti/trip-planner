"""Shared pytest setup for the skill tests (cd backend && uv run pytest ../skills -q).

Skill directories are uploaded as they are (notes 2c): keep them free of caches. Importing a
skill script or test module would otherwise leave __pycache__/ inside the skill directory.
This file sits in skills/, outside every skill directory, so it is never uploaded.
"""

import sys

sys.dont_write_bytecode = True
