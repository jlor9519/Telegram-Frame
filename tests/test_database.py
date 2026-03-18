from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.models import ImageRecord


class DatabaseTests(unittest.TestCase):
    def test_database_init_seed_and_latest_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            database = Database(Path(tmpdir) / "frame.db")
            database.initialize()
            database.seed_admins([111])
            database.seed_whitelist([222])

            self.assertTrue(database.is_admin(111))
            self.assertTrue(database.is_whitelisted(111))
            self.assertTrue(database.is_whitelisted(222))

            record = ImageRecord(
                image_id="img-1",
                telegram_file_id="file-1",
                local_original_path="/tmp/original.jpg",
                local_rendered_path="/tmp/rendered.png",
                dropbox_original_path=None,
                dropbox_rendered_path=None,
                location="Berlin",
                taken_at="2026-03-18",
                caption="A caption",
                uploaded_by=111,
                created_at="2026-03-18T12:00:00+00:00",
                status="displayed",
                last_error=None,
            )
            database.upsert_image(record)
            latest = database.get_latest_image()

            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.image_id, "img-1")
            self.assertEqual(latest.status, "displayed")


if __name__ == "__main__":
    unittest.main()

