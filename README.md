# 实况图 / Live Photo Skill

将一张配图和一段视频合成为**单个实况 JPG**，便于传输、分享或交给支持动态照片的应用。不限定发布平台，也可以不使用 AI，直接运行 Python 脚本。

图片和视频可以独立创作。脚本负责格式封装、必要的转码和本机校验；不生成内容，也不自动上传或发布。

## 安装到 Codex

在 Codex 中发送：

```text
请用 skill-installer 安装这个公开 skill：
https://github.com/fantasy19hit-lab/live-photo-skill/tree/main/skills/live-photo
```

也可以在已安装 Codex 内置 skill-installer 的 macOS/Linux 终端运行：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts/install-skill-from-github.py" \
  --repo fantasy19hit-lab/live-photo-skill \
  --path skills/live-photo
```

安装器只安装 skill 文件。还需要本机具备 **Python 3.9+** 和 **FFmpeg（包含 ffprobe 和 libx265 编码器）**；合成脚本不依赖第三方 Python 包。

安装后在下一轮消息或新会话中使用。若已有同名 skill，安装器会停止以避免覆盖；更新前先保留自己的修改。`CODEX_HOME` 未设置时，安装目录为 `~/.codex/skills/live-photo/`。

## 调用

提供图片和视频，告诉 Codex：

```text
用 $live-photo 将这张配图和视频合成为单文件实况图，保留完整视频。
```

也可以直接说“把这张图和视频合成 Live 图”，由支持自动选择 skill 的客户端调用。

交付文件为 `作品_MP.jpg`。旁边的 `作品_MP.jpg.json` 是本机校验报告，不需要跟 JPG 一起发送或上传。

## 独立脚本用法

```bash
git clone https://github.com/fantasy19hit-lab/live-photo-skill.git
cd live-photo-skill

python3 skills/live-photo/scripts/live_photo.py build \
  --image "/path/to/cover.png" \
  --video "/path/to/video.mp4" \
  --output "/path/to/output/live_MP.jpg"
```

可选参数：

| 参数 | 用途 |
| --- | --- |
| `--start 0.5 --duration 3` | 从 0.5 秒开始截取 3 秒；默认保留完整视频 |
| `--video-mode auto` | 默认：符合条件的视频直接嵌入，其余转码 |
| `--video-mode copy` | 仅接受符合条件的 HEVC/hvc1 MP4，不转码、不裁剪 |
| `--video-mode encode` | 强制转为本工具使用的 HEVC 配置 |
| `--report /path/to/report.json` | 指定新报告路径 |

文件名必须以 `_MP.jpg` 结尾。输出和报告都拒绝覆盖已有文件，原素材保持不变。

校验本工具生成的已有文件：

```bash
python3 skills/live-photo/scripts/live_photo.py verify "/path/to/output/live_MP.jpg"
```

退出码为 `0` 且报告 `status` 为 `passed` 表示本机校验通过。校验涵盖 XMP、JPEG/MP4 边界、视频长度以及图片和视频完整解码。这不是所有品牌实况文件的通用鉴定器。

## 格式和兼容性

- 输出采用 Motion Photo 形式：JPEG 图片、XMP 元数据和内嵌 MP4 放在同一个文件中。它不是 Apple 原生 JPG+MOV 双文件资源包。
- 普通 JPEG 保留压缩像素并替换旧 XMP；PNG 等图片会转成 JPEG。带 MPF 的多图/HDR JPEG 需先导出为普通 SDR 图片。
- 符合条件的 HEVC/hvc1、8-bit 4:2:0、最长边不超过 1920 的 MP4 可原样嵌入，音频如有则须为 AAC；其他视频会转为 HEVC、30fps、最长边不超过 1920，保留音频并转 AAC。无音频输入不补音轨。
- 封面不必来自视频中的某一帧，时间戳沿用固定模板的默认值 0。
- 历史样片已有安卓、iPhone、微信、小红书可用的维护者反馈；具体设备和软件版本未记录。新素材通过本机校验不等于已经完成手机发布测试，也不保证所有应用和机型兼容。
- 按**原文件**传输；聊天软件压缩图片或另存静态图可能去掉动态部分。目标应用与系统相册可能采用不同识别方式，以实际使用场景为准。

## 本地测试

```bash
python3 -m unittest discover -s tests -v
```

测试在临时目录生成合成素材，不需要账号、网络或私人素材。端到端测试需要 FFmpeg、ffprobe 和 libx265；缺少依赖时会明确跳过。

开发阶段还完成了历史样片逐字节回归，以及 GPT-6 Luna / max 在独立会话中读取 skill、调用脚本并处理 JPEG+HEVC 和 PNG+H.264 两组输入的本机测试。这些结果不代替新文件的目标设备测试。

## 开源来源

核心 XMP 模板和封装布局来自 [flashlab/motion-live-photo](https://github.com/flashlab/motion-live-photo)，固定提交 `48b884713c496ed4e4ad5ba688e84e6eb82ca059`。本项目将默认路径移植为 Python CLI，并补充输入处理、校验和 skill 指令。

使用 MIT 许可，见 [LICENSE](LICENSE)。保留的上游版权声明见 [FLASHLAB-LICENSE.txt](skills/live-photo/assets/FLASHLAB-LICENSE.txt)，详细格式来源见 [provenance.md](skills/live-photo/references/provenance.md)。
