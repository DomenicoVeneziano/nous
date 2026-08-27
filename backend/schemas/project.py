# backend/schemas/project.py
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from typing import Literal


# A scope entry can be a CIDR, and each expands into one asset per address, so
# an unbounded entry list is an unbounded amount of work. The count is capped
# here — a 422 before anything is parsed — and the addresses they expand to are
# capped separately by asset_service.MAX_CIDR_HOSTS_TOTAL.
MAX_SCOPE_ENTRIES = 1000

# Recurring-schedule vocabulary. SCAN_PHASES is also the canonical run order: a
# cycle enqueues recon before tech before crawl, because each phase consumes what
# the previous one discovered.
SCHEDULE_UNITS = ("hours", "days", "weeks", "months")
SCAN_PHASES = ("recon", "tech", "crawl")
# An interval is a multiplier on a unit, so the cap only has to keep the product
# inside a sane horizon; without it "1000000 weeks" is an accepted schedule.
MAX_INTERVAL_VALUE = 1000


def _canonical_phases(phases: list[str] | None) -> list[str] | None:
    """De-duplicate and re-order a phase list into recon -> tech -> crawl.

    Normalizing on the way in means the stored list has one spelling, so a
    schedule edit that only reshuffles the UI's checkboxes is not mistaken for a
    real change further down.
    """
    if phases is None:
        return None
    seen = set(phases)
    return [p for p in SCAN_PHASES if p in seen]


def _validate_schedule(model, enforce_complete: bool):
    """Shared schedule normalization for create and update.

    `enforce_complete` is the caller's answer to "is this payload turning the
    schedule on?" — only then can the schema tell that the interval and phases
    are required. An update that leaves an already-enabled project enabled says
    nothing about schedule_enabled, so that case is enforced in project_service,
    which can see the stored row.
    """
    # Only rewrite a field the payload actually carried: assigning here would
    # otherwise add it to model_fields_set, and update_project's exclude_unset
    # dump would start treating an untouched schedule as an edit that clears it.
    if "schedule_phases" in model.model_fields_set:
        model.schedule_phases = _canonical_phases(model.schedule_phases)
    if enforce_complete:
        if model.schedule_interval_value is None or model.schedule_interval_unit is None:
            raise ValueError(
                "schedule_interval_value and schedule_interval_unit are required "
                "when schedule_enabled is true"
            )
        if not model.schedule_phases:
            raise ValueError(
                "schedule_phases must name at least one phase when "
                "schedule_enabled is true"
            )
    return model


class ProjectCreate(BaseModel):
    title: str
    description: str | None = None
    root_domains: list[str] = Field(max_length=MAX_SCOPE_ENTRIES)
    subdomains: list[str] = []
    schedule_enabled: bool = False
    schedule_interval_value: int | None = Field(default=None, ge=1, le=MAX_INTERVAL_VALUE)
    schedule_interval_unit: Literal["hours", "days", "weeks", "months"] | None = None
    schedule_phases: list[Literal["recon", "tech", "crawl"]] | None = Field(
        default=None, max_length=3
    )

    @model_validator(mode="after")
    def _check_schedule(self):
        return _validate_schedule(self, self.schedule_enabled)


class ProjectUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    root_domains: list[str] | None = Field(default=None, max_length=MAX_SCOPE_ENTRIES)
    subdomains: list[str] | None = None
    status: str | None = None
    schedule_enabled: bool | None = None
    schedule_interval_value: int | None = Field(default=None, ge=1, le=MAX_INTERVAL_VALUE)
    schedule_interval_unit: Literal["hours", "days", "weeks", "months"] | None = None
    schedule_phases: list[Literal["recon", "tech", "crawl"]] | None = Field(
        default=None, max_length=3
    )

    @model_validator(mode="after")
    def _check_schedule(self):
        turning_on = "schedule_enabled" in self.model_fields_set and self.schedule_enabled
        return _validate_schedule(self, bool(turning_on))


class ProjectOut(BaseModel):
    id: str
    title: str
    description: str | None
    icon: str | None
    logo_path: str | None
    root_domains: list[str]
    subdomains: list[str]
    status: str
    last_scan_date: datetime | None
    last_scan_duration_s: float | None
    asset_count: int
    tech_count: int
    is_master: bool
    schedule_enabled: bool
    schedule_interval_value: int | None
    schedule_interval_unit: str | None
    schedule_phases: list[str] | None
    next_scan_at: datetime | None
    schedule_last_run_at: datetime | None
    schedule_cycle_active: bool

    model_config = {"from_attributes": True}


class BulkProjectAction(BaseModel):
    project_ids: list[str]
