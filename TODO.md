# TODO: Nordhold — стабилизация live-подключения памяти (1800s PASS)

Date: 2026-03-01
Owner: codex
Scope: `codex/projects/nordhold`

## Цели и DoD
- Финальный soak `1800s` проходит `PASS`, режим `memory`, без `memory_unavailable_no_replay` на стабильной трассе.
- Сетка кандидатов памяти обязана быть валидной/свежей.
- Любой массовый `winerr=299` должен детектироваться как `candidate_set_stale`/`transient_299_clustered` с fail-fast.
- В summary должны присутствовать поля:  
  `candidate_set_stale`, `candidate_stale_reason`, `failed_candidates_count`, `winerr299_rate`, `winner_candidate_id`, `no_stable_candidate`, `winner_candidate_age_sec`, `final_stop_reason`, `transient_299_share`.
- Документация и артефакты должны ссылаться только на безопасные пути, без секретов.

## Безопасные инфраструктурные ссылки
- `hosts`: `/mnt/c/Users/admin/Documents/cursor/hosts`
- `secrets`: `/mnt/c/Users/admin/Documents/cursor/.secrets/AGENTS.secrets.local.md`
- `pwsh`/`powershell` запуск только в безопасной среде Windows; в WSL — через `powershell.exe` для `scripts/*.ps1`.
- vCenter из инфраструктурного источника по пути `hosts`/`vcenter.mgmt.local`, креды только из `secrets`.

## Режим роя
- `max_threads`: 3–5
- `max_depth`: 1
- Порядок выполнения: `P-002 + P-005` → (`P-003 + P-004`) → (`P-006 + P-007`) → (`P-008 + P-009`) после синхронизации.
- Один файл только в одном пакете для предотвращения конфликтов.

## Текущий acceptance status
- Все основные блоки hardening уже реализованы и подтверждены локальными контрактными проверками.
- В этой сессии добавлен дополнительный тест fail-fast на массовый `winerr=299`:
  - `tests.test_replay_live.ReplayLiveTests.test_live_bridge_autoconnect_marks_all_transient_299_candidates_as_stale`.
- Текущий blocker: неустойчивые кандидаты (`winerr=299` на всех попытках) и необходимость живого `NordHold.exe` процесса.
- Дополнительный наблюдаемый симптом: массовый stale диагностируется только после всех кандидатов (`attempts=64`) в одном прогоне, что косвенно указывает на возможный рассинхрон `runtime/dist` с последними исходниками `live_bridge.py`.
- Для инфраструктурного слоя подтверждено:
  - исправление резолва Python helper и корректный `exit=0` на пути `C:\Users\admin\AppData\Local\Programs\Python\Python311\python.exe`;
  - `run_nordhold_live_soak.ps1` теперь пишет `helper_python_path/source`, `helper_python_ok`, `helper_launch_error`;
  - в refresh-цепочке зафиксировано приоритетное использование `memory_calibration_candidates*.json` без `autoload`, автоподбор на автозагрузке — только fallback.
- Git sync + аудит заметок выполнен:
  - `git pull --ff-only origin main` -> `already up to date`;
  - `git status --short --branch` -> `main...origin/main`;
  - заметки проверены: `TODO.md`, `PROJECT.md`, `docs/MENTOR_NOTES.md`, `STATUS.md`, `TASKS.md`;
  - секретов/участков с credentials в проектных заметках не найдено.
- Последний релевантный прогон автоподбора:
  - `runtime/logs/nordhold-live-soak-20260301_174605.summary.json` (`candidate_refresh_performed=true`, `candidate_set_stale=true`, `candidate_set_stale_reason=autoconnect_all_attempts_transient_299`, `transient_299_share=1`).
- Для финального acceptance остаётся запуск:
  - fresh refresh/promote с новым `memory_calibration_candidates_autoload.json`,
  - `run_nordhold_live_soak.ps1 -DurationS 1800` при живом процессе,
  - итоговый summary с `mode=memory`, без `memory_unavailable_no_replay`.

## Орбитальный план

