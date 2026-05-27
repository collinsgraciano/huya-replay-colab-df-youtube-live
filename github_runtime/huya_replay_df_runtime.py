from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL


VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".ts"}
DEEP_FILTER_DOWNLOAD_URL = (
    "https://github.com/Rikorose/DeepFilterNet/releases/download/"
    "v0.5.6/deep-filter-0.5.6-x86_64-unknown-linux-musl"
)


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
        "huya_url": _as_str(config.get("huya_url")),
        "drive_root": _as_str(config.get("drive_root"), "/content/drive/MyDrive/huya_replay_df"),
        "job_name": _as_str(config.get("job_name")),
        "use_drive_cached_raw_video": _as_bool(config.get("use_drive_cached_raw_video"), False),
        "cached_raw_video_path": _as_str(config.get("cached_raw_video_path")),
        "copy_raw_to_drive_immediately": _as_bool(config.get("copy_raw_to_drive_immediately"), True),
        "segment_duration_minutes": _as_int(config.get("segment_duration_minutes"), 8),
        "ytdlp_concurrent_fragments": _as_int(config.get("ytdlp_concurrent_fragments"), 8),
        "df_max_workers": _as_int(config.get("df_max_workers"), 1),
        "enable_postfilter": _as_bool(config.get("enable_postfilter"), False),
        "keep_workfiles": _as_bool(config.get("keep_workfiles"), False),
        "audio_sample_rate": _as_int(config.get("audio_sample_rate"), 48000),
        "deep_filter_binary": _as_str(
            config.get("deep_filter_binary"),
            "deep-filter-0.5.6-x86_64-unknown-linux-musl",
        ),
        "work_root": _as_str(config.get("work_root"), "/content/huya_df_work"),
    }


def build_context(config: dict[str, Any]) -> dict[str, Path]:
    work_root = Path(config["work_root"])
    drive_root = Path(config["drive_root"])
    deep_filter_binary = config["deep_filter_binary"]
    return {
        "work_root": work_root,
        "download_dir": work_root / "download",
        "segment_dir": work_root / "segments",
        "df_dir": work_root / "df",
        "raw_audio_path": work_root / "source_audio.wav",
        "merged_audio_path": work_root / "denoised_audio.wav",
        "drive_root": drive_root,
        "drive_raw_dir": drive_root / "raw",
        "drive_output_dir": drive_root / "outputs",
        "drive_meta_dir": drive_root / "meta",
        "drive_bin_dir": drive_root / "bin",
        "deep_filter_path": Path("/content") / deep_filter_binary,
        "deep_filter_drive": drive_root / "bin" / deep_filter_binary,
    }


def ensure_dirs(context: dict[str, Path]) -> None:
    for key in ["drive_root", "drive_raw_dir", "drive_output_dir", "drive_meta_dir", "drive_bin_dir"]:
        context[key].mkdir(parents=True, exist_ok=True)


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def run_cmd(cmd: list[str], capture_output: bool = False, text: bool = True):
    print("$", shell_join(cmd))
    try:
        return subprocess.run(cmd, check=True, capture_output=capture_output, text=text)
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print("STDOUT:\n", exc.stdout)
        if exc.stderr:
            print("STDERR:\n", exc.stderr)
        raise


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def newest_file(root: Path, suffixes: set[str]) -> Path | None:
    files = [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]
    return str(value)


def setup_deep_filter(config: dict[str, Any], context: dict[str, Path]) -> None:
    deep_filter_path = context["deep_filter_path"]
    deep_filter_drive = context["deep_filter_drive"]

    if deep_filter_path.exists():
        deep_filter_path.chmod(0o755)
        return

    if deep_filter_drive.exists():
        shutil.copy2(deep_filter_drive, deep_filter_path)
    else:
        run_cmd(["wget", "-O", str(deep_filter_path), DEEP_FILTER_DOWNLOAD_URL])
        shutil.copy2(deep_filter_path, deep_filter_drive)

    deep_filter_path.chmod(0o755)
    print("DeepFilter 已就绪:", deep_filter_path)


