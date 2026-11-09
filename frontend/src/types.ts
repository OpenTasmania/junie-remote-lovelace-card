// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

/**
 * Type definitions for JetBrains Junie Remote Lovelace Card.
 */

export interface ModelOption {
  value: string;
  label: string;
  id?: string;
  name?: string;
}

export interface PlanSummary {
  ready_for_review?: boolean;
  readyForReview?: boolean;
  show_actions?: boolean;
  showActions?: boolean;
  plan_file_path?: string | null;
  planFilePath?: string | null;
  section_names?: string[];
  sections?: PlanSection[];
  delivery_steps?: any[];
  deliverySteps?: any[];
}

export interface ActiveRequestOption {
  id?: string;
  label?: string;
  title?: string;
  name?: string;
  description?: string;
  type?: string;
  optionIndex?: number;
}

export interface ActiveRequest {
  id?: string;
  requestId?: string;
  type: "ask" | "choice" | "approve" | "action" | "ask-async" | string;
  question?: string;
  title?: string;
  prompt?: string;
  message?: string;
  name?: string;
  allowMultiple?: boolean;
  allow_multiple?: boolean;
  options?: ActiveRequestOption[];
  defaultValue?: string;
  [key: string]: any;
}

export interface JunieRemoteAttributes {
  host_key?: string;
  tunnel_id?: string;
  user_name?: string;
  os_name?: string;
  git_repo?: string;
  git_branch?: string;
  working_dir?: string;
  title?: string;
  connection_status?: string;
  session_status?: string;
  can_send_prompt?: boolean;
  brave_mode?: boolean;
  has_plan?: boolean;
  connected_clients?: number;
  last_error?: string | null;
  current_model_id?: string | null;
  current_effort_id?: string | null;
  selected_model_effort?: string | null;
  model_options?: ModelOption[];
  active_requests?: ActiveRequest[];
  plan_summary?: PlanSummary | null;
  progressing_steps_count?: number;
  last_step_preview?: string;
  transcript_json_url?: string | null;
  transcript_md_url?: string | null;
  transcript_updated_at?: string | null;
  [key: string]: any;
}

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: JunieRemoteAttributes & Record<string, any>;
  last_changed: string;
  last_updated: string;
  context?: {
    id: string;
    parent_id?: string | null;
    user_id?: string | null;
  };
}

export interface HomeAssistant {
  states: Record<string, HassEntity>;
  callService(
    domain: string,
    service: string,
    serviceData?: Record<string, any>
  ): Promise<any>;
  fetchWithAuth?(path: string, init?: Record<string, any>): Promise<Response>;
  callWS?(message: Record<string, any>): Promise<any>;
  language?: string;
  selectedTheme?: string | null;
  themes?: Record<string, any>;
  [key: string]: any;
}

export interface JunieRemoteCardConfig {
  type: string;
  entity: string;
  title?: string;
  max_height?: string;
  [key: string]: any;
}

export interface FileChangeSummary {
  path?: string;
  file?: string;
  action?: "modified" | "created" | "deleted" | "renamed" | string;
  added?: number;
  deleted?: number;
  [key: string]: any;
}

export interface StepVm {
  type?: "result" | "step" | string;
  status?: "success" | "error" | "cancelled" | string;
  name?: string;
  title?: string;
  description?: string;
  text?: string;
  result?: string;
  errorCode?: string | null;
  cancelled?: boolean;
  changesSummary?: Array<FileChangeSummary | string>;
  [key: string]: any;
}

export interface BaseStepItem {
  type: string;
  [key: string]: any;
}

export interface UserPromptStepItem extends BaseStepItem {
  type: "user-prompt";
  prompt?: string;
  text?: string;
  timestamp?: string;
}

export interface UserResponseStepItem extends BaseStepItem {
  type: "user-response";
  prompt?: string;
  displayText?: string;
  text?: string;
  timestamp?: string;
}

export interface TaskStepItem extends BaseStepItem {
  type: "step";
  vm?: StepVm;
  name?: string;
  title?: string;
  text?: string;
  result?: string;
  status?: string;
  changesSummary?: Array<FileChangeSummary | string>;
  timestamp?: string;
}

export interface SystemMessageStepItem extends BaseStepItem {
  type: "system-message";
  text?: string;
  message?: string;
  details?: string;
  level?: "info" | "error" | "warning";
  timestamp?: string;
}

export interface SkillsStatusStepItem extends BaseStepItem {
  type: "skills-status";
  status?: string;
  text?: string;
  newSkills?: string[];
  failedSkills?: Array<string | Record<string, any>>;
  timestamp?: string;
}

export type ReadyStepItem =
  | UserPromptStepItem
  | UserResponseStepItem
  | TaskStepItem
  | SystemMessageStepItem
  | SkillsStatusStepItem
  | (BaseStepItem & Record<string, any>);

export interface ProgressingStep {
  type?: string;
  name?: string;
  title?: string;
  description?: string;
  text?: string;
  [key: string]: any;
}

export interface PlanSection {
  name?: string;
  title?: string;
  description?: string;
  content?: string;
  tasks?: any[];
  subtasks?: any[];
  [key: string]: any;
}

export interface PlanProposal {
  ready_for_review?: boolean;
  readyForReview?: boolean;
  show_actions?: boolean;
  showActions?: boolean;
  plan_file_path?: string | null;
  planFilePath?: string | null;
  sections?: PlanSection[];
  section_names?: string[];
  delivery_steps?: any[];
  deliverySteps?: any[];
  [key: string]: any;
}

export interface TranscriptMetadata {
  title?: string;
  git_repo?: string;
  git_branch?: string;
  working_dir?: string;
  user_name?: string;
  os_name?: string;
  [key: string]: any;
}

export interface TranscriptDocument {
  host_key: string;
  tunnel_id: string;
  updated_at: string;
  connection_status: string;
  metadata: TranscriptMetadata;
  session_status: string;
  can_send_prompt: boolean;
  brave_mode: boolean;
  has_plan: boolean;
  model_selection: {
    current_model_id?: string | null;
    current_effort_id?: string | null;
    options: ModelOption[];
  };
  history: ReadyStepItem[];
  progressing_steps: ProgressingStep[];
  plan_proposal: PlanProposal | null;
  active_requests: ActiveRequest[];
}
