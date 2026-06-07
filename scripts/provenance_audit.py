#!/usr/bin/env python3
"""
provenance_audit.py — Аудит провенанса AgentForge артефактов.

Сканирует pending_candidates manifests и flywheel_health.json,
проверяет провенанс-поля на каноническое значение 'rust-agentforge-runner'
и рапортует о несоответствиях.

Использование:
    python3 provenance_audit.py                # Только отчёт
    python3 provenance_audit.py --fix          # Автоисправление
    python3 provenance_audit.py --json         # Вывод в JSON
    python3 provenance_audit.py --verbose      # Подробный вывод
"""

import argparse
import json
import os
import sys
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# === Конфигурация ===

# Каноническое значение провенанса
CANONICAL_PROVENANCE = 'rust-agentforge-runner'

# Пути для сканирования
PENDING_CANDIDATES_DIR = '/home/eveselove/agentforge/pending_candidates'
LEARNING_DIR = '/home/eveselove/agentforge/learning'
FLYWHEEL_HEALTH_PATHS = [
    '/tmp/agentforge_rust_flywheel/flywheel_health.json',
]

# Правила нормализации — какие значения считать допустимыми (маппятся на канон)
NORMALIZATION_MAP = {
    # Точные совпадения с каноном
    'rust-agentforge-runner': CANONICAL_PROVENANCE,
    'rust-agentforge-runner/flywheel-export': CANONICAL_PROVENANCE,
    # Вариации, которые нужно нормализовать
    'rust_flywheel': CANONICAL_PROVENANCE,
    'rust_flywheel_step + agentforge-runner': CANONICAL_PROVENANCE,
    'rust_flywheel_step + agentforge-runner bridge + SkillImprover': CANONICAL_PROVENANCE,
    'rust_flywheel_step + agentforge-runner (rich flywheel-export preferred)': CANONICAL_PROVENANCE,
    'agentforge-runner continuous skeleton (Phase 2 prep + shadow)': CANONICAL_PROVENANCE,
}

# Поля, в которых проверяем провенанс
PROVENANCE_FIELDS = [
    'source',
    'generated_by',
    'promoted_by',
    'last_promote_source',
    'rich_source',
    'engine',
    'provenance',
]


class AuditResult:
    """Результат аудита одного файла."""

    def __init__(self, filepath: str, filename: str):
        self.filepath = filepath
        self.filename = filename
        # Список кортежей: (поле, текущее_значение, статус, нормализованное)
        self.checks: list[tuple[str, str, str, str]] = []
        self.error: str | None = None

    @property
    def has_mismatch(self) -> bool:
        """Есть ли хотя бы одно несоответствие."""
        return any(c[2] == 'MISMATCH' for c in self.checks)

    @property
    def has_fields(self) -> bool:
        """Есть ли хотя бы одно провенанс-поле."""
        return len(self.checks) > 0

    def to_dict(self) -> dict:
        """Сериализация в словарь."""
        return {
            'filepath': self.filepath,
            'filename': self.filename,
            'checks': [
                {
                    'field': c[0],
                    'current_value': c[1],
                    'status': c[2],
                    'normalized': c[3],
                }
                for c in self.checks
            ],
            'error': self.error,
        }


def classify_provenance(value: str) -> tuple[str, str]:
    """
    Классифицирует значение провенанса.

    Возвращает (статус, нормализованное_значение):
    - ('OK', canonical) — уже каноническое
    - ('MISMATCH', canonical) — известная вариация, можно нормализовать
    - ('UNKNOWN', '') — неизвестное значение
    """
    if not value or not isinstance(value, str):
        return ('SKIP', '')

    value_stripped = value.strip()

    # Точное совпадение с каноном
    if value_stripped == CANONICAL_PROVENANCE:
        return ('OK', CANONICAL_PROVENANCE)

    # Проверяем карту нормализации
    if value_stripped in NORMALIZATION_MAP:
        normalized = NORMALIZATION_MAP[value_stripped]
        if value_stripped == normalized:
            return ('OK', normalized)
        return ('MISMATCH', normalized)

    # Частичное совпадение — если содержит 'rust' или 'agentforge'
    lower = value_stripped.lower()
    if 'rust' in lower and ('agentforge' in lower or 'flywheel' in lower):
        return ('MISMATCH', CANONICAL_PROVENANCE)

    return ('UNKNOWN', '')


def scan_file(filepath: str) -> AuditResult:
    """Сканирует один JSON-файл на провенанс-поля."""
    result = AuditResult(filepath, os.path.basename(filepath))

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, IOError) as e:
        result.error = f'Ошибка чтения: {e}'
        return result

    if not isinstance(data, dict):
        return result

    for field in PROVENANCE_FIELDS:
        if field in data and data[field] and isinstance(data[field], str):
            value = data[field]
            status, normalized = classify_provenance(value)
            if status != 'SKIP':
                result.checks.append((field, value, status, normalized))

    return result


