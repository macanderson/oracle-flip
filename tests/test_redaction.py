import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from common import MAX_CONTENT_BYTES, content_fields, redact, truncate  # noqa: E402


class RedactTests(unittest.TestCase):
    def test_replaces_common_secret_shapes(self):
        text = "\n".join(
            [
                "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
                "token: ghp_abcdefghijklmnopqrstuvwxyz0123456789",
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
                "DATABASE_URL=postgres://user:hunter2hunter2@db.internal/app",
                "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----",
                "OPENAI_API_KEY='sk-abcdefghijklmnopqrstuvwxyz'",
            ]
        )
        redacted, count = redact(text)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", redacted)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz0123456789", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz012345", redacted)
        self.assertNotIn("hunter2hunter2", redacted)
        self.assertNotIn("MIIE", redacted)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertGreaterEqual(count, 6)

    def test_leaves_ordinary_code_alone(self):
        text = "def prorate_cents(price, days_used, days_in_month):\n    return round(price * days_used / days_in_month)\n"
        redacted, count = redact(text)
        self.assertEqual(redacted, text)
        self.assertEqual(count, 0)

    def test_assignment_redaction_keeps_the_key_name(self):
        redacted, count = redact("CLIENT_SECRET = 's3cr3tvalue'")
        self.assertEqual(count, 1)
        self.assertTrue(redacted.startswith("CLIENT_SECRET = '"))
        self.assertIn("[REDACTED]", redacted)

    def test_truncate_marks_and_bounds(self):
        text = "x" * (MAX_CONTENT_BYTES + 10)
        shown, truncated = truncate(text)
        self.assertTrue(truncated)
        self.assertIn("[truncated 10 bytes]", shown)
        shown2, truncated2 = truncate("short")
        self.assertFalse(truncated2)
        self.assertEqual(shown2, "short")

    def test_content_fields_hash_the_original_not_the_redaction(self):
        fields = content_fields("output", "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertNotIn("ghp_", fields["output_redacted"])
        self.assertEqual(len(fields["output_hash"]), 64)
        # Both the token pattern and the TOKEN= assignment pattern fire on this value.
        self.assertGreaterEqual(fields["output_redactions"], 1)
        self.assertFalse(fields["truncated"])

    def test_content_fields_serialize_objects_deterministically(self):
        a = content_fields("input", {"b": 1, "a": 2})
        b = content_fields("input", {"a": 2, "b": 1})
        self.assertEqual(a["input_hash"], b["input_hash"])


if __name__ == "__main__":
    unittest.main()
