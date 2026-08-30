from __future__ import annotations

import unittest

from sqlalchemy.pool import NullPool

from db.session import get_engine


class DatabaseSessionTests(unittest.TestCase):
    def test_engine_does_not_reuse_connections_between_livekit_event_loops(self) -> None:
        engine = get_engine()

        self.assertIsInstance(engine.sync_engine.pool, NullPool)


if __name__ == "__main__":
    unittest.main()
