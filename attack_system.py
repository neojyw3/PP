import math

import pygame

from settings import (
    BOARD_H,
    BOARD_W,
    BOARD_Y,
    CELL,
)


ATTACK_FLIGHT_DURATION = 250
STACK_REORGANIZE_DURATION = 100
SHAKE_DURATION = 420
GARBAGE_LANDING_SHAKE_DURATION = 500
GARBAGE_LANDING_SHAKE_STRENGTH = 8
ATTACK_COLOR = (145, 145, 145)
ORB_RADIUS = max(1, round((CELL // 2 - 2) * 0.5))
LARGE_ORB_RADIUS = CELL // 2 - 2
STACK_COLORS = {
    "small": ATTACK_COLOR,
    "large": ATTACK_COLOR,
    "red": (255, 45, 45),
}
STACK_RADII = {
    "small": ORB_RADIUS,
    "large": LARGE_ORB_RADIUS,
    "red": LARGE_ORB_RADIUS,
}
GARBAGE_UNIT_VALUES = {
    "small": 1,
    "large": 6,
    "red": 30,
}
GARBAGE_COUNTER_ENABLED = True
MAX_CHAIN_COUNT = 99
ATTACK_TABLE = {
    2: (2, 3, 5, 7, 10),
    3: (5, 7, 9, 13, 16),
    4: (9, 14, 18, 24, 30),
    5: (18, 27, 37, 47, 57),
    6: (27, 42, 54, 70, 85),
    7: (37, 54, 74, 93, 112),
}
CHAIN_GROWTH_AFTER_7 = (10, 12, 20, 23, 27)


def attack_block_count(chain_count, cleared_count):
    if not 1 <= chain_count <= MAX_CHAIN_COUNT or cleared_count < 1:
        return 0

    if chain_count == 1:
        return max(1, min(cleared_count, BOARD_W * BOARD_H) - 3)

    if cleared_count < 2:
        return 1

    cleared_count = min(cleared_count, BOARD_W * BOARD_H)
    table_count = min(cleared_count, 6)

    if chain_count <= 7:
        attack_count = ATTACK_TABLE[chain_count][table_count - 2]
    else:
        attack_count = ATTACK_TABLE[7][table_count - 2]
        for _ in range(8, chain_count + 1):
            attack_count += CHAIN_GROWTH_AFTER_7[table_count - 2]

    if cleared_count > 6:
        attack_count += cleared_count - 6
    return attack_count


def launch_attacks(
    attacks,
    groups,
    chain_count,
    source_board_x,
    target_board_x,
    target_side,
    garbage_by_side,
    visual_garbage_by_side,
    garbage_ratio=1.0,
    deferred_garbage_by_side=None,
    defer_target=False,
):
    if not 1 <= chain_count <= MAX_CHAIN_COUNT:
        return []

    positions = [position for group in groups for position in group]
    if not positions:
        return []

    cleared_count = len(positions)
    base_attack_blocks = attack_block_count(chain_count, cleared_count)
    attack_blocks = int(base_attack_blocks * garbage_ratio + 0.5)
    if base_attack_blocks > 0:
        attack_blocks = max(1, attack_blocks)
    if attack_blocks == 0:
        return []

    starts = []
    for group in groups:
        if not group:
            continue
        center_x = sum(x for x, _ in group) / len(group)
        center_y = sum(y for _, y in group) / len(group)
        starts.append((
            source_board_x + (center_x + 0.5) * CELL,
            BOARD_Y + (center_y + 0.5) * CELL,
        ))
    source_center = (
        source_board_x + BOARD_W * CELL / 2,
        BOARD_Y - CELL / 2,
    )
    source_side = "player" if target_side == "ai" else "ai"
    source_pending = garbage_by_side[source_side]
    target_pending = garbage_by_side[target_side]
    source_existing_units = normalize_garbage(source_pending)
    canceled_count = 0
    if source_existing_units and GARBAGE_COUNTER_ENABLED:
        canceled_count, _ = cancel_garbage(source_pending, attack_blocks)
    if canceled_count and deferred_garbage_by_side is not None:
        source_deferred = deferred_garbage_by_side[source_side]
        source_total_before = garbage_value(source_existing_units)
        source_ready_before = max(0, source_total_before - source_deferred)
        deferred_canceled = max(0, canceled_count - source_ready_before)
        deferred_garbage_by_side[source_side] = max(
            0,
            source_deferred - deferred_canceled,
        )
    source_remaining_units = normalize_garbage(source_pending)
    if canceled_count:
        reconcile_pending_delivery_visuals(
            attacks,
            source_side,
            source_remaining_units,
        )
    remaining_attack = attack_blocks - canceled_count
    target_existing_units = normalize_garbage(
        visual_garbage_by_side[target_side]
    )
    target_final_units = normalize_garbage(
        target_pending + ["small"] * remaining_attack
    )
    source_pending[:] = source_remaining_units
    target_pending[:] = target_final_units
    if (
        remaining_attack
        and defer_target
        and deferred_garbage_by_side is not None
    ):
        deferred_garbage_by_side[target_side] += remaining_attack

    if canceled_count:
        phase = "to_cancel_center"
        target = source_center
    else:
        phase = "to_target_center"
        target = (
            target_board_x + BOARD_W * CELL / 2,
            BOARD_Y - CELL / 2,
        )

    attacks.append({
        "start": starts[0],
        "starts": starts,
        "target": target,
        "elapsed": 0,
        "attack_blocks": remaining_attack,
        "phase": phase,
        "source_board_x": source_board_x,
        "target_board_x": target_board_x,
        "source_side": source_side,
        "target_side": target_side,
        "source_existing_units": source_existing_units,
        "source_remaining_units": source_remaining_units,
        "target_existing_units": target_existing_units,
        "target_final_units": target_final_units,
    })
    return []


def update_attacks(
    attacks,
    dt,
    garbage_by_side,
    visual_garbage_by_side,
):
    active_attacks = []
    return_orbs = []
    impact_events = []
    for attack in attacks:
        attack["elapsed"] += dt

        if attack["phase"] in ("reorganize", "cancel_reorganize"):
            duration = attack.get("duration", ATTACK_FLIGHT_DURATION)
            if attack["elapsed"] >= duration:
                overflow = attack["elapsed"] - duration
                if attack["phase"] == "reorganize":
                    stack_units = attack["target_final_units"]
                    board_x = attack["target_board_x"]
                    stack_side = attack["target_side"]
                    stack_phase = "to_target_slot"
                else:
                    stack_units = normalize_garbage(
                        attack["remaining_units"]
                    )
                    board_x = attack["source_board_x"]
                    stack_side = attack["source_side"]
                    stack_phase = "to_restack"

                stack_orbs = make_stack_orbs(
                    attack["target"],
                    board_x,
                    stack_side,
                    stack_units,
                    overflow,
                    stack_phase,
                )
                if stack_orbs:
                    return_orbs.extend(stack_orbs)
                else:
                    visual_garbage_by_side[stack_side][:] = normalize_garbage(
                        garbage_by_side[stack_side]
                    )
            else:
                active_attacks.append(attack)
            continue

        while attack["elapsed"] >= ATTACK_FLIGHT_DURATION:
            overflow = attack["elapsed"] - ATTACK_FLIGHT_DURATION
            if attack["phase"] == "to_cancel_center":
                return_orbs.append({
                    "start": attack["target"],
                    "target": attack["target"],
                    "elapsed": 0,
                    "phase": "cancel_reorganize",
                    "source_board_x": attack["source_board_x"],
                    "source_side": attack["source_side"],
                    "existing_units": attack["source_existing_units"],
                    "remaining_units": attack["source_remaining_units"],
                })

                if attack["attack_blocks"] == 0:
                    attack = None
                    break

                attack["phase"] = "to_target_center"
                attack["start"] = attack["target"]
                attack["starts"] = [attack["target"]]
                attack["target"] = (
                    attack["target_board_x"] + BOARD_W * CELL / 2,
                    BOARD_Y - CELL / 2,
                )
                attack["elapsed"] = overflow
            elif attack["phase"] == "to_target_center":
                impact_events.append((
                    attack["target_side"],
                    attack["attack_blocks"],
                ))
                if attack["target_existing_units"]:
                    return_orbs.append({
                        "start": attack["target"],
                        "target": attack["target"],
                        "elapsed": overflow,
                        "phase": "reorganize",
                        "target_side": attack["target_side"],
                        "target_board_x": attack["target_board_x"],
                        "existing_units": attack["target_existing_units"],
                        "target_final_units": attack["target_final_units"],
                        "attack_blocks": attack["attack_blocks"],
                    })
                else:
                    return_orbs.extend(make_stack_orbs(
                        attack["target"],
                        attack["target_board_x"],
                        attack["target_side"],
                        attack["target_final_units"],
                        overflow,
                        "to_target_slot",
                    ))
                attack = None
                break
            elif attack["phase"] in ("to_target_slot", "to_restack"):
                layout = attack.get("visual_layout")
                if layout is not None:
                    layout["remaining"] -= 1
                    if layout["remaining"] == 0:
                        visual_garbage_by_side[layout["side"]][:] = (
                            normalize_garbage(
                                garbage_by_side[layout["side"]]
                            )
                        )
                attack = None
                break
            else:
                attack = None
                break

        if attack is not None:
            active_attacks.append(attack)

    attacks[:] = active_attacks + return_orbs
    return impact_events


def make_stack_orbs(start, board_x, side, units, elapsed, phase):
    visible_units = units[:BOARD_W]
    hidden_units = units[BOARD_W:]
    if not visible_units:
        return []

    layout = {
        "side": side,
        "board_x": board_x,
        "units": units[:],
        "remaining": len(visible_units),
    }
    return [
        {
            "start": start,
            "target": (
                board_x + (column + 0.5) * CELL,
                BOARD_Y - CELL / 2,
            ),
            "elapsed": elapsed,
            "phase": phase,
            "target_side": side,
            "column": column,
            "tier": unit,
            "visual_layout": layout,
            "hidden_units": (
                hidden_units if column == len(visible_units) - 1 else []
            ),
        }
        for column, unit in enumerate(visible_units)
    ]


def start_stack_reorganization(attacks, board_x, side, old_units, new_units):
    existing_units = normalize_garbage(old_units)[:BOARD_W]
    target_units = normalize_garbage(new_units)
    if not existing_units:
        start = (
            board_x + BOARD_W * CELL / 2,
            BOARD_Y - CELL / 2,
        )
        return make_stack_orbs(
            start,
            board_x,
            side,
            target_units,
            0,
            "to_target_slot",
        )

    center = (
        board_x + BOARD_W * CELL / 2,
        BOARD_Y - CELL / 2,
    )
    attacks.append({
        "start": center,
        "target": center,
        "elapsed": 0,
        "phase": "reorganize",
        "duration": STACK_REORGANIZE_DURATION,
        "target_side": side,
        "target_board_x": board_x,
        "existing_units": existing_units,
        "target_final_units": target_units,
        "attack_blocks": 0,
    })
    return []


def attack_shake_strength(attack_blocks):
    if attack_blocks <= 1:
        return 1
    if attack_blocks <= 10:
        return 1 + (attack_blocks - 1) * 4 / 9
    if attack_blocks <= 30:
        return 5 + (attack_blocks - 10) * 7 / 20
    return min(18, 12 + (attack_blocks - 30) * 0.15)


def start_field_shake(state, attack_blocks):
    remaining_strength = state["strength"] * max(
        0,
        1 - state["elapsed"] / SHAKE_DURATION,
    )
    state["elapsed"] = 0
    state["strength"] = max(
        remaining_strength,
        attack_shake_strength(attack_blocks),
    )


def update_field_shake(state, dt):
    if state["strength"] <= 0:
        return 0, 0

    state["elapsed"] = min(state["elapsed"] + dt, SHAKE_DURATION)
    progress = state["elapsed"] / SHAKE_DURATION
    ramp = min(progress * 5, 1)
    envelope = ramp * (1 - progress) ** 2
    phase = state["elapsed"] * 0.055
    strength = state["strength"] * envelope
    offset = (
        round(math.sin(phase) * strength),
        round(math.sin(phase * 1.37 + 0.8) * strength * 0.65),
    )
    if progress >= 1:
        state["strength"] = 0
    return offset


def start_garbage_landing_shake(state):
    state["elapsed"] = 0
    state["strength"] = GARBAGE_LANDING_SHAKE_STRENGTH


def update_garbage_landing_shake(state, dt):
    if state["strength"] <= 0:
        return 0, 0

    state["elapsed"] = min(
        state["elapsed"] + dt,
        GARBAGE_LANDING_SHAKE_DURATION,
    )
    progress = state["elapsed"] / GARBAGE_LANDING_SHAKE_DURATION
    strength = state["strength"] * (1 - progress)
    offset_y = round(math.sin(state["elapsed"] * 0.075) * strength)
    if progress >= 1:
        state["strength"] = 0
    return 0, offset_y


def attack_position(attack, start=None):
    progress = min(attack["elapsed"] / ATTACK_FLIGHT_DURATION, 1)
    progress = progress * progress * (3 - 2 * progress)
    start_x, start_y = attack["start"] if start is None else start
    target_x, target_y = attack["target"]
    return (
        start_x + (target_x - start_x) * progress,
        start_y + (target_y - start_y) * progress,
    )


def deliver_attack(attack, hidden_garbage):
    hidden_garbage.append(attack["tier"])
    hidden_garbage.extend(attack.get("hidden_units", []))
    hidden_garbage[:] = normalize_garbage(hidden_garbage)


def normalize_garbage(units):
    return garbage_from_value(garbage_value(units))


def has_pending_delivery(attacks, side):
    return any(
        (
            attack.get("target_side") == side
            and attack["phase"] in (
                "reorganize",
                "to_target_slot",
                "to_restack",
            )
        )
        or (
            attack.get("source_side") == side
            and attack["phase"] == "cancel_reorganize"
        )
        for attack in attacks
    )


def has_delivery_in_flight(attacks, side):
    return any(
        attack.get("target_side") == side
        and attack["phase"] in ("to_cancel_center", "to_target_center")
        for attack in attacks
    )


def has_delivery_in_progress(attacks, side):
    return (
        has_delivery_in_flight(attacks, side)
        or has_pending_delivery(attacks, side)
    )


def has_stack_cancellation_in_progress(attacks, side):
    return any(
        (
            attack.get("source_side") == side
            and attack["phase"] in (
                "to_cancel_center",
                "cancel_reorganize",
            )
        )
        or (
            attack.get("target_side") == side
            and attack["phase"] == "to_restack"
        )
        for attack in attacks
    )


def garbage_value(units):
    return sum(GARBAGE_UNIT_VALUES.get(unit, 1) for unit in units)


def garbage_from_value(value):
    value = max(0, value)
    red_count, value = divmod(value, GARBAGE_UNIT_VALUES["red"])
    large_count, small_count = divmod(value, GARBAGE_UNIT_VALUES["large"])
    return (
        ["red"] * red_count
        + ["large"] * large_count
        + ["small"] * small_count
    )


def cancel_garbage(units, attack_blocks):
    normalized = normalize_garbage(units)
    canceled_count = min(attack_blocks, garbage_value(normalized))
    visible_units = normalized[:BOARD_W]
    canceled_columns = sorted(
        range(len(visible_units)),
        key=lambda column: (
            GARBAGE_UNIT_VALUES[visible_units[column]],
            -column,
        ),
    )[:min(canceled_count, BOARD_W)]
    units[:] = garbage_from_value(garbage_value(normalized) - canceled_count)
    return canceled_count, canceled_columns


def reconcile_pending_delivery_visuals(attacks, side, units):
    slot_layouts = {}
    for attack in attacks:
        if attack.get("target_side") != side:
            continue
        if attack["phase"] in ("to_target_center", "reorganize"):
            attack["target_final_units"] = units[:]
        elif attack["phase"] == "to_target_slot":
            layout = attack.get("visual_layout")
            if layout is not None:
                slot_layouts.setdefault(
                    id(layout),
                    (
                        layout,
                        attack["start"],
                        attack["elapsed"],
                    ),
                )

    if not slot_layouts:
        return

    reconciled_attacks = []
    added_layouts = set()
    for attack in attacks:
        layout = attack.get("visual_layout")
        layout_id = id(layout) if layout is not None else None
        if layout_id not in slot_layouts:
            reconciled_attacks.append(attack)
            continue
        if layout_id in added_layouts:
            continue
        old_layout, start, elapsed = slot_layouts[layout_id]
        reconciled_attacks.extend(make_stack_orbs(
            start,
            old_layout["board_x"],
            side,
            units,
            elapsed,
            "to_target_slot",
        ))
        added_layouts.add(layout_id)

    attacks[:] = reconciled_attacks


def draw_garbage_stacks(
    screen,
    stacks,
    shake_offsets=None,
    hidden_boards=(),
):
    if shake_offsets is None:
        shake_offsets = {}

    for board_x, pending in stacks:
        if board_x in hidden_boards:
            continue
        offset_x, offset_y = shake_offsets.get(board_x, (0, 0))

        for column, tier in enumerate(normalize_garbage(pending)[:BOARD_W]):
            pygame.draw.circle(
                screen,
                STACK_COLORS[tier],
                (
                    round(board_x + (column + 0.5) * CELL + offset_x),
                    round(BOARD_Y - CELL / 2 + offset_y),
                ),
                STACK_RADII[tier],
            )


def draw_attacks(screen, attacks):
    for attack in attacks:
        if attack["phase"] in ("reorganize", "cancel_reorganize"):
            duration = attack.get("duration", ATTACK_FLIGHT_DURATION)
            progress = min(attack["elapsed"] / duration, 1)
            progress = progress * progress * (3 - 2 * progress)
            center_x, center_y = attack["target"]
            board_x = (
                attack["source_board_x"]
                if attack["phase"] == "cancel_reorganize"
                else attack["target_board_x"]
            )
            for column, tier in enumerate(
                attack["existing_units"][:BOARD_W]
            ):
                start = (
                    board_x + (column + 0.5) * CELL,
                    BOARD_Y - CELL / 2,
                )
                center = (
                    round(start[0] + (center_x - start[0]) * progress),
                    round(start[1] + (center_y - start[1]) * progress),
                )
                pygame.draw.circle(
                    screen,
                    STACK_COLORS[tier],
                    center,
                    STACK_RADII[tier],
                )
            pygame.draw.circle(
                screen,
                ATTACK_COLOR,
                (round(center_x), round(center_y)),
                ORB_RADIUS,
            )
            continue

        tier = attack.get("tier", "small")
        for start in attack.get("starts", [attack["start"]]):
            position = attack_position(attack, start)
            center = (round(position[0]), round(position[1]))
            pygame.draw.circle(
                screen,
                STACK_COLORS[tier],
                center,
                STACK_RADII[tier],
            )