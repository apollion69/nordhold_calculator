export type CalcMode = "expected" | "combat" | "monte_carlo";

export interface TowerPlanInput {
  tower_id: string;
  count: number;
  level: number;
  focus_priorities: string[];
  focus_until_death: boolean;
}

export interface BuildActionInput {
  wave: number;
  at_s: number;
  type: string;
  target_id: string;
  value: number;
  payload: Record<string, unknown>;
}

export interface BuildPlanInput {
  scenario_id: string;
  towers: TowerPlanInput[];
  active_global_modifiers: string[];
  actions: BuildActionInput[];
}

export interface TimelineRequest {
  dataset_version?: string;
  mode: CalcMode;
  seed: number;
  monte_carlo_runs: number;
  build_plan: BuildPlanInput;
}

export interface WaveResult {
  wave: number;
  potential_damage: number;
  combat_damage: number;
  effective_dps: number;
  clear_time_s: number;
  leaks: number;
  enemy_hp_pool: number;
  breakdown: Record<string, number>;
}

export interface TimelineResponse {
  dataset: {
    dataset_version: string;
    game_version: string;
    build_id: string;
  };
  result: {
    mode: CalcMode;
    scenario_id: string;
    dataset_version: string;
    seed: number;
    monte_carlo_runs: number;
    wave_results: WaveResult[];
    totals: {
      potential_damage: number;
      combat_damage: number;
      leaks: number;
    };
  };
}

export interface LiveFieldCoverage {
  required_total: number;
  required_resolved: number;
  optional_total: number;
  optional_resolved: number;
}

export interface LiveFieldResolutionEntry {
  present: boolean;
  resolved: boolean;
  source: string;
  type: string;
  address: string;
  offsets: number[];
  relative_to_module: boolean;
}

export type LiveSnapshotScalar = number | string | boolean | null;

export interface LiveSnapshotRawMemoryFields extends Record<string, unknown> {
  base_hp_current?: LiveSnapshotScalar;
  base_hp_max?: LiveSnapshotScalar;
  leaks_total?: LiveSnapshotScalar;
  enemies_alive?: LiveSnapshotScalar;
  boss_alive?: LiveSnapshotScalar;
  boss_hp_current?: LiveSnapshotScalar;
  boss_hp_max?: LiveSnapshotScalar;
  wave_elapsed_s?: LiveSnapshotScalar;
  wave_remaining_s?: LiveSnapshotScalar;
  barrier_hp_total?: LiveSnapshotScalar;
  enemy_regen_total_per_s?: LiveSnapshotScalar;
  is_combat_phase?: LiveSnapshotScalar;
  wood?: LiveSnapshotScalar;
  stone?: LiveSnapshotScalar;
  wheat?: LiveSnapshotScalar;
  workers_total?: LiveSnapshotScalar;
  workers_free?: LiveSnapshotScalar;
  tower_inflation_index?: LiveSnapshotScalar;
  base_hp?: LiveSnapshotScalar;
  base_health?: LiveSnapshotScalar;
  player_hp?: LiveSnapshotScalar;
  current_hp?: LiveSnapshotScalar;
  leaks?: LiveSnapshotScalar;
  wave_leaks?: LiveSnapshotScalar;
  leak_count?: LiveSnapshotScalar;
  alive_enemies?: LiveSnapshotScalar;
  enemy_alive?: LiveSnapshotScalar;
  boss_hp?: LiveSnapshotScalar;
  boss_health?: LiveSnapshotScalar;
  boss_max_hp?: LiveSnapshotScalar;
  boss_health_max?: LiveSnapshotScalar;
  boss_is_alive?: LiveSnapshotScalar;
  is_boss_alive?: LiveSnapshotScalar;
  boss_active?: LiveSnapshotScalar;
  wave_elapsed?: LiveSnapshotScalar;
  wave_time_elapsed?: LiveSnapshotScalar;
  wave_remaining?: LiveSnapshotScalar;
  wave_time_remaining?: LiveSnapshotScalar;
  barrier_hp?: LiveSnapshotScalar;
  barrier_health?: LiveSnapshotScalar;
  shield_hp?: LiveSnapshotScalar;
  regen_per_s?: LiveSnapshotScalar;
  regen_ps?: LiveSnapshotScalar;
  hp_regen_per_s?: LiveSnapshotScalar;
  combat_phase?: LiveSnapshotScalar;
  in_combat?: LiveSnapshotScalar;
  is_combat?: LiveSnapshotScalar;
  workers?: LiveSnapshotScalar;
  population_total?: LiveSnapshotScalar;
  free_workers?: LiveSnapshotScalar;
  idle_workers?: LiveSnapshotScalar;
  population_free?: LiveSnapshotScalar;
  inflation_index?: LiveSnapshotScalar;
  build_cost_index?: LiveSnapshotScalar;
}

