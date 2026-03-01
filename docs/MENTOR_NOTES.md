# MENTOR NOTES

## Что изменено в `resolve_live_memory_candidate.ps1`

- Вынесена сборка итогового summary в отдельную функцию `New-ResolverSummary`.
- Добавлен fail-safe сценарий для случая, когда API возвращает пустой список кандидатов.
  - Вместо немедленного `throw` скрипт теперь формирует структурированный summary,
    помечает набор кандидатов как stale и завершает работу с кодом `2`.
  - Это делает поведение совместимым с оркестратором soak-прогона, который ожидает
    диагностические поля (`candidate_set_stale`, `candidate_stale_reason`, и т.д.) даже
    при деградации.

## Почему это важно

Ранее при `No calibration candidates available ...` пайплайн терял часть
контекстной диагностики (stdout JSON отсутствовал), из-за чего разбор причины
остановки в автоматизации был менее надёжным. Теперь диагностика унифицирована
для успешного и деградированного путей.

## Рекомендации для следующих правок

1. Сохранять обратную совместимость ключей summary (`candidate_stale_reason`,
   `winerr299_rate`, `winner_candidate_id`, `no_stable_candidate`).
2. При добавлении новых причин stale использовать префикс,
   например `no_candidates_available:<detail>`.
3. Если меняется форма payload `/api/v1/live/calibration/candidates`,
   обновить оба пути извлечения (`candidate_ids` и `candidates[].id`).
4. Для всех early-exit веток поддерживать единый формат JSON через
   `New-ResolverSummary`.
