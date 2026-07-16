# AIOS 开发环境

## 推荐基线

- Python：3.12.10
- Node.js：20.18.0
- PostgreSQL：16 + pgvector
- Python 虚拟环境：`F:\AIOS\.venv`

## 推荐方式：uv

`uv` 只负责安装解释器、创建环境和同步依赖。生成的 `.venv` 是标准 Python 虚拟环境，应用启动不依赖 `uv`。

```powershell
python -m pip install --user uv
python -m uv python install 3.12.10
python -m uv venv --python 3.12.10 .venv
python -m uv pip sync --python .venv\Scripts\python.exe backend\requirements.lock
```

运行后端命令时显式使用项目解释器：

```powershell
.venv\Scripts\python.exe -m pytest -q backend\tests
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第二条命令需要在 `F:\AIOS\backend` 目录执行，或设置正确的 Python 模块路径。

## 可替换方案

### 官方 Python

安装 Python 3.12.10 后直接创建同一个标准环境：

```powershell
"<Python312>\python.exe" -m venv F:\AIOS\.venv
F:\AIOS\.venv\Scripts\python.exe -m pip install --require-hashes -r F:\AIOS\backend\requirements.lock
```

### Conda

```powershell
conda create -p F:\AIOS\.venv python=3.12.10
F:\AIOS\.venv\Scripts\python.exe -m pip install --require-hashes -r F:\AIOS\backend\requirements.lock
```

以后改用 Docker Python 镜像时，也应从 `requirements.lock` 安装依赖。三种方式共享同一依赖契约，不修改业务代码。

## 依赖文件职责

- `backend/requirements.in`：人工维护的直接依赖来源。
- `backend/requirements.txt`：兼容传统 pip 的直接依赖版本清单。
- `backend/requirements.lock`：Python 3.12 完整传递依赖和哈希，用于严格复现。

更新依赖时先修改 `requirements.in`，再重新生成 lock：

```powershell
python -m uv pip compile backend\requirements.in --python-version 3.12 --generate-hashes --output-file backend\requirements.lock
```

## LLM 运行时

`OpenAIProvider` 只使用公开 SDK 参数，支持注入 client；未配置 `OPENAI_API_KEY` 时会明确报配置错误。其他模型通过 `BaseLLMProvider` 新增 Provider，或注入 OpenAI-compatible client，不需要修改对话业务层。

## 语音运行时

Expo 52 使用兼容版本 `expo-audio ~0.3.5` 和 `expo-file-system ~18.0.12`。手机端采用短时半双工按住说话，录音只作为上传重试所需的本地临时文件；转写完成后通过标准 `TurnCreate.input.kind=transcript` 进入原有 Conversation 管道。

后端 Provider 由环境变量选择，业务层不引用厂商 SDK 类型：

- 阿里云：配置 `DASHSCOPE_API_KEY` 和 `ALIYUN_WORKSPACE_ID`。
- 本地：配置独立运行的 `LOCAL_STT_URL` 和/或 `LOCAL_TTS_URL`。
- 未配置时：`GET /api/v1/voice/providers` 正常返回空 `stt` / `tts` 列表；客户端显示不可用状态，不静默切换 Provider。

开发启动：

```powershell
cd F:\AIOS\backend
F:\AIOS\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

cd F:\AIOS\mobile
$env:EXPO_PUBLIC_API_URL='http://127.0.0.1:8001'
npx expo start --web --port 8082
```

真机不能使用手机自身的 `127.0.0.1` 访问电脑，应把 `EXPO_PUBLIC_API_URL` 或 App 设置中的 API 地址改为电脑局域网地址。公开部署前仍需 HTTPS、设备认证和用户数据边界。

验证命令：

```powershell
cd F:\AIOS\mobile
npm test -- --runInBand
npx tsc --noEmit
npx expo install --check
npx expo-doctor
npx expo export --platform web --output-dir dist
```

`mobile/tsconfig.json` 排除 `dist` 和 `web-build`。Expo Web 导出文件体积较大且基础配置开启 `allowJs`，不能把生成 bundle 再送入 TypeScript 类型检查。
