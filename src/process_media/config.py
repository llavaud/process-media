"""Configuration models and YAML loader.

Two YAML layouts are accepted:

* **Single-document** (recommended) with explicit ``global:`` and
  ``formats:`` top-level keys.
* **Multi-document** where the first YAML document holds the global
  options and the second holds the formats dictionary.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Rotate = Literal["auto", "90", "180", "270"]
Vcodec = Literal["x264", "x265"]
StripExcludeItem = Literal["gps", "orientation"]


_OUTPUT_DIR_RE = re.compile(r"^[\w\-/.]+$")


class GlobalOptions(BaseModel):
    """Tool-wide options."""

    model_config = ConfigDict(extra="forbid")

    max_threads: int = Field(default=0, ge=0)
    verbose: bool = False
    keep_name: bool = False
    overwrite: bool = False
    tzoffset: int = 0


class FormatSpec(BaseModel):
    """One output flavour (e.g. ``web_photo``).

    Pydantic validates every field and raises clean ``ValidationError``
    messages for invalid configurations.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["photo", "video"]
    rotate: Rotate = "auto"
    resize: int | None = Field(default=None, gt=0)
    compress: int | None = Field(default=None, ge=0, le=100)
    progressive: bool = False
    strip: bool = False
    strip_exclude: list[StripExcludeItem] = Field(default_factory=list)
    vcodec: Vcodec | None = None
    vcodec_params: str | None = None
    reencode: bool = False
    thumbnail: bool = False
    output_dir: str | None = None

    @field_validator("rotate", mode="before")
    @classmethod
    def _coerce_rotate(cls, v: Any) -> Any:
        # YAML may parse 90/180/270 as int.
        if isinstance(v, int):
            return str(v)
        return v

    @field_validator("strip_exclude", mode="before")
    @classmethod
    def _split_strip_exclude(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("output_dir")
    @classmethod
    def _check_output_dir(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _OUTPUT_DIR_RE.match(v):
            raise ValueError(f"output_dir contains invalid characters: {v!r}")
        # Refuse path traversal: any `..` component is rejected even if the
        # regex would have allowed it (writing outside the source tree is
        # almost never intended and easy to do by accident).
        parts = Path(v).parts
        if ".." in parts:
            raise ValueError(f"output_dir must not contain '..': {v!r}")
        return v

    @field_validator("vcodec_params")
    @classmethod
    def _check_vcodec_params(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Real-world x264/x265 params commonly include ``-``, ``.`` and
        # ``,`` (e.g. ``bframes=3:b-adapt=2``, ``qcomp=0.6``). Whitespace
        # and shell metacharacters remain forbidden — the command is
        # passed as a list to ``subprocess`` so no shell injection is
        # possible regardless, but rejecting them upfront keeps misuse
        # obvious.
        if not re.match(r"^[\w:=,.\-]+$", v):
            raise ValueError(f"vcodec_params has invalid characters: {v!r}")
        return v

    @model_validator(mode="after")
    def _check_video_only_options(self) -> FormatSpec:
        # Use ``is`` comparisons explicitly: ``0 in (None, False)`` is True
        # because ``0 == False`` in Python, which would let ``compress: 0``
        # slip through on a video format.
        if self.type == "photo":
            if self.reencode:
                raise ValueError("option 'reencode' is not valid for type=photo")
            if self.thumbnail:
                raise ValueError("option 'thumbnail' is not valid for type=photo")
            if self.vcodec is not None:
                raise ValueError("option 'vcodec' is not valid for type=photo")
            if self.vcodec_params is not None:
                raise ValueError("option 'vcodec_params' is not valid for type=photo")
        else:  # video
            if self.progressive:
                raise ValueError("option 'progressive' is not valid for type=video")
            if self.compress is not None:
                raise ValueError("option 'compress' is not valid for type=video")
        return self


class Config(BaseModel):
    """Full configuration: global options + named formats."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    global_options: GlobalOptions = Field(default_factory=GlobalOptions, alias="global")
    formats: dict[str, FormatSpec] = Field(default_factory=dict)


def _load_yaml_documents(text: str) -> list[Any]:
    """Parse a YAML stream returning the list of documents (filter Nones)."""
    return [doc for doc in yaml.safe_load_all(text) if doc is not None]


def _looks_like_new_layout(doc: Any) -> bool:
    return isinstance(doc, dict) and ("global" in doc or "formats" in doc)


def load_config(
    path: str | Path | None = None,
    *,
    source_path: str | Path | None = None,
) -> Config:
    """Load configuration and return it.

    See :func:`resolve_and_load_config` for the search order; this thin
    wrapper exists for the common case where the caller doesn't care
    which file was actually used.
    """
    cfg, _ = resolve_and_load_config(path, source_path=source_path)
    return cfg


def resolve_and_load_config(
    path: str | Path | None = None,
    *,
    source_path: str | Path | None = None,
) -> tuple[Config, Path]:
    """Load configuration and return ``(Config, source_file)``.

    Search order (first hit wins):

    1. Explicit ``path`` argument (typically from ``--config``).
    2. ``$PROCESS_MEDIA_CONFIG`` environment variable.
    3. ``<source_path>/process-media.yaml`` — when ``source_path`` is a
       directory, or its parent when ``source_path`` is a file. This lets
       users drop a config alongside their media without thinking about
       the current working directory.
    4. ``./process-media.yaml`` (current working directory).
    5. ``/etc/process-media.yaml``.

    Raises:
        FileNotFoundError: if no configuration file can be located.
        pydantic.ValidationError: on malformed content.
    """
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    else:
        env_path = os.environ.get("PROCESS_MEDIA_CONFIG")
        if env_path:
            candidates.append(Path(env_path))
        if source_path is not None:
            sp = Path(source_path)
            base = sp if sp.is_dir() else sp.parent
            candidates.append(base / "process-media.yaml")
        candidates.append(Path.cwd() / "process-media.yaml")
        candidates.append(Path("/etc/process-media.yaml"))

    for candidate in candidates:
        if candidate.is_file():
            return _parse_config_text(candidate.read_text(encoding="utf-8")), candidate

    raise FileNotFoundError(
        "No configuration file found. Tried: " + ", ".join(str(c) for c in candidates)
    )


def _parse_config_text(text: str) -> Config:
    docs = _load_yaml_documents(text)
    if not docs:
        raise ValueError("Configuration file is empty.")

    if len(docs) == 1 and _looks_like_new_layout(docs[0]):
        # Validate the document as-is so ``Config(extra=forbid)`` catches
        # typos like ``globals:`` instead of ``global:`` at the root level.
        return Config.model_validate(docs[0])

    if len(docs) == 1:
        # Single dict containing only formats.
        return Config.model_validate({"global": {}, "formats": docs[0]})

    # Legacy multi-doc layout: first = globals, remainder = formats merged.
    globals_doc = docs[0] if isinstance(docs[0], dict) else {}
    formats: dict[str, Any] = {}
    for doc in docs[1:]:
        if isinstance(doc, dict):
            formats.update(doc)
    return Config.model_validate({"global": globals_doc, "formats": formats})
