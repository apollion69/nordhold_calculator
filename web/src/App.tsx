import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  BuildActionInput,
  BuildPlanInput,
  CalcMode,
  LiveAutoconnectRequest,
  LiveCalibrationCandidatesResponse,
  LiveConnectRequest,
  LiveSnapshot,
  LiveSseEventPayload,
  LiveSseState,
  LiveStatus,
  TimelineRequest,
  TimelineResponse,
  TowerPlanInput
} from "./types";

type ActionDraft = {
  wave: number;
  at_s: number;
  type: string;
  target_id: string;
  value: number;
  payloadText: string;
};

type LiveConnectFormState = {
  process_name: string;
  poll_ms: number;
  require_admin: boolean;
  dataset_version: string;
  signature_profile_id: string;
  calibration_candidates_path: string;
  calibration_candidate_id: string;
  replay_session_id: string;
};

type CandidateLoadResult = {
  path: string;
  candidateId: string;
  candidateIds: string[];
};

const defaultTowers: TowerPlanInput[] = [
  {
    tower_id: "arrow_tower",
    count: 2,
    level: 1,
    focus_priorities: ["progress", "lowest_hp"],
    focus_until_death: false
  },
  {
    tower_id: "frost_tower",
    count: 1,
    level: 0,
    focus_priorities: ["barrier", "progress"],
    focus_until_death: true
  }
];

const defaultActions: BuildActionInput[] = [
  {
    wave: 2,
    at_s: 0,
    type: "build",
    target_id: "",
    value: 1,
    payload: { tower_id: "arrow_tower", count: 1, level: 0 }
  }
];

const defaultActionDraft = (): ActionDraft => ({
  wave: 1,
  at_s: 0,
  type: "build",
  target_id: "",
  value: 1,
  payloadText: JSON.stringify({ tower_id: "arrow_tower", count: 1, level: 0 })
});

const defaultLiveConnectForm: LiveConnectFormState = {
  process_name: "NordHold.exe",
  poll_ms: 1000,
  require_admin: true,
  dataset_version: "1.0.0",
  signature_profile_id: "",
  calibration_candidates_path: "",
  calibration_candidate_id: "",
  replay_session_id: ""
};

const toFiniteNumber = (value: unknown, fallback: number): number => {
  const next = typeof value === "number" ? value : Number(value);
  return Number.isFinite(next) ? next : fallback;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const toOptionalText = (value: string): string | undefined => {
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
};

const normalizeSignatureProfileIdForRequest = (value: string): string | undefined => {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  // Runtime status may expose calibrated composite ids like "profile@candidate".
  // Connect API expects base signature profile id from memory_signatures catalog.
  const baseProfile = trimmed.includes("@") ? trimmed.split("@", 1)[0].trim() : trimmed;
  return baseProfile || undefined;
};

const sanitizeCandidateIds = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (candidateId): candidateId is string => typeof candidateId === "string" && candidateId.trim().length > 0
  );
};

const buildLiveConnectPayloadFromForm = (form: LiveConnectFormState): LiveConnectRequest => {
  const payload: LiveConnectRequest = {
    process_name: form.process_name.trim() || "NordHold.exe",
    poll_ms: Math.max(200, Math.floor(toFiniteNumber(form.poll_ms, 1000))),
    require_admin: form.require_admin
  };

  const datasetVersion = toOptionalText(form.dataset_version);
  const signatureProfileId = normalizeSignatureProfileIdForRequest(form.signature_profile_id);
  const calibrationCandidatesPath = toOptionalText(form.calibration_candidates_path);
  const calibrationCandidateId = toOptionalText(form.calibration_candidate_id);
  const replaySessionId = toOptionalText(form.replay_session_id);

  if (datasetVersion) {
    payload.dataset_version = datasetVersion;
  }
  if (signatureProfileId) {
    payload.signature_profile_id = signatureProfileId;
  }
  if (calibrationCandidatesPath) {
    payload.calibration_candidates_path = calibrationCandidatesPath;
  }
  if (calibrationCandidateId) {
    payload.calibration_candidate_id = calibrationCandidateId;
  }
  if (replaySessionId) {
    payload.replay_session_id = replaySessionId;
  }

  return payload;
};

const buildLiveConnectPayloadFromStatus = (status: LiveStatus): LiveConnectRequest => {
  const payload: LiveConnectRequest = {
    process_name: status.process_name?.trim() || "NordHold.exe",
    poll_ms: Math.max(200, Math.floor(toFiniteNumber(status.poll_ms, 1000))),
    require_admin: Boolean(status.require_admin)
  };

  const datasetVersion = toOptionalText(status.dataset_version || "");
  const signatureProfileId = normalizeSignatureProfileIdForRequest(status.signature_profile || "");
  const calibrationCandidatesPath = toOptionalText(status.calibration_candidates_path || "");
  const calibrationCandidateId = toOptionalText(status.calibration_candidate || "");
  const replaySessionId = toOptionalText(status.replay_session_id || "");

  if (datasetVersion) {
    payload.dataset_version = datasetVersion;
  }
  if (signatureProfileId) {
    payload.signature_profile_id = signatureProfileId;
  }
  if (calibrationCandidatesPath) {
    payload.calibration_candidates_path = calibrationCandidatesPath;
  }
  if (calibrationCandidateId) {
    payload.calibration_candidate_id = calibrationCandidateId;
  }
  if (replaySessionId) {
    payload.replay_session_id = replaySessionId;
  }

  return payload;
};

const apiErrorMessage = (payload: unknown, fallback: string): string => {
  if (isRecord(payload) && typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail;
  }
  return fallback;
};

const toActionDraft = (action: BuildActionInput): ActionDraft => ({
  wave: action.wave,
  at_s: action.at_s,
  type: action.type,
  target_id: action.target_id,
  value: action.value,
  payloadText: JSON.stringify(action.payload)
});

const normalizeAction = (raw: unknown, index: number): BuildActionInput => {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(`Action #${index + 1} must be an object.`);
  }

  const item = raw as Record<string, unknown>;
  const payload = item.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error(`Action #${index + 1} payload must be a JSON object.`);
  }

  return {
    wave: Math.max(1, Math.floor(toFiniteNumber(item.wave, 1))),
    at_s: Math.max(0, toFiniteNumber(item.at_s, 0)),
    type: typeof item.type === "string" && item.type.trim() ? item.type : "build",
    target_id: typeof item.target_id === "string" ? item.target_id : "",
    value: toFiniteNumber(item.value, 0),
    payload: payload as Record<string, unknown>
  };
};

const parseActionsText = (text: string): BuildActionInput[] => {
  const parsed = JSON.parse(text);
  if (!Array.isArray(parsed)) {
    throw new Error("Timeline Actions JSON must be an array.");
  }
  return parsed.map((item, index) => normalizeAction(item, index));
};

