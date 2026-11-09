# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Models and data structures for JetBrains Junie Remote."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class JunieRemoteError(Exception):
    """Base exception for Junie Remote errors."""


class JunieAuthError(JunieRemoteError):
    """Authentication or authorization failure (HTTP 401)."""


class TunnelNotFoundError(JunieRemoteError):
    """Remote tunnel not found or expired (HTTP 404)."""


class TunnelConflictError(JunieRemoteError):
    """Client connection conflict or already connected (HTTP 409)."""


@dataclass
class TunnelMetadata:
    """Metadata describing the remote host running Junie CLI."""

    current_directory: str = ""
    user_name: str = ""
    os_name: str = ""
    created_at: str | None = None
    git_repo_url: str | None = None
    git_branch: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TunnelMetadata:
        """Create TunnelMetadata from a dictionary."""
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            current_directory=str(data.get("currentDirectory") or ""),
            user_name=str(data.get("userName") or ""),
            os_name=str(data.get("osName") or ""),
            created_at=data.get("createdAt"),
            git_repo_url=data.get("gitRepoUrl"),
            git_branch=data.get("gitBranch"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "currentDirectory": self.current_directory,
            "userName": self.user_name,
            "osName": self.os_name,
            "createdAt": self.created_at,
            "gitRepoUrl": self.git_repo_url,
            "gitBranch": self.git_branch,
        }


@dataclass
class TunnelInfo:
    """Information about an active Junie CLI remote tunnel."""

    tunnel_id: str
    connected_clients: int = 0
    metadata: TunnelMetadata = field(default_factory=TunnelMetadata)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TunnelInfo:
        """Create TunnelInfo from a dictionary."""
        meta = data.get("metadata")
        return cls(
            tunnel_id=str(data.get("tunnelId", "")),
            connected_clients=int(data.get("connectedClients", 0)),
            metadata=TunnelMetadata.from_dict(meta if isinstance(meta, dict) else None),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tunnelId": self.tunnel_id,
            "connectedClients": self.connected_clients,
            "metadata": self.metadata.to_dict(),
        }

    def compute_host_key(self) -> str:
        """Produce a deterministic slug from (userName, osName, gitRepoUrl or currentDirectory)."""
        user = (self.metadata.user_name or "user").strip()
        os_name = (self.metadata.os_name or "os").strip()
        location = (
            self.metadata.git_repo_url or self.metadata.current_directory or self.tunnel_id
        ).strip()
        raw = f"{user}_{os_name}_{location}"
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
        return slug or f"tunnel_{self.tunnel_id}"


@dataclass
class ModelOption:
    """Selectable LLM model option."""

    id: str
    name: str
    current_effort_id: str | None = None
    supported_efforts: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelOption:
        """Create ModelOption from a dictionary."""
        efforts = data.get("supportedEfforts", [])
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            current_effort_id=data.get("currentEffortId"),
            supported_efforts=list(efforts) if isinstance(efforts, list) else [],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "currentEffortId": self.current_effort_id,
            "supportedEfforts": self.supported_efforts,
        }


@dataclass
class ModelSelectionState:
    """Current model selection state."""

    current_model_id: str | None = None
    current_effort_id: str | None = None
    models: list[ModelOption] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ModelSelectionState:
        """Create ModelSelectionState from a dictionary."""
        if not data or not isinstance(data, dict):
            return cls()
        models_raw = data.get("models", [])
        models = (
            [ModelOption.from_dict(m) for m in models_raw if isinstance(m, dict)]
            if isinstance(models_raw, list)
            else []
        )
        return cls(
            current_model_id=data.get("currentModelId"),
            current_effort_id=data.get("currentEffortId"),
            models=models,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "currentModelId": self.current_model_id,
            "currentEffortId": self.current_effort_id,
            "models": [m.to_dict() for m in self.models],
        }

    @property
    def current_selection(self) -> str:
        """Return composite selection value 'model_id:effort_id' or 'model_id'."""
        if self.current_model_id and self.current_effort_id:
            return f"{self.current_model_id}:{self.current_effort_id}"
        return self.current_model_id or ""

    def get_selectable_options(self) -> list[tuple[str, str]]:
        """Return list of (value, label) tuples for selectable model options."""
        options: list[tuple[str, str]] = []
        for model in self.models:
            if model.supported_efforts:
                for effort in model.supported_efforts:
                    effort_id = effort.get("id", "")
                    effort_name = effort.get("name", effort_id)
                    val = f"{model.id}:{effort_id}"
                    label = f"{model.name} · {effort_name}"
                    options.append((val, label))
            else:
                options.append((model.id, model.name))
        return options