| Пакет | Статус | Owner | Start | Done | Evidence path | Risks | Next action |
|---|---|---|---|---|---|---|---|
| P-001 Orchestrator/Coordinator | [x] | codex | 2026-03-01T09:40:00+04:00 | 2026-03-01T10:05:00+04:00 | `codex/projects/nordhold/TODO.md` | Нет | Подтвердить финальный acceptance после `P-009` |
| P-002 Resolver hardening (`scripts/resolve_live_memory_candidate.ps1`) | [x] | codex | 2026-03-01T10:05:00+04:00 | 2026-03-01T10:45:00+04:00 | `runtime/logs/t56-memory` и `worklogs/t56-memory-soak/*` | Неполный stale при пустых метриках | Проверить fallback при zero candidates в свежем ините |
| P-003 Calibration scoring (`src/nordhold/realtime/calibration_candidates.py`) | [x] | codex | 2026-03-01T10:45:00+04:00 | 2026-03-01T11:20:00+04:00 | `runtime/logs/nordhold-live-soak-20260228_232640.summary.json` | Ложный stable с малыми окнами | Зафиксировать threshold в `snapshot_ok_ratio=0.66` |
| P-004 Bridge classification (`src/nordhold/realtime/live_bridge.py`) | [x] | codex | 2026-03-01T11:20:00+04:00 | 2026-03-01T12:00:00+04:00 | `runtime/logs/nordhold-live-soak-20260228_222430.summary.json` | Маскировка root-cause при replay attach | Проверить статус на сценарии без active replay |
| P-005 Memory reader filtering (`src/nordhold/realtime/memory_reader.py`) | [x] | codex | 2026-03-01T12:00:00+04:00 | 2026-03-01T12:20:00+04:00 | `runtime/logs/nordhold-live-soak-20260228_232640.partial.json` | Неполная проверка placeholder-адресов | Расширить placeholder-set по новым профилям |
| P-006 Refresh pipeline (`nordhold_memory_scan.py`, deep-probe, promote) | [~] | codex | 2026-03-01T12:20:00+04:00 | 2026-03-01T15:35:00+04:00 | `worklogs/t56-memory-soak/20260301_003842_t56_pass` / `runtime/logs/` | Редкий риск `combat_deep_probe` timeout на слабом стенде | `P-007a` fix применён; требуется живой `1800s` прогон |
| P-007 Soak guardrails (`scripts/run_nordhold_live_soak.ps1`) | [~] | codex | 2026-03-01T12:20:00+04:00 | 2026-03-01T12:52:00+04:00 | `runtime/logs/nordhold-live-soak-20260301_135747.summary.json` | Риск ложного `mode!=memory` при старте и пустом autoconnect потоке | Снять 1800s прогон на живой среде и подтвердить PASS |
| P-008 Environment/docs (`codex/projects/nordhold/PROJECT.md`) | [x] | codex | 2026-03-01T12:40:00+04:00 | 2026-03-01T13:00:00+04:00 | `codex/projects/nordhold/PROJECT.md` | Несовпадение формулировок с текущими контрактами | Проверить консистентность после следующего релиза |
| P-009 Verification suite | [x] | codex | 2026-03-01T13:00:00+04:00 | 2026-03-01T14:03:00+04:00 | `runtime/logs/nordhold-live-soak-20260301_140313.summary.json` + `tests/` | `pytest` не доступен локально: fallback на `unittest` | Дальше: целевой 1800s PASS только с живым процессом + свежими кандидатами |
| P-010 Soak fail-fast test hardening | [x] | codex | 2026-03-01T14:10:00+04:00 | 2026-03-01T14:11:00+04:00 | `tests/test_replay_live.py` | Нет фиксации массового `299`-кластера в автоконнекте | Добавить `test_live_bridge_autoconnect_marks_all_transient_299_candidates_as_stale` |
| P-007a Python resolver preflight fix (`Probe-PythonExecutable`) | [x] | codex | 2026-03-01T15:15:00+04:00 | 2026-03-01T17:33:00+04:00 | `runtime/logs/nordhold-live-soak-20260301_173324.summary.json` / локальный smoke-check `python -c print(1)` | Нет | Проверить probe-контроль и зафиксировать `helper_python_path`, `helper_launch_error`, `helper_python_ok` |
| P-011 Final report | [~] | codex | 2026-03-01T13:05:00+04:00 |  | `worklogs/t56-memory-soak/manual_20260301_133935_refresh/` | Нет свежего live-окна для 1800s PASS (отсутствует свежий autoload/живой процесс) | Дождаться финального soak после фикса Python resolver и подтвердить PASS summary |
| P-012 Final regression (1800s) | [ ] | codex | 2026-03-01T15:45:00+04:00 |  | `runtime/logs/nordhold-live-soak-20260301_183044.summary.json` | Возможна регрессия из-за окружения WSL/PowerShell | Перезапустить 1800s PASS с уточненной диагностикой кандидатов |
| P-013 Refresh source anchor hardening | [x] | codex | 2026-03-01T00:00:00+04:00 | 2026-03-01T17:50:00+04:00 | `scripts/run_nordhold_live_soak.ps1`, `runtime/logs/nordhold-live-soak-20260301_174605.summary.json` | Возможна рекурсия refresh через `memory_calibration_candidates_autoload.json` в `worklogs/...candidates-refresh` | Поддерживать предупреждение `refresh source selected from autoload artifact` при падении; continue to acceptance |
| P-014 Final 1800s acceptance (live game required) | [~] | codex | 2026-03-01T17:50:00+04:00 |  | `runtime/logs/nordhold-live-soak-*.summary.json` | Живой процесс `NordHold.exe` и стабильный `mode=memory` на старте | Дождаться live-окна с процессом и запустить `DurationS 1800`, зафиксировать PASS и `candidate_set_stale=false` |
| P-015 Backend dist/runtime freshness and fallback | [x] | codex | 2026-03-01T18:20:00+04:00 | 2026-03-01T18:25:00+04:00 | `runtime/dist/NordholdRealtimeLauncher`, `run script`, `runtime/logs/nordhold-live-soak-20260301_175604.summary.json` | Риск: `EXE` содержит старую версию `live_bridge.py`/`calibration_candidates.py` | Ввести проверку freshness `dist` vs src и fallback на `python uvicorn` через `-PythonPath` при mismatch |
| P-016 Final 1800s acceptance (runtime-validated) | [~] | codex | 2026-03-01T18:22:00+04:00 |  | `runtime/logs/nordhold-live-soak-20260301_183044.summary.json`, `runtime/logs/nordhold-live-soak-20260301_183407.summary.json` | `candidate_set_stale=true` на массовом transient 299 при live режиме | Проверить валидацию набора: либо корректный профиль памяти, либо пересборка кандидатов в боевой сцене; только потом повторять `DurationS 1800` |
| P-017 Git sync + notes audit | [x] | codex | 2026-03-01T20:00:00+04:00 | 2026-03-01T20:06:00+04:00 | `TODO.md`, `PROJECT.md`, `docs/MENTOR_NOTES.md`, `runtime/logs/*` | Нет drift ветки при пуле и блокеров по secret-handling | Подготовить финальный live 1800s пайплайн |
| P-018 Final 1800s acceptance (live process required) | [ ] | codex | 2026-03-01T20:10:00+04:00 |  | `runtime/logs/nordhold-live-soak-<ts>.summary.json` | Зависит от живого процесса `NordHold.exe` + стабильного autoload | Запустить `run_nordhold_live_soak.ps1 -DurationS 1800` и сохранить PASS summary |

