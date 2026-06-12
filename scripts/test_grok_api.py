#!/usr/bin/env python3
"""
Quick test: verify xAI (Grok) API connectivity.
Loads key from .env or environment, sends a minimal request.
"""

import json
import os
import sys
import urllib.request
import urllib.error

# Load .env if present
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("XAI_API_KEY", "")
API_BASE = os.environ.get("XAI_API_BASE", "https://api.x.ai/v1")
MODEL = os.environ.get("XAI_MODEL", "grok-4")

def test_connection():
    if not API_KEY or API_KEY == "ВСТАВЬ_СЮДА_СВОЙ_КЛЮЧ":
        print("❌ XAI_API_KEY не задан! Отредактируйте .env файл.")
        sys.exit(1)

    print(f"🔑 API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"🌐 API Base: {API_BASE}")
    print(f"🤖 Model: {MODEL}")
    print()

    # 1. Test: list models
    print("── Тест 1: Список моделей ──")
    try:
        req = urllib.request.Request(
            f"{API_BASE}/models",
            headers={"Authorization": f"Bearer {API_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            models = [m.get("id", "?") for m in data.get("data", [])]
            print(f"✅ Доступные модели ({len(models)}):")
            for m in models[:10]:
                marker = " 👈" if m == MODEL else ""
                print(f"   • {m}{marker}")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"❌ HTTP {e.code}: {body[:200]}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)

    # 2. Test: minimal chat completion
    print()
    print("── Тест 2: Chat completion ──")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Ты AgentForge worker. Отвечай коротко."},
            {"role": "user", "content": "Скажи 'AgentForge online' и текущую дату."}
        ],
        "max_tokens": 50,
        "temperature": 0.1
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{API_BASE}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            msg = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})
            print(f"✅ Grok ответил: {msg}")
            print(f"   Tokens: prompt={usage.get('prompt_tokens',0)}, completion={usage.get('completion_tokens',0)}")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"❌ HTTP {e.code}: {body[:300]}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)

    print()
    print("🎉 Все тесты пройдены — Grok (xAI) подключён и работает!")

if __name__ == "__main__":
    test_connection()
