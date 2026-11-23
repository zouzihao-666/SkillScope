"""Secrets stay in host memory and never enter container arguments or run records."""

import os
import shutil
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, SecretStr


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    api_key: SecretStr
    base_url: str = "https://api.deepseek.com"
    docker: str = "docker"


def local_values(env_file: Path = Path(".env")) -> dict:
    return {**dotenv_values(env_file, encoding="utf-8-sig"), **os.environ}


def find_docker(value: str | None = None) -> str:
    value = value or local_values().get("SKILLSCOPE_DOCKER") or "docker"
    found = shutil.which(value)
    if found:
        return found
    raise ValueError(
        "Docker CLI not found; set SKILLSCOPE_DOCKER or pass --docker with its full path"
    )


def load_settings(env_file: Path = Path(".env"), docker: str | None = None) -> Settings:
    values = local_values(env_file)
    key = (values.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise ValueError("Missing DEEPSEEK_API_KEY; configure it locally in .env")
    base_url = (values.get("SKILLSCOPE_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    if base_url not in ("https://api.deepseek.com", "https://api.deepseek.com/v1"):
        raise ValueError("This milestone only sends credentials to the official DeepSeek HTTPS API")
    if values.get("SKILLSCOPE_THINKING", "disabled") != "disabled":
        raise ValueError("This milestone fixes thinking=disabled")
    executable = docker or values.get("SKILLSCOPE_DOCKER") or "docker"
    return Settings(api_key=key, base_url=base_url, docker=find_docker(executable))