## Контракты для проверки в коде и логах
- `resolve_live_memory_candidate.ps1` (stdout/JSON):  
  `candidate_set_stale`, `candidate_stale_reason`, `failed_candidates_count`, `winerr299_rate`, `winner_candidate_id`, `no_stable_candidate`, `winner_candidate_age_sec`, `transient_299_clustered`.
- `run_nordhold_live_soak.ps1` summary:  
  `candidate_set_stale`, `candidate_stale_reason`, `winner_candidate_age_sec`, `final_stop_reason`, `transient_299_share`.
- `LiveBridge.status()` и автоконнект payload:  
  `candidate_set_stale`, `candidate_set_stale_reason`, `failed_candidates_count`, `winner_candidate_id`, `winner_candidate_age_sec`, `transient_299_clustered`, `autoconnect_last_result`.
- `LiveBridge.autoconnect()`:  
  массовый transient-299 переход в `memory_unavailable_no_replay:memory_read_transient_299_cluster` только после подтверждённого threshold.
- `calibration_candidate_recommendation()`:  
  `no_stable_candidate=true` + `reason=max_required_resolved_no_stable_probe` для unstable/insufficient probe.
- `memory_reader`:  
  hard-fail на нулевые/фиктивные адреса с `reason=memory_profile_invalid`.

