import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.cloud_batch import main, restore_checkpoints, safe_checkpoint_path


class CloudBatchTests(unittest.TestCase):
    def test_parallel_restore_verifies_and_writes_every_object(self):
        payloads = {f"data/screened/{index}.json": json.dumps({"id": index}).encode()
                    for index in range(64)}
        files = {name: hashlib.sha256(data).hexdigest()
                 for name, data in payloads.items()}

        class FakeS3:
            def get_object(self, *, Bucket, Key):
                if Key.endswith("crawler/checkpoints.json"):
                    body = json.dumps({"files": files}).encode()
                    return {"Body": io.BytesIO(body), "ETag": "checkpoint-etag"}
                digest = Key.rsplit("/", 1)[-1]
                name = next(name for name, value in files.items() if value == digest)
                return {"Body": io.BytesIO(payloads[name])}

        with tempfile.TemporaryDirectory() as folder:
            previous = Path.cwd()
            try:
                os.chdir(folder)
                restored, etag = restore_checkpoints(FakeS3(), "bucket", "run")
                self.assertEqual(restored, files)
                self.assertEqual(etag, "checkpoint-etag")
                self.assertEqual(len(list(Path("data/screened").glob("*.json"))), 64)
            finally:
                os.chdir(previous)

    def test_checkpoint_path_is_confined(self):
        self.assertEqual(safe_checkpoint_path("data/screened/1.json").as_posix(), "data/screened/1.json")
        for value in ("../secret.json", "/data/a.json", "data/../../a.json", "data/a.txt", "data\\a.json"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_checkpoint_path(value)

    def test_default_does_not_start_any_aws_or_crawler_calls(self):
        args = ["cloud_batch", "--bucket", "unused", "--run-id", "deployment-test",
                "--category", "상의", "--stage", "discover"]
        with patch("sys.argv", args), patch("src.cloud_batch.boto3.client") as aws, \
                patch("src.cloud_batch.subprocess.run") as crawler:
            main()
            aws.assert_not_called()
            crawler.assert_not_called()
