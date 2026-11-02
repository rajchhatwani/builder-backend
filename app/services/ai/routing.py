"""Small/large model routing by task class."""

from app.config import Settings
from app.services.ai.base import TaskClass

SMALL_TASKS = frozenset({TaskClass.route, TaskClass.classify, TaskClass.summarize})


def route_model(task_class: TaskClass, settings: Settings) -> str:
    """Routing, classification and summaries go to the small model; planning, code, repair and
    verification go to the large one. Unknown classes are not possible (enum)."""
    return settings.ai_small_model if task_class in SMALL_TASKS else settings.ai_large_model
