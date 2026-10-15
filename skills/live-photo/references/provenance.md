# 来源与实测边界

- 上游：[flashlab/motion-live-photo](https://github.com/flashlab/motion-live-photo)
- 固定 commit：`48b884713c496ed4e4ad5ba688e84e6eb82ca059`
- `assets/default.xmp` 是 `src/lib/extractutil.ts` 的 `XmpStrings.default` 原始文本。
- Python 将默认封装路径移植为：JPEG SOI → APP1 XMP → 原 JPEG 剩余部分（至 EOI）→ 完整 MP4。对应上游 `extractmotion.ts` 的 `createMotion`，`hasXmp=false`、`model=default`，不替换品牌 EXIF。
- 三处视频长度更新为实际 MP4 字节数；时间戳保持上游默认 0。独立封面不承诺对应视频中某一帧。
- 保留 Google MotionPhoto/MicroVideo、Container Directory、MiCamera、Oplus 兼容字段。`MotionPhotoOwner=oplus` 是上游模板字段，并不表示文件由 OPPO 手机拍摄。
- 上游 MIT 版权声明完整保存在 `assets/FLASHLAB-LICENSE.txt`。本封装为本地 Python 移植，不能声称执行未经修改的上游 TypeScript。

2026-10-15，维护者报告历史样片在安卓、iPhone、微信和小红书中可用。该反馈未记录具体机型、系统或应用版本，不构成全平台兼容保证。

历史样片 `MVIMG_XHS_TEST_V2_MP.jpg`，3,526,870 字节，SHA-256：
`2bcf80ade2297372e3bac12a4d341398a7cd699b2cf94292a0285eff1f1b066a`

素材：独立 JPEG 3072×4096；HEVC/hvc1 1440×1920、30fps、3秒，AAC 音频。用户未提供具体设备和软件版本。PNG 转换、其他视频输入和时长属于新增脚本能力，本机校验通过不代表各变体都做过手机实测。

先前只有四个 MicroVideo 字段的样片未在用户小米系统相册识别；不可当作成功基线。系统相册的识别也不是小红书自身解析的必备前置条件。
