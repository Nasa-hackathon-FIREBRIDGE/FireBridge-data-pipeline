from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

UTC = timezone.utc


def now():
    return datetime.now(UTC)


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time(), UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def uid(value):
    return uuid5(NAMESPACE_URL, "firebridge:" + str(value))


def days(start, end):
    current = utc(start)
    end = utc(end)
    if current >= end or current.time().isoformat() != "00:00:00" or end.time().isoformat() != "00:00:00":
        raise ValueError("Use UTC midnight bounds with start < end_exclusive")
    while current < end:
        yield current
        current += timedelta(days=1)
