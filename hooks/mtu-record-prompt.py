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

MTU_API = os.environ.get("MTU_API_URL", "http://localhost:7799/api/record")


def sanitize(text: str) -> str:
    """Remove control chars que quebram JSON."""
    import re
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


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
    model = msg.get("model", "claude-sonnet-4-6")
    assistant_uuid = last_assistant_line.get("uuid")

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)

    # Achar último user message antes deste assistant
    prompt_preview = ""
    past_assistant = False
    for line in reversed(lines):
        if line.get("uuid") == assistant_uuid:
            past_assistant = True
            continue
        if not past_assistant:
            continue
        msg_inner = line.get("message", {})
        if isinstance(msg_inner, dict) and msg_inner.get("role") == "user":
            content = msg_inner.get("content", "")
            if isinstance(content, str):
                prompt_preview = sanitize(content[:300])
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        prompt_preview = sanitize(block.get("text", "")[:300])
                        break
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
