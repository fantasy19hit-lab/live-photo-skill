#!/usr/bin/env python3
"""Build and verify single-file motion JPEGs. Python standard library + FFmpeg.

Default XMP and packing layout adapted from flashlab/motion-live-photo,
commit 48b884713c496ed4e4ad5ba688e84e6eb82ca059 (MIT; bundled license).
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"
COMMIT = "48b884713c496ed4e4ad5ba688e84e6eb82ca059"
XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\0"
EXT_HEADER = b"http://ns.adobe.com/xmp/extension/\0"
NS = {"g": "http://ns.google.com/photos/1.0/camera/",
      "o": "http://ns.oplus.com/photos/1.0/camera/",
      "mi": "http://ns.xiaomi.com/photos/1.0/camera/",
      "c": "http://ns.google.com/photos/1.0/container/",
      "i": "http://ns.google.com/photos/1.0/container/item/"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def executable(name):
    found = shutil.which(name)
    if found:
        return found
    for directory in ("/opt/homebrew/bin", "/usr/local/bin"):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise ValueError(f"Missing {name}. Install FFmpeg (includes ffprobe) or add it to PATH.")


def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"{Path(str(args[0])).name} failed: {result.stderr[-3000:]}")
    return result.stdout


def probe(path):
    return json.loads(run([executable("ffprobe"), "-v", "error", "-show_streams",
                           "-show_format", "-of", "json", path]))


def decode(path):
    run([executable("ffmpeg"), "-nostdin", "-v", "error", "-xerror", "-i", path,
         "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"])


def jpeg_parts(data):
    """Parse JPEG markers including progressive scans; never search EXIF for EOI."""
    require(data[:2] == b"\xff\xd8", "Cover is not a JPEG")
    parts = []
    pos = 2
    in_scan = False
    while pos < len(data):
        if in_scan:
            start = pos
            while True:
                marker = data.find(b"\xff", pos)
                require(marker >= 0 and marker + 1 < len(data), "Truncated JPEG scan")
                end = marker + 1
                while end < len(data) and data[end] == 255:
                    end += 1
                require(end < len(data), "Truncated JPEG marker")
                code = data[end]
                if code == 0 or 0xD0 <= code <= 0xD7:
                    pos = end + 1
                    continue
                parts.append((None, start, marker, b""))
                pos = marker
                in_scan = False
                break
        start = pos
        require(data[pos] == 255, "Invalid JPEG marker boundary")
        while pos < len(data) and data[pos] == 255:
            pos += 1
        require(pos < len(data), "Truncated JPEG marker")
        code = data[pos]
        pos += 1
        if code == 0xD9:
            parts.append((code, start, pos, b""))
            return parts, pos
        if code == 0x01 or 0xD0 <= code <= 0xD7:
            parts.append((code, start, pos, b""))
            continue
        require(code not in (0, 0xD8), "Unexpected JPEG marker")
        require(pos + 2 <= len(data), "Truncated JPEG segment")
        size = int.from_bytes(data[pos:pos+2], "big")
        require(size >= 2 and pos + size <= len(data), "Invalid JPEG segment length")
        end = pos + size
        parts.append((code, start, end, data[pos+2:end]))
        pos = end
        in_scan = code == 0xDA
    raise ValueError("Missing JPEG end marker")


def clean_jpeg(data):
    parts, end = jpeg_parts(data)
    require(end == len(data), "Cover contains appended data; export a plain JPEG/PNG first")
    result = bytearray(data[:2])
    removed = 0
    for code, start, stop, payload in parts:
        require(not (code == 0xE2 and payload.startswith(b"MPF\0")),
                "Multi-picture/HDR JPEG offsets need conversion: export an SDR PNG/JPEG first")
        if code == 0xE1 and payload.startswith((XMP_HEADER, EXT_HEADER)):
            removed += 1
        else:
            result.extend(data[start:stop])
    return bytes(result), removed


def xmp_for(video_length):
    template = (ROOT / "assets/default.xmp").read_text(encoding="utf-8")
    # The three lengths are identical in the pinned upstream default template.
    require(template.count('="5417125"') == 3, "Bundled XMP template changed unexpectedly")
    return template.replace('="5417125"', f'="{video_length}"').encode("utf-8")


def pack(cover, video):
    payload = XMP_HEADER + xmp_for(len(video)) + b"\n"
    require(len(payload) + 2 <= 65535, "XMP APP1 exceeds JPEG segment limit")
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return cover[:2] + app1 + cover[2:] + video


def check_mp4(data):
    pos, kinds = 0, []
    while pos < len(data):
        require(pos + 8 <= len(data), "Truncated MP4 box")
        size, kind = struct.unpack_from(">I4s", data, pos)
        header = 8
        if size == 1:
            require(pos + 16 <= len(data), "Truncated MP4 extended box")
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            header = 16
        elif size == 0:
            size = len(data) - pos
        require(size >= header and pos + size <= len(data), "Invalid MP4 box size")
        kinds.append(kind)
        pos += size
    require(kinds and kinds[0] == b"ftyp" and b"moov" in kinds and b"mdat" in kinds,
            "Expected a complete MP4 with leading ftyp, moov and mdat")


def split_verified(data):
    parts, image_end = jpeg_parts(data)
    xmp_parts = [p for p in parts if p[0] == 0xE1 and p[3].startswith(XMP_HEADER)]
    require(len(xmp_parts) == 1 and xmp_parts[0][1] == 2,
            "Expected exactly one XMP APP1 immediately after JPEG SOI")
    xml_bytes = xmp_parts[0][3][len(XMP_HEADER):]
    tree = ET.fromstring(xml_bytes)
    desc = tree.find(".//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description")
    require(desc is not None, "Missing XMP Description")
    def attr(prefix, name):
        return desc.get("{" + NS[prefix] + "}" + name)
    for name in ("MotionPhoto", "MotionPhotoVersion", "MicroVideo", "MicroVideoVersion"):
        require(attr("g", name) == "1", f"Invalid {name}")
    require(attr("o", "MotionPhotoOwner") == "oplus" and attr("o", "OLivePhotoVersion") == "2",
            "Missing upstream Oplus compatibility fields")
    require(attr("mi", "XMPMeta") is not None, "Missing MiCamera compatibility field")
    length = int(attr("g", "MicroVideoOffset") or "0")
    require(length > 0 and attr("o", "VideoLength") == str(length), "Video lengths disagree")
    items = tree.findall(".//c:Directory//c:Item", NS)
    require(len(items) == 2, "Expected Primary and MotionPhoto directory items")
    ia = lambda item, name: item.get("{" + NS["i"] + "}" + name)
    require(ia(items[0], "Semantic") == "Primary" and ia(items[0], "Mime") == "image/jpeg",
            "Invalid primary item")
    require(ia(items[1], "Semantic") == "MotionPhoto" and ia(items[1], "Mime") == "video/mp4"
            and ia(items[1], "Length") == str(length), "Invalid motion item")
    require(xml_bytes == xmp_for(length) + b"\n", "XMP differs from the validated default preset")
    require(len(data) - length == image_end, "Video offset does not align with JPEG end")
    video = data[image_end:]
    check_mp4(video)
    return data[:image_end], video, image_end


def summarize(info):
    keys = ("codec_type", "codec_name", "codec_tag_string", "width", "height", "pix_fmt",
            "duration", "avg_frame_rate", "sample_rate", "channels")
    return {"duration_seconds": float(info["format"].get("duration", 0)),
            "streams": [{k: s[k] for k in keys if k in s} for s in info["streams"]]}


def verify_bytes(data, tmp):
    cover, video, offset = split_verified(data)
    cover_path, video_path = tmp / "verify.jpg", tmp / "verify.mp4"
    cover_path.write_bytes(cover)
    video_path.write_bytes(video)
    decode(cover_path)
    decode(video_path)
    info = probe(video_path)
    require(any(s["codec_type"] == "video" for s in info["streams"]), "No video stream")
    require(float(info["format"].get("duration", 0)) > 0, "Video has no duration")
    return {"status": "passed", "bytes": len(data), "sha256": sha(data),
            "video_offset": offset, "video_bytes": len(video), "video_sha256": sha(video),
            "xmp_preset": "flashlab-default", "xmp_at_byte_2": True,
            "jpeg_and_mp4_decode": "passed", "video": summarize(info),
            "platform_validation": "local_checks_only; historical sample user-validated"}


def prepare_cover(source, tmp):
    raw = source.read_bytes()
    converted = raw[:2] != b"\xff\xd8"
    if converted:
        dest = tmp / "converted-cover.jpg"
        run([executable("ffmpeg"), "-nostdin", "-v", "error", "-i", source,
             "-frames:v", "1", "-q:v", "2", "-pix_fmt", "yuvj420p", "-update", "1", dest])
        raw = dest.read_bytes()
    cleaned, removed = clean_jpeg(raw)
    return cleaned, {"converted_to_jpeg": converted, "removed_xmp_segments": removed}


def prepare_video(source, tmp, args):
    info = probe(source)
    videos = [s for s in info["streams"] if s["codec_type"] == "video"]
    audios = [s for s in info["streams"] if s["codec_type"] == "audio"]
    require(videos, "Input has no video stream")
    duration = float(info["format"].get("duration", 0))
    require(math.isfinite(duration) and duration > 0, "Video duration must be positive")
    require(args.start < duration, "Start time is beyond the video duration")
    v = videos[0]
    raw = source.read_bytes()
    try:
        check_mp4(raw)
        is_mp4 = True
    except ValueError:
        is_mp4 = False
    rotation = any(float(d.get("rotation", 0)) != 0 for d in v.get("side_data_list", []))
    compatible = (is_mp4 and len(videos) == 1 and len(audios) <= 1
                  and len(info["streams"]) == 1 + len(audios)
                  and v.get("codec_name") == "hevc" and v.get("codec_tag_string") == "hvc1"
                  and v.get("pix_fmt") in ("yuv420p", "yuvj420p")
                  and max(v["width"], v["height"]) <= 1920
                  and all(s.get("codec_name") == "aac" for s in audios) and not rotation)
    editing = args.start != 0 or args.duration is not None
    if args.video_mode == "copy":
        require(compatible and not editing,
                "copy requires HEVC/hvc1 8-bit MP4, max edge 1920, optional AAC, no trimming/rotation")
    if compatible and not editing and args.video_mode != "encode":
        return raw, {"mode": "copy", "source": summarize(info)}
    dest = tmp / "normalized.mp4"
    command = [executable("ffmpeg"), "-nostdin", "-v", "error"]
    if args.start:
        command += ["-ss", str(args.start)]
    command += ["-i", source]
    if args.duration is not None:
        command += ["-t", str(args.duration)]
    command += ["-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
                "-vf", "scale=w='min(1920,iw)':h='min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                "-r", "30", "-c:v", "libx265", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-tag:v", "hvc1",
                "-x265-params", "log-level=error:pools=2:frame-threads=2",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dest]
    run(command)
    return dest.read_bytes(), {"mode": "encode_hevc", "source": summarize(info),
                               "start_seconds": args.start, "requested_duration": args.duration}


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return number


def nonnegative(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    subs = parser.add_subparsers(dest="action", required=True)
    build = subs.add_parser("build", help="Combine cover and video, then validate")
    build.add_argument("--image", type=Path, required=True)
    build.add_argument("--video", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True, help="New filename ending _MP.jpg")
    build.add_argument("--report", type=Path, help="New JSON path; default OUTPUT.jpg.json")
    build.add_argument("--video-mode", choices=("auto", "copy", "encode"), default="auto")
    build.add_argument("--start", type=nonnegative, default=0)
    build.add_argument("--duration", type=positive, help="Optional explicit trim duration; default keeps full video")
    verify = subs.add_parser("verify", help="Validate XMP, boundaries, and full JPEG/video decode")
    verify.add_argument("file", type=Path)
    verify.add_argument("--report", type=Path, help="Optional new JSON report")
    args = parser.parse_args()
    if args.action == "build":
        output = args.output.resolve()
        report_path = (args.report or Path(str(output) + ".json")).resolve()
        require(output.name.endswith("_MP.jpg"), "Output filename must end with _MP.jpg")
        require(not output.exists() and not report_path.exists(), "Output/report already exists; choose new paths")
        inputs = {args.image.resolve(), args.video.resolve()}
        require(output not in inputs and report_path not in inputs and output != report_path,
                "Inputs, output and report must have distinct paths")
        with tempfile.TemporaryDirectory(prefix="xhs-live-") as temp:
            tmp = Path(temp)
            cover, cover_info = prepare_cover(args.image.resolve(), tmp)
            video, video_info = prepare_video(args.video.resolve(), tmp, args)
            data = pack(cover, video)
            result = verify_bytes(data, tmp)
        result.update({"file": str(output), "tool_version": VERSION, "upstream_commit": COMMIT,
                       "inputs": {"image": str(args.image.resolve()), "video": str(args.video.resolve()),
                                  "image_sha256": sha(args.image.read_bytes()),
                                  "video_sha256": sha(args.video.read_bytes())},
                       "cover_processing": cover_info, "video_processing": video_info})
        warnings = []
        if result["video"]["duration_seconds"] > 5:
            warnings.append("Video exceeds 5s; full duration preserved. Historical phone test used 3s.")
        result["warnings"] = warnings
        write_new(output, data)
    else:
        report_path = args.report.resolve() if args.report else None
        require(report_path is None or not report_path.exists(), "Report exists; choose a new path")
        with tempfile.TemporaryDirectory(prefix="xhs-live-check-") as temp:
            result = verify_bytes(args.file.read_bytes(), Path(temp))
        result.update({"file": str(args.file.resolve()), "tool_version": VERSION})
    if report_path:
        write_new(report_path, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
        result["report"] = str(report_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, ET.ParseError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
