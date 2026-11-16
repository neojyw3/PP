import math
import random

from settings import (
    BOARD_H,
    BOARD_W,
    FALL_INTERVAL,
    GARBAGE_DROP_ENABLED,
    GARBAGE_FALL_DURATION,
    MAX_GARBAGE_DROP,
    ROTATION_DURATION,
)


GARBAGE_BLOCK = -1
FROZEN_GARBAGE_BLOCK = -2
FROZEN_COLOR_BASE = -10
GARBAGE_TYPE_BLOCKS = {
    "garbage": GARBAGE_BLOCK,
    "frozen_garbage": FROZEN_GARBAGE_BLOCK,
    "frozen_red": FROZEN_COLOR_BASE,
    "frozen_yellow": FROZEN_COLOR_BASE - 1,
    "frozen_green": FROZEN_COLOR_BASE - 3,
    "frozen_blue": FROZEN_COLOR_BASE - 2,
    "frozen_purple": FROZEN_COLOR_BASE - 4,
}


def is_frozen_color(block):
    return block is not None and block <= FROZEN_COLOR_BASE


def frozen_color_value(block):
    return FROZEN_COLOR_BASE - block


def is_garbage(block):
    return block in (GARBAGE_BLOCK, FROZEN_GARBAGE_BLOCK)


class Piece:
    def __init__(self):
        self.x = 2
        self.y = 0
        self.c1 = random.choice(active_color_indices)
        self.c2 = random.choice(active_color_indices)
        self.rot = 0
        self.kick_x = 0
        self.kick_y = 0
        self.blocked_rotation_direction = None

    def get_blocks(self):
        offsets = ((0, -1), (1, 0), (0, 1), (-1, 0))
        offset_x, offset_y = offsets[self.rot]
        return [
            (self.x, self.y, self.c1),
            (
                self.x + offset_x + self.kick_x,
                self.y + offset_y + self.kick_y,
                self.c2,
            ),
        ]


color_count = 4
ai_difficulty = "normal"
custom_ai_settings = {
    "soft_drop_seconds": 1.0,
    "soft_drop_enabled": True,
    "action_interval_seconds": 0.1,
    "chain_goal": 3,
}
ai_calculation_distance = 2
player_clear_group_size = 4
ai_clear_group_size = 4
player_max_garbage_drop = MAX_GARBAGE_DROP
ai_max_garbage_drop = MAX_GARBAGE_DROP
player_garbage_ratio = 1.0
ai_garbage_ratio = 1.0
margin_time_settings = {
    "enabled": True,
    "start_seconds": 100,
    "interval_seconds": 50,
    "increase_amount": 0.5,
}
margin_time_elapsed_ms = 0
margin_time_next_increase_ms = margin_time_settings["start_seconds"] * 1000
margin_time_attack_bonus = 0.0
player_garbage_type = "garbage"
ai_garbage_type = "garbage"
active_color_indices = tuple(random.sample(range(5), color_count))
board = [[None for _ in range(BOARD_W)] for _ in range(BOARD_H)]
piece_queue = [Piece() for _ in range(3)]
piece = None
fall_timer = 0
contact_timer = 0
current_fall_interval = FALL_INTERVAL
rotation_animation = None
resolution_phase = None
clearing_groups = []
clearing_elapsed = 0
chain_count = 0
hidden_garbage = []
garbage_fall_blocks = []
garbage_fall_elapsed = 0


def valid(candidate, target_board=None):
    if target_board is None:
        target_board = board
    blocks = candidate.get_blocks()
    if (blocks[0][0], blocks[0][1]) == (blocks[1][0], blocks[1][1]):
        return False

    for x, y, _ in blocks:
        if x < 0 or x >= BOARD_W or y >= BOARD_H:
            return False
        if y >= 0 and target_board[y][x] is not None:
            return False

    return True


def rotate_piece(candidate, direction, steps=1, target_board=None):
    if target_board is None:
        target_board = board
    old_rot = candidate.rot
    old_x = candidate.x
    old_y = candidate.y
    old_kick_x = candidate.kick_x
    old_kick_y = candidate.kick_y
    candidate.rot = (candidate.rot + direction * steps) % 4
    offsets = ((0, -1), (1, 0), (0, 1), (-1, 0))
    target_x, target_y = offsets[candidate.rot]
    candidate.kick_x = 0
    candidate.kick_y = 0

    candidates = []
    if candidate.x + target_x < 0:
        candidates.append((1, 0))
    elif candidate.x + target_x >= BOARD_W:
        candidates.append((-1, 0))
    elif candidate.y + target_y >= BOARD_H:
        candidates.append((0, -1))
    elif (
        candidate.y + target_y >= 0
        and target_board[candidate.y + target_y][candidate.x + target_x] is not None
    ):
        if target_y > 0:
            candidates.append((0, -1))
        elif target_y < 0:
            candidates.append((0, 1))
        else:
            candidates.append((-1 if target_x > 0 else 1, 0))

    candidates.extend(((0, 0), (0, -1), (-1, 0), (1, 0), (0, 1)))
    for shift_x, shift_y in candidates:
        candidate.x = old_x + shift_x
        candidate.y = old_y + shift_y
        if valid(candidate, target_board):
            return True

    candidate.rot = old_rot
    candidate.x = old_x
    candidate.y = old_y
    candidate.kick_x = old_kick_x
    candidate.kick_y = old_kick_y
    return False


