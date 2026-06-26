#!/usr/bin/env python3
"""
MTU Stop hook — lê JSONL do transcript, extrai usage real, POST para container MTU.
Stdlib only. Silencia em caso de erro (nunca bloqueia Claude Code).
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
import re

MTU_API = os.environ.get("MTU_API_URL", "http://localhost:7799/api/record")
DEFAULT_MODEL = os.environ.get("MTU_DEFAULT_MODEL", "gpt-5.5")


def sanitize(text: str) -> str:
    """Remove control chars que quebram JSON."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def extract_model(payload, lines):
    candidates = [
        payload.get("model"),
        payload.get("selected_model"),
        payload.get("active_model"),
        payload.get("model_name"),
        payload.get("requested_model"),
        payload.get("provider_model"),
    ]

    for line in reversed(lines):
        msg = line.get("message", {}) if isinstance(line, dict) else {}
        if isinstance(msg, dict) and msg.get("model"):
            candidates.append(msg.get("model"))
        if isinstance(line, dict) and line.get("model"):
            candidates.append(line.get("model"))
        meta = line.get("metadata") if isinstance(line, dict) else None
        if isinstance(meta, dict):
            for k in ("model", "requested_model", "active_model", "provider_model"):
                if meta.get(k):
                    candidates.append(meta.get(k))

    for model in candidates:
        if isinstance(model, str) and model.strip():
            return model.strip()

    return DEFAULT_MODEL


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    session_id = data.get("session_id", "unknown")
    cwd = data.get("cwd", os.getcwd())
    transcript_path = data.get("transcript_path")

    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    try:
        with open(transcript_path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
    except Exception:
        sys.exit(0)

    # Achar última mensagem assistant com usage
    last_assistant_line = None
    for line in reversed(lines):
        msg = line.get("message", {})
        if isinstance(msg, dict) and msg.get("role") == "assistant" and "usage" in msg:
            last_assistant_line = line
            break

    if not last_assistant_line:
        sys.exit(0)

    msg = last_assistant_line["message"]
    usage = msg.get("usage", {})
    model = extract_model(data, lines)
    assistant_uuid = last_assistant_line.get("uuid")

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)

    def extract_content(content):
        """Returns (text, has_image) from message content."""
        if isinstance(content, str):
            return content.strip(), False
        if isinstance(content, list):
            texts, has_image = [], False
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "text":
                    t = block.get("text", "").strip()
                    if t:
                        texts.append(t)
                elif btype == "image":
                    has_image = True
            return " ".join(texts), has_image
        return "", False

    def build_preview(content):
        text, has_image = extract_content(content)
        if text:
            prefix = "[Imagem] " if has_image else ""
            return sanitize((prefix + text)[:2000])
        if has_image:
            return "[Imagem]"
        return ""

    # Achar último user message com texto real antes do assistant (pula tool_result puro)
    prompt_preview = ""
    past_assistant = False
    for line in reversed(lines):
        if line.get("uuid") == assistant_uuid:
            past_assistant = True
            continue
        if not past_assistant:
            continue
        msg_inner = line.get("message", {})
        if not isinstance(msg_inner, dict) or msg_inner.get("role") != "user":
            continue
        preview = build_preview(msg_inner.get("content", ""))
        if preview:
            prompt_preview = preview
            break

    # Fallback: qualquer user message no transcript
    if not prompt_preview:
        for line in reversed(lines):
            msg_inner = line.get("message", {})
            if not isinstance(msg_inner, dict) or msg_inner.get("role") != "user":
                continue
            preview = build_preview(msg_inner.get("content", ""))
            if preview:
                prompt_preview = preview
                break

    project = os.path.basename(cwd.rstrip("/"))

    payload = json.dumps({
        "session_id": session_id,
        "project": project,
        "prompt_preview": prompt_preview,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
        "model": model,
        "timestamp": datetime.now().isoformat(),
    }).encode()

    try:
        req = urllib.request.Request(
            MTU_API,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            result = json.loads(resp.read())

        tips = result.get("tips", [])
        if tips:
            cost = result.get("cost_usd", 0)
            total = result.get("total_tokens", 0)
            print(f"[MTU] {total // 1000}K tokens | ${cost:.5f} | " + " | ".join(tips))

    except urllib.error.URLError:
        # Container não rodando — silencia
        pass
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