@dataclass
class PlanProposal:
    """Proposed plan generated by Junie."""

    seq: int = 0
    ready_for_review: bool = False
    show_actions: bool = False
    plan_file_path: str | None = None
    sections: list[dict[str, Any]] = field(default_factory=list)
    delivery_steps: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanProposal:
        """Create PlanProposal from a dictionary."""
        sections = data.get("sections", [])
        delivery_steps = data.get("deliverySteps", [])
        return cls(
            seq=int(data.get("seq", 0)),
            ready_for_review=bool(data.get("readyForReview", False)),
            show_actions=bool(data.get("showActions", False)),
            plan_file_path=data.get("planFilePath"),
            sections=list(sections) if isinstance(sections, list) else [],
            delivery_steps=list(delivery_steps) if isinstance(delivery_steps, list) else [],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "seq": self.seq,
            "readyForReview": self.ready_for_review,
            "showActions": self.show_actions,
            "planFilePath": self.plan_file_path,
            "sections": self.sections,
            "deliverySteps": self.delivery_steps,
        }


@dataclass
class ChatSessionState:
    """State reducer for an active Junie CLI remote session."""

    title: str = ""
    git_branch: str = ""
    working_dir: str = ""
    session_status: str = "idle"
    can_send_prompt: bool = True
    brave_mode: bool = False
    has_plan: bool = False
    last_status_seq: int = 0
    last_reset_seq: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    progressing_steps: list[dict[str, Any]] = field(default_factory=list)
    active_requests: list[dict[str, Any]] = field(default_factory=list)
    plan_proposal: PlanProposal | None = None
    model_selection: ModelSelectionState = field(default_factory=ModelSelectionState)

    def apply_event(self, event: dict[str, Any]) -> None:
        """Apply an incoming WebSocket event to update session state."""
        event_type = event.get("type")
        if not event_type:
            return

        if event_type == "ready-step":
            step = event.get("step")
            if step and isinstance(step, dict):
                self.history.append(step)

        elif event_type == "progressing-steps":
            steps = event.get("steps")
            self.progressing_steps = list(steps) if isinstance(steps, list) else []

        elif event_type == "active-requests":
            requests = event.get("requests")
            self.active_requests = list(requests) if isinstance(requests, list) else []

        elif event_type == "session-status":
            if "status" in event:
                self.session_status = str(event["status"])
            if "canSendPrompt" in event:
                self.can_send_prompt = bool(event["canSendPrompt"])
            if "braveMode" in event:
                self.brave_mode = bool(event["braveMode"])
            has_plan = bool(event.get("hasPlan", False))
            self.has_plan = has_plan
            seq = int(event.get("seq", 0))
            self.last_status_seq = seq
            if not has_plan:
                self.last_reset_seq = seq
                if self.plan_proposal is not None and self.plan_proposal.seq < seq:
                    self.plan_proposal = None

        elif event_type == "plan-proposal":
            seq = int(event.get("seq", 0))
            if seq >= self.last_reset_seq:
                self.plan_proposal = PlanProposal.from_dict(event)

        elif event_type == "brave-mode-state":
            if "enabled" in event:
                self.brave_mode = bool(event["enabled"])

        elif event_type == "model-selection-state":
            self.model_selection = ModelSelectionState.from_dict(event)

        elif event_type == "session-metadata":
            if "title" in event and event["title"] is not None:
                self.title = str(event["title"])
            if "gitBranch" in event and event["gitBranch"] is not None:
                self.git_branch = str(event["gitBranch"])
            if "workingDir" in event and event["workingDir"] is not None:
                self.working_dir = str(event["workingDir"])

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            "title": self.title,
            "gitBranch": self.git_branch,
            "workingDir": self.working_dir,
            "sessionStatus": self.session_status,
            "canSendPrompt": self.can_send_prompt,
            "braveMode": self.brave_mode,
            "hasPlan": self.has_plan,
            "lastStatusSeq": self.last_status_seq,
            "lastResetSeq": self.last_reset_seq,
            "history": self.history,
            "progressingSteps": self.progressing_steps,
            "activeRequests": self.active_requests,
            "planProposal": self.plan_proposal.to_dict() if self.plan_proposal else None,
            "modelSelection": self.model_selection.to_dict(),
        }
