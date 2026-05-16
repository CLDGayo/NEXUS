"""Phase 2 test bootstrap.

Sets a deterministic ``WEBHOOK_API_KEY`` and clears Langfuse keys so no real
network calls are issued during unit tests. Imports of ``rag.messenger.main``
elsewhere in the suite must occur AFTER pytest imports this module.
"""

from __future__ import annotations

import os

os.environ.setdefault("WEBHOOK_API_KEY", "test-key")
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
