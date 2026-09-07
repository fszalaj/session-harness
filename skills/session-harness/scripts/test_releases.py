"""Release validation and update contracts without network or model calls."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import releases


def archive(extra=None, selected="0.1.0"):
    buffer = io.BytesIO()
    files = {"RELEASE.json": json.dumps(dict(repository=releases.REPOSITORY, version=selected)),
             "skills/session-harness/VERSION": selected,
             "scripts/install-agent-profile.py": "# installer\n"}
    files.update(extra or {})
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, value in files.items():
            item = zipfile.ZipInfo()
            item.filename = item.orig_filename = f"session-harness-{selected}/" + name
            bundle.writestr(item, value)
    return buffer.getvalue()


class ReleaseTests(unittest.TestCase):
    def metadata(self):
        base = "https://github.com/fszalaj/session-harness/releases/download/v0.1.0/"
        return dict(tag_name="v0.1.0", immutable=True, draft=False, prerelease=False,
                    assets=[dict(name=n, browser_download_url=base+n)
                            for n in ("session-harness-0.1.0.zip", "SHA256SUMS")])

    def test_only_exact_stable_versions(self):
        self.assertEqual(releases.version("v0.1.0"), "0.1.0")
        for value in ("main", "latest", "1.2", "1.2.3-rc1", "../1.2.3", "01.2.3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                releases.version(value)

    def test_metadata_rejects_mutable_draft_prerelease_and_wrong_tag(self):
        for changes in ({"immutable": False}, {"draft": True}, {"prerelease": True}, {"tag_name": "v0.2.0"}):
            data = dict(self.metadata(), **changes)
            with patch.object(releases, "fetch", return_value=json.dumps(data).encode()):
                with self.assertRaises(ValueError):
                    releases.release_metadata("0.1.0")

    def test_safe_archive_extracts_and_rejects_wrong_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = releases.unpack(archive(), Path(directory), "0.1.0")
            self.assertTrue((root / "scripts/install-agent-profile.py").is_file())
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            releases.unpack(archive({"skills/session-harness/VERSION": "0.2.0"}), Path(directory), "0.1.0")

    def test_unsafe_archive_names_and_duplicate_paths_are_rejected(self):
        for name in ("../escape", "x/../../escape", "x\\escape", "C:/escape", "./escape", "release.JSON", "CON.txt", "x/aux", "x. ", "x//y"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                releases.unpack(archive({name: "bad"}), Path(directory), "0.1.0")

    def test_symlink_and_size_bounds(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            item = zipfile.ZipInfo("session-harness-0.1.0/link")
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(item, "../outside")
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            releases.unpack(buffer.getvalue(), Path(directory), "0.1.0")
        with patch.object(releases, "MAX_EXTRACTED", 1):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                releases.unpack(archive(), Path(directory), "0.1.0")

    def test_checksums_and_asset_urls(self):
        data = archive()
        checksum = hashlib.sha256(data).hexdigest() + "  session-harness-0.1.0.zip\n"
        with patch.object(releases, "fetch", side_effect=[checksum.encode(), data]):
            with tempfile.TemporaryDirectory() as directory:
                self.assertTrue(releases.download_release(self.metadata(), Path(directory)).is_dir())
        with patch.object(releases, "fetch", side_effect=[b"0"*64 + b"  session-harness-0.1.0.zip\n", data]):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                releases.download_release(self.metadata(), Path(directory))
        meta = self.metadata(); meta["assets"][0]["browser_download_url"] = "https://example.com/archive"
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            releases.download_release(meta, Path(directory))

    def test_failed_download_preserves_private_state_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); state = home / ".local/state/session-harness"
            state.mkdir(parents=True)
            ledger = state / "quota.sqlite3"; ledger.write_bytes(b"history stays unchanged")
            with patch.object(releases, "download_release", side_effect=ValueError("checksum")):
                with self.assertRaises(ValueError): releases.update(home, self.metadata(), {})
            self.assertEqual(ledger.read_bytes(), b"history stays unchanged")
            self.assertFalse((state / "update.lock").exists())

    def test_concurrent_update_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); lock = home / ".local/state/session-harness/update.lock"
            lock.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "Another update"):
                releases.update(home, self.metadata(), {})
            self.assertTrue(lock.is_dir())


if __name__ == "__main__":
    unittest.main()
