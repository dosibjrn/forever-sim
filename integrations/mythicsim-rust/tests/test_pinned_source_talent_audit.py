"""Source-provenance tests only: these are NOT native Rust score tests."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_pinned_source_talent_audit import SourceAuditError, verify_row


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


class PinnedSourceTalentAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.engine = self.root / "engine"
        (self.engine / "fixtures").mkdir(parents=True)
        self.path = self.engine / "fixtures" / "mage.request.json"
        self.request = {"raid": {"parties": [{"players": [{
            "class": "ClassMage", "talentsString": "5-5-5"
        }]}]}}
        self.write_request()
        self.row = {
            "profile_id": "mage/fire",
            "source_repository": "sage3648/mythicsim-forever-engine",
            "source_path": "fixtures/mage.request.json",
            "git_blob_sha1": blob_sha(self.path.read_bytes()),
            "source_talent_string": "5-5-5",
            "source_talent_points": 15,
            "points_missing_to_51": 36,
            "point_total_status": "INCOMPLETE_51",
        }

    def write_request(self):
        self.path.write_text(json.dumps(self.request), encoding="utf-8")

    def verify(self):
        return verify_row(self.row, repo_root=self.root, engine_src=self.engine)

    def test_exact_git_blob_and_talent_payload_are_verified(self):
        self.assertEqual(("mage", "5-5-5", 15), self.verify())

    def test_changed_fixture_is_not_accepted_using_old_git_blob(self):
        self.request["raid"]["parties"][0]["players"][0]["talentsString"] = "5-5-4"
        self.write_request()
        with self.assertRaisesRegex(SourceAuditError, "git_blob_sha1"):
            self.verify()

    def test_changed_talents_are_rejected_even_with_updated_blob(self):
        self.request["raid"]["parties"][0]["players"][0]["talentsString"] = "5-5-4"
        self.write_request()
        self.row["git_blob_sha1"] = blob_sha(self.path.read_bytes())
        with self.assertRaisesRegex(SourceAuditError, "source_talent_string"):
            self.verify()

    def test_wrong_class_and_path_escape_are_rejected(self):
        self.request["raid"]["parties"][0]["players"][0]["class"] = "ClassWarrior"
        self.write_request()
        self.row["git_blob_sha1"] = blob_sha(self.path.read_bytes())
        with self.assertRaisesRegex(SourceAuditError, "class identity"):
            self.verify()
        self.row["source_path"] = "../outside.json"
        with self.assertRaisesRegex(SourceAuditError, "source_path"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
