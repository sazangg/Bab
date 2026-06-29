def status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def outcome_for_status(status_code: int) -> str:
    if status_code < 400:
        return "succeeded"
    if status_code < 500:
        return "denied"
    return "failed"


def safe_path(path: str) -> str:
    return path