## Текущее состояние исполнения
- Автоматические блоки стабилизации реализованы и покрыты локальными контракт-тестами.
- В этой сессии выполнено:
  - `PYTHONPATH=src python3 -m unittest tests.test_live_memory_v1 tests.test_replay_live` — OK (skipped=4).
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` — OK (skipped=7 без FastAPI).
  - `PYTHONPATH=src python3 -m unittest tests.test_replay_live.ReplayLiveTests.test_live_bridge_autoconnect_marks_all_transient_299_candidates_as_stale` — OK.
  - powershell parse check:
    - `scripts/resolve_live_memory_candidate.ps1` — OK
    - `scripts/run_nordhold_live_soak.ps1` — OK
    - `scripts/start_nordhold_realtime.ps1` — OK
  - `powershell.exe -File scripts/run_nordhold_live_soak.ps1 -DurationS 30 -NoAutoconnect -Port 8013 -CandidateTtlHours 24` — ранний stop на `Candidate artifact is stale ... and refresh failed.` (summary: `runtime/logs/nordhold-live-soak-20260301_140313.summary.json`)
- Критический blocker для `P-010`: не проведён LIVE 1800s PASS из-за массового `winerr=299` во всех кандидатах. Свежий `DurationS 1800` прогон `runtime/logs/nordhold-live-soak-20260301_183044.summary.json` остановлен через `autoconnect_candidate_set_stale`.
- Дополнительный blocker, ранее наблюдаемый на WSL+`powershell.exe` сценарии:
  - refresh-цепочка падала до авторезолва с `No Python at '\"/usr/bin\\python.exe\"'` из‑за невалидной подстановки аргументов `-c`; баг локализован и устранён.
- Следующий шаг acceptance: fresh/валидный refresh `memory_calibration_candidates_autoload.json` + живой `NordHold.exe` + `run_nordhold_live_soak.ps1 -DurationS 1800`.

## Сценарии валидации (автономно)
- Fresh run после refresh + лучший кандидат.
- Негативный тест: битый кандидат -> `candidate_set_stale=true`.
- Софт-failover mass-299 -> fail-fast на 2–3 попытках, no long degraded loop.
- Регрессионный soak `1800s` с PASS summary и `mode=memory`.

## Команды
- Refresh + promote:
  - `python3 scripts/nordhold_memory_scan.py build-calibration-candidates ...`
  - `python3 scripts/nordhold_combat_deep_probe.py ...`
  - `python3 scripts/nordhold_promote_deep_probe_candidates.py ...`
- Авторезолв:
  - `powershell.exe scripts/resolve_live_memory_candidate.ps1 -CalibrationCandidatesPath <path> -DatasetVersion 1.0.0 -CandidateTtlHours 24`
- Soak:
  - `powershell.exe scripts/run_nordhold_live_soak.ps1 -DurationS 1800 -CalibrationCandidatesPath <autoload.json> -CandidateTtlHours 24`

## Проверки окружения
- `pwsh` может отсутствовать в WSL; использовать `powershell.exe`.
- Для python-тестов в Linux/Windows использовать `PYTHONPATH=src python3 -m unittest ...` (`pytest` не обязательный, только при явной доступности).
- Для soak smoke на WSL без game-процесса использовать `-NoAutoconnect` и свежий артефакт; для целевого регресса — живой игровой процесс обязателен.
- Результаты актуальных проверок:
  - `PYTHONPATH=src python3 -m unittest tests.test_live_memory_v1 tests.test_replay_live` — OK.
  - `PYTHONPATH=src python3 -m unittest discover -s tests -v` — OK.
  - `powershell.exe -File scripts/run_nordhold_live_soak.ps1 -DurationS 30 -NoAutoconnect -Port 8013 -CandidateTtlHours 24` — подтверждён fail-fast на stale артефакте (summary: `runtime/logs/nordhold-live-soak-20260301_140313.summary.json`).
- `powershell.exe -File scripts/run_nordhold_live_soak.ps1 -DurationS 30 -NoAutoconnect -Port 8014 -PythonPath "C:\Users\admin\AppData\Local\Programs\Python\Python311\python.exe"` — smoke-check helper preflight и диагностика probe (`tmp_diag_py_probe2.ps1`): `cmd=-c print(1)`, `exit=0`, `out=1`.
- Все прогоны и summarize сохранять в:
  - `runtime/logs/nordhold-live-soak-<timestamp>.summary.json`
  - `runtime/logs/nordhold-live-soak-<timestamp>.partial.json`
  - `worklogs/t56-memory-soak/...`

## Примечание
`TODO.md` и `PROJECT.md` содержат только безопасные ссылки на `hosts`/`secrets`; любые креды хранятся исключительно в `secrets` и в среде запуска.
