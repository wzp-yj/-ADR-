# AIOS P1-C：可切换语音交互设计

> 版本：v1.0  
> 日期：2026-07-15  
> 状态：已批准实施  
> 前置：P1-A 可审计对话核心、P1-B 手机文字对话

## 1. 目标

P1-C 为 Expo 手机端增加可用的按住说话闭环：

```text
录音 -> STT 转写资源 -> 标准 Conversation Turn -> 文本回复 -> 可选 TTS -> 播放
```

语音只是输入和输出适配器。项目解析、上下文组装、记忆候选、LLM 调用、失败重试和未来任务草案仍由现有 Conversation Turn 负责。

本阶段必须满足：

- 云端和本地语音 Provider 可配置切换，业务层不引用厂商 SDK 类型。
- STT 成功结果可审计、可恢复、可绑定到唯一 Turn。
- LLM 失败后重试复用原转写，不要求重新上传音频。
- 原始录音默认不落库；只保存音频哈希、格式、大小、时长和 Provider 元数据。
- TTS 失败只降级为文字，不改变 Turn 的完成状态。
- 没有语音 Provider 或麦克风权限时，文字聊天保持可用。

## 2. 推荐与原因

### 2.1 第一阶段采用批量按住说话

用户按下麦克风开始录音，松开后上传完整文件。P1-C 不做全双工、打断、回声消除和边说边传。

原因：当前首要目标是验证“语音沟通 -> 标准 Turn -> 后续任务确认”的完整产品链路。流式音频会同时引入 WebSocket、部分转写合并、网络抖动和音频焦点问题，但不会改变核心产品判断。

### 2.2 云端首选阿里云百炼

- STT：`qwen3-asr-flash` 批量 OpenAI-compatible Chat Completions。
- TTS：`qwen-audio-3.0-tts-flash` HTTP。
- 后续流式 STT：`fun-asr-realtime` WebSocket，继续实现同一流式契约。

原因：短录音批量接口最容易稳定接入；百炼统一 API Key、地域和业务空间，避免新项目引入旧 NLS 的 Appkey 与临时 Token 体系。流式能力通过接口保留，不在本阶段提前承担复杂度。

### 2.3 本地首选独立语音服务

- STT：FunASR OpenAI-compatible HTTP，默认模型 SenseVoiceSmall。
- TTS：CosyVoice HTTP；低资源替代保留 Kokoro/sherpa-onnx 适配入口。

原因：FunASR 适合 Windows/CPU 的整句中文转写；CosyVoice 质量更高但更适合 Linux/WSL2/Docker 独立部署。AIOS 后端只依赖 HTTP 契约，模型运行环境可以独立替换。

### 2.4 Expo SDK 52 使用 `expo-audio`

SDK 52 的本地依赖清单同时提供 `expo-audio ~0.3.5` 和 `expo-av ~15.0.2`。P1-C 使用 `expo-audio`，并把所有调用封装在 `mobile/src/voice`。

原因：AIOS 只需要音频能力，不需要 `expo-av` 的视频 API；`expo-audio` 是 Expo 后续维护方向。SDK 52 的 API 较早，通过本地适配层可以在未来升级 Expo 时只改一个模块。

## 3. 领域边界

### 3.1 VoiceTranscription

新增 `voice_transcriptions`：

```text
id: UUID
session_id: UUID
client_audio_id: UUID
turn_id: UUID | null
status: accepted | processing | completed | failed
provider_name: varchar | null
provider_model: varchar | null
language: varchar
detected_language: varchar | null
text: text | null
audio_mime_type: varchar
audio_size_bytes: bigint
audio_sha256: char(64)
duration_ms: integer | null
latency_ms: integer | null
error_code: varchar | null
error_message: text | null
created_at, updated_at, completed_at
```

约束：

- `UNIQUE(session_id, client_audio_id)` 保证上传重试幂等。
- `turn_id` 唯一且只能在 `completed` 后绑定。
- 同一转写只能创建一个 Turn。
- 原始音频不写数据库、日志或审计 payload。
- 已完成转写不可覆盖；重新录音创建新资源。

### 3.2 标准 Turn

