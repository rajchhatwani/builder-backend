"""Queue advisor: a table of declared requirements -> the recommended queue, with reasons and cautions."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.services.queue_advisor import POSTGRES_THROUGHPUT, QueueRequirements, advise

# (id, requirements, recommended)
ROWS: list[tuple[str, dict[str, Any], str]] = [
    ("defaults", {}, "postgres"),
    ("small_durable", {"throughput_per_sec": 5}, "postgres"),
    ("at_the_postgres_limit", {"throughput_per_sec": 1000}, "postgres"),
    ("delayed_jobs", {"throughput_per_sec": 50, "delayed_jobs": True}, "postgres"),
    ("global_order_low_rate", {"throughput_per_sec": 20, "ordering": "global"}, "postgres"),
    ("per_key_order_low_rate", {"throughput_per_sec": 200, "ordering": "per_key"}, "postgres"),
    ("big_backlog_still_ok", {"throughput_per_sec": 10, "expected_backlog": 5_000_000}, "postgres"),
    ("latency_seconds_fine", {"latency_ms_p99": 2000}, "postgres"),
    ("cross_service_low_rate", {"throughput_per_sec": 50, "cross_service": True}, "postgres"),
    ("best_effort_low_rate", {"throughput_per_sec": 10, "durability": "best_effort"}, "postgres"),
    ("sub_ms_best_effort", {"latency_ms_p99": 1, "durability": "best_effort"}, "redis_celery"),
    ("fast_best_effort", {"throughput_per_sec": 2500, "durability": "best_effort"}, "redis_celery"),
    ("fast_best_effort_ephemeral_latency", {"latency_ms_p99": 5, "throughput_per_sec": 300, "durability": "best_effort"}, "redis_celery"),
    ("sub_20ms_durable", {"latency_ms_p99": 10, "durability": "durable"}, "rabbitmq"),
    ("fast_durable", {"throughput_per_sec": 2500, "durability": "durable"}, "rabbitmq"),
    ("multi_consumer", {"fanout": "multi_consumer"}, "rabbitmq"),
    ("multi_consumer_best_effort", {"fanout": "multi_consumer", "durability": "best_effort"}, "rabbitmq"),
    ("cross_service_busy", {"throughput_per_sec": 500, "cross_service": True}, "rabbitmq"),
    ("replay_multi_consumer", {"fanout": "multi_consumer", "replay_needed": True}, "kafka"),
    ("replay_multi_consumer_low_rate", {"throughput_per_sec": 1, "fanout": "multi_consumer", "replay_needed": True}, "kafka"),
    ("very_high_rate", {"throughput_per_sec": 20_000}, "kafka"),
    ("very_high_rate_best_effort", {"throughput_per_sec": 20_000, "durability": "best_effort"}, "kafka"),
    ("huge_backlog", {"throughput_per_sec": 100, "expected_backlog": 80_000_000}, "kafka"),
    ("per_key_order_busy", {"throughput_per_sec": 3000, "ordering": "per_key"}, "kafka"),
    ("replay_at_rate", {"throughput_per_sec": 800, "replay_needed": True}, "kafka"),
    ("replay_single_consumer_low_rate", {"throughput_per_sec": 20, "replay_needed": True}, "postgres"),
    ("replay_wins_over_latency", {"fanout": "multi_consumer", "replay_needed": True, "latency_ms_p99": 1}, "kafka"),
]


def req(**kw: Any) -> QueueRequirements:
    return QueueRequirements.model_validate(kw)


@pytest.mark.parametrize(("case", "kw", "expected"), ROWS, ids=[r[0] for r in ROWS])
def test_the_advisor_picks_per_declared_need(case: str, kw: dict[str, Any], expected: str) -> None:
    advice = advise(req(**kw))
    assert advice.recommended == expected, (case, advice.reasons)
    assert advice.reasons, "every answer says why"
    assert advice.upgrade_path


def test_there_are_at_least_twenty_rows_and_every_backend_is_reached() -> None:
    assert len(ROWS) >= 20
    assert {r[2] for r in ROWS} == {"postgres", "redis_celery", "rabbitmq", "kafka"}


def test_the_default_is_postgres_with_no_warning() -> None:
    advice = advise(req())
    assert advice.recommended == "postgres"
    assert advice.warnings == []


def test_anything_but_postgres_says_it_is_not_implemented_yet() -> None:
    for kw in ({"latency_ms_p99": 1, "durability": "best_effort"}, {"fanout": "multi_consumer"}, {"throughput_per_sec": 99_999}):
        advice = advise(req(**kw))
        assert any("not available yet" in w for w in advice.warnings), kw


def test_postgres_near_its_limit_warns() -> None:
    advice = advise(req(throughput_per_sec=POSTGRES_THROUGHPUT * 0.9))
    assert advice.recommended == "postgres"
    assert any("close to the comfortable limit" in w for w in advice.warnings)


def test_redis_warns_about_lost_jobs_and_order() -> None:
    advice = advise(req(latency_ms_p99=2, durability="best_effort", ordering="per_key"))
    assert advice.recommended == "redis_celery"
    assert any("lose jobs" in w for w in advice.warnings)
    assert any("order" in w for w in advice.warnings)


def test_kafka_warns_about_delayed_jobs() -> None:
    advice = advise(req(throughput_per_sec=50_000, delayed_jobs=True))
    assert any("delayed" in w for w in advice.warnings)


def test_global_ordering_warns_on_postgres_and_on_brokers() -> None:
    assert any("one worker" in w for w in advise(req(ordering="global")).warnings)
    assert any("one consumer" in w for w in advise(req(ordering="global", fanout="multi_consumer")).warnings)


def test_the_advice_is_deterministic() -> None:
    kw = {"throughput_per_sec": 1500, "durability": "durable", "cross_service": True}
    assert advise(req(**kw)) == advise(req(**kw))


@pytest.mark.parametrize(
    "bad",
    [
        {"throughput_per_sec": -1},
        {"ordering": "sorted"},
        {"fanout": "many"},
        {"durability": "maybe"},
        {"expected_backlog": -5},
        {"latency_ms_p99": -1},
        {"unknown": 1},
        {"replay_needed": "sometimes"},
    ],
)
def test_bad_requirements_are_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        QueueRequirements.model_validate(bad)
