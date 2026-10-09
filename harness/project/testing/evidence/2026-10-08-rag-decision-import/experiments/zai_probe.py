"""Four synthetic Russian RAG checks against native Z.AI; stdlib only.

Read credentials as data, never source the env file. No retries or paid fallback.
Reuses saved local benchmark prompts; does not test retrieval or LangGraph.
"""
import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"
ROOT = Path(__file__).resolve().parents[1]


def read_key(path):
    for line in path.read_text().splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name in {"Z_AI_API_KEY_ID", "ZAI_API_KEY"}:
            value = value.strip().strip("\"'")
            if value and not any(c.isspace() for c in value):
                return value
    raise ValueError("No valid Z.AI key assignment found")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_stream(response, started):
    result = {"text": "", "first_text_seconds": None, "done": False,
              "first_reasoning_seconds": None, "reasoning_characters": 0}
    for line in response:
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            result["done"] = True
            break
        event = json.loads(data)
        if event.get("error"):
            raise ValueError("Provider returned an SSE error")
        if event.get("model"):
            result["returned_model"] = event["model"]
        if event.get("usage"):
            result["usage"] = event["usage"]
        for choice in event.get("choices", []):
            reasoning = choice.get("delta", {}).get("reasoning_content")
            if reasoning:
                if result["first_reasoning_seconds"] is None:
                    result["first_reasoning_seconds"] = time.perf_counter() - started
                result["reasoning_characters"] += len(reasoning)
            content = choice.get("delta", {}).get("content")
            if content:
                if result["first_text_seconds"] is None:
                    result["first_text_seconds"] = time.perf_counter() - started
                result["text"] += content
            if choice.get("finish_reason"):
                result["finish_reason"] = choice["finish_reason"]
    result["total_seconds"] = time.perf_counter() - started
    if not result["text"] or result.get("finish_reason") != "stop" or not result["done"]:
        raise ValueError("Incomplete or non-successful response stream")
    return result


def self_check():
    good = b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n'
    assert read_stream(io.BytesIO(good), time.perf_counter())["text"] == "ok"
    reasoning = b'data: {"choices":[{"delta":{"reasoning_content":"internal"}}]}\n' + good
    observed = read_stream(io.BytesIO(reasoning), time.perf_counter())
    assert observed["reasoning_characters"] == 8 and observed["text"] == "ok"
    for bad in (good.split(b"data: [DONE]")[0], good.replace(b'"stop"', b'"length"'),
                b'data: {"error":{"code":"1302"}}\n'):
        try:
            read_stream(io.BytesIO(bad), time.perf_counter())
        except ValueError:
            continue
        raise AssertionError("Failed stream accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--thinking", choices=["disabled", "enabled"], default="disabled")
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument("--output", type=Path, default=ROOT / "_docs/benchmarks/zai-glm-47-flash.json")
    args = parser.parse_args()
    self_check()
    if args.self_check:
        print("Stream checks passed")
        return
    if args.key_file is None:
        parser.error("--key-file required for live test")
    key = read_key(args.key_file)
    baseline = json.loads((ROOT / "_docs/benchmarks/e5-qwen35-2b-q4-t4-tb8.json").read_text())
    params = {"model": "glm-4.7-flash", "stream": True, "max_tokens": args.max_tokens,
              "temperature": 0, "thinking": {"type": args.thinking}}
    report = {"date_utc": datetime.now(timezone.utc).isoformat(), "endpoint": ENDPOINT,
              "parameters": params, "generation": [], "checks": {}, "retries": 0,
              "socket_timeout_seconds": args.timeout}
    output = args.output
    opener = urllib.request.build_opener(NoRedirect())
    try:
        for case in baseline["generation"]:
            name, messages = case["case"], case["messages"]
            report["last_attempted_case"] = name
            if name == "followup":
                messages = [dict(m) for m in messages]
                messages[-2]["content"] = report["generation"][0]["text"]
            payload = {**params, "messages": messages}
            request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
            started = time.perf_counter()
            with opener.open(request, timeout=args.timeout) as response:
                answer = read_stream(response, started)
            report["generation"].append({"case": name, "messages": messages, **answer})
            text = answer["text"].lower()
            expected = {"fact": ("вторник", "16:00", "[d1]"),
                        "long_context": ("вторник", "16:00", "[d1]"),
                        "followup": ("лебедев", "[d1]"), "missing": ("нет",)}[name]
            report["checks"][name] = all(fragment in text for fragment in expected)
            print(json.dumps({"case": name, **answer}, ensure_ascii=False).replace(key, "[REDACTED]"), flush=True)
    except KeyboardInterrupt:
        report["error"] = {"type": "Cancelled", "message": "Probe interrupted by user"}
    except urllib.error.HTTPError as exc:
        report["error"] = {"http_status": exc.code,
            "elapsed_seconds": time.perf_counter() - started,
            "body": exc.read(4096).decode(errors="replace").replace(key, "[REDACTED]"),
            "retry_after": exc.headers.get("Retry-After")}
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc).replace(key, "[REDACTED]"),
                           "elapsed_seconds": time.perf_counter() - started}
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2).replace(key, "[REDACTED]") + "\n")
    print(json.dumps({"checks": report["checks"], "error": report.get("error"), "output": str(output)}, ensure_ascii=False))
    if report.get("error") or len(report["checks"]) != 4 or not all(report["checks"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
