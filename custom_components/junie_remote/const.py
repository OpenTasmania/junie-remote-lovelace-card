# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Constants for the JetBrains Junie Remote integration."""

from typing import Final

DOMAIN: Final = "junie_remote"

# API & Gateway URLs
BASE_URL: Final = "https://junie.jetbrains.com"
API_BASE_PATH: Final = "/api/public"

# Configuration options & keys
CONF_COOKIE_HEADER: Final = "cookie_header"
CONF_STORAGE_STATE: Final = "storage_state"
CONF_STORAGE_TYPE: Final = "storage_type"
CONF_LOCAL_STORAGE_PATH: Final = "local_storage_path"
CONF_S3_ENDPOINT: Final = "s3_endpoint"
CONF_S3_BUCKET: Final = "s3_bucket"
CONF_S3_ACCESS_KEY: Final = "s3_access_key"
CONF_S3_SECRET_KEY: Final = "s3_secret_key"
CONF_S3_REGION: Final = "s3_region"
CONF_S3_PUBLIC_URL_BASE: Final = "s3_public_url_base"

# Storage types & defaults
STORAGE_TYPE_LOCAL: Final = "local"
STORAGE_TYPE_S3: Final = "s3"
DEFAULT_STORAGE_TYPE: Final = STORAGE_TYPE_LOCAL
DEFAULT_LOCAL_STORAGE_PATH: Final = "junie_remote/transcripts"
DEFAULT_POLL_INTERVAL: Final = 10  # Seconds

# Integration service names
SERVICE_SEND_PROMPT: Final = "send_prompt"
SERVICE_SEND_PLAN_PROMPT: Final = "send_plan_prompt"
SERVICE_CONFIRM_PLAN: Final = "confirm_plan"
SERVICE_CANCEL_TASK: Final = "cancel_task"
SERVICE_CANCEL: Final = "cancel"
SERVICE_TOGGLE_BRAVE_MODE: Final = "toggle_brave_mode"
SERVICE_SELECT_MODEL: Final = "select_model"
SERVICE_RESPOND: Final = "respond"
SERVICE_RESPOND_REQUEST: Final = "respond_request"
SERVICE_KICK_CLIENT: Final = "kick_client"
SERVICE_CLEANUP_TRANSCRIPTS: Final = "cleanup_transcripts"
SERVICE_RESUME_TRANSCRIPTS: Final = "resume_transcripts"
