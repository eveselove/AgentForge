#!/usr/bin/env python3
"""
AgentForge Skill Capture — Self-Expansion Tool Creation Helper
==============================================================
Позволяет агентам (Grok, Jules и др.) автоматически сохранять новые YAML-playbooks
в ~/agentforge/skills/ после создания переиспользуемых скриптов, парсеров, API-клиентов,
деплой-тулов и т.п.

Использование агентом в конце задачи:
  python /home/eveselove/agentforge/skill_capture.py \
    --name "parse-newsupplier" \
    --description "Парсер каталога нового поставщика NewSupplier (скрапинг + нормализация)" \
    --tags "parser,scrape,supplier,newsupplier" \
    --timeout 1200 \
    --model grok \
    --prompt-file /tmp/new_skill_prompt.txt

Или через stdin JSON (удобно для LLM, который выводит JSON):
  cat > /tmp/skill.json <<'J'
  {"name": "...", "description": "...", "system_prompt": "...", "required_tags": ["a","b"]}
  J
  python /home/eveselove/agentforge/skill_capture.py --stdin < /tmp/skill.json

После сохранения skill становится доступен для select_skill() при следующих dispatch.
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import yaml

SKILLS_DIR = os.path.expanduser("~/agentforge/skills")


def sanitize_name(name: str) -> str:
    """Приводит имя к безопасному kebab-case для имени файла."""
    if not name:
        return "unnamed-skill"
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower())
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return cleaned[:64] or "unnamed-skill"


def generate_skill_yaml(
    name: str,
    description: str,
    system_prompt: str,
    required_tags: List[str],
    ci_checks: Optional[List[str]] = None,
    timeout: int = 900,
    preferred_model: str = "grok",
) -> str:
    """Генерирует полный текст YAML-файла skill с комментарием-заголовком."""
    data: Dict[str, Any] = {
        "name": sanitize_name(name),
        "description": description.strip(),
        "system_prompt": system_prompt.rstrip() + "\n",
        "required_tags": [t.strip() for t in required_tags if t.strip()],
        "ci_checks": ci_checks or [],
        "timeout": int(timeout),
        "preferred_model": preferred_model,
    }

    header = (
        "# =============================================================================\n"
        f"# AgentForge Skill: {data['name']}\n"
        "# =============================================================================\n"
        "# Автоматически сгенерирован через self-expansion (tool-creation).\n"
        "# Этот playbook будет автоматически подставляться агентам при совпадении required_tags.\n"
        "# =============================================================================\n\n"
    )

    body = yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        width=100,
        default_flow_style=False,
    )
    return header + body


def save_skill(
    name: str,
    description: str,
    system_prompt: str,
    required_tags: List[str],
    ci_checks: Optional[List[str]] = None,
    timeout: int = 900,
    preferred_model: str = "grok",
) -> str:
    """
    Сохраняет skill на диск + инвалидирует кэш загрузчика.
    Возвращает полный путь к созданному .yaml файлу.
    """
    os.makedirs(SKILLS_DIR, exist_ok=True)
    safe = sanitize_name(name)
    path = os.path.join(SKILLS_DIR, f"{safe}.yaml")

    content = generate_skill_yaml(
        name=safe,
        description=description,
        system_prompt=system_prompt,
        required_tags=required_tags,
        ci_checks=ci_checks,
        timeout=timeout,
        preferred_model=preferred_model,
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # Инвалидация кэша в task_queue (если модуль уже загружен)
    try:
        import task_queue

        if hasattr(task_queue, "_skills_cache"):
            task_queue._skills_cache = None  # type: ignore[attr-defined]
    except Exception:
        pass  # ок, если запущено standalone

    print(f"[AgentForge SkillCapture] ✅ Skill сохранён: {safe}")
    print(f"[AgentForge SkillCapture]    → {path}")
    print(f"[AgentForge SkillCapture]    tags={required_tags}")
    return path


def capture_from_json(obj: Dict[str, Any]) -> str:
    """Сохранение из словаря/JSON (самый удобный путь для LLM-агентов)."""
    return save_skill(
        name=obj.get("name") or obj.get("skill_name") or "unnamed",
        description=obj.get("description")
        or obj.get("desc")
        or "Auto-captured tool skill",
        system_prompt=obj.get("system_prompt") or obj.get("prompt") or "",
        required_tags=obj.get("required_tags") or obj.get("tags") or [],
        ci_checks=obj.get("ci_checks") or obj.get("ci") or [],
        timeout=obj.get("timeout", 900),
        preferred_model=obj.get("preferred_model") or obj.get("model") or "grok",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AgentForge self-expanding skills capture (Tool Creation)"
    )
    parser.add_argument("--name", "-n", help="Skill name (kebab-case recommended)")
    parser.add_argument(
        "--description", "-d", help="Human-readable description of the skill"
    )
    parser.add_argument(
        "--tags",
        "-t",
        help="Comma-separated list of required_tags (e.g. parser,api,acme)",
    )
    parser.add_argument(
        "--prompt", "-p", help="Full system_prompt text (for short prompts)"
    )
    parser.add_argument(
        "--prompt-file", "-f", help="Path to file containing the full system_prompt"
    )
    parser.add_argument("--ci", help="Comma-separated CI check commands")
    parser.add_argument(
        "--timeout", type=int, default=900, help="Timeout seconds (default 900)"
    )
    parser.add_argument("--model", default="grok", help="Preferred model")
    parser.add_argument(
        "--stdin", action="store_true", help="Read full JSON spec from stdin"
    )
    parser.add_argument(
        "--json", help="JSON string with full spec (alternative to --stdin)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated YAML and exit without writing",
    )

    args = parser.parse_args()

    # === Режим 1: Полный JSON (рекомендуется агентам) ===
    if args.stdin or args.json:
        if args.json:
            data = json.loads(args.json)
        else:
            data = json.load(sys.stdin)
        if args.dry_run:
            print(
                generate_skill_yaml(
                    name=data.get("name", "dry"),
                    description=data.get("description", ""),
                    system_prompt=data.get("system_prompt", ""),
                    required_tags=data.get("required_tags") or data.get("tags") or [],
                    ci_checks=data.get("ci_checks") or data.get("ci") or [],
                    timeout=data.get("timeout", 900),
                    preferred_model=data.get("preferred_model", "grok"),
                )
            )
            return 0
        capture_from_json(data)
        return 0

    # === Режим 2: CLI флаги ===
    if not args.name or not args.description:
        parser.error(
            "--name and --description are required unless using --stdin/--json"
        )

    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    ci = [c.strip() for c in (args.ci or "").split(",") if c.strip()]

    prompt_text = ""
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as pf:
            prompt_text = pf.read()
    elif args.prompt:
        prompt_text = args.prompt
    else:
        # fallback — читаем из stdin до EOF (удобно в heredoc)
        if not sys.stdin.isatty():
            prompt_text = sys.stdin.read()

    if not prompt_text.strip():
        parser.error(
            "system_prompt is required (use --prompt, --prompt-file, or pipe stdin)"
        )

    if args.dry_run:
        print(
            generate_skill_yaml(
                name=args.name,
                description=args.description,
                system_prompt=prompt_text,
                required_tags=tags,
                ci_checks=ci,
                timeout=args.timeout,
                preferred_model=args.model,
            )
        )
        return 0

    save_skill(
        name=args.name,
        description=args.description,
        system_prompt=prompt_text,
        required_tags=tags,
        ci_checks=ci,
        timeout=args.timeout,
        preferred_model=args.model,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
