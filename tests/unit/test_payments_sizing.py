"""The sizing function behind the generated deployment files (estimates, see its docstring)."""

import pytest

from app.core.payments_sizing import (
    CONNECTION_BUDGET_SHARE,
    MIN_POOL_SIZE,
    PROFILE_PAYMENTS_PER_MINUTE,
    size,
)
from app.core.spec_models import SpecPaymentsScale


def scale(**kwargs: object) -> SpecPaymentsScale:
    return SpecPaymentsScale.model_validate(kwargs)


def test_profiles_fill_the_numbers_left_empty() -> None:
    for profile, expected in PROFILE_PAYMENTS_PER_MINUTE.items():
        sizing = size(scale(profile=profile))
        assert sizing.payments_per_minute == expected
        assert sizing.webhooks_per_minute == expected * 5


def test_explicit_numbers_beat_the_profile() -> None:
    sizing = size(scale(profile="large", peak_payments_per_minute=7, peak_webhooks_per_minute=9))
    assert (sizing.payments_per_minute, sizing.webhooks_per_minute) == (7, 9)


def test_a_small_project_is_one_of_everything_and_inline() -> None:
    sizing = size(scale())
    assert (sizing.api_replicas, sizing.worker_replicas) == (1, 1)
    assert sizing.webhook_mode == "inline"
    assert sizing.needs_pgbouncer is False
    assert sizing.warnings == ()


def test_high_availability_never_leaves_a_single_process() -> None:
    sizing = size(scale(availability="ha"))
    assert sizing.api_replicas >= 2
    assert sizing.worker_replicas >= 2
    assert any("separate machines" in w for w in sizing.warnings)


def test_a_busy_project_queues_webhooks_and_scales_out() -> None:
    sizing = size(scale(profile="large"))
    assert sizing.webhook_mode == "queued"
    assert sizing.api_replicas * sizing.server_workers > 1
    assert sizing.worker_replicas >= 1
    assert sizing.poll_interval_seconds < 1.0


def test_the_webhook_mode_can_be_forced() -> None:
    assert size(scale(profile="large", webhook_mode="inline")).worker_replicas == 1
    assert size(scale(webhook_mode="queued")).webhook_mode == "queued"


def test_overrides_win_over_computed_values() -> None:
    sizing = size(
        scale(
            api_replicas=3,
            server_workers=2,
            worker_replicas=4,
            worker_concurrency=16,
            pool_size=3,
        )
    )
    assert (sizing.api_replicas, sizing.server_workers) == (3, 2)
    assert (sizing.worker_replicas, sizing.worker_concurrency) == (4, 16)
    assert sizing.pool_size == 3
    assert sizing.worker_pool_size == 18


@pytest.mark.parametrize("profile", ["small", "medium", "large"])
@pytest.mark.parametrize("availability", ["single", "ha"])
@pytest.mark.parametrize("max_connections", [50, 100, 500, 5000])
def test_the_database_connection_budget_is_respected_or_reported(
    profile: str, availability: str, max_connections: int
) -> None:
    sizing = size(
        scale(profile=profile, availability=availability, db_max_connections=max_connections)
    )
    assert sizing.connection_budget == int(max_connections * CONNECTION_BUDGET_SHARE)
    # Either it fits, or the sizing says so and asks for a pooler: never silently over budget.
    assert sizing.total_db_connections <= sizing.connection_budget or sizing.needs_pgbouncer
    if sizing.needs_pgbouncer:
        assert any("PgBouncer" in w for w in sizing.warnings)


def test_pools_shrink_before_a_pooler_is_demanded() -> None:
    # high availability: 2 api processes x (5+2) = 14, 2 workers x 10 = 20, 6 overhead = 40, which
    # is over 80 percent of 45 (=36); with pools of 2 it is 4 + 20 + 6 = 30 and fits.
    sizing = size(scale(availability="ha", db_max_connections=45))
    assert sizing.needs_pgbouncer is False
    assert sizing.pool_size == MIN_POOL_SIZE
    assert sizing.total_db_connections <= sizing.connection_budget
    assert any("reduced" in w for w in sizing.warnings)


def test_an_unfittable_plan_asks_for_pgbouncer_and_pgbouncer_fixes_it() -> None:
    crowded = scale(profile="large", availability="ha", db_max_connections=40)
    assert size(crowded).needs_pgbouncer is True

    pooled = size(crowded.model_copy(update={"pgbouncer": True}))
    assert pooled.needs_pgbouncer is False
    assert pooled.pgbouncer_pool_size is not None
    assert pooled.total_db_connections <= pooled.connection_budget


def test_more_load_never_needs_fewer_processes() -> None:
    previous = (0, 0)
    for payments in (1, 10, 100, 1000, 10_000, 100_000):
        sizing = size(scale(peak_payments_per_minute=payments, db_max_connections=100_000))
        current = (sizing.api_replicas * sizing.server_workers, sizing.worker_replicas)
        assert current[0] >= previous[0] and current[1] >= previous[1]
        previous = current


def test_a_load_beyond_a_postgres_queue_is_flagged() -> None:
    sizing = size(scale(peak_payments_per_minute=1_000_000, db_max_connections=100_000))
    assert any("message broker" in w for w in sizing.warnings)


def test_the_output_is_deterministic_and_serialisable() -> None:
    first, second = size(scale(profile="medium")), size(scale(profile="medium"))
    assert first == second
    assert first.to_dict()["assumptions"]