`TurnInput` 改为判别联合：

```json
{ "kind": "text", "text": "继续 AIOS" }
```

或：

```json
{ "kind": "transcript", "transcription_id": "uuid" }
```

ConversationService 在同一输入事务中锁定转写、创建 Turn 和 `kind=transcript` 的用户消息，并把 `turn_id` 绑定回转写。消息内容使用服务端保存的 transcript，不接受客户端重传的转写文本。

消息 metadata 保存：

```json
{
  "voice": {
    "transcription_id": "uuid",
    "provider": "aliyun",
    "model": "qwen3-asr-flash",
    "language": "zh",
    "detected_language": "zh",
    "audio_mime_type": "audio/mp4",
    "audio_size_bytes": 12345,
    "audio_sha256": "...",
    "duration_ms": 4200,
    "latency_ms": 680
  }
}
```

## 4. Provider 契约

业务层使用 Pydantic 强类型请求和响应：

```text
STTRequest
  request_id, audio bytes, mime_type, file_name,
  language, sample_rate_hz?, channels?, duration_ms?,
  enable_itn, timeout_seconds

STTResponse
  request_id, text, provider, model, detected_language?,
  segments[], duration_ms?, latency_ms, usage

TTSRequest
  request_id, text, language, voice?, format,
  sample_rate_hz?, speed, timeout_seconds

TTSResponse
  request_id, audio bytes, content_type, format,
  sample_rate_hz, channels, provider, model,
  latency_ms, usage
```

`VoiceRouter` 分别路由 STT 和 TTS，选择优先级为请求显式 Provider、配置默认 Provider。缺失配置返回稳定的 `VOICE_PROVIDER_UNAVAILABLE`，不得悄悄改用另一家 Provider；后续可在配置策略中显式允许回退。

流式方法保留强类型 chunk：

- STT chunk 区分 `partial` 与 `final`。
- TTS chunk 包含格式、采样率和序号。
- 已产生部分输出后不得透明重试，避免重复文本或重复播放。

## 5. API

### 5.1 Provider 能力

```text
GET /api/v1/voice/providers
```

返回默认 STT/TTS 和已配置 Provider。只暴露名称、模型和能力，不暴露密钥、内部 URL 或 Workspace ID。

### 5.2 创建转写

```text
POST /api/v1/conversations/{conversation_id}/transcriptions
Content-Type: multipart/form-data
```

字段：

- `client_audio_id: UUID`
- `audio: file`
- `language: string = zh`
- `duration_ms: int | null`
- `provider: string | null`

限制：单文件最大 10 MiB，录音端默认最长 60 秒；允许 `audio/mp4`、`audio/m4a`、`audio/aac`、`audio/mpeg`、`audio/wav`、`audio/webm`、`audio/ogg`。

首次成功创建返回 201；相同 `client_audio_id` 返回原资源和 200。Provider 失败仍返回已持久化资源，状态为 `failed`，不会伪装为 HTTP 整体失败。

### 5.3 提交转写 Turn

继续使用：

```text
POST /api/v1/conversations/{conversation_id}/turns
```

客户端只提交 `transcription_id`。若转写不属于当前会话、未完成或已绑定其他 Turn，返回稳定的 409/404 错误。

### 5.4 合成语音

```text
POST /api/v1/voice/speech
Content-Type: application/json
```

请求包含 `text`、`language`、`voice`、`format` 和可选 Provider。响应直接返回音频字节，并通过响应头返回 Provider、模型、采样率和请求 ID。移动端将短音频写入缓存文件后交给 `expo-audio` 播放，播放结束或新回复开始时清理旧文件。

## 6. 移动端状态

新增独立状态机：

```text
idle
-> requesting_permission
-> recording
-> transcribing
-> sending_turn
-> synthesizing
-> playing
-> idle

任一阶段 -> error -> idle | retry_transcription
```

规则：