def download_huya_replay(config: dict[str, Any], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    ydl_opts = {
        "outtmpl": str(output_dir / "%(title).150B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "format": "bv*+ba/b",
        "merge_output_format": "mp4",
        "concurrent_fragment_downloads": config["ytdlp_concurrent_fragments"],
        "writethumbnail": True,
        "writeinfojson": True,
        "restrictfilenames": True,
        "postprocessors": [
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
        ],
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(config["huya_url"], download=True)

    video_path = newest_file(output_dir, VIDEO_SUFFIXES)
    if video_path is None:
        raise FileNotFoundError("下载完成后没有在工作目录找到视频文件。")

    print("下载完成:", video_path)
    return info, video_path


def prepare_raw_video(config: dict[str, Any], context: dict[str, Path]):
    if config["use_drive_cached_raw_video"]:
        cached_raw_video_path = config["cached_raw_video_path"].strip()
        if not cached_raw_video_path:
            raise ValueError("启用 USE_DRIVE_CACHED_RAW_VIDEO 时，必须填写 CACHED_RAW_VIDEO_PATH。")

        cached_raw_path = Path(cached_raw_video_path)
        if not cached_raw_path.exists():
            raise FileNotFoundError(f"找不到缓存原视频: {cached_raw_path}")

        local_raw_path = context["download_dir"] / cached_raw_path.name
        if cached_raw_path.resolve() != local_raw_path.resolve():
            shutil.copy2(cached_raw_path, local_raw_path)

        drive_raw_path = context["drive_raw_dir"] / cached_raw_path.name
        if cached_raw_path.resolve() != drive_raw_path.resolve():
            shutil.copy2(cached_raw_path, drive_raw_path)

        info = {
            "source_mode": "drive_cached_raw_video",
            "source_url": config["huya_url"],
            "cached_raw_video_path": str(cached_raw_path),
        }
        print("使用 Drive 缓存原视频:", cached_raw_path)
        return info, local_raw_path, drive_raw_path

    info, local_raw_path = download_huya_replay(config, context["download_dir"])
    drive_raw_path = context["drive_raw_dir"] / local_raw_path.name
    if config["copy_raw_to_drive_immediately"]:
        shutil.copy2(local_raw_path, drive_raw_path)
        print("原视频已立即备份到 Drive:", drive_raw_path)
    return info, local_raw_path, drive_raw_path


def probe_duration_seconds(media_path: Path) -> float:
    result = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
    )
    return float(result.stdout.strip())


def estimate_wav_size_mb(seconds: float, sample_rate: int, channels: int = 2, sample_bytes: int = 2) -> float:
    return seconds * sample_rate * channels * sample_bytes / (1024 * 1024)


def extract_audio(config: dict[str, Any], video_path: Path, output_wav: Path) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            str(config["audio_sample_rate"]),
            "-c:a",
            "pcm_s16le",
            str(output_wav),
        ]
    )
    print("音频提取完成:", output_wav)


def split_wav_to_segments(config: dict[str, Any], input_wav: Path, output_dir: Path) -> None:
    total_seconds = probe_duration_seconds(input_wav)
    seg_seconds = config["segment_duration_minutes"] * 60
    total_parts = max(1, math.ceil(total_seconds / seg_seconds))
    estimated_mb = estimate_wav_size_mb(min(seg_seconds, total_seconds), config["audio_sample_rate"])
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"音频总时长: {total_seconds / 60:.2f} 分钟, 切成 {total_parts} 段")
    print(
        f"每段未压缩 WAV 约: {estimated_mb:.1f} MB @ "
        f"{config['audio_sample_rate']}Hz stereo 16-bit"
    )
    if estimated_mb > 150:
        print("警告: 单段 WAV 偏大，建议把 SEGMENT_DURATION_MINUTES 调到 5-8，并把 DF_MAX_WORKERS 设为 1。")

    for index in range(total_parts):
        start = index * seg_seconds
        duration = min(seg_seconds, total_seconds - start)
        segment_path = output_dir / f"{index + 1:03d}.wav"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-t",
                str(duration),
                "-i",
                str(input_wav),
                "-ac",
                "2",
                "-ar",
                str(config["audio_sample_rate"]),
                "-c:a",
                "pcm_s16le",
                str(segment_path),
            ]
        )


def process_one_wav(config: dict[str, Any], context: dict[str, Path], wav_file: Path) -> Path:
    segment_output_dir = context["df_dir"] / wav_file.stem
    segment_output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(context["deep_filter_path"]), str(wav_file), "--output-dir", str(segment_output_dir)]
    if config["enable_postfilter"]:
        cmd.append("--pf")
    subprocess.run(cmd, check=True)

    output_files = sorted(segment_output_dir.rglob("*.wav"))
    if not output_files:
        raise FileNotFoundError(f"DeepFilter 没有输出 WAV: {wav_file}")
    return output_files[0]


def merge_wav_files_ffmpeg(wav_files: list[Path], final_output_file: Path) -> None:
    if not wav_files:
        raise FileNotFoundError("没有可合并的降噪 WAV 文件。")

    if len(wav_files) == 1:
        run_cmd(["ffmpeg", "-y", "-i", str(wav_files[0]), "-c:a", "pcm_s16le", str(final_output_file)])
        return

    cmd = ["ffmpeg", "-y"]
    for wav_path in wav_files:
        cmd.extend(["-i", str(wav_path)])

    concat_inputs = "".join(f"[{index}:a]" for index in range(len(wav_files)))
    cmd.extend(
        [
            "-filter_complex",
            f"{concat_inputs}concat=n={len(wav_files)}:v=0:a=1[aout]",
            "-map",
            "[aout]",
            "-c:a",
            "pcm_s16le",
            str(final_output_file),
        ]
    )
    run_cmd(cmd)


