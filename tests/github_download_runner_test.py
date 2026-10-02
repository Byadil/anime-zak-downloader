import importlib.util
import socket
from pathlib import Path
import unittest
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("runner", Path(__file__).resolve().parents[1] / "scripts/github-download-runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class DownloadRunnerSecurity(unittest.TestCase):
    def test_requires_canonical_https_worker_and_uuid(self):
        for origin in ["http://example.com", "https://user:pass@example.com", "https://example.com/path", "https://example.com?x=y"]:
            with self.assertRaises(ValueError):
                runner.Client(origin, "12345678-1234-1234-1234-123456789abc")
        with self.assertRaises(ValueError):
            runner.Client("https://example.com", "invalid")
    def test_rejects_initial_private_addresses_and_mixed_dns(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8",443)),
                     (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1",443))]
        with patch.object(socket, "getaddrinfo", return_value=addresses):
            with self.assertRaises(ValueError):
                runner.validate_source("https://example.com/video")
    def test_rejects_credentials_non_https_and_nonstandard_ports(self):
        for url in ["http://example.com/v", "https://u:p@example.com/v", "https://example.com:8080/v"]:
            with self.assertRaises(ValueError):
                runner.validate_source(url)
    def test_public_source_and_private_callback_path(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8",443))]
        with patch.object(socket, "getaddrinfo", return_value=addresses):
            self.assertEqual(runner.validate_source("https://example.com/v"), "https://example.com/v")
        c = runner.Client("https://example.com", "12345678-1234-1234-1234-123456789abc")
        self.assertIn("/api/internal/downloads/", c.base)
        self.assertNotIn("/media/jobs/", c.base)

if __name__ == "__main__":
    unittest.main()