const parsePayloadText = (payloadText: string, rowIndex: number): Record<string, unknown> => {
  const parsed = JSON.parse(payloadText || "{}");
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`Action row ${rowIndex + 1} payload must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
};

const toActionFromDraft = (draft: ActionDraft, rowIndex: number): BuildActionInput => ({
  wave: Math.max(1, Math.floor(toFiniteNumber(draft.wave, 1))),
  at_s: Math.max(0, toFiniteNumber(draft.at_s, 0)),
  type: draft.type.trim() || "build",
  target_id: draft.target_id,
  value: toFiniteNumber(draft.value, 0),
  payload: parsePayloadText(draft.payloadText, rowIndex)
});

const formatLiveValue = (value: number | null | undefined): string => {
  if (value === null || value === undefined) {
    return "-";
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
};

const formatLiveBooleanValue = (value: boolean | null | undefined): string => {
  if (value === null || value === undefined) {
    return "-";
  }
  return value ? "Yes" : "No";
};

const formatLivePairValue = (
  current: number | null | undefined,
  max: number | null | undefined,
  suffix = ""
): string => {
  const currentText = formatLiveValue(current);
  const maxText = formatLiveValue(max);
  const withSuffix = (value: string): string =>
    suffix && value !== "-" ? `${value}${suffix}` : value;

  if (currentText === "-" && maxText === "-") {
    return "-";
  }
  if (maxText === "-") {
    return withSuffix(currentText);
  }
  return `${withSuffix(currentText)} / ${withSuffix(maxText)}`;
};

const formatLiveDecimalValue = (value: number | null | undefined, digits = 2): string => {
  if (value === null || value === undefined) {
    return "-";
  }
  return value.toFixed(digits);
};

const formatIsoDateTime = (value: string | null | undefined): string => {
  const raw = (value || "").trim();
  if (!raw) {
    return "-";
  }
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString();
};

const COMBAT_RAW_MEMORY_KEYS = [
  "base_hp_current",
  "base_hp_max",
  "leaks_total",
  "enemies_alive",
  "boss_alive",
  "boss_hp_current",
  "boss_hp_max",
  "wave_elapsed_s",
  "wave_remaining_s",
  "barrier_hp_total",
  "enemy_regen_total_per_s",
  "is_combat_phase"
] as const;

type CombatRawMemoryKey = (typeof COMBAT_RAW_MEMORY_KEYS)[number];

const ECONOMY_RAW_MEMORY_KEYS = [
  "wood",
  "stone",
  "wheat",
  "workers_total",
  "workers_free",
  "tower_inflation_index"
] as const;

type EconomyRawMemoryKey = (typeof ECONOMY_RAW_MEMORY_KEYS)[number];

type CombatLiveMetrics = {
  baseHpCurrent: number | null;
  baseHpMax: number | null;
  leaksTotal: number | null;
  enemiesAlive: number | null;
  bossAlive: boolean | null;
  bossHpCurrent: number | null;
  bossHpMax: number | null;
  waveElapsedS: number | null;
  waveRemainingS: number | null;
  barrierHpTotal: number | null;
  enemyRegenTotalPerS: number | null;
  isCombatPhase: boolean | null;
};

type EconomyLiveMetrics = {
  wood: number | null;
  stone: number | null;
  wheat: number | null;
  workersTotal: number | null;
  workersFree: number | null;
  towerInflationIndex: number | null;
};

const toOptionalNumber = (value: unknown): number | null => {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const toOptionalBoolean = (value: unknown): boolean | null => {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value !== 0 : null;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (!normalized) {
      return null;
    }
    if (["true", "1", "yes", "y", "on"].includes(normalized)) {
      return true;
    }
    if (["false", "0", "no", "n", "off"].includes(normalized)) {
      return false;
    }
  }
  return null;
};

const readNumericByAliases = (
  sources: Array<Record<string, unknown> | null>,
  aliases: readonly string[]
): number | null => {
  for (const source of sources) {
    if (!source) {
      continue;
    }
    for (const alias of aliases) {
      const parsed = toOptionalNumber(source[alias]);
      if (parsed !== null) {
        return parsed;
      }
    }
  }
  return null;
};

const readBooleanByAliases = (
  sources: Array<Record<string, unknown> | null>,
  aliases: readonly string[]
): boolean | null => {
  for (const source of sources) {
    if (!source) {
      continue;
    }
    for (const alias of aliases) {
      const parsed = toOptionalBoolean(source[alias]);
      if (parsed !== null) {
        return parsed;
      }
    }
  }
  return null;
};

const readCombatFirstNumber = (
  rawMemory: Record<string, unknown> | null,
  sources: Array<Record<string, unknown> | null>,
  exactKey: string,
  fallbackAliases: readonly string[]
): number | null => {
  const exactValue = rawMemory ? toOptionalNumber(rawMemory[exactKey]) : null;
  if (exactValue !== null) {
    return exactValue;
  }
  return readNumericByAliases(sources, [exactKey, ...fallbackAliases]);
};

const readCombatFirstBoolean = (
  rawMemory: Record<string, unknown> | null,
  sources: Array<Record<string, unknown> | null>,
  exactKey: string,
  fallbackAliases: readonly string[]
): boolean | null => {
  const exactValue = rawMemory ? toOptionalBoolean(rawMemory[exactKey]) : null;
  if (exactValue !== null) {
    return exactValue;
  }
  return readBooleanByAliases(sources, [exactKey, ...fallbackAliases]);
};

const extractCombatRawMemoryDiagnostics = (
  snapshot: LiveSnapshot | null
): Record<CombatRawMemoryKey, unknown> => {
  const build = snapshot && isRecord(snapshot.build) ? snapshot.build : null;
  const rawMemory = build && isRecord(build.raw_memory_fields) ? build.raw_memory_fields : null;

  return COMBAT_RAW_MEMORY_KEYS.reduce<Record<CombatRawMemoryKey, unknown>>(
    (acc, key) => {
      acc[key] = rawMemory?.[key] ?? null;
      return acc;
    },
    {} as Record<CombatRawMemoryKey, unknown>
  );
};

const extractEconomyRawMemoryDiagnostics = (
  snapshot: LiveSnapshot | null
): Record<EconomyRawMemoryKey, unknown> => {
  const build = snapshot && isRecord(snapshot.build) ? snapshot.build : null;
  const rawMemory = build && isRecord(build.raw_memory_fields) ? build.raw_memory_fields : null;

  return ECONOMY_RAW_MEMORY_KEYS.reduce<Record<EconomyRawMemoryKey, unknown>>(
    (acc, key) => {
      acc[key] = rawMemory?.[key] ?? null;
      return acc;
    },
    {} as Record<EconomyRawMemoryKey, unknown>
  );
};

const extractCombatLiveMetrics = (snapshot: LiveSnapshot | null): CombatLiveMetrics => {
  if (!snapshot) {
    return {
      baseHpCurrent: null,
      baseHpMax: null,
      leaksTotal: null,
      enemiesAlive: null,
      bossAlive: null,
      bossHpCurrent: null,
      bossHpMax: null,
      waveElapsedS: null,
      waveRemainingS: null,
      barrierHpTotal: null,
      enemyRegenTotalPerS: null,
      isCombatPhase: null
    };
  }

  const topLevel = snapshot as unknown as Record<string, unknown>;
  const build = isRecord(snapshot.build) ? snapshot.build : null;
  const combat = build && isRecord(build.combat) ? build.combat : null;
  const combatSnapshot = combat && isRecord(combat.snapshot) ? combat.snapshot : null;
  const rawMemory = build && isRecord(build.raw_memory_fields) ? build.raw_memory_fields : null;
  const sources: Array<Record<string, unknown> | null> = [
    rawMemory,
    combatSnapshot,
    combat,
    build,
    topLevel
  ];

  return {
    baseHpCurrent: readCombatFirstNumber(rawMemory, sources, "base_hp_current", [
      "base_hp",
      "base_health",
      "player_hp",
      "current_hp"
    ]),
    baseHpMax: readCombatFirstNumber(rawMemory, sources, "base_hp_max", [
      "base_max_hp",
      "base_health_max",
      "player_hp_max",
      "max_hp"
    ]),
    leaksTotal: readCombatFirstNumber(rawMemory, sources, "leaks_total", [
      "leaks",
      "wave_leaks",
      "leak_count"
    ]),
    enemiesAlive: readCombatFirstNumber(rawMemory, sources, "enemies_alive", [
      "alive_enemies",
      "enemy_alive"
    ]),
    bossAlive: readCombatFirstBoolean(rawMemory, sources, "boss_alive", [
      "boss_is_alive",
      "is_boss_alive",
      "boss_active"
    ]),
    bossHpCurrent: readCombatFirstNumber(rawMemory, sources, "boss_hp_current", ["boss_hp", "boss_health"]),
    bossHpMax: readCombatFirstNumber(rawMemory, sources, "boss_hp_max", ["boss_max_hp", "boss_health_max"]),
    waveElapsedS: readCombatFirstNumber(rawMemory, sources, "wave_elapsed_s", [
      "wave_elapsed",
      "wave_time_elapsed"
    ]),
    waveRemainingS: readCombatFirstNumber(rawMemory, sources, "wave_remaining_s", [
      "wave_remaining",
      "wave_time_remaining"
    ]),
    barrierHpTotal: readCombatFirstNumber(rawMemory, sources, "barrier_hp_total", [
      "barrier_hp",
      "barrier_health",
      "shield_hp"
    ]),
    enemyRegenTotalPerS: readCombatFirstNumber(rawMemory, sources, "enemy_regen_total_per_s", [
      "regen_per_s",
      "regen_ps",
      "hp_regen_per_s"
    ]),
    isCombatPhase: readCombatFirstBoolean(rawMemory, sources, "is_combat_phase", [
      "combat_phase",
      "in_combat",
      "is_combat"
    ])
  };
};

const extractEconomyLiveMetrics = (snapshot: LiveSnapshot | null): EconomyLiveMetrics => {
  if (!snapshot) {
    return {
      wood: null,
      stone: null,
      wheat: null,
      workersTotal: null,
      workersFree: null,
      towerInflationIndex: null
    };
  }

  const topLevel = snapshot as unknown as Record<string, unknown>;
  const build = isRecord(snapshot.build) ? snapshot.build : null;
  const rawMemory = build && isRecord(build.raw_memory_fields) ? build.raw_memory_fields : null;
  const sources: Array<Record<string, unknown> | null> = [rawMemory, build, topLevel];

  return {
    wood: readCombatFirstNumber(rawMemory, sources, "wood", []),
    stone: readCombatFirstNumber(rawMemory, sources, "stone", []),
    wheat: readCombatFirstNumber(rawMemory, sources, "wheat", []),
    workersTotal: readCombatFirstNumber(rawMemory, sources, "workers_total", [
      "workers",
      "population_total"
    ]),
    workersFree: readCombatFirstNumber(rawMemory, sources, "workers_free", [
      "free_workers",
      "idle_workers",
      "population_free"
    ]),
    towerInflationIndex: readCombatFirstNumber(rawMemory, sources, "tower_inflation_index", [
      "inflation_index",
      "build_cost_index"
    ])
  };
};

const extractUnresolvedRequiredFields = (status: LiveStatus | null): string[] => {
  if (!status?.required_field_resolution) {
    return [];
  }

  return Object.entries(status.required_field_resolution)
    .filter(([, details]) => !details?.resolved)
    .map(([fieldName, details]) => {
      const addressSuffix = details?.address ? ` @ ${details.address}` : "";
      return `${fieldName}${addressSuffix}`;
    });
};

export function App() {
  const worker = useMemo(
    () => new Worker(new URL("./simWorker.ts", import.meta.url), { type: "module" }),
    []
  );

  const [mode, setMode] = useState<CalcMode>("expected");
  const [seed, setSeed] = useState(42);
  const [runs, setRuns] = useState(200);
  const [towers, setTowers] = useState<TowerPlanInput[]>(defaultTowers);
  const [actions, setActions] = useState<BuildActionInput[]>(defaultActions);
  const [actionDrafts, setActionDrafts] = useState<ActionDraft[]>(() => defaultActions.map(toActionDraft));
  const [actionsText, setActionsText] = useState(() => JSON.stringify(defaultActions, null, 2));
  const [actionsSyncError, setActionsSyncError] = useState("");
  const [result, setResult] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState("");
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const [liveSnapshot, setLiveSnapshot] = useState<LiveSnapshot | null>(null);
  const [liveConnectForm, setLiveConnectForm] = useState<LiveConnectFormState>(defaultLiveConnectForm);
  const [candidateIds, setCandidateIds] = useState<string[]>([]);
  const [connectError, setConnectError] = useState("");
  const [candidateLoadError, setCandidateLoadError] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [isAutoconnecting, setIsAutoconnecting] = useState(false);
  const [autoconnectError, setAutoconnectError] = useState("");
  const [autoconnectBootstrapState, setAutoconnectBootstrapState] = useState<
    "idle" | "running" | "ok" | "failed" | "fallback"
  >("idle");
  const [isLoadingCandidates, setIsLoadingCandidates] = useState(false);
  const [autoReconnectEnabled, setAutoReconnectEnabled] = useState(true);
  const [autoReconnectIntervalSec, setAutoReconnectIntervalSec] = useState(5);
  const [sseState, setSseState] = useState<LiveSseState>({
    connection: "idle",
    lastEventType: "-",
    lastEventAt: ""
  });
  const [sensitivity, setSensitivity] = useState<Record<string, unknown> | null>(null);
  const [expandedWave, setExpandedWave] = useState<number | null>(null);
  const liveConnectInFlightRef = useRef(false);
  const liveStatusRef = useRef<LiveStatus | null>(null);
  const isMountedRef = useRef(true);
  const liveRefreshInFlightRef = useRef(false);
  const liveRefreshQueuedRef = useRef(false);
  const lastHealthyConnectPayloadRef = useRef<LiveConnectRequest | null>(null);
  const autoCandidateBootstrapAttemptedRef = useRef(false);
  const autoConnectBootstrapAttemptedRef = useRef(false);

  useEffect(() => {
    worker.onmessage = (event: MessageEvent<{ type: string; payload?: TimelineResponse; error?: string }>) => {
      if (event.data.type === "result" && event.data.payload) {
        setError("");
        setResult(event.data.payload);
      }
      if (event.data.type === "error") {
        setError(event.data.error || "Unknown worker error");
      }
    };
    return () => worker.terminate();
  }, [worker]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const applyLiveStatusPayload = useCallback(
    (statusPayload: LiveStatus, options: { overwriteCalibration?: boolean } = {}) => {
      setLiveStatus(statusPayload);
      liveStatusRef.current = statusPayload;

      const nextCandidateIds = sanitizeCandidateIds(statusPayload.calibration_candidate_ids);
      setCandidateIds(nextCandidateIds);

      const statusDatasetVersion = toOptionalText(statusPayload.dataset_version || "");
      const statusSignatureProfile = normalizeSignatureProfileIdForRequest(
        statusPayload.signature_profile || ""
      );
      const statusCalibrationPath = toOptionalText(statusPayload.calibration_candidates_path || "");
      const statusCalibrationCandidate = toOptionalText(statusPayload.calibration_candidate || "");
      const overwriteCalibration = Boolean(options.overwriteCalibration);

      setLiveConnectForm((prev) => {
        let changed = false;
        const next = { ...prev };

        if (!prev.dataset_version.trim() && statusDatasetVersion) {
          next.dataset_version = statusDatasetVersion;
          changed = true;
        }
        if (!prev.signature_profile_id.trim() && statusSignatureProfile) {
          next.signature_profile_id = statusSignatureProfile;
          changed = true;
        }

        if (overwriteCalibration) {
          if (statusCalibrationPath && prev.calibration_candidates_path !== statusCalibrationPath) {
            next.calibration_candidates_path = statusCalibrationPath;
            changed = true;
          }
          if (statusCalibrationCandidate && prev.calibration_candidate_id !== statusCalibrationCandidate) {
            next.calibration_candidate_id = statusCalibrationCandidate;
            changed = true;
          } else if (
            !statusCalibrationCandidate &&
            nextCandidateIds.length > 0 &&
            !nextCandidateIds.includes(prev.calibration_candidate_id.trim())
          ) {
            const fallbackCandidate = nextCandidateIds[0] ?? "";
            if (fallbackCandidate && prev.calibration_candidate_id !== fallbackCandidate) {
              next.calibration_candidate_id = fallbackCandidate;
              changed = true;
            }
          }
        } else {
          if (!prev.calibration_candidates_path.trim() && statusCalibrationPath) {
            next.calibration_candidates_path = statusCalibrationPath;
            changed = true;
          }
          if (!prev.calibration_candidate_id.trim() && statusCalibrationCandidate) {
            next.calibration_candidate_id = statusCalibrationCandidate;
            changed = true;
          }
        }

        return changed ? next : prev;
      });

      if (statusPayload.mode === "memory" && statusPayload.memory_connected) {
        lastHealthyConnectPayloadRef.current = buildLiveConnectPayloadFromStatus(statusPayload);
      }
    },
    []
  );

  const refreshLiveState = useCallback(async () => {
    if (liveRefreshInFlightRef.current) {
      liveRefreshQueuedRef.current = true;
      return;
    }
    liveRefreshInFlightRef.current = true;

    try {
      do {
        liveRefreshQueuedRef.current = false;

        try {
          const [statusRes, snapshotRes] = await Promise.all([
            fetch("/api/v1/live/status"),
            fetch("/api/v1/live/snapshot")
          ]);

          if (statusRes.ok) {
            const statusPayload = (await statusRes.json()) as unknown;
            if (isMountedRef.current && isRecord(statusPayload)) {
              applyLiveStatusPayload(statusPayload as LiveStatus);
            }
          }

          if (snapshotRes.ok) {
            const snapshotPayload = (await snapshotRes.json()) as unknown;
            if (isMountedRef.current && isRecord(snapshotPayload)) {
              setLiveSnapshot(snapshotPayload as LiveSnapshot);
            }
          }
        } catch {
          // Keep previous values while bridge is not reachable.
        }
      } while (liveRefreshQueuedRef.current && isMountedRef.current);
    } finally {
      liveRefreshInFlightRef.current = false;
    }
  }, [applyLiveStatusPayload]);

  useEffect(() => {
    void refreshLiveState();
    const timer = window.setInterval(() => {
      void refreshLiveState();
    }, 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, [refreshLiveState]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (typeof EventSource === "undefined") {
      setSseState((prev) => ({
        ...prev,
        connection: "unsupported",
        lastEventType: "unsupported",
        lastEventAt: new Date().toISOString()
      }));
      return;
    }

    setSseState((prev) => ({ ...prev, connection: "connecting" }));
    const events = new EventSource("/api/v1/events");

    const handleRefreshEvent = (eventType: string) => {
      setSseState((prev) => ({
        ...prev,
        lastEventType: eventType,
        lastEventAt: new Date().toISOString()
      }));
      void refreshLiveState();
    };

    events.onopen = () => {
      setSseState((prev) => ({ ...prev, connection: "open" }));
    };

    events.onmessage = (event) => {
      let parsedType = "message";
      if (typeof event.data === "string" && event.data.trim()) {
        try {
          const payload = JSON.parse(event.data) as LiveSseEventPayload;
          const fromPayload =
            (typeof payload.event === "string" && payload.event.trim()) ||
            (typeof payload.type === "string" && payload.type.trim()) ||
            (typeof payload.topic === "string" && payload.topic.trim()) ||
            "";
          if (fromPayload) {
            parsedType = fromPayload;
          }
        } catch {
          // keep default message type
        }
      }
      handleRefreshEvent(parsedType);
    };

    events.onerror = () => {
      setSseState((prev) => ({
        ...prev,
        connection: "error"
      }));
    };

    const namedEvents = [
      "live_status",
      "live_snapshot",
      "live_update",
      "bridge_status",
      "bridge_snapshot",
      "autoconnect",
      "status",
      "snapshot"
    ];

    const listeners: Array<{ eventName: string; listener: EventListener }> = namedEvents.map(
      (eventName) => {
        const listener: EventListener = () => {
          handleRefreshEvent(eventName);
        };
        events.addEventListener(eventName, listener);
        return { eventName, listener };
      }
    );

    return () => {
      for (const { eventName, listener } of listeners) {
        events.removeEventListener(eventName, listener);
      }
      events.close();
    };
  }, [refreshLiveState]);

  const syncActionsFromDrafts = (drafts: ActionDraft[]) => {
    try {
      const nextActions = drafts.map((draft, rowIndex) => toActionFromDraft(draft, rowIndex));
      setActions(nextActions);
      setActionsText(JSON.stringify(nextActions, null, 2));
      setActionsSyncError("");
    } catch (syncError) {
      setActionsSyncError(syncError instanceof Error ? syncError.message : String(syncError));
    }
  };

  const updateActionDraft = (index: number, patch: Partial<ActionDraft>) => {
    setActionDrafts((prev) => {
      const next = prev.map((draft, rowIndex) => (rowIndex === index ? { ...draft, ...patch } : draft));
      syncActionsFromDrafts(next);
      return next;
    });
  };

  const addActionDraft = () => {
    setActionDrafts((prev) => {
      const next = [...prev, defaultActionDraft()];
      syncActionsFromDrafts(next);
      return next;
    });
  };

  const removeActionDraft = (index: number) => {
    setActionDrafts((prev) => {
      const next = prev.filter((_, rowIndex) => rowIndex !== index);
      syncActionsFromDrafts(next);
      return next;
    });
  };

  const handleActionsTextChange = (nextText: string) => {
    setActionsText(nextText);
    try {
      const parsed = parseActionsText(nextText);
      setActions(parsed);
      setActionDrafts(parsed.map(toActionDraft));
      setActionsSyncError("");
    } catch (parseError) {
      setActionsSyncError(parseError instanceof Error ? parseError.message : String(parseError));
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      runEvaluation();
    }, 240);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, seed, runs, towers, actions, actionsSyncError]);

  const runEvaluation = () => {
    if (actionsSyncError) {
      setError(actionsSyncError);
      return;
    }

    const plan: BuildPlanInput = {
      scenario_id: "normal_baseline",
      towers,
      active_global_modifiers: ["village_arsenal_l3"],
      actions
    };

    const payload: TimelineRequest = {
      mode,
      seed,
      monte_carlo_runs: mode === "monte_carlo" ? runs : 1,
      build_plan: plan
    };

    setError("");
    worker.postMessage({ type: "evaluate", payload });
  };

  const updateTower = (index: number, patch: Partial<TowerPlanInput>) => {
    setTowers((prev) => prev.map((tower, towerIndex) => (towerIndex === index ? { ...tower, ...patch } : tower)));
  };

  const addTower = () => {
    setTowers((prev) => [
      ...prev,
      {
        tower_id: "arrow_tower",
        count: 1,
        level: 0,
        focus_priorities: ["progress", "lowest_hp"],
        focus_until_death: false
      }
    ]);
  };

  const removeTower = (index: number) => {
    setTowers((prev) => prev.filter((_, towerIndex) => towerIndex !== index));
  };

  const buildLiveConnectPayload = useCallback(
    (formState: LiveConnectFormState = liveConnectForm): LiveConnectRequest =>
      buildLiveConnectPayloadFromForm(formState),
    [liveConnectForm]
  );

  const buildLiveAutoconnectPayload = useCallback(
    (
      formState: LiveConnectFormState = liveConnectForm,
      noManualOverrides: boolean = false
    ): LiveAutoconnectRequest => {
      const payload: LiveAutoconnectRequest = {
        process_name: formState.process_name.trim() || "NordHold.exe",
        poll_ms: Math.max(200, Math.floor(toFiniteNumber(formState.poll_ms, 1000))),
        require_admin: formState.require_admin,
        dataset_autorefresh: true
      };

      if (noManualOverrides) {
        return payload;
      }

      const datasetVersion = toOptionalText(formState.dataset_version);
      const signatureProfileId = normalizeSignatureProfileIdForRequest(formState.signature_profile_id);
      const calibrationCandidatesPath = toOptionalText(formState.calibration_candidates_path);
      const calibrationCandidateId = toOptionalText(formState.calibration_candidate_id);
      const replaySessionId = toOptionalText(formState.replay_session_id);

      if (datasetVersion) {
        payload.dataset_version = datasetVersion;
      }
      if (signatureProfileId) {
        payload.signature_profile_id = signatureProfileId;
      }
      if (calibrationCandidatesPath) {
        payload.calibration_candidates_path = calibrationCandidatesPath;
      }
      if (calibrationCandidateId) {
        payload.calibration_candidate_id = calibrationCandidateId;
      }
      if (replaySessionId) {
        payload.replay_session_id = replaySessionId;
      }

      return payload;
    },
    [liveConnectForm]
  );

  const loadCalibrationCandidates = useCallback(
    async ({
      pathOverride,
      preferredCandidateId,
      silent = false,
      showLoading = false
    }: {
      pathOverride?: string;
      preferredCandidateId?: string;
      silent?: boolean;
      showLoading?: boolean;
    } = {}): Promise<CandidateLoadResult | null> => {
      const path = (pathOverride ?? liveConnectForm.calibration_candidates_path ?? "").trim();
      const preferredId = (preferredCandidateId ?? liveConnectForm.calibration_candidate_id ?? "").trim();

      if (!silent) {
        setCandidateLoadError("");
      }
      if (showLoading) {
        setIsLoadingCandidates(true);
      }

      try {
        const query = new URLSearchParams({ path }).toString();
        const response = await fetch(`/api/v1/live/calibration/candidates?${query}`);
        let payload: unknown = null;
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }

        if (!response.ok) {
          throw new Error(apiErrorMessage(payload, `Candidate load failed (${response.status})`));
        }
        if (!isRecord(payload) || !Array.isArray(payload.candidate_ids)) {
          throw new Error("Candidate load failed: invalid response payload.");
        }

        const parsedPayload = payload as LiveCalibrationCandidatesResponse;
        const nextCandidateIds = sanitizeCandidateIds(parsedPayload.candidate_ids);
        const activeCandidateId =
          typeof parsedPayload.active_candidate_id === "string"
            ? parsedPayload.active_candidate_id.trim()
            : "";
        const selectedCandidateId = nextCandidateIds.includes(preferredId)
          ? preferredId
          : nextCandidateIds.includes(activeCandidateId)
            ? activeCandidateId
            : (nextCandidateIds[0] ?? "");
        const resolvedPath =
          typeof parsedPayload.path === "string" && parsedPayload.path.trim()
            ? parsedPayload.path.trim()
            : path;

        setCandidateIds(nextCandidateIds);
        setLiveConnectForm((prev) => {
          const prevCandidateId = prev.calibration_candidate_id.trim();
          const fallbackCandidateId = nextCandidateIds.includes(prevCandidateId) ? prevCandidateId : "";
          const nextCandidateId = selectedCandidateId || fallbackCandidateId;
          const nextPath = resolvedPath || prev.calibration_candidates_path;

          if (
            prev.calibration_candidates_path === nextPath &&
            prev.calibration_candidate_id === nextCandidateId
          ) {
            return prev;
          }

          return {
            ...prev,
            calibration_candidates_path: nextPath,
            calibration_candidate_id: nextCandidateId
          };
        });

        return {
          path: resolvedPath,
          candidateId: selectedCandidateId,
          candidateIds: nextCandidateIds
        };
      } catch (requestError) {
        if (!silent) {
          setCandidateLoadError(
            requestError instanceof Error ? requestError.message : "Candidate load failed."
          );
        }
        return null;
      } finally {
        if (showLoading) {
          setIsLoadingCandidates(false);
        }
      }
    },
    [liveConnectForm.calibration_candidates_path, liveConnectForm.calibration_candidate_id]
  );

  const autoconnectLive = useCallback(
    async ({
      silent = false,
      startup = false,
      noManualOverrides = false
    }: {
      silent?: boolean;
      startup?: boolean;
      noManualOverrides?: boolean;
    } = {}): Promise<boolean> => {
      if (liveConnectInFlightRef.current) {
        return false;
      }
      liveConnectInFlightRef.current = true;
      setIsAutoconnecting(true);
      if (startup) {
        setAutoconnectBootstrapState("running");
      }
      if (!silent) {
        setAutoconnectError("");
      }

      try {
        const response = await fetch("/api/v1/live/autoconnect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildLiveAutoconnectPayload(liveConnectForm, noManualOverrides))
        });

        let payload: unknown = null;
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }

        if (!response.ok) {
          throw new Error(apiErrorMessage(payload, `Autoconnect failed (${response.status})`));
        }
        if (!isRecord(payload)) {
          throw new Error("Autoconnect failed: invalid response payload.");
        }

        applyLiveStatusPayload(payload as LiveStatus, { overwriteCalibration: true });
        setAutoconnectError("");
        if (startup) {
          const status = payload as LiveStatus;
          setAutoconnectBootstrapState(
            status.mode === "memory" && status.memory_connected ? "ok" : "failed"
          );
        }
        return true;
      } catch (requestError) {
        const message =
          requestError instanceof Error ? requestError.message : "Autoconnect failed.";
        if (!silent) {
          setAutoconnectError(message);
        }
        if (startup) {
          setAutoconnectBootstrapState("failed");
        }
        return false;
      } finally {
        liveConnectInFlightRef.current = false;
        setIsAutoconnecting(false);
      }
    },
    [applyLiveStatusPayload, buildLiveAutoconnectPayload, liveConnectForm]
  );

  const connectLive = useCallback(
    async (autoReconnect: boolean = false) => {
      if (liveConnectInFlightRef.current) {
        return;
      }
      liveConnectInFlightRef.current = true;
      setIsConnecting(true);
      if (!autoReconnect) {
        setConnectError("");
      }

      try {
        let connectPayload = buildLiveConnectPayload();
        if (autoReconnect && lastHealthyConnectPayloadRef.current) {
          const rememberedPayload = lastHealthyConnectPayloadRef.current;
          connectPayload = {
            ...connectPayload,
            dataset_version: connectPayload.dataset_version ?? rememberedPayload.dataset_version,
            signature_profile_id:
              connectPayload.signature_profile_id ?? rememberedPayload.signature_profile_id,
            calibration_candidates_path:
              connectPayload.calibration_candidates_path ?? rememberedPayload.calibration_candidates_path,
            calibration_candidate_id:
              connectPayload.calibration_candidate_id ?? rememberedPayload.calibration_candidate_id,
            replay_session_id: connectPayload.replay_session_id ?? rememberedPayload.replay_session_id
          };
        }

        const needsCandidateResolution =
          !connectPayload.replay_session_id &&
          (!connectPayload.calibration_candidates_path || !connectPayload.calibration_candidate_id);

        if (needsCandidateResolution) {
          const candidateLoad = await loadCalibrationCandidates({
            pathOverride: connectPayload.calibration_candidates_path ?? "",
            preferredCandidateId: connectPayload.calibration_candidate_id ?? "",
            silent: autoReconnect,
            showLoading: false
          });

          if (candidateLoad) {
            if (!connectPayload.calibration_candidates_path && candidateLoad.path) {
              connectPayload.calibration_candidates_path = candidateLoad.path;
            }
            if (!connectPayload.calibration_candidate_id && candidateLoad.candidateId) {
              connectPayload.calibration_candidate_id = candidateLoad.candidateId;
            }
          }
        }

        const unresolvedAutoReconnectPayload =
          autoReconnect &&
          !connectPayload.replay_session_id &&
          !connectPayload.calibration_candidates_path &&
          !connectPayload.calibration_candidate_id &&
          !connectPayload.signature_profile_id;
        if (unresolvedAutoReconnectPayload) {
          setConnectError(
            "Auto reconnect paused: waiting for resolved calibration candidate payload."
          );
          return;
        }

        const response = await fetch("/api/v1/live/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(connectPayload)
        });
        let payload: unknown = null;
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }

        if (!response.ok) {
          throw new Error(apiErrorMessage(payload, `Connect failed (${response.status})`));
        }
        if (!isRecord(payload)) {
          throw new Error("Connect failed: invalid response payload.");
        }

        const statusPayload = payload as LiveStatus;
        applyLiveStatusPayload(statusPayload, { overwriteCalibration: true });
        setConnectError("");
      } catch (requestError) {
        const message = requestError instanceof Error ? requestError.message : "Connect failed.";
        setConnectError(autoReconnect ? `Auto reconnect: ${message}` : message);
      } finally {
        liveConnectInFlightRef.current = false;
        setIsConnecting(false);
      }
    },
    [applyLiveStatusPayload, buildLiveConnectPayload, loadCalibrationCandidates]
  );

  useEffect(() => {
    if (autoCandidateBootstrapAttemptedRef.current) {
      return;
    }
    if (
      liveConnectForm.calibration_candidates_path.trim() ||
      liveConnectForm.calibration_candidate_id.trim()
    ) {
      return;
    }

    autoCandidateBootstrapAttemptedRef.current = true;
    void loadCalibrationCandidates({
      pathOverride: "",
      preferredCandidateId: "",
      silent: true,
      showLoading: false
    });
  }, [
    liveConnectForm.calibration_candidates_path,
    liveConnectForm.calibration_candidate_id,
    loadCalibrationCandidates
  ]);

  useEffect(() => {
    if (autoConnectBootstrapAttemptedRef.current) {
      return;
    }
    if (liveStatusRef.current?.mode === "memory" && liveStatusRef.current.memory_connected) {
      return;
    }

    autoConnectBootstrapAttemptedRef.current = true;
    const timer = window.setTimeout(() => {
      void (async () => {
        const autoconnectOk = await autoconnectLive({
          silent: true,
          startup: true,
          noManualOverrides: true
        });
        if (!autoconnectOk) {
          setAutoconnectBootstrapState("fallback");
          void connectLive(true);
        }
      })();
    }, 250);
    return () => window.clearTimeout(timer);
  }, [autoconnectLive, connectLive]);

  useEffect(() => {
    if (!autoReconnectEnabled) {
      return;
    }

    const intervalMs = Math.max(1, Math.floor(toFiniteNumber(autoReconnectIntervalSec, 1))) * 1000;
    const timer = window.setInterval(() => {
      const currentStatus = liveStatusRef.current;
      if (currentStatus?.mode === "memory" && currentStatus.memory_connected) {
        return;
      }
      void connectLive(true);
    }, intervalMs);

    return () => {
      window.clearInterval(timer);
    };
  }, [autoReconnectEnabled, autoReconnectIntervalSec, connectLive]);

  const runSensitivity = async () => {
    if (actionsSyncError) {
      setError(actionsSyncError);
      return;
    }

    setSensitivity(null);
    try {
      const response = await fetch("/api/v1/analytics/sensitivity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          seed,
          monte_carlo_runs: mode === "monte_carlo" ? runs : 1,
          parameter: "tower_damage_scale",
          values: [0.8, 0.9, 1.0, 1.1, 1.2],
          build_plan: {
            scenario_id: "normal_baseline",
            towers,
            active_global_modifiers: ["village_arsenal_l3"],
            actions
          }
        })
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail || "Sensitivity request failed");
      }
      setError("");
      setSensitivity(payload.result as Record<string, unknown>);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : String(requestError));
    }
  };

  const totals = result?.result.totals;
  const waves = result?.result.wave_results || [];
  const liveWave = liveSnapshot?.wave ?? null;
  const liveSourceMode = liveSnapshot?.source_mode || liveStatus?.mode || "-";
  const combatMetrics = useMemo(() => extractCombatLiveMetrics(liveSnapshot), [liveSnapshot]);
  const economyMetrics = useMemo(() => extractEconomyLiveMetrics(liveSnapshot), [liveSnapshot]);
  const combatRawMemoryDiagnostics = useMemo(
    () => extractCombatRawMemoryDiagnostics(liveSnapshot),
    [liveSnapshot]
  );
  const economyRawMemoryDiagnostics = useMemo(
    () => extractEconomyRawMemoryDiagnostics(liveSnapshot),
    [liveSnapshot]
  );
  const unresolvedRequiredFields = useMemo(
    () => extractUnresolvedRequiredFields(liveStatus),
    [liveStatus]
  );
  const fieldCoverage = liveStatus?.field_coverage;
  const calibrationQuality = (liveStatus?.calibration_quality || "minimal").toLowerCase();
  const calibrationQualityClass =
    calibrationQuality === "full"
      ? "quality-full"
      : calibrationQuality === "partial"
        ? "quality-partial"
        : "quality-minimal";
  const requiredResolved = fieldCoverage?.required_resolved ?? 0;
  const requiredTotal = fieldCoverage?.required_total ?? 0;
  const optionalResolved = fieldCoverage?.optional_resolved ?? 0;
  const optionalTotal = fieldCoverage?.optional_total ?? 0;
  const requiredCoveragePercent =
    requiredTotal > 0 ? Math.round((requiredResolved / requiredTotal) * 100) : 0;
  const optionalCoveragePercent =
    optionalTotal > 0 ? Math.round((optionalResolved / optionalTotal) * 100) : 0;
  const activeRequiredFields = (liveStatus?.active_required_fields || []).join(", ");
  const workersDisplay = formatLivePairValue(economyMetrics.workersFree, economyMetrics.workersTotal);
  const autoconnectLastAttemptAt = formatIsoDateTime(liveStatus?.autoconnect_last_attempt_at || "");
  const autoconnectLastResult =
    liveStatus?.autoconnect_last_result && isRecord(liveStatus.autoconnect_last_result)
      ? liveStatus.autoconnect_last_result
      : null;
  const autoconnectLastMode =
    autoconnectLastResult && typeof autoconnectLastResult.mode === "string"
      ? autoconnectLastResult.mode
      : "-";
  const autoconnectLastReason =
    autoconnectLastResult && typeof autoconnectLastResult.reason === "string"
      ? autoconnectLastResult.reason
      : "-";
  const autoconnectCandidateSelection =
    autoconnectLastResult &&
    isRecord(autoconnectLastResult.candidate_selection) &&
    typeof autoconnectLastResult.candidate_selection.selected_candidate_id === "string"
      ? autoconnectLastResult.candidate_selection.selected_candidate_id
      : "-";
  const datasetAutorefreshLabel =
    typeof liveStatus?.dataset_autorefresh === "boolean"
      ? liveStatus.dataset_autorefresh
        ? "on"
        : "off"
      : "-";
  const sseConnectionLabel =
    sseState.connection === "open"
      ? "connected"
      : sseState.connection === "connecting"
        ? "connecting"
        : sseState.connection === "unsupported"
          ? "unsupported"
          : sseState.connection === "error"
            ? "reconnecting"
            : "idle";
  const sseLastEventAt = formatIsoDateTime(sseState.lastEventAt);
  const autoconnectBootstrapLabel =
    autoconnectBootstrapState === "running"
      ? "running"
      : autoconnectBootstrapState === "ok"
        ? "ok"
        : autoconnectBootstrapState === "failed"
          ? "failed"
          : autoconnectBootstrapState === "fallback"
            ? "fallback->connect"
            : "idle";
  const baseHpDisplay = formatLivePairValue(combatMetrics.baseHpCurrent, combatMetrics.baseHpMax);
  const bossHpDisplay = formatLivePairValue(combatMetrics.bossHpCurrent, combatMetrics.bossHpMax);
  const waveTimerDisplay = formatLivePairValue(
    combatMetrics.waveElapsedS,
    combatMetrics.waveRemainingS,
    "s"
  );

  return (
    <main className="page">
      <header className="hero">
        <h1>Nordhold Realtime Wave Calculator</h1>
        <p>
          Offline-first planner with interactive timeline editing and 1-second live snapshot polling.
        </p>
      </header>

      <section className="layout">
        <article className="panel control-panel">
          <h2>Build Planner</h2>

          <div className="control-row">
            <label>
              Mode
              <select value={mode} onChange={(event) => setMode(event.target.value as CalcMode)}>
                <option value="expected">Expected</option>
                <option value="combat">Combat</option>
                <option value="monte_carlo">Monte-Carlo</option>
              </select>
            </label>
            <label>
              Seed
              <input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value || 0))} />
            </label>
            <label>
              Runs
              <input
                type="number"
                min={1}
                value={runs}
                onChange={(event) => setRuns(Number(event.target.value || 1))}
                disabled={mode !== "monte_carlo"}
              />
            </label>
          </div>

          <div className="tower-grid">
            {towers.map((tower, index) => (
              <div className="tower-row" key={`${tower.tower_id}-${index}`}>
                <label>
                  Tower
                  <select
                    value={tower.tower_id}
                    onChange={(event) => updateTower(index, { tower_id: event.target.value })}
                  >
                    <option value="arrow_tower">Arrow Tower</option>
                    <option value="frost_tower">Frost Tower</option>
                  </select>
                </label>

                <label>
                  Count
                  <input
                    type="number"
                    min={0}
                    value={tower.count}
                    onChange={(event) => updateTower(index, { count: Number(event.target.value || 0) })}
                  />
                </label>

                <label>
                  Level
                  <input
                    type="number"
                    min={0}
                    value={tower.level}
                    onChange={(event) => updateTower(index, { level: Number(event.target.value || 0) })}
                  />
                </label>

                <button className="ghost" onClick={() => removeTower(index)} type="button">
                  Remove
                </button>
              </div>
            ))}
          </div>

          <div className="actions">
            <button onClick={addTower} type="button">
              Add Tower
            </button>
            <button onClick={runEvaluation} type="button">
              Recalculate
            </button>
            <button onClick={runSensitivity} type="button">
              Run Sensitivity
            </button>
          </div>

          <div className="timeline-editor">
            <div className="section-head">
              <h3>Timeline Actions Editor</h3>
              <button className="ghost" onClick={addActionDraft} type="button">
                Add Action Row
              </button>
            </div>

            {actionDrafts.length === 0 ? <p className="muted">No actions. Add a row or paste JSON below.</p> : null}

            {actionDrafts.map((action, index) => (
              <div className="timeline-row" key={`timeline-action-${index}`}>
                <label>
                  Wave
                  <input
                    type="number"
                    min={1}
                    value={action.wave}
                    onChange={(event) =>
                      updateActionDraft(index, { wave: Math.max(1, Math.floor(Number(event.target.value || 1))) })
                    }
                  />
                </label>
                <label>
                  At (s)
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={action.at_s}
                    onChange={(event) =>
                      updateActionDraft(index, { at_s: Math.max(0, Number(event.target.value || 0)) })
                    }
                  />
                </label>
                <label>
                  Type
                  <input value={action.type} onChange={(event) => updateActionDraft(index, { type: event.target.value })} />
                </label>
                <label>
                  Target
                  <input
                    value={action.target_id}
                    onChange={(event) => updateActionDraft(index, { target_id: event.target.value })}
                  />
                </label>
                <label>
                  Value
                  <input
                    type="number"
                    step={0.1}
                    value={action.value}
                    onChange={(event) => updateActionDraft(index, { value: Number(event.target.value || 0) })}
                  />
                </label>
                <label className="payload-field">
                  Payload JSON
                  <textarea
                    rows={3}
                    value={action.payloadText}
                    onChange={(event) => updateActionDraft(index, { payloadText: event.target.value })}
                  />
                </label>
                <button className="ghost" onClick={() => removeActionDraft(index)} type="button">
                  Remove
                </button>
              </div>
            ))}
          </div>

          <label className="textarea-label">
            Raw Timeline Actions JSON (Power)
            <textarea value={actionsText} onChange={(event) => handleActionsTextChange(event.target.value)} rows={10} />
          </label>

          {actionsSyncError ? <p className="error">{actionsSyncError}</p> : <p className="muted">Editor and raw JSON are synchronized.</p>}
        </article>

        <article className="panel output-panel">
          <h2>Wave Dashboard</h2>

          <div className="live-cards">
            <div className="live-card">
              <span>Live Wave</span>
              <strong>{liveWave ?? "-"}</strong>
            </div>
            <div className="live-card">
              <span>Gold</span>
              <strong>{formatLiveValue(liveSnapshot?.gold)}</strong>
            </div>
            <div className="live-card">
              <span>Essence</span>
              <strong>{formatLiveValue(liveSnapshot?.essence)}</strong>
            </div>
            <div className="live-card">
              <span>Source</span>
              <strong>{liveSourceMode}</strong>
            </div>
          </div>

          <div className="live-cards combat-live-cards">
            <div className="live-card">
              <span>Base HP</span>
              <strong>{baseHpDisplay}</strong>
            </div>
            <div className="live-card">
              <span>Leaks Total</span>
              <strong>{formatLiveValue(combatMetrics.leaksTotal)}</strong>
            </div>
            <div className="live-card">
              <span>Enemies Alive</span>
              <strong>{formatLiveValue(combatMetrics.enemiesAlive)}</strong>
            </div>
            <div className="live-card">
              <span>Boss Alive</span>
              <strong>{formatLiveBooleanValue(combatMetrics.bossAlive)}</strong>
            </div>
            <div className="live-card">
              <span>Boss HP</span>
              <strong>{bossHpDisplay}</strong>
            </div>
            <div className="live-card">
              <span>Wave Timer (elapsed/remaining)</span>
              <strong>{waveTimerDisplay}</strong>
            </div>
            <div className="live-card">
              <span>Barrier HP</span>
              <strong>{formatLiveValue(combatMetrics.barrierHpTotal)}</strong>
            </div>
            <div className="live-card">
              <span>Enemy Regen/s</span>
              <strong>{formatLiveValue(combatMetrics.enemyRegenTotalPerS)}</strong>
            </div>
            <div className="live-card">
              <span>Combat Phase</span>
              <strong>{formatLiveBooleanValue(combatMetrics.isCombatPhase)}</strong>
            </div>
          </div>

          <div className="live-cards economy-live-cards">
            <div className="live-card">
              <span>Wood</span>
              <strong>{formatLiveValue(economyMetrics.wood)}</strong>
            </div>
            <div className="live-card">
              <span>Stone</span>
              <strong>{formatLiveValue(economyMetrics.stone)}</strong>
            </div>
            <div className="live-card">
              <span>Wheat</span>
              <strong>{formatLiveValue(economyMetrics.wheat)}</strong>
            </div>
            <div className="live-card">
              <span>Workers (free / total)</span>
              <strong>{workersDisplay}</strong>
            </div>
            <div className="live-card">
              <span>Tower Inflation</span>
              <strong>{formatLiveDecimalValue(economyMetrics.towerInflationIndex, 3)}</strong>
            </div>
          </div>

          <div className="live-connect-panel">
            <div className="section-head">
              <h3>Live Connection</h3>
            </div>

            <div className="live-connect-grid">
              <label>
                Process Name
                <input
                  value={liveConnectForm.process_name}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({ ...prev, process_name: event.target.value }))
                  }
                />
              </label>
              <label>
                Poll (ms)
                <input
                  type="number"
                  min={200}
                  value={liveConnectForm.poll_ms}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({
                      ...prev,
                      poll_ms: Math.max(200, Math.floor(Number(event.target.value || 200)))
                    }))
                  }
                />
              </label>
              <label className="checkbox-toggle">
                <span>Require Admin</span>
                <input
                  type="checkbox"
                  checked={liveConnectForm.require_admin}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({ ...prev, require_admin: event.target.checked }))
                  }
                />
              </label>
              <label>
                Dataset Version (optional)
                <input
                  value={liveConnectForm.dataset_version}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({ ...prev, dataset_version: event.target.value }))
                  }
                />
              </label>
              <label>
                Signature Profile ID (optional)
                <input
                  value={liveConnectForm.signature_profile_id}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({ ...prev, signature_profile_id: event.target.value }))
                  }
                />
              </label>
              <label>
                Calibration Candidates Path (optional)
                <input
                  value={liveConnectForm.calibration_candidates_path}
                  onChange={(event) => {
                    const nextPath = event.target.value;
                    setLiveConnectForm((prev) => ({ ...prev, calibration_candidates_path: nextPath }));
                    if (!nextPath.trim()) {
                      setCandidateLoadError("");
                    }
                  }}
                />
              </label>
              <label>
                Calibration Candidate ID (optional)
                <input
                  value={liveConnectForm.calibration_candidate_id}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({ ...prev, calibration_candidate_id: event.target.value }))
                  }
                />
              </label>
              <label>
                Replay Session ID (optional)
                <input
                  value={liveConnectForm.replay_session_id}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({ ...prev, replay_session_id: event.target.value }))
                  }
                />
              </label>
              <label>
                Candidate Select
                <select
                  value={liveConnectForm.calibration_candidate_id}
                  onChange={(event) =>
                    setLiveConnectForm((prev) => ({
                      ...prev,
                      calibration_candidate_id: event.target.value
                    }))
                  }
                  disabled={candidateIds.length === 0}
                >
                  <option value="">No candidate selected</option>
                  {candidateIds.map((candidateId) => (
                    <option key={`candidate-${candidateId}`} value={candidateId}>
                      {candidateId}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="actions live-connect-actions">
              <button onClick={() => void connectLive()} type="button" disabled={isConnecting}>
                {isConnecting ? "Connecting..." : "Connect Live"}
              </button>
              <button
                className="ghost"
                onClick={() => void autoconnectLive()}
                type="button"
                disabled={isAutoconnecting || isConnecting}
              >
                {isAutoconnecting ? "Autoconnecting..." : "Autoconnect"}
              </button>
              <button
                className="ghost"
                onClick={() =>
                  void loadCalibrationCandidates({
                    showLoading: true
                  })
                }
                type="button"
                disabled={isLoadingCandidates}
              >
                {isLoadingCandidates ? "Loading..." : "Load Candidates"}
              </button>
            </div>

            <div className="live-connect-grid live-connect-auto">
              <label className="checkbox-toggle">
                <span>Auto reconnect</span>
                <input
                  type="checkbox"
                  checked={autoReconnectEnabled}
                  onChange={(event) => setAutoReconnectEnabled(event.target.checked)}
                />
              </label>
              <label>
                Interval (seconds)
                <input
                  type="number"
                  min={1}
                  value={autoReconnectIntervalSec}
                  onChange={(event) =>
                    setAutoReconnectIntervalSec(Math.max(1, Math.floor(Number(event.target.value || 1))))
                  }
                  disabled={!autoReconnectEnabled}
                />
              </label>
              <p className="muted live-connect-hint">
                Auto reconnect runs only while live mode is not <strong>memory</strong>.
              </p>
            </div>

            {connectError ? <p className="error">{connectError}</p> : null}
            {autoconnectError ? <p className="error">{autoconnectError}</p> : null}
            {candidateLoadError ? <p className="error">{candidateLoadError}</p> : null}
          </div>

          <div className="metrics">
            <div>
              <span>Potential Damage</span>
              <strong>{totals ? totals.potential_damage.toFixed(2) : "-"}</strong>
            </div>
            <div>
              <span>Combat Damage</span>
              <strong>{totals ? totals.combat_damage.toFixed(2) : "-"}</strong>
            </div>
            <div>
              <span>Leaks</span>
              <strong>{totals ? totals.leaks.toFixed(2) : "-"}</strong>
            </div>
          </div>

          <div className="chart">
            {waves.map((wave) => {
              const ratio = wave.enemy_hp_pool > 0 ? Math.min(1, wave.combat_damage / wave.enemy_hp_pool) : 0;
              const isLive = liveWave !== null && wave.wave === liveWave;
              return (
                <div className={`wave-bar${isLive ? " live-wave-bar" : ""}`} key={wave.wave}>
                  <div className="wave-label">
                    <span>Wave {wave.wave}</span>
                    {isLive ? <span className="live-marker">LIVE</span> : null}
                  </div>
                  <div className="wave-track">
                    <div className="wave-fill" style={{ width: `${ratio * 100}%` }} />
                  </div>
                  <div className="wave-value">{wave.combat_damage.toFixed(0)}</div>
                </div>
              );
            })}
          </div>

          <div className="wave-table-wrap">
            <table className="wave-table">
              <thead>
                <tr>
                  <th>Wave</th>
                  <th>Potential</th>
                  <th>Combat</th>
                  <th>DPS</th>
                  <th>Clear(s)</th>
                  <th>Leaks</th>
                  <th>Breakdown</th>
                </tr>
              </thead>
              <tbody>
                {waves.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="muted">
                      No wave output yet.
                    </td>
                  </tr>
                ) : null}
                {waves.map((wave) => {
                  const isLive = liveWave !== null && wave.wave === liveWave;
                  const isExpanded = expandedWave === wave.wave;
                  const breakdownEntries = Object.entries(wave.breakdown || {}).sort((a, b) => b[1] - a[1]);
                  return (
                    <Fragment key={`wave-table-${wave.wave}`}>
                      <tr className={isLive ? "live-wave-row" : ""}>
                        <td>
                          <div className="wave-cell">
                            <span>Wave {wave.wave}</span>
                            {isLive ? <span className="live-marker">LIVE</span> : null}
                          </div>
                        </td>
                        <td>{wave.potential_damage.toFixed(2)}</td>
                        <td>{wave.combat_damage.toFixed(2)}</td>
                        <td>{wave.effective_dps.toFixed(2)}</td>
                        <td>{wave.clear_time_s.toFixed(2)}</td>
                        <td>{wave.leaks.toFixed(2)}</td>
                        <td>
                          <button
                            className="ghost small"
                            type="button"
                            onClick={() => setExpandedWave((prev) => (prev === wave.wave ? null : wave.wave))}
                          >
                            {isExpanded ? "Hide" : "Show"}
                          </button>
                        </td>
                      </tr>
                      {isExpanded ? (
                        <tr className="breakdown-row">
                          <td colSpan={7}>
                            {breakdownEntries.length === 0 ? (
                              <p className="muted">No breakdown values for this wave.</p>
                            ) : (
                              <div className="breakdown-grid">
                                {breakdownEntries.map(([key, value]) => (
                                  <div className="breakdown-item" key={`wave-${wave.wave}-${key}`}>
                                    <span>{key}</span>
                                    <strong>{value.toFixed(2)}</strong>
                                  </div>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          <section className="diagnostics live-bridge-diagnostics">
            <h3>Live Bridge Diagnostics</h3>
            <div className="diag-summary-grid">
              <div className="diag-summary-card">
                <span>Calibration Quality</span>
                <strong className={`quality-pill ${calibrationQualityClass}`}>{calibrationQuality}</strong>
                {fieldCoverage ? (
                  <p className="muted">
                    Required coverage: {requiredResolved}/{requiredTotal} ({requiredCoveragePercent}%)
                  </p>
                ) : (
                  <p className="muted">Required coverage: -</p>
                )}
                {fieldCoverage ? (
                  <p className="muted">
                    Optional coverage: {optionalResolved}/{optionalTotal} ({optionalCoveragePercent}%)
                  </p>
                ) : (
                  <p className="muted">Optional coverage: -</p>
                )}
              </div>
              <div className="diag-summary-card">
                <span>Unresolved Required</span>
                <strong>{unresolvedRequiredFields.length}</strong>
                {unresolvedRequiredFields.length > 0 ? (
                  <p className="error diag-inline-error">{unresolvedRequiredFields.join(", ")}</p>
                ) : (
                  <p className="muted">All required fields resolved.</p>
                )}
              </div>
              <div className="diag-summary-card">
                <span>Autoconnect</span>
                <strong>{liveStatus?.autoconnect_enabled ? "enabled" : "disabled"}</strong>
                <p className="muted">Startup flow: {autoconnectBootstrapLabel}</p>
                <p className="muted">Last attempt: {autoconnectLastAttemptAt}</p>
                <p className="muted">
                  Last result: {autoconnectLastMode} ({autoconnectLastReason})
                </p>
                <p className="muted">Selected candidate: {autoconnectCandidateSelection}</p>
              </div>
              <div className="diag-summary-card">
                <span>Events Stream</span>
                <strong>{sseConnectionLabel}</strong>
                <p className="muted">Last event: {sseState.lastEventType}</p>
                <p className="muted">At: {sseLastEventAt}</p>
                <p className="muted">dataset_autorefresh: {datasetAutorefreshLabel}</p>
              </div>
            </div>
            <p className="muted diag-active-required">
              Active required fields: {activeRequiredFields || "-"}
            </p>
            <p className="muted diag-active-required">
              Autoconnect endpoint startup mode keeps manual overrides untouched and runs once on app boot.
            </p>
            <details className="diagnostics-raw">
              <summary>Combat raw_memory_fields contract snapshot</summary>
              <pre>{JSON.stringify(combatRawMemoryDiagnostics, null, 2)}</pre>
            </details>
            <details className="diagnostics-raw">
              <summary>Economy raw_memory_fields contract snapshot</summary>
              <pre>{JSON.stringify(economyRawMemoryDiagnostics, null, 2)}</pre>
            </details>
            <details className="diagnostics-raw">
              <summary>Raw live status JSON</summary>
              <pre>{JSON.stringify(liveStatus, null, 2)}</pre>
            </details>
          </section>

          <details className="diagnostics">
            <summary>Sensitivity Snapshot</summary>
            <pre>{JSON.stringify(sensitivity, null, 2)}</pre>
          </details>

          {error ? <p className="error">{error}</p> : null}
        </article>
      </section>
    </main>
  );
}
