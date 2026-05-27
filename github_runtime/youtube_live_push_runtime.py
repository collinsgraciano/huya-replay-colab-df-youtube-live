from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "input_video_path": _as_str(config.get("input_video_path")),
        "stream_url": _as_str(config.get("stream_url"), "rtmps://a.rtmp.youtube.com/live2"),
        "stream_key": _as_str(config.get("stream_key")),
        "loop_forever": _as_bool(config.get("loop_forever"), False),
        "target_height": _as_int(config.get("target_height"), 1080),
        "fps": _as_int(config.get("fps"), 30),
        "video_bitrate": _as_str(config.get("video_bitrate"), "6000k"),
        "audio_bitrate": _as_str(config.get("audio_bitrate"), "128k"),
        "preset": _as_str(config.get("preset"), "veryfast"),
        "dry_run_only": _as_bool(config.get("dry_run_only"), False),
    }


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def ffprobe_streams(video_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def bitrate_kbits(value: str) -> int:
    text = value.strip().lower()
    if text.endswith("k"):
        return int(float(text[:-1]))
    if text.endswith("m"):
        return int(float(text[:-1]) * 1000)
    return int(float(text) / 1000)


def build_ffmpeg_command(config: dict[str, Any], input_video: Path) -> list[str]:
    vf_parts = []
    if config["target_height"]:
        vf_parts.append(f"scale=-2:{config['target_height']}:flags=lanczos")
    if config["fps"]:
        vf_parts.append(f"fps={config['fps']}")
    vf_parts.append("format=yuv420p")

    stream_target = f"{config['stream_url'].rstrip('/')}/{config['stream_key']}"
    command = ["ffmpeg", "-re"]
    if config["loop_forever"]:
        command.extend(["-stream_loop", "-1"])

    command.extend(
        [
            "-i",
            str(input_video),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            ",".join(vf_parts),
            "-c:v",
            "libx264",
            "-preset",
            config["preset"],
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(config["fps"]),
            "-g",
            str(config["fps"] * 2),
            "-keyint_min",
            str(config["fps"] * 2),
            "-sc_threshold",
            "0",
            "-b:v",
            config["video_bitrate"],
            "-maxrate",
            config["video_bitrate"],
            "-bufsize",
            f"{bitrate_kbits(config['video_bitrate']) * 2}k",
            "-c:a",
            "aac",
            "-b:a",
            config["audio_bitrate"],
            "-ar",
            "44100",
            "-ac",
            "2",
            "-f",
            "flv",
            stream_target,
        ]
    )
    return command


def run_stream(config: dict[str, Any]) -> dict[str, Any]:
    config = normalize_config(config)
    input_video = Path(config["input_video_path"])
    if not input_video.exists():
        raise FileNotFoundError(f"输入视频不存在: {input_video}")

    if not config["stream_key"]:
        env_stream_key = os.environ.get("YOUTUBE_STREAM_KEY", "").strip()
        if not env_stream_key:
            raise ValueError("STREAM_KEY 为空，也没有设置环境变量 YOUTUBE_STREAM_KEY。")
        config["stream_key"] = env_stream_key

    probe = ffprobe_streams(input_video)
    summary = {
        "duration": probe.get("format", {}).get("duration"),
        "bit_rate": probe.get("format", {}).get("bit_rate"),
        "streams": [
            {
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "avg_frame_rate": stream.get("avg_frame_rate"),
                "sample_rate": stream.get("sample_rate"),
            }
            for stream in probe.get("streams", [])
        ],
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    command = build_ffmpeg_command(config, input_video)
    print("\n即将执行的推流命令:")
    print(shell_join(command))

    result = {
        "input_video": str(input_video),
        "stream_url": config["stream_url"],
        "loop_forever": config["loop_forever"],
        "ffmpeg_command": command,
    }

    if config["dry_run_only"]:
        print("\nDRY_RUN_ONLY=True，本次不实际推流。")
        return result

    subprocess.run(command, check=True)
    return result
