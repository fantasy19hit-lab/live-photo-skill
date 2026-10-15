"""Portable tests; generated fixtures only, no private workspace paths."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/live-photo/scripts/live_photo.py"
spec = importlib.util.spec_from_file_location("live_photo", SCRIPT)
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class StructureTests(unittest.TestCase):
    def setUp(self):
        # Minimal container fixtures, intentionally not decodable media.
        self.cover = b"\xff\xd8\xff\xd9"
        self.video = b"".join(struct.pack(">I4s", 8, tag) for tag in (b"ftyp", b"moov", b"mdat"))
        self.motion = live.pack(self.cover, self.video)

    def test_roundtrip_preserves_payload(self):
        cover, video, offset = live.split_verified(self.motion)
        self.assertEqual(video, self.video)
        self.assertEqual(live.clean_jpeg(cover)[0], self.cover)
        self.assertEqual(offset + len(video), len(self.motion))

    def test_truncation_and_extra_data_rejected(self):
        for data in (self.motion[:-1], self.motion + b"x"):
            with self.subTest(data_length=len(data)), self.assertRaises(ValueError):
                live.split_verified(data)

    def test_wrong_metadata_rejected(self):
        for original, changed in ((b'MotionPhoto="1"', b'MotionPhoto="0"'),
                                  (b'MotionPhotoPresentationTimestampUs="0"',
                                   b'MotionPhotoPresentationTimestampUs="1"')):
            with self.subTest(field=original), self.assertRaises(ValueError):
                live.split_verified(self.motion.replace(original, changed, 1))

    def test_plain_jpeg_is_not_motion_photo(self):
        with self.assertRaises(ValueError):
            live.split_verified(self.cover)

    def test_mpf_and_appended_cover_rejected(self):
        for data in (self.motion, self.cover[:2] + b"\xff\xe2\x00\x06MPF\0" + self.cover[2:]):
            with self.subTest(data_length=len(data)), self.assertRaises(ValueError):
                live.clean_jpeg(data)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ffmpeg = live.executable("ffmpeg")
            live.executable("ffprobe")
        except ValueError as error:
            raise unittest.SkipTest(str(error))
        encoders = subprocess.run([cls.ffmpeg, "-hide_banner", "-encoders"],
                                  capture_output=True, text=True, check=True).stdout
        if "libx265" not in encoders or "libx264" not in encoders:
            raise unittest.SkipTest("Integration fixtures require libx264 and libx265")

    def test_png_h264_build_verify_copy_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="live-photo-test-") as directory:
            work = Path(directory)
            image, video = work / "cover.png", work / "video.mp4"
            def ffmpeg(*args):
                subprocess.run([self.ffmpeg, "-nostdin", "-v", "error", *map(str, args)],
                               check=True, capture_output=True)
            ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=240x320", "-frames:v", "1", image)
            ffmpeg("-f", "lavfi", "-i", "testsrc2=size=240x320:rate=30", "-t", "1",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", video)
            source_hashes = (live.sha(image.read_bytes()), live.sha(video.read_bytes()))
            output = work / "result_MP.jpg"
            command = [sys.executable, str(SCRIPT), "build", "--image", str(image),
                       "--video", str(video), "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["cover_processing"]["converted_to_jpeg"])
            self.assertEqual(report["video_processing"]["mode"], "encode_hevc")
            self.assertFalse(any(s["codec_type"] == "audio" for s in report["video"]["streams"]))
            self.assertAlmostEqual(report["video"]["duration_seconds"], 1, places=1)
            verified = subprocess.run([sys.executable, str(SCRIPT), "verify", str(output)],
                                      capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(verified.stdout)["sha256"], live.sha(output.read_bytes()))
            before = output.read_bytes()
            rejected = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(source_hashes, (live.sha(image.read_bytes()), live.sha(video.read_bytes())))
            cover, embedded, _ = live.split_verified(before)
            clean_cover, _ = live.clean_jpeg(cover)
            jpg, mp4 = work / "clean.jpg", work / "embedded.mp4"
            jpg.write_bytes(clean_cover)
            mp4.write_bytes(embedded)
            second = work / "copy_MP.jpg"
            copied = subprocess.run([sys.executable, str(SCRIPT), "build", "--image", str(jpg),
                                     "--video", str(mp4), "--video-mode", "copy", "--output", str(second)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(copied.stdout)["video_processing"]["mode"], "copy")
            self.assertEqual(second.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