def rotation_progress(animation):
    progress = min(animation["elapsed"] / ROTATION_DURATION, 1)
    return progress * progress * (3 - 2 * progress)


def rotation_position(animation, candidate):
    eased = rotation_progress(animation)
    start_angle = math.atan2(animation["start_y"], animation["start_x"])
    rotation_angle = (
        animation["direction"]
        * animation.get("steps", 1)
        * math.pi / 2
    )
    angle = start_angle + rotation_angle * eased
    ideal_end_angle = start_angle + rotation_angle
    ideal_end_x = math.cos(ideal_end_angle)
    ideal_end_y = math.sin(ideal_end_angle)
    kick_x = animation["end_x"] - ideal_end_x
    kick_y = animation["end_y"] - ideal_end_y
    return (
        candidate.x + animation["pivot_offset_x"] * (1 - eased)
        + math.cos(angle) + kick_x * eased,
        candidate.y + animation["pivot_offset_y"] * (1 - eased)
        + math.sin(angle) + kick_y * eased,
    )


def find_match_groups(target_board=None, min_group_size=None):
    if target_board is None:
        target_board = board
    if min_group_size is None:
        min_group_size = player_clear_group_size
    visited = set()
    groups = []

    for y in range(BOARD_H):
        for x in range(BOARD_W):
            color = target_board[y][x]
            if (
                color is None
                or is_garbage(color)
                or is_frozen_color(color)
                or (x, y) in visited
            ):
                continue

            group = []
            pending = [(x, y)]
            visited.add((x, y))
            while pending:
                current_x, current_y = pending.pop()
                group.append((current_x, current_y))
                for neighbor_x, neighbor_y in (
                    (current_x - 1, current_y),
                    (current_x + 1, current_y),
                    (current_x, current_y - 1),
                    (current_x, current_y + 1),
                ):
                    if not (
                        0 <= neighbor_x < BOARD_W
                        and 0 <= neighbor_y < BOARD_H
                    ):
                        continue
                    if (neighbor_x, neighbor_y) in visited:
                        continue
                    if target_board[neighbor_y][neighbor_x] != color:
                        continue

                    visited.add((neighbor_x, neighbor_y))
                    pending.append((neighbor_x, neighbor_y))

            if len(group) >= min_group_size:
                groups.append(group)

    return groups


def start_chain_clear(groups):
    global chain_count, clearing_groups, clearing_elapsed, resolution_phase
    chain_count += 1
    clearing_groups = groups
    clearing_elapsed = 0
    resolution_phase = "chain_starting"


def can_move_down(candidate, target_board=None):
    test = Piece()
    test.x = candidate.x
    test.y = candidate.y + 1
    test.rot = candidate.rot
    test.c1 = candidate.c1
    test.c2 = candidate.c2
    test.kick_x = candidate.kick_x
    test.kick_y = candidate.kick_y
    return valid(test, target_board)


def lock_piece(candidate, target_board=None):
    if target_board is None:
        target_board = board
    for x, y, color in candidate.get_blocks():
        if 0 <= y < BOARD_H:
            target_board[y][x] = color


def plan_garbage_drop(target_board, block_count, garbage_type="garbage"):
    try:
        garbage_block = GARBAGE_TYPE_BLOCKS[garbage_type]
    except KeyError as error:
        raise ValueError(f"Unknown garbage type: {garbage_type}") from error

    remaining_by_column = []
    for x in range(BOARD_W):
        y = BOARD_H - 1
        while y >= 0 and target_board[y][x] is not None:
            y -= 1
        remaining_by_column.append(y)

    falling_blocks = []
    remaining = block_count
    layer_index = 0
    while remaining > 0:
        layer_count = min(remaining, BOARD_W)
        columns = random.sample(range(BOARD_W), layer_count)
        for x in columns:
            y = remaining_by_column[x]
            start_y = -1 - layer_index
            falling_blocks.append({
                "x": x,
                "y": y,
                "start_y": start_y,
                "current_y": start_y,
                "landed": False,
                "hidden": y < 0,
                "block": garbage_block,
            })
            remaining_by_column[x] -= 1
        remaining -= layer_count
        layer_index += 1
    return falling_blocks