export interface LiveSnapshotBuild {
  towers?: unknown[];
  raw_memory_fields?: LiveSnapshotRawMemoryFields;
  combat?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface LiveSnapshot {
  timestamp: number;
  wave: number;
  gold: number;
  essence: number;
  build: LiveSnapshotBuild;
  source_mode: "memory" | "replay" | "synthetic";
  base_hp_current?: number;
  base_hp_max?: number;
  leaks_total?: number;
  base_hp?: number;
  leaks?: number;
  enemies_alive?: number;
  boss_alive?: boolean;
  boss_hp_current?: number;
  boss_hp_max?: number;
  boss_hp?: number;
  wave_elapsed_s?: number;
  wave_remaining_s?: number;
  barrier_hp_total?: number;
  enemy_regen_total_per_s?: number;
  is_combat_phase?: boolean;
  barrier_hp?: number;
  regen_per_s?: number;
}

export interface LiveStatus {
  status: string;
  mode: string;
  process_name: string;
  poll_ms: number;
  require_admin: boolean;
  dataset_version: string;
  game_build: string;
  signature_profile: string;
  calibration_candidates_path: string;
  calibration_candidate: string;
  reason: string;
  replay_session_id: string;
  memory_connected: boolean;
  required_field_resolution?: Record<string, LiveFieldResolutionEntry>;
  field_coverage?: LiveFieldCoverage;
  calibration_quality?: "minimal" | "partial" | "full" | string;
  active_required_fields?: string[];
  calibration_candidate_ids?: string[];
  last_memory_values?: Record<string, unknown>;
  last_error?: Record<string, string>;
  autoconnect_enabled?: boolean;
  autoconnect_last_attempt_at?: string;
  autoconnect_last_result?: LiveAutoconnectResult;
  dataset_autorefresh?: boolean;
}

export interface LiveConnectRequest {
  process_name: string;
  poll_ms: number;
  require_admin: boolean;
  dataset_version?: string;
  signature_profile_id?: string;
  calibration_candidates_path?: string;
  calibration_candidate_id?: string;
  replay_session_id?: string;
}

export interface LiveAutoconnectRequest {
  process_name?: string;
  poll_ms?: number;
  require_admin?: boolean;
  dataset_version?: string;
  dataset_autorefresh?: boolean;
  signature_profile_id?: string;
  calibration_candidates_path?: string;
  calibration_candidate_id?: string;
  replay_session_id?: string;
}

export interface LiveAutoconnectCandidateSelection {
  selected_candidate_id?: string;
  resolved_candidates_path?: string;
  recommendation_reason?: string;
  [key: string]: unknown;
}

export interface LiveAutoconnectResult {
  ok?: boolean;
  mode?: string;
  reason?: string;
  dataset_version?: string;
  calibration_candidates_path?: string;
  calibration_candidate?: string;
  candidate_selection?: LiveAutoconnectCandidateSelection;
  [key: string]: unknown;
}

export interface LiveCalibrationCandidateQuality {
  valid?: boolean;
  resolved_required_count?: number;
  resolved_optional_count?: number;
  unresolved_required_field_names?: string[];
  [key: string]: unknown;
}

export interface LiveCalibrationCandidateSummary {
  id: string;
  profile_id?: string;
  fields?: Record<string, string>;
  candidate_quality?: LiveCalibrationCandidateQuality;
  [key: string]: unknown;
}

export interface LiveCalibrationRecommendationSupport {
  active_candidate_id?: string;
  recommended_candidate_id?: string;
  reason?: string;
  candidate_scores?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface LiveCalibrationCandidatesResponse {
  path: string;
  active_candidate_id: string;
  recommended_candidate_id?: string;
  recommended_candidate_support?: LiveCalibrationRecommendationSupport;
  candidate_ids: string[];
  candidates?: LiveCalibrationCandidateSummary[];
}

export interface LiveSseEventPayload extends Record<string, unknown> {
  type?: string;
  event?: string;
  topic?: string;
  source?: string;
  reason?: string;
}

export interface LiveSseState {
  connection: "idle" | "connecting" | "open" | "error" | "unsupported";
  lastEventType: string;
  lastEventAt: string;
}
