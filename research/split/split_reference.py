"""A second, independently structured implementation used only to cross-check split_lab.

split_lab walks the holding window hour by hour. This module instead looks for the
events directly: the first hour the step-1 stop line is touched, the first evaluation
hour whose open meets the step-2 trigger, and then the first hour the new stop line is
touched. Both must give the same (step-2 hour, stop hour) for every case.
"""

from collections.abc import Callable, Sequence

from split_lab import EVAL_EVERY_HOURS, Bar


def _first(hours: range, condition: Callable[[int], bool]) -> int | None:
    return next((hour for hour in hours if condition(hour)), None)


def reference_events(
    bars: Sequence[Bar],
    entry: int,
    hold_hours: int,
    drop_pct: int | None,
    stop_pct: int = 5,
) -> tuple[int | None, int | None]:
    """Return (step-2 hour, stop hour) for one case, hours counted from the entry."""
    window = bars[entry : entry + hold_hours]
    if len(window) != hold_hours:
        msg = "the holding window must fit inside the series"
        raise ValueError(msg)
    p1 = window[0].open
    line1 = p1 * (100 - stop_pct) / 100
    # Lows never exceed opens, so "open <= line" is already covered by "low <= line".
    stop1 = _first(range(hold_hours), lambda h: window[h].low <= line1)
    if drop_pct is None:
        return None, stop1
    trigger = p1 * (100 - drop_pct) / 100
    step2 = _first(
        range(EVAL_EVERY_HOURS, hold_hours, EVAL_EVERY_HOURS),
        lambda h: not window[h].filled and window[h].open <= trigger,
    )
    if step2 is None:
        return None, stop1
    if stop1 is not None and (stop1 < step2 or window[step2].open <= line1):
        # Stopped earlier, or the evaluation hour opened at or below the stop line.
        return None, stop1
    p2 = window[step2].open
    average = 2 / (1 / p1 + 1 / p2)  # equal KRW amounts
    line2 = average * (100 - stop_pct) / 100
    stop2 = _first(range(step2, hold_hours), lambda h: window[h].low <= line2)
    return step2, stop2