def scan_directory(dirpath: str) -> list[AuditResult]:
    """Рекурсивно сканирует директорию."""
    results = []
    if not os.path.isdir(dirpath):
        return results

    for root, _dirs, files in os.walk(dirpath):
        for fname in sorted(files):
            if not fname.endswith('.json'):
                continue
            # Пропускаем JSONL-файлы
            if fname.endswith('.jsonl'):
                continue
            filepath = os.path.join(root, fname)
            result = scan_file(filepath)
            if result.has_fields or result.error:
                results.append(result)

    return results


def fix_file(filepath: str, dry_run: bool = False) -> dict[str, Any]:
    """
    Исправляет провенанс в файле на каноническое значение.

    Возвращает словарь с информацией об изменениях.
    """
    changes = {
        'filepath': filepath,
        'changes': [],
        'backed_up': False,
        'dry_run': dry_run,
    }

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        changes['error'] = str(e)
        return changes

    if not isinstance(data, dict):
        return changes

    original = copy.deepcopy(data)
    modified = False

    for field in PROVENANCE_FIELDS:
        if field in data and data[field] and isinstance(data[field], str):
            status, normalized = classify_provenance(data[field])
            if status == 'MISMATCH' and normalized:
                changes['changes'].append({
                    'field': field,
                    'old': data[field],
                    'new': normalized,
                })
                data[field] = normalized
                modified = True

    if modified and not dry_run:
        # Создаём бэкап
        backup_path = filepath + '.bak'
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(original, f, indent=2, ensure_ascii=False)
            changes['backed_up'] = True
            changes['backup_path'] = backup_path
        except Exception as e:
            changes['backup_error'] = str(e)

        # Записываем исправленный файл
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            changes['written'] = True
        except Exception as e:
            changes['write_error'] = str(e)

    return changes


def print_table(results: list[AuditResult], verbose: bool = False) -> None:
    """Выводит красивую таблицу результатов."""
    # Собираем статистику
    total_files = len(results)
    ok_count = sum(1 for r in results if r.has_fields and not r.has_mismatch and not r.error)
    mismatch_count = sum(1 for r in results if r.has_mismatch)
    error_count = sum(1 for r in results if r.error)
    unknown_count = sum(
        1 for r in results
        if any(c[2] == 'UNKNOWN' for c in r.checks)
    )

    # Заголовок
    print()
    print('=' * 100)
    print('  ПРОВЕНАНС-АУДИТ AgentForge — {}'.format(
        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    ))
    print('=' * 100)
    print()

    # Сводка
    print('  Сводка:')
    print('     Всего файлов с провенансом: {}'.format(total_files))
    print('     OK (канон):                {}'.format(ok_count))
    print('     MISMATCH (вариации):       {}'.format(mismatch_count))
    print('     UNKNOWN:                   {}'.format(unknown_count))
    print('     Ошибки чтения:             {}'.format(error_count))
    print('     Канон: "{}"'.format(CANONICAL_PROVENANCE))
    print()

    if mismatch_count == 0 and error_count == 0 and unknown_count == 0:
        print('  Все провенанс-значения соответствуют канону!')
        print()
        return

    # Таблица несоответствий
    if mismatch_count > 0 or unknown_count > 0:
        # Форматирование таблицы
        header = '  {:<55} {:<22} {:<50} {:<10}'.format(
            'Файл', 'Поле', 'Текущее значение', 'Статус'
        )
        print(header)
        print('  ' + '-' * 135)

        for result in results:
            for field, value, status, normalized in result.checks:
                if status in ('MISMATCH', 'UNKNOWN') or verbose:
                    # Укорачиваем путь для отображения
                    short_path = result.filepath
                    if '/pending_candidates/' in short_path:
                        short_path = '.../' + short_path.split('/pending_candidates/')[-1]
                    elif '/learning/' in short_path:
                        short_path = '.../learning/' + short_path.split('/learning/')[-1]

                    # Маркировка статуса
                    status_icon = '[OK]' if status == 'OK' else ('[!!]' if status == 'MISMATCH' else '[??]')
                    display_status = '{} {}'.format(status_icon, status)

                    # Укорачиваем длинные значения
                    display_value = value if len(value) <= 48 else value[:45] + '...'

                    print('  {:<55} {:<22} {:<50} {:<10}'.format(
                        short_path, field, display_value, display_status
                    ))

        print()

    # Ошибки
    if error_count > 0:
        print('  Файлы с ошибками:')
        for result in results:
            if result.error:
                print('     {}: {}'.format(result.filepath, result.error))
        print()

    # Подсказка
    if mismatch_count > 0:
        print('  Для автоисправления запустите: python3 {} --fix'.format(__file__))
        print()


