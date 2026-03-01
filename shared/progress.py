STAGE_PROGRESS_FRACTIONS = {
    "pending": 0.1,
    "running": 0.6,
    "succeeded": 1.0,
    "failed": 1.0,
    "retrying": 0.6,
    "canceled": 1.0,
}


def stage_progress_percent(status: str | None) -> int:
    if not status:
        return 0
    return int(STAGE_PROGRESS_FRACTIONS.get(status, 0) * 100)


def progress_percent_for_stages(statuses: list[str | None]) -> int:
    if not statuses:
        return 0

    total = sum(STAGE_PROGRESS_FRACTIONS.get(status, 0) for status in statuses)
    return int(total / len(statuses) * 100)