def advance_garbage_drop(target_board, falling_blocks, dt):
    fall_speed = BOARD_H / GARBAGE_FALL_DURATION
    for block in falling_blocks:
        if block["landed"]:
            continue

        next_y = min(
            block["y"],
            block["current_y"] + fall_speed * dt,
        )
        if next_y >= block["y"] - 1e-9:
            x, y = block["x"], block["y"]
            if y < 0 or target_board[y][x] is not None:
                block["hidden"] = True
            else:
                target_board[y][x] = block["block"]
            block["current_y"] = float(y)
            block["landed"] = True
        else:
            block["current_y"] = next_y

    return all(block["landed"] for block in falling_blocks)


def land_garbage_drop(target_board, falling_blocks):
    for block in falling_blocks:
        x, y = block["x"], block["y"]
        if target_board[y][x] is not None:
            return False
    for block in falling_blocks:
        target_board[block["y"]][block["x"]] = block.get(
            "block",
            GARBAGE_BLOCK,
        )
    return True


def clear_groups_with_adjacent_garbage(target_board, groups):
    clear_positions = {
        (x, y)
        for group in groups
        for x, y in group
    }
    for x, y in tuple(clear_positions):
        for neighbor_x, neighbor_y in (
            (x - 1, y),
            (x + 1, y),
            (x, y - 1),
            (x, y + 1),
        ):
            if (
                0 <= neighbor_x < BOARD_W
                and 0 <= neighbor_y < BOARD_H
            ):
                neighbor = target_board[neighbor_y][neighbor_x]
                if neighbor == GARBAGE_BLOCK:
                    clear_positions.add((neighbor_x, neighbor_y))
                elif neighbor == FROZEN_GARBAGE_BLOCK:
                    target_board[neighbor_y][neighbor_x] = GARBAGE_BLOCK
                elif is_frozen_color(neighbor):
                    target_board[neighbor_y][neighbor_x] = frozen_color_value(
                        neighbor
                    )
    for x, y in clear_positions:
        target_board[y][x] = None


def apply_board_gravity(target_board=None):
    if target_board is None:
        target_board = board
    moved = False

    for x in range(BOARD_W):
        for y in range(BOARD_H - 2, -1, -1):
            if (
                target_board[y][x] is not None
                and (GARBAGE_DROP_ENABLED or not is_garbage(target_board[y][x]))
                and target_board[y + 1][x] is None
            ):
                target_board[y + 1][x] = target_board[y][x]
                target_board[y][x] = None
                moved = True
    return moved


def spawn_piece():
    global piece, piece_queue, fall_timer, contact_timer, rotation_animation
    piece = piece_queue.pop(0)
    piece_queue.append(Piece())
    piece.y = -1
    fall_timer = 0
    contact_timer = 0
    rotation_animation = None


def set_color_count(count):
    global color_count, active_color_indices
    if count not in (3, 4, 5):
        raise ValueError("Color count must be 3, 4, or 5")
    color_count = count
    active_color_indices = tuple(random.sample(range(5), count))


def set_ai_difficulty(difficulty):
    global ai_difficulty
    if difficulty not in (
        "very_easy",
        "easy",
        "normal",
        "hard",
        "very_hard",
        "custom",
    ):
        raise ValueError(
            "AI difficulty must be very_easy, easy, normal, hard, very_hard, or custom"
        )
    ai_difficulty = difficulty


def set_ai_calculation_distance(distance):
    global ai_calculation_distance
    if type(distance) is not int or not 0 <= distance <= 30:
        raise ValueError("AI calculation distance must be an integer from 0 to 30")
    ai_calculation_distance = distance


def set_custom_ai_setting(key, value):
    if key == "soft_drop_seconds":
        if value == 0:
            value = 0.0
        elif 0.1 <= value <= 10.0:
            value = round(value, 1)
        else:
            raise ValueError(
                "Soft drop time must be immediate or between 0.1 and 10 seconds"
            )
    elif key == "soft_drop_enabled":
        if not isinstance(value, bool):
            raise TypeError("Soft drop enabled setting must be a boolean")
    elif key == "action_interval_seconds":
        if value == 0:
            value = 0.0
        elif 0.1 <= value <= 10.0:
            value = round(value, 1)
        else:
            raise ValueError(
                "Action interval must be immediate or between 0.1 and 10 seconds"
            )
    elif key == "chain_goal":
        if not isinstance(value, int) or not 1 <= value <= 50:
            raise ValueError("Chain goal must be an integer between 1 and 50")
    else:
        raise ValueError(f"Unknown custom AI setting: {key}")
    custom_ai_settings[key] = value