def df_and_merge_wav_files(config: dict[str, Any], context: dict[str, Path]) -> None:
    wav_files = sorted(context["segment_dir"].glob("*.wav"))
    if not wav_files:
        raise FileNotFoundError(f"没有找到待降噪的 WAV 文件: {context['segment_dir']}")

    context["df_dir"].mkdir(parents=True, exist_ok=True)
    max_workers = max(1, min(config["df_max_workers"], len(wav_files), os.cpu_count() or 1))
    print(f"DeepFilter 并发数: {max_workers}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        processed = list(executor.map(lambda wav: process_one_wav(config, context, wav), wav_files))

    merge_wav_files_ffmpeg(processed, context["merged_audio_path"])
    print("降噪音频合并完成:", context["merged_audio_path"])


def merge_audio_video(raw_video_path: Path, merged_audio_path: Path, output_path: Path) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_video_path),
            "-i",
            str(merged_audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_path),
        ]
    )
    print("音视频合并完成:", output_path)


def copy_sidecar_files(download_dir: Path, drive_meta_dir: Path, stem: str) -> None:
    for suffix in [".info.json", ".jpg", ".webp", ".png"]:
        for source in download_dir.rglob(f"*{suffix}"):
            target = drive_meta_dir / f"{stem}{suffix}"
            shutil.copy2(source, target)


def save_metadata(
    config: dict[str, Any],
    context: dict[str, Path],
    job_stem: str,
    info: dict[str, Any],
    drive_raw_path: Path,
    drive_output_path: Path,
) -> Path | None:
    meta_payload = {
        "source_url": config["huya_url"],
        "job_name": job_stem,
        "raw_video": str(drive_raw_path),
        "denoised_video": str(drive_output_path),
        "segment_duration_minutes": config["segment_duration_minutes"],
        "audio_sample_rate": config["audio_sample_rate"],
        "deepfilter_binary": config["deep_filter_binary"],
        "use_drive_cached_raw_video": config["use_drive_cached_raw_video"],
        "cached_raw_video_path": config["cached_raw_video_path"],
        "info": make_json_safe(info),
    }

    metadata_path = context["drive_meta_dir"] / f"{job_stem}.json"
    try:
        metadata_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata_path
    except Exception as exc:  # pragma: no cover - defensive logging for Colab
        print("警告: 元数据写入失败，但视频处理已经完成。", exc)
        return None


def run_pipeline(config: dict[str, Any]) -> dict[str, str]:
    config = normalize_config(config)
    context = build_context(config)
    ensure_dirs(context)

    setup_deep_filter(config, context)
    reset_dir(context["work_root"])
    context = build_context(config)
    ensure_dirs(context)
    context["download_dir"].mkdir(parents=True, exist_ok=True)
    context["segment_dir"].mkdir(parents=True, exist_ok=True)
    context["df_dir"].mkdir(parents=True, exist_ok=True)

    info, raw_video_path, drive_raw_path = prepare_raw_video(config, context)
    job_stem = config["job_name"].strip() or raw_video_path.stem
    denoised_video_path = context["work_root"] / f"{job_stem}_df.mp4"

    print("\n[1/4] 提取音频")
    extract_audio(config, raw_video_path, context["raw_audio_path"])

    print("\n[2/4] 切分 WAV")
    split_wav_to_segments(config, context["raw_audio_path"], context["segment_dir"])

    print("\n[3/4] DeepFilter 降噪")
    df_and_merge_wav_files(config, context)

    print("\n[4/4] 替换视频音轨")
    merge_audio_video(raw_video_path, context["merged_audio_path"], denoised_video_path)

    drive_output_path = context["drive_output_dir"] / denoised_video_path.name
    if not drive_raw_path.exists():
        shutil.copy2(raw_video_path, drive_raw_path)
        print("原视频已保存到 Drive:", drive_raw_path)
    shutil.copy2(denoised_video_path, drive_output_path)

    metadata_path = save_metadata(config, context, job_stem, info, drive_raw_path, drive_output_path)
    copy_sidecar_files(context["download_dir"], context["drive_meta_dir"], job_stem)

    print("\n处理完成")
    print("原视频:", drive_raw_path)
    print("降噪后视频:", drive_output_path)
    if metadata_path:
        print("元数据:", metadata_path)

    if not config["keep_workfiles"] and context["work_root"].exists():
        shutil.rmtree(context["work_root"])
        print("临时工作目录已清理")

    result = {
        "raw_video": str(drive_raw_path),
        "denoised_video": str(drive_output_path),
    }
    if metadata_path:
        result["metadata"] = str(metadata_path)
    return result
