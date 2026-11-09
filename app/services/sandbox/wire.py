"""Wire format between RemoteSandbox (API process) and the narrow runner (P1).

Every model forbids unknown fields. The runner re-validates every value with the same
`_validate`/`build_run_args` the direct DockerSandbox uses; these models only bound sizes and types.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.sandbox.base import Limits, ReapResult, RunResult, SandboxSpec


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


SID = Field(pattern=r"^[a-f0-9]{8,32}$")


class LimitsW(_Strict):
    cpus: float = 0.5
    memory: str = Field(default="512m", max_length=12)
    pids: int = 100
    wall_seconds: int = 30
    tmpfs_size: str = Field(default="64m", max_length=12)
    db_size: str = Field(default="1g", max_length=12)
    ttl_seconds: int = 3600

    def to_limits(self) -> Limits:
        return Limits(**self.model_dump())

    @classmethod
    def of(cls, lim: Limits) -> "LimitsW":
        return cls(**{k: getattr(lim, k) for k in cls.model_fields})


class SpecW(_Strict):
    image: str = Field(max_length=255)
    command: list[str] | None = Field(default=None, max_length=64)
    code_dir: str | None = Field(default=None, max_length=1024)
    env: dict[str, str] = Field(default_factory=dict, max_length=64)
    extra_hosts: dict[str, str] = Field(default_factory=dict, max_length=16)
    tmpfs: dict[str, str] = Field(default_factory=dict, max_length=8)
    network: str | None = Field(default=None, max_length=63)
    network_owner: str | None = Field(default=None, max_length=32)
    tmpfs_uid: int | None = None
    user: str = Field(default="10001:10001", max_length=21)
    limits: LimitsW = Field(default_factory=LimitsW)
    sandbox_id: str = SID

    def to_spec(self) -> SandboxSpec:
        return SandboxSpec(
            image=self.image,
            command=self.command,
            code_dir=Path(self.code_dir) if self.code_dir is not None else None,
            env=dict(self.env),
            extra_hosts=dict(self.extra_hosts),
            tmpfs=dict(self.tmpfs),
            network=self.network,
            network_owner=self.network_owner,
            tmpfs_uid=self.tmpfs_uid,
            user=self.user,
            limits=self.limits.to_limits(),
            sandbox_id=self.sandbox_id,
        )

    @classmethod
    def of(cls, spec: SandboxSpec) -> "SpecW":
        return cls(
            image=spec.image,
            command=spec.command,
            code_dir=str(spec.code_dir) if spec.code_dir is not None else None,
            env=dict(spec.env),
            extra_hosts=dict(spec.extra_hosts),
            tmpfs=dict(spec.tmpfs),
            network=spec.network,
            network_owner=spec.network_owner,
            tmpfs_uid=spec.tmpfs_uid,
            user=spec.user,
            limits=LimitsW.of(spec.limits),
            sandbox_id=spec.sandbox_id,
        )


class Empty(_Strict):
    pass


class SpecReq(_Strict):
    spec: SpecW


class IdReq(_Strict):
    sandbox_id: str = SID


class CreateNetworkReq(_Strict):
    sandbox_id: str = SID
    limits: LimitsW | None = None


class LogsReq(_Strict):
    sandbox_id: str = SID
    tail: int = Field(default=2000, ge=1, le=2000)
    since: str | None = Field(default=None, max_length=64, pattern=r"^[0-9A-Za-z.:+-]+$")


class ExecReq(_Strict):
    sandbox_id: str = SID
    argv: list[str] = Field(min_length=1, max_length=64)
    timeout: float = Field(gt=0, le=3600)


class IpReq(_Strict):
    sandbox_id: str = SID
    network: str = Field(max_length=63)


class ReapReq(_Strict):
    now: float | None = None


def run_result_to_dict(r: RunResult) -> dict[str, Any]:
    return dict(r.__dict__)


def reap_to_dict(r: ReapResult) -> dict[str, Any]:
    return {"containers": r.containers, "networks": r.networks}
