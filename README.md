# Huya Replay -> DeepFilter -> YouTube Live

文件：

- [huya_replay_df_to_drive_colab.ipynb](<C:/Users/super/Documents/虎牙直播回放在colab下载并df并直播推流/huya_replay_df_to_drive_colab.ipynb>)
- [youtube_live_push_colab.ipynb](<C:/Users/super/Documents/虎牙直播回放在colab下载并df并直播推流/youtube_live_push_colab.ipynb>)
- [github_runtime/huya_replay_df_runtime.py](<C:/Users/super/Documents/虎牙直播回放在colab下载并df并直播推流/github_runtime/huya_replay_df_runtime.py>)
- [github_runtime/youtube_live_push_runtime.py](<C:/Users/super/Documents/虎牙直播回放在colab下载并df并直播推流/github_runtime/youtube_live_push_runtime.py>)

现在的结构：

- Colab notebook 只保留配置和启动逻辑。
- 真正执行下载、降噪、推流的代码都放在 `github_runtime/`。
- 你把 `github_runtime/` 推到 GitHub 后，Colab 每次运行都会先下载最新 `.py` 再执行。

推荐的 GitHub 用法：

1. 把当前项目推到你自己的 GitHub 仓库。
2. 确保 `github_runtime/` 目录也一起推上去。
3. 在 Colab 表单里填写：
   `GITHUB_RAW_BASE_URL = https://raw.githubusercontent.com/<你的用户名>/<你的仓库名>/<分支名>/github_runtime`
4. 保持 `FORCE_RUNTIME_DOWNLOAD = True`。
5. 以后你只改 GitHub 上的 `.py` 文件，然后在 Colab 重新运行即可拿到最新逻辑。

示例：

```text
https://raw.githubusercontent.com/someuser/huya-colab-tools/main/github_runtime
```

下载降噪 notebook 的参数重点：

- `HUYA_URL`: 虎牙回放地址
- `DRIVE_ROOT`: Drive 输出根目录
- `USE_DRIVE_CACHED_RAW_VIDEO`: 是否复用已备份的原视频
- `CACHED_RAW_VIDEO_PATH`: 复用时填写 Drive 里的原视频路径
- `COPY_RAW_TO_DRIVE_IMMEDIATELY`: 下载后立刻备份原视频到 Drive
- `SEGMENT_DURATION_MINUTES`: 切片时长
- `DF_MAX_WORKERS`: DeepFilter 并发数

推流 notebook 的参数重点：

- `INPUT_VIDEO_PATH`: Drive 里的待推流视频
- `STREAM_URL`: 通常保持 `rtmps://a.rtmp.youtube.com/live2`
- `STREAM_KEY`: YouTube 直播串流密钥
- `DRY_RUN_ONLY`: 为 `True` 时只打印推流命令，不实际开播

调试建议：

- 第一次跑下载流程时，保持 `COPY_RAW_TO_DRIVE_IMMEDIATELY = True`。
- 后续只调 `df` 参数时，把 `USE_DRIVE_CACHED_RAW_VIDEO = True`，并填写 `CACHED_RAW_VIDEO_PATH`，这样不用重新下载。
- 如果你刚 push 了 GitHub 新代码，保持 `FORCE_RUNTIME_DOWNLOAD = True`，Colab 会强制重新拉取。
