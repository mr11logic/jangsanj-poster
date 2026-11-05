"""Date utilities: format English (Gregorian) and Persian (Jalali) dates.

Used by the poster generator to render the date line at the top of the big
red box. Both formatters accept either an ISO date string (YYYY-MM-DD) or a
`datetime.date` / `datetime.datetime` instance. If nothing is passed, today's
date (in Asia/Tehran) is used.
"""
from __future__ import annotations

import datetime as dt
from typing import Union

import jdatetime

# Persian weekday names — note: in the Jalali calendar the week starts on
# Saturday (شنبه). jdatetime already maps weekday() correctly.
PERSIAN_WEEKDAYS = [
    "شنبه",       # Saturday  (jd.weekday() == 0)
    "یکشنبه",     # Sunday    (jd.weekday() == 1)
    "دوشنبه",     # Monday    (jd.weekday() == 2)
    "سه‌شنبه",     # Tuesday   (jd.weekday() == 3)
    "چهارشنبه",   # Wednesday (jd.weekday() == 4)
    "پنجشنبه",    # Thursday  (jd.weekday() == 5)
    "جمعه",       # Friday    (jd.weekday() == 6)
]

# Persian month names (Jalali calendar)
PERSIAN_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

# English weekday names — Python's weekday(): Monday=0 .. Sunday=6
ENGLISH_WEEKDAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]

# English month names — Python: January=1 .. December=12
ENGLISH_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Persian digits lookup
PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def to_persian_digits(text: str) -> str:
    """Replace ASCII digits 0-9 with Persian digits ۰-۹."""
    translation = str.maketrans("0123456789", PERSIAN_DIGITS)
    return text.translate(translation)


DateLike = Union[str, dt.date, dt.datetime, None]


def _coerce_date(value: DateLike) -> dt.date:
    """Accept ISO string, date, datetime, or None (=today)."""
    if value is None:
        # Use Asia/Tehran "today" to be safe around midnight UTC.
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=3, minutes=30))).date()
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        # Accept "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
        return dt.date.fromisoformat(value[:10])
    raise TypeError(f"Unsupported date type: {type(value).__name__}")


def format_english_date(value: DateLike = None) -> str:
    """Return e.g. 'November 01, 2026'."""
    d = _coerce_date(value)
    return f"{ENGLISH_MONTHS[d.month - 1]} {d.day:02d}, {d.year}"


def format_persian_date(value: DateLike = None,
                        include_weekday: bool = True) -> str:
    """Return e.g. 'یکشنبه ۱۰ آبان ۱۴۰۵' (with Persian digits).

    The weekday name comes first, then day, month, year — matching the layout
    seen on the JangSanj sample poster.
    """
    d = _coerce_date(value)
    jd = jdatetime.date.fromgregorian(date=d)
    parts = []
    if include_weekday:
        parts.append(PERSIAN_WEEKDAYS[jd.weekday()])
    parts.append(str(jd.day))
    parts.append(PERSIAN_MONTHS[jd.month - 1])
    parts.append(str(jd.year))
    joined = " ".join(parts)
    return to_persian_digits(joined)


if __name__ == "__main__":
    # Quick self-test
    today = dt.date(2026, 11, 1)
    print("English:", format_english_date(today))
    print("Persian:", format_persian_date(today))
    print("Today  :", format_english_date(), "/", format_persian_date())