def print_fix_report(fix_results: list[dict]) -> None:
    """Выводит отчёт об исправлениях."""
    total_changes = sum(len(r.get('changes', [])) for r in fix_results)
    files_changed = sum(1 for r in fix_results if r.get('changes'))

    print()
    print('=' * 80)
    print('  ОТЧЁТ ОБ ИСПРАВЛЕНИЯХ')
    print('=' * 80)
    print()
    print('  Файлов исправлено: {}'.format(files_changed))
    print('  Всего изменений:   {}'.format(total_changes))
    print()

    for r in fix_results:
        if not r.get('changes'):
            continue
        print('  [FILE] {}'.format(r['filepath']))
        if r.get('backed_up'):
            print('     [BAK] {}'.format(r.get('backup_path', 'N/A')))
        for ch in r['changes']:
            print('     {}: "{}" -> "{}"'.format(ch['field'], ch['old'], ch['new']))
        print()


def main():
    """Точка входа."""
    parser = argparse.ArgumentParser(
        description='Аудит провенанса AgentForge артефактов',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python3 provenance_audit.py                 # Только отчёт
  python3 provenance_audit.py --fix           # Автоисправление с бэкапами
  python3 provenance_audit.py --fix --dry-run # Показать что будет исправлено
  python3 provenance_audit.py --json          # Вывод в JSON
  python3 provenance_audit.py --verbose       # Все поля, включая OK
        """,
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Автоисправление MISMATCH-значений на каноническое',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Показать что будет исправлено (без записи)',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Вывод результатов в JSON формате',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Подробный вывод (включая OK статусы)',
    )
    parser.add_argument(
        '--candidates-dir',
        default=PENDING_CANDIDATES_DIR,
        help='Путь к pending_candidates (по умолчанию: {})'.format(PENDING_CANDIDATES_DIR),
    )
    parser.add_argument(
        '--learning-dir',
        default=LEARNING_DIR,
        help='Путь к learning (по умолчанию: {})'.format(LEARNING_DIR),
    )

    args = parser.parse_args()

    # Сбор результатов
    all_results: list[AuditResult] = []

    # 1. Сканируем pending_candidates
    print('  Сканирование {}...'.format(args.candidates_dir), file=sys.stderr)
    all_results.extend(scan_directory(args.candidates_dir))

    # 2. Сканируем learning
    print('  Сканирование {}...'.format(args.learning_dir), file=sys.stderr)
    all_results.extend(scan_directory(args.learning_dir))

    # 3. Сканируем flywheel_health.json
    for health_path in FLYWHEEL_HEALTH_PATHS:
        if os.path.isfile(health_path):
            print('  Сканирование {}...'.format(health_path), file=sys.stderr)
            result = scan_file(health_path)
            if result.has_fields or result.error:
                all_results.append(result)

    # Режим JSON-вывода
    if args.json and not args.fix:
        output = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'canonical': CANONICAL_PROVENANCE,
            'total_files': len(all_results),
            'mismatches': sum(1 for r in all_results if r.has_mismatch),
            'results': [r.to_dict() for r in all_results if r.has_mismatch or r.error or args.verbose],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        sys.exit(0)

    # Режим отчёта
    if not args.fix:
        print_table(all_results, verbose=args.verbose)
        # Код возврата: 1 если есть несоответствия
        if any(r.has_mismatch for r in all_results):
            sys.exit(1)
        sys.exit(0)

    # Режим исправления (--fix)
    dry_run = args.dry_run
    if dry_run:
        print('\n  РЕЖИМ DRY-RUN — файлы НЕ будут изменены\n', file=sys.stderr)

    fix_results = []

    for result in all_results:
        if result.has_mismatch:
            fix_result = fix_file(result.filepath, dry_run=dry_run)
            fix_results.append(fix_result)

    # Также проверяем flywheel_health
    for health_path in FLYWHEEL_HEALTH_PATHS:
        if os.path.isfile(health_path):
            health_result = scan_file(health_path)
            if health_result.has_mismatch:
                fix_result = fix_file(health_path, dry_run=dry_run)
                fix_results.append(fix_result)

    if args.json:
        print(json.dumps(fix_results, indent=2, ensure_ascii=False))
    else:
        print_fix_report(fix_results)

    # Повторный аудит после исправления (если не dry-run)
    if not dry_run and fix_results:
        print('  Повторный аудит после исправлений...\n', file=sys.stderr)
        recheck = []
        recheck.extend(scan_directory(args.candidates_dir))
        recheck.extend(scan_directory(args.learning_dir))
        for health_path in FLYWHEEL_HEALTH_PATHS:
            if os.path.isfile(health_path):
                r = scan_file(health_path)
                if r.has_fields or r.error:
                    recheck.append(r)
        print_table(recheck, verbose=args.verbose)


if __name__ == '__main__':
    main()
