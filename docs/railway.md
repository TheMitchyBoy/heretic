# Heretic Chat on Railway

Deploy a ChatGPT-style web UI that streams responses from a Heretic model on [Railway](https://railway.app).

## What you get

- Web chat UI at `/`
- Streaming API at `POST /api/chat/stream`
- Health check at `GET /api/health`
- Inference-only server (no Optuna optimization in production)

## Deploy to Railway

1. Create a new Railway project from this repository.
2. Add a **GPU** service if you plan to run larger models locally.
3. Set these environment variables:

| Variable | Required | Example |
| --- | --- | --- |
| `HERETIC_MODEL` | Yes | `p-e-w/Qwen3-4B-Instruct-2507-heretic` |
| `HF_TOKEN` | For gated/private models | `hf_...` |
| `HERETIC_QUANTIZATION` | Use `bnb_4bit` **only with a GPU** | `bnb_4bit` |
| `HERETIC_MAX_RESPONSE_LENGTH` | Optional | `4096` |
| `HERETIC_SYSTEM_PROMPT` | Optional | `You are a helpful assistant.` |
| `CHAT_API_KEY` | Optional auth for API routes | `your-secret-key` |
| `PORT` | Set by Railway automatically | `8000` |

4. Deploy. Railway uses `Dockerfile` and `railway.toml` in this repo.

## How long deploy takes

Expect two slow phases on the **first** deploy:

| Phase | Typical time | What is happening |
| --- | --- | --- |
| **Build image** | 10-20 min | Installing PyTorch, CUDA libraries, and Python dependencies |
| **Load model** | 5-20 min | Downloading the model from Hugging Face and loading it into memory |

The web server now starts immediately and returns `"status": "loading"` from `/api/health` while the model loads. Railway should mark the service healthy sooner instead of waiting for the full model download.

Open your Railway URL during startup — the UI shows a loading screen and becomes ready automatically.

Subsequent redeploys are faster when Docker layer cache is reused, but the model still downloads again unless you add persistent storage.

The first deploy can take several minutes while the model downloads and loads.

## Run locally

```bash
uv sync --extra chat
export HERETIC_MODEL=p-e-w/Qwen3-4B-Instruct-2507-heretic
export HERETIC_QUANTIZATION=bnb_4bit
heretic-chat
```

Open [http://localhost:8000](http://localhost:8000).

## API

### Stream chat

```http
POST /api/chat/stream
Content-Type: application/json

{
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user", "content": "Hello!" }
  ]
}
```

Server-Sent Events response:

```
data: {"content":"Hello"}
data: {"content":" there"}
data: [DONE]
```

If `CHAT_API_KEY` is set, include `X-API-Key: your-secret-key`.

## Troubleshooting

### `Failed to load model with all configured dtypes`

This usually means the model could not load on your Railway hardware. Check the full error in Railway logs.

Common causes:

| Cause | Fix |
| --- | --- |
| **No GPU but `bnb_4bit` set** | Remove `HERETIC_QUANTIZATION` or set `HERETIC_QUANTIZATION=none`. 4-bit needs CUDA. |
| **Model too large for RAM/VRAM** | Use a smaller model, add a GPU service, or set `HERETIC_QUANTIZATION=bnb_4bit` with GPU |
| **Gated model** | Accept the license on Hugging Face and set `HF_TOKEN` |
| **Wrong model name** | Double-check `HERETIC_MODEL` spelling |

**Recommended Railway setup for most users:**

```bash
HERETIC_MODEL=p-e-w/Qwen3-4B-Instruct-2507-heretic
HERETIC_QUANTIZATION=bnb_4bit
HF_TOKEN=hf_...
```

Requires a **GPU** Railway service. CPU-only Railway cannot run 4-bit quantization.

## Notes

- Use a Heretic-produced model from Hugging Face, or a model you abliterated locally.
- GPU memory requirements depend on model size; 4-bit quantization helps on smaller GPUs.
- Heretic is AGPL-3.0. Review license obligations before offering a public hosted service.