- `recording` 时松开麦克风停止；少于 300ms 的录音直接丢弃。
- 转写成功后自动提交 transcript Turn，不复制文字发送逻辑。
- 录音 URI 保留到转写成功或用户取消，网络失败允许重新上传。
- 只有语音产生的 Turn 默认自动播放 TTS；文字 Turn 不自动朗读。
- 新录音开始时停止当前播放，避免扬声器声音进入麦克风。
- Web 预览在安全上下文可录音；普通局域网 HTTP 浏览器不保证麦克风权限，真机原生 App 是主要验收环境。

## 7. 错误、隐私和安全

- `VOICE_PROVIDER_UNAVAILABLE`：未配置或请求 Provider 不存在。
- `VOICE_AUDIO_UNSUPPORTED`：格式不支持。
- `VOICE_AUDIO_TOO_LARGE`：超过 10 MiB。
- `VOICE_TRANSCRIPTION_FAILED`：Provider 调用失败，资源已保存。
- `VOICE_TRANSCRIPTION_NOT_READY`：Turn 引用了未完成转写。
- `VOICE_TRANSCRIPTION_ALREADY_USED`：转写已绑定其他 Turn。
- `VOICE_SYNTHESIS_FAILED`：TTS 失败，客户端保留文字。

API Key 只在后端环境变量中。日志和审计不得包含音频 Base64、完整 Provider 原始响应或密钥。音频 SHA-256 用于追踪和去重证据，不用于跨用户关联。当前局域网开发阶段仍是单用户；公开部署前必须增加设备令牌和用户数据边界。

## 8. 可观测性和审计

新增事件：

```text
voice.transcription.accepted
voice.transcription.completed
voice.transcription.failed
voice.transcription.bound_to_turn
voice.synthesis.completed
voice.synthesis.failed
memory.extraction.skipped
```

审计 payload 只保存资源 ID、Provider、模型、格式、大小、时延、状态和错误码。

## 9. 测试

后端覆盖：

- Provider 强类型契约和路由选择。
- 阿里与 FunASR/CosyVoice HTTP 请求转换及错误映射。
- 文件类型、大小、空转写和 Provider 缺失。
- 转写资源先提交再调用 Provider。
- 上传幂等、会话隔离、转写只能绑定一个 Turn。
- transcript Turn 继续经过项目解析、记忆和 LLM。
- TTS 二进制响应、元数据响应头和失败降级。
- Provider 失败后重试 Turn 不重复生成记忆候选。

移动端覆盖：

- 权限拒绝、开始/停止录音和短录音丢弃。
- multipart 上传和 transcript Turn 提交。
- 网络失败保留录音并重试。
- TTS 缓存、播放、停止和清理。
- App 重载后文字会话保持原有恢复能力。

## 10. 本阶段不做

- 全双工实时语音、用户打断、回声消除和 WebSocket 音频传输。
- 保存或同步用户原始录音。
- 音色克隆、声纹识别、唤醒词和后台持续监听。
- 自动选择或静默回退到另一 Provider。
- 在 AIOS 后端进程内加载 FunASR/CosyVoice 大模型。
- 因语音输入而绕过任务确认或审核中心。

## 11. 后续替换点

- `VoiceRouter` 可新增阿里 `fun-asr-realtime`、NLS、OpenAI 或其他 Provider。
- `BaseSTTProvider` / `BaseTTSProvider` 内部实现可以从 HTTP 换成 SDK/WebSocket。
- `mobile/src/voice` 可在 Expo 升级后替换 `expo-audio` 实现。
- 需要跨设备恢复原始录音时，再引入加密对象存储和保留策略，不修改 Turn 语义。

## 12. 主要来源

- 阿里云 Qwen-ASR API：https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference
- 阿里云 Fun-ASR 实时 API：https://help.aliyun.com/zh/model-studio/fun-asr-realtime-websocket-api
- 阿里云 TTS HTTP API：https://help.aliyun.com/zh/model-studio/cosyvoice-tts-http-api
- FunASR：https://github.com/modelscope/FunASR
- SenseVoice：https://github.com/FunAudioLLM/SenseVoice
- CosyVoice：https://github.com/FunAudioLLM/CosyVoice
- Expo Audio：https://docs.expo.dev/versions/latest/sdk/audio/
- Expo SDK 52 bundled modules：`mobile/node_modules/expo/bundledNativeModules.json`