def set_clear_group_size(size):
    global player_clear_group_size
    if not 2 <= size <= 6:
        raise ValueError("Clear group size must be between 2 and 6")
    player_clear_group_size = size


def set_ai_clear_group_size(size):
    global ai_clear_group_size
    if not 2 <= size <= 6:
        raise ValueError("Clear group size must be between 2 and 6")
    ai_clear_group_size = size


def set_max_garbage_drop(side, count):
    global player_max_garbage_drop, ai_max_garbage_drop
    if type(count) is not int or not 1 <= count <= 101:
        raise ValueError("Maximum garbage drop must be an integer from 1 to 101")
    if side == "player":
        player_max_garbage_drop = count
    elif side == "ai":
        ai_max_garbage_drop = count
    else:
        raise ValueError("Side must be 'player' or 'ai'")


def effective_garbage_drop_count(garbage_count, maximum):
    if maximum <= 1:
        return 0
    if maximum > 100:
        return garbage_count
    return min(garbage_count, maximum)


def set_garbage_ratio(side, ratio):
    global player_garbage_ratio, ai_garbage_ratio
    if not 0.1 <= ratio <= 10.0:
        raise ValueError("Garbage ratio must be between 0.1 and 10.0")
    ratio = round(ratio, 1)
    if side == "player":
        player_garbage_ratio = ratio
    elif side == "ai":
        ai_garbage_ratio = ratio
    else:
        raise ValueError("Side must be 'player' or 'ai'")


def set_margin_time_setting(key, value):
    if key == "enabled":
        if not isinstance(value, bool):
            raise TypeError("Margin time enabled setting must be a boolean")
    elif key == "start_seconds":
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("Margin time start must be an integer")
        if not 0 <= value <= 1000:
            raise ValueError("Margin time start must be between 0 and 1000")
    elif key == "interval_seconds":
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("Margin time interval must be an integer")
        if not 1 <= value <= 100:
            raise ValueError("Margin time interval must be between 1 and 100")
    elif key == "increase_amount":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("Margin time increase must be a number")
        if not 0.1 <= value <= 10.0:
            raise ValueError("Margin time increase must be between 0.1 and 10.0")
        value = round(value, 1)
    else:
        raise ValueError(f"Unknown margin time setting: {key}")
    margin_time_settings[key] = value


def advance_margin_time(dt):
    global margin_time_elapsed_ms, margin_time_next_increase_ms
    global margin_time_attack_bonus
    if not margin_time_settings["enabled"]:
        return
    margin_time_elapsed_ms += dt
    start_ms = margin_time_settings["start_seconds"] * 1000
    if margin_time_elapsed_ms < start_ms:
        return

    interval_ms = margin_time_settings["interval_seconds"] * 1000
    while margin_time_elapsed_ms >= margin_time_next_increase_ms:
        margin_time_attack_bonus = round(
            margin_time_attack_bonus
            + margin_time_settings["increase_amount"],
            1,
        )
        margin_time_next_increase_ms += interval_ms


def effective_garbage_ratio(side):
    if side == "player":
        ratio = player_garbage_ratio
    elif side == "ai":
        ratio = ai_garbage_ratio
    else:
        raise ValueError("Side must be 'player' or 'ai'")
    return round(ratio + margin_time_attack_bonus, 1)


def set_garbage_type(side, garbage_type):
    global player_garbage_type, ai_garbage_type
    if garbage_type not in GARBAGE_TYPE_BLOCKS:
        raise ValueError(f"Unknown garbage type: {garbage_type}")
    if side == "player":
        player_garbage_type = garbage_type
    elif side == "ai":
        ai_garbage_type = garbage_type
    else:
        raise ValueError("Side must be 'player' or 'ai'")


def restart_game():
    global board, piece_queue, fall_timer, contact_timer
    global rotation_animation, resolution_phase, clearing_groups
    global clearing_elapsed, chain_count, current_fall_interval
    global hidden_garbage, garbage_fall_blocks, garbage_fall_elapsed
    global margin_time_elapsed_ms, margin_time_next_increase_ms
    global margin_time_attack_bonus
    board = [[None for _ in range(BOARD_W)] for _ in range(BOARD_H)]
    piece_queue = [Piece() for _ in range(3)]
    fall_timer = 0
    contact_timer = 0
    rotation_animation = None
    resolution_phase = None
    clearing_groups = []
    clearing_elapsed = 0
    chain_count = 0
    hidden_garbage = []
    garbage_fall_blocks = []
    garbage_fall_elapsed = 0
    margin_time_elapsed_ms = 0
    margin_time_next_increase_ms = margin_time_settings["start_seconds"] * 1000
    margin_time_attack_bonus = 0.0
    current_fall_interval = FALL_INTERVAL
    spawn_piece()


spawn_piece()
