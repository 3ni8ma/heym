"""Smooth weighted round-robin over per-instance assignment counters.

Every assigned run increments a counter, including a MAIN_ONLY run that main was
forced to take. That single rule is what makes a percentage describe total load:
forced work spends main's quota, so the next ANYWHERE runs fall to the workers.
The consequence, which the UI and docs state: main's percentage is a ceiling,
not a floor.

A counter only means something while its instance is a candidate. An instance
that was not one - Offline, Disabled, or on a version main cannot hand work to -
must be re-entered at the pool's current position rather than repaid for the
time it was away; see level_counters.
"""

from __future__ import annotations

COUNTER_RESCALE_THRESHOLD = 1_000_000


def normalized_weights(weights: dict[str, int]) -> dict[str, float]:
    """Configured weights as shares of the live pool, summing to 1."""
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {instance_id: weight / total for instance_id, weight in weights.items()}


def pick_instance(weights: dict[str, int], *, counters: dict[str, int]) -> str | None:
    """The instance furthest below its share. Ties break on id, so it is deterministic."""
    shares = normalized_weights(weights)
    if not shares:
        return None
    total = sum(counters.get(instance_id, 0) for instance_id in shares) + 1
    return max(
        sorted(shares),
        key=lambda instance_id: shares[instance_id] * total - counters.get(instance_id, 0),
    )


def level_counters(counters: dict[str, int], weights: dict[str, int]) -> dict[str, int]:
    """Keep the pool's counters, forget the rest, and enter a joiner level.

    Counters are lifetime totals, so an instance that was not a candidate for a
    while builds a deficit it never earned, and pick_instance repays it in one
    burst: after a worker spends a night on a mismatched version, a 70/30 split
    runs as 0/100 for thousands of runs. Dropping an absent instance's counter
    is how the next pass knows it was away; it then rejoins carrying the same
    number of runs per unit of weight the pool already carries, so the split
    holds from the first run after the rejoin.

    A deficit built while the instance *was* a candidate is left alone - that is
    the catch-up that makes main's percentage a ceiling.
    """
    if not weights:
        return counters
    present = {i: counters[i] for i in weights if i in counters}
    joining = [i for i in weights if i not in present]
    if not joining:
        return present

    served_weight = sum(weights[i] for i in present)
    per_weight = sum(present.values()) / served_weight if served_weight else 0.0
    for instance_id in joining:
        present[instance_id] = round(per_weight * weights[instance_id])
    return present


def rescale_counters(counters: dict[str, int]) -> dict[str, int]:
    """Halve every counter once the largest gets big, preserving the ratios."""
    if not counters or max(counters.values()) < COUNTER_RESCALE_THRESHOLD:
        return counters
    return {instance_id: value // 2 for instance_id, value in counters.items()}


def seed_weights(current: dict[str, tuple[bool, int]]) -> dict[str, int] | None:
    """Give every never-configured instance a share, or None if there is none.

    `current` maps instance id to (weight_configured, weight). An instance is a
    newcomer only while `weight_configured` is False, so this runs once per
    machine: an operator who deliberately sets a worker to 0 is never fought.

    Newcomers take an equal share of the pool and the configured instances are
    scaled down proportionally, so a deliberate 70/30 still reads as 70/30
    afterwards. The result always totals exactly 100; the rounding remainder
    goes to the largest configured instance, which is main in practice.
    """
    newcomers = sorted(i for i, (configured, _w) in current.items() if not configured)
    if not newcomers:
        return None

    pool_size = len(current)
    share = 100 // pool_size
    seeded = {instance_id: share for instance_id in newcomers}

    configured = {i: w for i, (c, w) in current.items() if c}
    configured_total = sum(configured.values())
    remaining = 100 - share * len(newcomers)

    if configured_total > 0:
        for instance_id, weight in configured.items():
            seeded[instance_id] = int(weight * remaining / configured_total)
    else:
        # Nothing configured to scale against: split what is left evenly.
        for instance_id in configured:
            seeded[instance_id] = remaining // max(len(configured), 1)

    drift = 100 - sum(seeded.values())
    if drift:
        largest = max(seeded, key=lambda i: (seeded[i], i))
        seeded[largest] += drift
    return seeded
