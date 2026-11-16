import copy
from collections import deque

import attack_system
import game_logic
from settings import (
    BOARD_H,
    BOARD_W,
    CHAIN_CONTINUE_START_DELAY,
    CHAIN_START_DELAY,
    CLEAR_DURATION,
    CONTACT_DELAY,
    FALL_INTERVAL,
    HORIZONTAL_REPEAT_INTERVAL,
    NEXT_PIECE_DELAY,
    ROTATION_DURATION,
    SOFT_DROP_INTERVAL,
)


def _choose_placement_worker(
    board,
    piece,
    piece_queue,
    difficulty,
    clear_group_size,
    custom_settings,
    garbage_pressure,
    calculation_distance,
    prioritize_max_chain=False,
):
    planner = AIPlayer.__new__(AIPlayer)
    planner.board = board
    planner.piece_queue = piece_queue
    planner.difficulty = difficulty
    planner.clear_group_size = clear_group_size
    planner.custom_settings = custom_settings
    planner.garbage_pressure = garbage_pressure
    planner.garbage_response_pending = False
    planner.calculation_distance = calculation_distance
    planner.prioritize_max_chain = prioritize_max_chain
    return planner._choose_placement_plan(
        piece,
        board,
        return_search_state=True,
        force_chain_search=prioritize_max_chain,
    )


def _advance_frontier_worker(
    frontier,
    steps,
    difficulty,
    clear_group_size,
    custom_settings,
    calculation_distance,
    prioritize_max_chain=False,
):
    planner = AIPlayer.__new__(AIPlayer)
    planner.board = []
    planner.piece_queue = []
    planner.difficulty = difficulty
    planner.clear_group_size = clear_group_size
    planner.custom_settings = custom_settings
    planner.garbage_pressure = False
    planner.garbage_response_pending = False
    planner.calculation_distance = calculation_distance
    planner.prioritize_max_chain = prioritize_max_chain
    plan = None
    for target, added_piece in steps:
        plan, frontier = planner._advance_search_frontier(
            frontier,
            target,
            added_piece,
        )
        if frontier is None:
            return None, None
    return plan, frontier


def _copy_piece(piece):
    duplicate = game_logic.Piece.__new__(game_logic.Piece)
    duplicate.__dict__.update(piece.__dict__)
    return duplicate


class AIPlayer:
    PLANNER_BEAM_WIDTH = 16

    DIFFICULTIES = {
        "very_easy": {"drop_delay": None, "action_interval": 250, "chain_goal": 2},
        "easy": {"drop_delay": 3000, "action_interval": 250, "chain_goal": 2},
        "normal": {"drop_delay": 2000, "action_interval": 100, "chain_goal": 3},
        "hard": {"drop_delay": 1000, "action_interval": 100, "chain_goal": 4},
        "very_hard": {"drop_delay": 0, "action_interval": 100, "chain_goal": 5},
        "custom": {
            "drop_delay": None,
            "action_interval": 100,
            "chain_goal": 3,
        },
    }

    def __init__(
        self,
        difficulty="normal",
        planner_executor=None,
        clear_group_size=4,
        garbage_type="garbage",
    ):
        self.difficulty = difficulty
        self.planner_executor = planner_executor
        self.clear_group_size = clear_group_size
        self.max_garbage_drop = game_logic.ai_max_garbage_drop
        self.custom_settings = game_logic.custom_ai_settings.copy()
        self.calculation_distance = game_logic.ai_calculation_distance
        self.prioritize_max_chain = False
        self.garbage_pressure = False
        self.garbage_pressure_signature = (0, 0, False, False)
        self.garbage_response_pending = False
        self.garbage_response_piece_generation = None
        self.garbage_response_consumed = False
        if garbage_type not in game_logic.GARBAGE_TYPE_BLOCKS:
            raise ValueError(f"Unknown garbage type: {garbage_type}")
        self.garbage_type = garbage_type
        self.planning_future = None
        self.planning_difficulty = None
        self.planning_piece_generation = None
        self.planning_task_kind = None
        self.planning_frontier = None
        self.planning_locked_steps = []
        self.last_locked_target = None
        self.garbage_fall_spawn_piece = None
        self.restart()

    def set_difficulty(self, difficulty):
        if difficulty not in self.DIFFICULTIES:
            raise ValueError(f"Unknown AI difficulty: {difficulty}")
        if self.difficulty == difficulty:
            return
        self.difficulty = difficulty
        self._invalidate_search_state()
        self.planned_followups = []
        if self.piece is not None:
            if self.planner_executor is None:
                self._apply_placement_plan(
                    self._choose_placement_plan(self.piece)
                )
            else:
                self._request_placement()

    def set_custom_settings(self, settings):
        if self.custom_settings == settings:
            return
        self.custom_settings = settings.copy()
        if self.difficulty == "custom" and self.piece is not None:
            self._invalidate_search_state()
            self.planned_followups = []
            if self.planner_executor is None:
                self._apply_placement_plan(
                    self._choose_placement_plan(self.piece)
                )
            else:
                self._request_placement()

    def set_calculation_distance(self, distance):
        if type(distance) is not int or not 0 <= distance <= 30:
            raise ValueError(
                "AI calculation distance must be an integer from 0 to 30"
            )
        if self.calculation_distance == distance:
            return
        self.calculation_distance = distance
        self._invalidate_search_state()
        queue_size = max(3, distance)
        self.piece_queue = self.piece_queue[:queue_size]
        while len(self.piece_queue) < queue_size:
            self.piece_queue.append(game_logic.Piece())
        self.planned_followups = []
        if self.piece is not None:
            if self.planner_executor is None:
                self._apply_placement_plan(
                    self._choose_placement_plan(self.piece)
                )
            else:
                self._request_placement()

    def _difficulty_settings(self):
        if self.difficulty != "custom":
            settings = self.DIFFICULTIES[self.difficulty].copy()
        else:
            settings = {
                "drop_delay": (
                    None
                    if not self.custom_settings["soft_drop_enabled"]
                    else (
                        0
                        if self.custom_settings["soft_drop_seconds"] == 0
                        else round(
                            self.custom_settings["soft_drop_seconds"] * 1000
                        )
                    )
                ),
                "action_interval": round(
                    self.custom_settings["action_interval_seconds"] * 1000
                )
                if self.custom_settings["action_interval_seconds"] > 0
                else HORIZONTAL_REPEAT_INTERVAL,
                "chain_goal": self.custom_settings["chain_goal"],
            }
        if self.garbage_pressure or self.garbage_response_pending:
            settings["drop_delay"] = 0
            settings["action_interval"] = HORIZONTAL_REPEAT_INTERVAL
        return settings

    def _board_heights(self, board):
        return [
            BOARD_H
            - next(
                (
                    y
                    for y in range(BOARD_H)
                    if board[y][x] is not None
                ),
                BOARD_H,
            )
            for x in range(BOARD_W)
        ]

    def _is_urgent_mode(self, board):
        return board[0][2] is not None or max(
            self._board_heights(board),
            default=0,
        ) >= BOARD_H - 4

    def set_clear_group_size(self, size):
        if not 2 <= size <= 6:
            raise ValueError("Clear group size must be between 2 and 6")
        if self.clear_group_size == size:
            return
        self.clear_group_size = size
        self._invalidate_search_state()
        self.planned_followups = []
        if self.piece is not None:
            if self.planner_executor is None:
                self._apply_placement_plan(
                    self._choose_placement_plan(self.piece)
                )
            else:
                self._request_placement()

    def set_max_garbage_drop(self, count):
        game_logic.set_max_garbage_drop("ai", count)
        self.max_garbage_drop = count

    def set_garbage_type(self, garbage_type):
        if garbage_type not in game_logic.GARBAGE_TYPE_BLOCKS:
            raise ValueError(f"Unknown garbage type: {garbage_type}")
        self.garbage_type = garbage_type

    def restart(self):
        if self.planning_future is not None:
            self.planning_future.cancel()
        self.planning_future = None
        self.planning_difficulty = None
        self.planning_piece_generation = None
        self.planning_task_kind = None
        self.planning_frontier = None
        self.planning_locked_steps = []
        self.last_locked_target = None
        self.garbage_fall_spawn_piece = None
        self.piece_generation = 0
        self.prioritize_max_chain = False
        self.planned_followups = []
        self.board = [[None for _ in range(BOARD_W)] for _ in range(BOARD_H)]
        self.piece_queue = [
            game_logic.Piece()
            for _ in range(max(3, self.calculation_distance))
        ]
        self.piece = None
        self.fall_timer = 0
        self.contact_timer = 0
        self.resolution_phase = None
        self.clearing_groups = []
        self.clearing_elapsed = 0
        self.chain_count = 0
        self.chain_attack_event = None
        self.top_out_pending = False
        self.top_out_drop_done = False
        self.needs_post_delivery_lock = False
        self.incoming_attack_lockout_active = False
        self.hidden_garbage = []
        self.garbage_pressure = False
        self.garbage_pressure_signature = (0, 0, False, False)
        self.garbage_response_pending = False
        self.garbage_response_piece_generation = None
        self.garbage_response_consumed = False
        self.garbage_fall_blocks = []
        self.garbage_fall_elapsed = 0
        self.game_over = False
        self.rotation_animation = None
        self.piece_age = 0
        self.placement_ready = False
        self.placement_replan_pending = False
        self.action_elapsed = 0
        self.target_x = None
        self.target_rot = None
        self.current_fall_interval = FALL_INTERVAL
        self._spawn_piece()

    def _invalidate_search_state(self):
        self.planning_frontier = None
        self.planning_locked_steps = []
        if self.planning_future is not None:
            self.planning_piece_generation = None

    def valid(self, candidate):
        return game_logic.valid(candidate, self.board)

    def can_move_down(self, candidate):
        test = copy.copy(candidate)
        test.y += 1
        return self.valid(test)

    def _settle_board(self, board):
        while game_logic.apply_board_gravity(board):
            pass

    def _simulate_placement(self, candidate, board):
        simulated = [row[:] for row in board]
        game_logic.lock_piece(candidate, simulated)
        self._settle_board(simulated)
        total_cleared = 0
        chain_length = 0
        while True:
            groups = game_logic.find_match_groups(
                simulated,
                self.clear_group_size,
            )
            if not groups:
                break
            chain_length += 1
            total_cleared += sum(len(group) for group in groups)
            game_logic.clear_groups_with_adjacent_garbage(
                simulated,
                groups,
            )
            self._settle_board(simulated)
        return simulated, chain_length, total_cleared

    def _best_two_piece_followup(self, board):
        if len(self.piece_queue) < 2:
            return 0, self._chain_setup_potential(board), (None, None)
        goal = self._difficulty_settings()["chain_goal"]
        best_plan_score = None
        best_plan = (0, 0)
        best_targets = (None, None)
        for first_candidate in self._landing_positions(
            self.piece_queue[0], board
        ):
            after_first, first_chain, _ = self._simulate_placement(
                first_candidate, board
            )
            first_setup = self._chain_setup_potential(after_first)
            first_plan = (first_chain, first_setup)
            first_score = (
                int(after_first[0][2] is None),
                first_setup * 1_500_000
                + self._chain_goal_reward(first_chain, goal)
                - self._short_chain_penalty(
                    first_chain,
                    goal,
                    after_first,
                )
                - self._board_safety_penalty(after_first),
            )
            if best_plan_score is None or first_score > best_plan_score:
                best_plan = first_plan
                best_plan_score = first_score
                best_targets = (
                    (first_candidate.x, first_candidate.rot),
                    None,
                )
            for second_candidate in self._landing_positions(
                self.piece_queue[1], after_first
            ):
                after_second, second_chain, _ = self._simulate_placement(
                    second_candidate, after_first
                )
                plan = (
                    max(first_chain, second_chain),
                    max(
                        first_setup,
                        self._chain_setup_potential(after_second),
                    ),
                )
                plan_score = (
                    int(after_second[0][2] is None),
                    plan[1] * 1_500_000
                    + self._chain_goal_reward(plan[0], goal)
                    - self._short_chain_penalty(
                        first_chain,
                        goal,
                        after_first,
                    )
                    - self._short_chain_penalty(
                        second_chain,
                        goal,
                        after_second,
                    )
                    - self._board_safety_penalty(after_second),
                )
                if best_plan_score is None or plan_score > best_plan_score:
                    best_plan = plan
                    best_plan_score = plan_score
                    best_targets = (
                        (first_candidate.x, first_candidate.rot),
                        (second_candidate.x, second_candidate.rot),
                    )
        return best_plan[0], best_plan[1], best_targets

    def _chain_goal_reward(self, chain_length, goal):
        if chain_length > goal:
            return -12_000_000 - (chain_length - goal) * 100_000
        if chain_length < goal:
            return 0
        return 12_000_000 + chain_length * 100_000

    def _short_chain_penalty(self, chain_length, goal, board):
        if not 0 < chain_length < goal:
            return 0
        danger_height = max(
            BOARD_H
            - next(
                (
                    y
                    for y in range(BOARD_H)
                    if board[y][2] is not None
                ),
                BOARD_H,
            ),
            max(
                (
                    BOARD_H
                    - next(
                        (
                            y
                            for y in range(BOARD_H)
                            if board[y][x] is not None
                        ),
                        BOARD_H,
                    )
                    for x in range(BOARD_W)
                ),
                default=0,
            ),
        )
        danger_threshold = BOARD_H - 4
        danger = min(
            max(danger_height - danger_threshold, 0)
            / max(BOARD_H - danger_threshold, 1),
            1,
        )
        remaining_goal = (goal - chain_length) / goal
        return (
            1_500_000
            * remaining_goal
            * (1 - danger) ** 2
        )

    def _board_safety_penalty(self, board):
        heights = [
            BOARD_H
            - next(
                (
                    y
                    for y in range(BOARD_H)
                    if board[y][x] is not None
                ),
                BOARD_H,
            )
            for x in range(BOARD_W)
        ]
        peak_height = max(heights, default=0)
        x_column_height = heights[2]
        general_risk = max(peak_height - (BOARD_H - 8), 0)
        x_column_risk = max(x_column_height - (BOARD_H - 9), 0)
        return (
            general_risk * general_risk * 160_000
            + x_column_risk * x_column_risk * 320_000
            + (20_000_000 if board[0][2] is not None else 0)
        )

    def _chain_setup_potential(self, board):
        visited = set()
        potential = 0
        for y in range(BOARD_H):
            for x in range(BOARD_W):
                color = board[y][x]
                if (
                    color is None
                    or game_logic.is_garbage(color)
                    or game_logic.is_frozen_color(color)
                    or (x, y) in visited
                ):
                    continue
                component = [(x, y)]
                visited.add((x, y))
                for current_x, current_y in component:
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
                        if board[neighbor_y][neighbor_x] != color:
                            continue
                        visited.add((neighbor_x, neighbor_y))
                        component.append((neighbor_x, neighbor_y))

                if 1 <= len(component) < self.clear_group_size:
                    completion = min(
                        len(component) / max(self.clear_group_size - 1, 1),
                        1,
                    )
                    potential += completion * completion
        return potential

    def _chain_setup_score(self, board, heights=None):
        if heights is None:
            heights = self._board_heights(board)
        tower_penalty = sum(
            max(height - 3, 0) ** 2
            for height in heights
        )
        return (
            self._chain_setup_potential(board)
            - tower_penalty * 0.25
        )

    def _best_possible_chain(self, board, goal):
        best_chain = 0
        prototype = game_logic.Piece()
        candidates = list(self._landing_positions(prototype, board))
        colors = game_logic.active_color_indices
        for color_a in colors:
            for color_b in colors:
                for candidate in candidates:
                    candidate.c1 = color_a
                    candidate.c2 = color_b
                    _, chain_length, _ = self._simulate_placement(
                        candidate,
                        board,
                    )
                    best_chain = max(best_chain, chain_length)
                    if best_chain >= goal:
                        return best_chain
        return best_chain

    def _latent_chain_potential(self, board):
        visited = set()
        best_chain = 0
        best_score = 0.0
        for y in range(BOARD_H):
            for x in range(BOARD_W):
                color = board[y][x]
                if (
                    color is None
                    or game_logic.is_garbage(color)
                    or game_logic.is_frozen_color(color)
                    or (x, y) in visited
                ):
                    continue
                component = [(x, y)]
                visited.add((x, y))
                for current_x, current_y in component:
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
                        if board[neighbor_y][neighbor_x] != color:
                            continue
                        visited.add((neighbor_x, neighbor_y))
                        component.append((neighbor_x, neighbor_y))

                if not 1 <= len(component) < self.clear_group_size:
                    continue
                simulated = [row[:] for row in board]
                game_logic.clear_groups_with_adjacent_garbage(
                    simulated,
                    [component],
                )
                self._settle_board(simulated)
                chain_length = 1
                while True:
                    groups = game_logic.find_match_groups(
                        simulated,
                        self.clear_group_size,
                    )
                    if not groups:
                        break
                    chain_length += 1
                    game_logic.clear_groups_with_adjacent_garbage(
                        simulated,
                        groups,
                    )
                    self._settle_board(simulated)
                completion = min(
                    len(component) / max(self.clear_group_size - 1, 1),
                    1,
                )
                potential_score = chain_length * completion
                if potential_score > best_score:
                    best_chain = chain_length
                    best_score = potential_score
        return best_chain, best_score

    def _piece_state_key(self, piece):
        return (
            piece.x,
            piece.y,
            piece.rot,
            piece.kick_x,
            piece.kick_y,
        )

    def _piece_transitions(self, piece, board):
        for direction, action in ((-1, "left"), (1, "right")):
            candidate = _copy_piece(piece)
            candidate.x += direction
            if game_logic.valid(candidate, board):
                yield action, candidate

        for direction, action in ((-1, "rotate_left"), (1, "rotate_right")):
            candidate = _copy_piece(piece)
            if game_logic.rotate_piece(
                candidate,
                direction,
                target_board=board,
            ):
                yield action, candidate

        candidate = _copy_piece(piece)
        candidate.y += 1
        if game_logic.valid(candidate, board):
            yield "down", candidate

    def _reachable_targets(self, piece, board):
        start = copy.copy(piece)
        if not game_logic.valid(start, board):
            return set()
        queue = deque([start])
        visited = {self._piece_state_key(start)}
        targets = set()
        while queue:
            current = queue.popleft()
            targets.add((current.x, current.rot))
            for _, candidate in self._piece_transitions(current, board):
                key = self._piece_state_key(candidate)
                if key not in visited:
                    visited.add(key)
                    queue.append(candidate)
        return targets

    def _route_action_to_target(self, piece, board):
        start = copy.copy(piece)
        start_key = self._piece_state_key(start)
        queue = deque([(start, None)])
        visited = {start_key}
        while queue:
            current, first_action = queue.popleft()
            if current.x == self.target_x and current.rot == self.target_rot:
                return "done" if first_action is None else first_action
            for action, candidate in self._piece_transitions(current, board):
                key = self._piece_state_key(candidate)
                if key in visited:
                    continue
                visited.add(key)
                queue.append(
                    (
                        candidate,
                        action if first_action is None else first_action,
                    )
                )
        return None

    def _landing_positions(self, piece, board, require_reachable=False):
        reachable_targets = (
            self._reachable_targets(piece, board)
            if require_reachable
            else None
        )
        for rotation in range(4):
            for x in range(BOARD_W):
                candidate = copy.copy(piece)
                candidate.x = x
                candidate.y = piece.y
                candidate.rot = rotation
                candidate.kick_x = 0
                candidate.kick_y = 0
                if (
                    reachable_targets is not None
                    and (x, rotation) not in reachable_targets
                ):
                    continue
                if not game_logic.valid(candidate, board):
                    continue
                while True:
                    test = copy.copy(candidate)
                    test.y += 1
                    if not game_logic.valid(test, board):
                        break
                    candidate.y += 1
                if not any(y < 0 for _, y, _ in candidate.get_blocks()):
                    yield candidate

    def _placement_score(self, candidate, board=None):
        if board is None:
            board = self.board
        simulated, chain_length, total_cleared = self._simulate_placement(
            candidate, board
        )
        heights = self._board_heights(simulated)
        holes = sum(
            cell is None
            for x in range(BOARD_W)
            for y, cell in enumerate(simulated)
            if any(simulated[above][x] is not None for above in range(y))
        )

        goal = self._difficulty_settings()["chain_goal"]
        urgent_mode = (
            self.garbage_pressure
            or self.garbage_response_pending
            or self._is_urgent_mode(board)
        )
        if urgent_mode:
            followup_chain = 0
            setup_potential = 0
            followup_targets = (None, None)
        else:
            followup_chain, setup_potential, followup_targets = (
                self._best_two_piece_followup(simulated)
            )
            setup_potential -= sum(
                max(height - 3, 0) ** 2
                for height in heights
            ) * 0.25
        best_chain = max(chain_length, followup_chain)
        safety_score = -self._board_safety_penalty(simulated)
        shape_score = (
            -sum(height * height for height in heights) * 1_000
            - abs(candidate.x - (BOARD_W - 1) / 2) * 1_000
            - max(heights, default=0) * 12
            - holes * 30
            + total_cleared * 10
        )
        if urgent_mode:
            score = (
                int(simulated[0][2] is None),
                int(chain_length <= goal),
                chain_length if chain_length <= goal else 0,
                chain_length,
                safety_score,
                shape_score,
            )
            return score, followup_targets

        score = (
            setup_potential * 1_500_000
            + self._chain_goal_reward(best_chain, goal)
            - self._short_chain_penalty(chain_length, goal, simulated)
            + safety_score
            + shape_score
        )
        return (int(simulated[0][2] is None), score), followup_targets

    def _choose_fallback_placement(self, piece, board=None):
        if board is None:
            board = self.board
        urgent_mode = (
            self.garbage_pressure
            or self.garbage_response_pending
            or self._is_urgent_mode(board)
        )
        candidates = []
        goal = self._difficulty_settings()["chain_goal"]
        for candidate in self._landing_positions(
            piece,
            board,
            require_reachable=True,
        ):
            simulated, chain_length, total_cleared = (
                self._simulate_placement(candidate, board)
            )
            heights = self._board_heights(simulated)
            holes = sum(
                cell is None
                for x in range(BOARD_W)
                for y, cell in enumerate(simulated)
                if any(simulated[above][x] is not None for above in range(y))
            )
            safety_score = -self._board_safety_penalty(simulated)
            shape_score = (
                -sum(height * height for height in heights) * 1_000
                -abs(candidate.x - (BOARD_W - 1) / 2) * 1_000
                -max(heights, default=0) * 12
                -holes * 30
                +total_cleared * 10
            )
            if urgent_mode:
                score = (
                    int(simulated[0][2] is None),
                    int(chain_length <= goal),
                    chain_length if chain_length <= goal else 0,
                    chain_length,
                    safety_score,
                    shape_score,
                )
            else:
                score = (
                    int(simulated[0][2] is None),
                    int(chain_length <= goal),
                    chain_length,
                    self._chain_setup_score(simulated, heights),
                    safety_score,
                    shape_score,
                )
            candidates.append((score, candidate))
        if not candidates:
            return []
        _, best_candidate = max(candidates, key=lambda item: item[0])
        return [(best_candidate.x, best_candidate.rot)]

    def _choose_placement(self, piece, board=None):
        plan = self._choose_placement_plan(piece, board)
        return plan[0] if plan else None

    def _choose_placement_plan(
        self,
        piece,
        board=None,
        return_search_state=False,
        force_chain_search=False,
    ):
        if board is None:
            board = self.board
        goal = self._difficulty_settings()["chain_goal"]
        urgent_mode = (
            self.garbage_pressure
            or self.garbage_response_pending
            or self._is_urgent_mode(board)
        )
        max_chain_mode = (
            self.prioritize_max_chain
            or force_chain_search
            or urgent_mode
        )
        pieces = [
            piece,
            *self.piece_queue[:self.calculation_distance],
        ]
        search_beam_width = max(
            2,
            min(
                self.PLANNER_BEAM_WIDTH,
                384 // len(pieces),
            ),
        )
        beam = [((1, 0, 0, 0, 0, 0, 0), board, 0, 0, None, [], 0)]
        completed_plans = []
        for planned_piece in pieces:
            expanded = []
            goal_plans = []
            for (
                _,
                current_board,
                best_chain,
                short_chain_count,
                goal_turn,
                path,
                peak_height,
            ) in beam:
                candidate_states = []
                for candidate in self._landing_positions(
                    planned_piece,
                    current_board,
                    require_reachable=True,
                ):
                    next_board, chain_length, _ = self._simulate_placement(
                        candidate,
                        current_board,
                    )
                    if next_board[0][2] is not None:
                        continue
                    candidate_states.append(
                        (candidate, next_board, chain_length)
                    )
                bounded_states = [
                    state
                    for state in candidate_states
                    if state[2] <= goal
                ]
                if bounded_states:
                    candidate_states = bounded_states
                for candidate, next_board, chain_length in candidate_states:
                    next_best_chain = max(best_chain, chain_length)
                    next_short_chain_count = short_chain_count + int(
                        0 < chain_length < goal
                    )
                    next_path = [*path, (candidate.x, candidate.rot)]
                    next_goal_turn = goal_turn
                    reached_goal = (
                        next_goal_turn is None and chain_length >= goal
                    )
                    if reached_goal:
                        next_goal_turn = len(next_path)
                    heights = self._board_heights(next_board)
                    next_peak_height = max(
                        peak_height,
                        max(heights, default=0),
                    )
                    setup_potential = self._chain_setup_score(
                        next_board,
                        heights,
                    )
                    if max_chain_mode:
                        rank = (
                            -next_short_chain_count,
                            int(next_goal_turn is not None),
                            int(next_best_chain <= goal),
                            min(next_best_chain, goal),
                            -max(0, next_best_chain - goal),
                            -next_peak_height,
                            -self._board_safety_penalty(next_board),
                            setup_potential,
                            -sum(height * height for height in heights),
                        )
                    else:
                        rank = (
                            int(next_board[0][2] is None),
                            -next_short_chain_count,
                            int(next_goal_turn is not None),
                            (
                                -next_goal_turn
                                if next_goal_turn is not None
                                else 0
                            ),
                            -next_peak_height,
                            -self._board_safety_penalty(next_board),
                            setup_potential,
                            -sum(height * height for height in heights),
                            next_best_chain,
                        )
                    state = (
                        rank,
                        next_board,
                        next_best_chain,
                        next_short_chain_count,
                        next_goal_turn,
                        next_path,
                        next_peak_height,
                    )
                    expanded.append(state)
                    if reached_goal:
                        goal_plans.append(state)
            if not expanded:
                break
            bounded_expanded = [
                state for state in expanded if state[2] <= goal
            ]
            if bounded_expanded:
                expanded = bounded_expanded
                goal_plans = [
                    state for state in goal_plans if state[2] <= goal
                ]
            safer_expanded = [
                state for state in expanded if state[6] <= BOARD_H - 5
            ]
            if safer_expanded:
                expanded = safer_expanded
                goal_plans = [
                    state
                    for state in goal_plans
                    if state[6] <= BOARD_H - 5
                ]
            expanded.sort(key=lambda item: item[0], reverse=True)
            if goal_plans:
                goal_plans.sort(key=lambda item: item[0], reverse=True)
                beam = goal_plans[:search_beam_width]
                completed_plans = beam
                break
            beam = expanded[:search_beam_width]
            completed_plans = expanded[:search_beam_width]
        if not completed_plans:
            return ([], None) if return_search_state else []
        best_path = self._select_frontier_plan(
            completed_plans,
            goal,
            max_chain_mode,
        )
        if return_search_state:
            return best_path, beam
        return best_path

    def _select_frontier_plan(
        self,
        frontier,
        goal,
        prioritize_max_chain=None,
    ):
        if prioritize_max_chain is None:
            prioritize_max_chain = self.prioritize_max_chain
        if prioritize_max_chain:
            best_state = max(
                frontier,
                key=lambda item: (
                    int(item[2] >= goal),
                    int(item[2] == goal),
                    int(item[2] <= goal),
                    min(item[2], goal),
                    -max(0, item[2] - goal),
                    -item[6],
                    -item[3],
                    -self._board_safety_penalty(item[1]),
                    self._chain_setup_score(item[1]),
                    item[0][-1],
                ),
            )
            return best_state[5]
        ranked_plans = []
        for (
            rank,
            final_board,
            best_chain,
            short_chain_count,
            goal_turn,
            path,
            peak_height,
        ) in frontier[:8]:
            possible_chain = (
                0
                if best_chain >= goal
                else self._best_possible_chain(final_board, goal)
            )
            latent_chain, latent_score = self._latent_chain_potential(
                final_board
            )
            target_reached = (
                best_chain >= goal or possible_chain >= goal
            )
            setup_potential = self._chain_setup_score(final_board)
            tower_penalty = sum(
                max(height - 3, 0) ** 2
                for height in self._board_heights(final_board)
            ) * 0.25
            chain_progress = max(
                setup_potential,
                latent_score - tower_penalty,
            )
            target_turn = (
                goal_turn
                if goal_turn is not None
                else (
                    len(path) + 1
                    if possible_chain == goal
                    else (len(path) + 2 if target_reached else 0)
                )
            )
            extended_rank = (
                rank[0],
                int(target_reached),
                -target_turn if target_reached else 0,
                -peak_height,
                rank[4],
                rank[5],
                -short_chain_count,
                chain_progress,
                setup_potential,
                max(best_chain, possible_chain, latent_chain),
            )
            ranked_plans.append((extended_rank, path))
        _, best_path = max(ranked_plans, key=lambda item: item[0])
        return best_path

    def _advance_search_frontier(
        self,
        frontier,
        target,
        added_piece,
        prioritize_max_chain=None,
    ):
        if prioritize_max_chain is None:
            prioritize_max_chain = self.prioritize_max_chain
        goal = self._difficulty_settings()["chain_goal"]
        retained = []
        for (
            rank,
            board,
            best_chain,
            short_chain_count,
            goal_turn,
            path,
            peak_height,
        ) in frontier:
            if not path or path[0] != target:
                continue
            retained.append(
                (
                    rank,
                    board,
                    best_chain,
                    short_chain_count,
                    max(0, goal_turn - 1) if goal_turn is not None else None,
                    path[1:],
                    peak_height,
                )
            )
        if not retained:
            return None, None

        expanded = []
        goal_plans = []
        for (
            _,
            current_board,
            best_chain,
            short_chain_count,
            goal_turn,
            path,
            peak_height,
        ) in retained:
            candidate_states = []
            for candidate in self._landing_positions(
                added_piece,
                current_board,
                require_reachable=True,
            ):
                next_board, chain_length, _ = self._simulate_placement(
                    candidate,
                    current_board,
                )
                if next_board[0][2] is not None:
                    continue
                candidate_states.append(
                    (candidate, next_board, chain_length)
                )
            bounded_states = [
                state
                for state in candidate_states
                if state[2] <= goal
            ]
            if bounded_states:
                candidate_states = bounded_states
            for candidate, next_board, chain_length in candidate_states:
                next_best_chain = max(best_chain, chain_length)
                next_short_chain_count = short_chain_count + int(
                    0 < chain_length < goal
                )
                next_path = [*path, (candidate.x, candidate.rot)]
                next_goal_turn = goal_turn
                reached_goal = (
                    next_goal_turn is None and chain_length >= goal
                )
                if reached_goal:
                    next_goal_turn = len(next_path)
                heights = self._board_heights(next_board)
                next_peak_height = max(
                    peak_height,
                    max(heights, default=0),
                )
                if prioritize_max_chain:
                    rank = (
                        -next_short_chain_count,
                        int(next_goal_turn is not None),
                        int(next_best_chain <= goal),
                        min(next_best_chain, goal),
                        -max(0, next_best_chain - goal),
                        -next_peak_height,
                        -self._board_safety_penalty(next_board),
                        -next_goal_turn if next_goal_turn is not None else 0,
                        self._chain_setup_score(next_board, heights),
                        -sum(height * height for height in heights),
                    )
                else:
                    rank = (
                        int(next_board[0][2] is None),
                        -next_short_chain_count,
                        int(next_goal_turn is not None),
                        -next_goal_turn if next_goal_turn is not None else 0,
                        -next_peak_height,
                        -self._board_safety_penalty(next_board),
                        self._chain_setup_score(next_board, heights),
                        -sum(height * height for height in heights),
                        next_best_chain,
                    )
                state = (
                    rank,
                    next_board,
                    next_best_chain,
                    next_short_chain_count,
                    next_goal_turn,
                    next_path,
                    next_peak_height,
                )
                expanded.append(state)
                if reached_goal:
                    goal_plans.append(state)
        if not expanded:
            return None, None
        bounded_expanded = [
            state for state in expanded if state[2] <= goal
        ]
        if bounded_expanded:
            expanded = bounded_expanded
            goal_plans = [
                state for state in goal_plans if state[2] <= goal
            ]
        safer_expanded = [
            state for state in expanded if state[6] <= BOARD_H - 5
        ]
        if safer_expanded:
            expanded = safer_expanded
            goal_plans = [
                state
                for state in goal_plans
                if state[6] <= BOARD_H - 5
            ]
        expanded.sort(key=lambda item: item[0], reverse=True)
        if goal_plans:
            goal_plans.sort(key=lambda item: item[0], reverse=True)
            frontier = goal_plans[:self.PLANNER_BEAM_WIDTH]
            return (
                self._select_frontier_plan(
                    frontier,
                    goal,
                    prioritize_max_chain,
                ),
                frontier,
            )
        beam_width = max(
            2,
            min(
                self.PLANNER_BEAM_WIDTH,
                384 // (self.calculation_distance + 1),
            ),
        )
        frontier = expanded[:beam_width]
        return (
            self._select_frontier_plan(
                frontier,
                goal,
                prioritize_max_chain,
            ),
            frontier,
        )

    def _spawn_piece(self):
        if (
            self.garbage_response_pending
            and self.garbage_response_consumed
            and not self.garbage_pressure
        ):
            self.garbage_response_pending = False
            self.garbage_response_piece_generation = None
            self.garbage_response_consumed = False
        self.piece = self.piece_queue.pop(0)
        next_queued_piece = (
            self.garbage_fall_spawn_piece
            if self.garbage_fall_spawn_piece is not None
            else game_logic.Piece()
        )
        self.garbage_fall_spawn_piece = None
        self.piece_queue.append(next_queued_piece)
        self.piece_generation += 1
        if self.last_locked_target is not None:
            step = (
                self.last_locked_target,
                copy.copy(next_queued_piece),
            )
            if self.planning_future is not None:
                self.planning_locked_steps.append(step)
            elif self.planning_frontier is not None:
                self._request_frontier_advance([step])
            self.last_locked_target = None
        if self.garbage_response_pending:
            self.garbage_response_piece_generation = self.piece_generation
            self.garbage_response_consumed = False
        self.piece.y = 0
        self.fall_timer = 0
        self.contact_timer = 0
        self.piece_age = 0
        self.placement_ready = False
        self.placement_replan_pending = False
        self.action_elapsed = 0
        self.current_fall_interval = FALL_INTERVAL
        self.rotation_animation = None
        next_target = (
            self.planned_followups.pop(0)
            if self.planned_followups
            else None
        )
        if not self.prioritize_max_chain and (
            self.garbage_pressure
            or self.garbage_response_pending
            or self._is_urgent_mode(self.board)
        ):
            self._invalidate_search_state()
            self.planned_followups = []
            next_target = None
        if next_target is not None:
            self._apply_placement(next_target)
        if self.planner_executor is None and next_target is None:
            plan = self._choose_placement_plan(self.piece)
            self._apply_placement_plan(plan)
        elif self.planner_executor is not None and next_target is None:
            self._request_placement()

    def _request_placement(self):
        if self.planner_executor is None:
            self.placement_replan_pending = False
            self._apply_placement_plan(
                self._choose_placement_plan(self.piece)
            )
            return
        if self.target_x is None or self.target_rot is None:
            fallback_plan = self._choose_fallback_placement(self.piece)
            if fallback_plan:
                self._apply_placement(fallback_plan[0])
        self.placement_replan_pending = False
        if (
            self.planning_future is not None
            and not self.planning_future.done()
        ):
            return
        if self.planning_future is not None:
            self.planning_future.cancel()
        self.planning_frontier = None
        self.planning_locked_steps = []
        self.planning_difficulty = self.difficulty
        self.planning_piece_generation = self.piece_generation
        self.planning_future = self.planner_executor.submit(
            _choose_placement_worker,
            [row[:] for row in self.board],
            copy.copy(self.piece),
            [copy.copy(piece) for piece in self.piece_queue],
            self.difficulty,
            self.clear_group_size,
            self.custom_settings.copy(),
            self.garbage_pressure or self.garbage_response_pending,
            self.calculation_distance,
            (
                self.prioritize_max_chain
                or self.garbage_pressure
                or self.garbage_response_pending
                or self._is_urgent_mode(self.board)
            ),
        )
        self.planning_task_kind = "plan"

    def _request_frontier_advance(self, steps, frontier=None):
        if frontier is None:
            frontier = self.planning_frontier
        if not frontier:
            if self.piece is not None and self.resolution_phase is None:
                self._request_placement()
            return
        prioritize_max_chain = (
            self.prioritize_max_chain
            or self.garbage_pressure
            or self.garbage_response_pending
            or self._is_urgent_mode(self.board)
        )
        if self.planner_executor is None:
            plan = None
            for target, added_piece in steps:
                plan, frontier = self._advance_search_frontier(
                    frontier,
                    target,
                    added_piece,
                    prioritize_max_chain,
                )
                if frontier is None:
                    self.planning_frontier = None
                    if self.piece is not None and self.resolution_phase is None:
                        self._request_placement()
                    return
            self.planning_frontier = frontier
            self.planned_followups = plan
            return

        self.planning_piece_generation = self.piece_generation
        self.planning_difficulty = self.difficulty
        self.planning_locked_steps = []
        self.planning_future = self.planner_executor.submit(
            _advance_frontier_worker,
            frontier,
            steps,
            self.difficulty,
            self.clear_group_size,
            self.custom_settings.copy(),
            self.calculation_distance,
            prioritize_max_chain,
        )
        self.planning_task_kind = "advance"

    def _request_garbage_fall_plan(self):
        if self.planning_future is not None:
            return
        if self.garbage_fall_spawn_piece is None:
            self.garbage_fall_spawn_piece = game_logic.Piece()
        projected_board = [row[:] for row in self.board]
        for block in self.garbage_fall_blocks:
            x, y = block["x"], block["y"]
            if y >= 0:
                projected_board[y][x] = block["block"]
        queued_pieces = [
            copy.copy(piece) for piece in self.piece_queue[1:]
        ]
        queued_pieces.append(copy.copy(self.garbage_fall_spawn_piece))
        next_piece = copy.copy(self.piece_queue[0])
        custom_settings = self.custom_settings.copy()
        if self.planner_executor is None:
            result = _choose_placement_worker(
                projected_board,
                next_piece,
                queued_pieces,
                self.difficulty,
                self.clear_group_size,
                custom_settings,
                False,
                self.calculation_distance,
                True,
            )
            self._apply_search_result(
                result,
                self.piece_generation + 1,
                self.difficulty,
            )
            return
        self.planning_difficulty = self.difficulty
        self.planning_piece_generation = self.piece_generation + 1
        self.planning_future = self.planner_executor.submit(
            _choose_placement_worker,
            projected_board,
            next_piece,
            queued_pieces,
            self.difficulty,
            self.clear_group_size,
            custom_settings,
            False,
            self.calculation_distance,
            True,
        )
        self.prioritize_max_chain = True
        self.planning_task_kind = "garbage"

    def _begin_garbage_fall_planning(self):
        self._invalidate_search_state()
        self.prioritize_max_chain = True
        self.planned_followups = []
        self.last_locked_target = None
        self._request_garbage_fall_plan()

    def _apply_search_result(self, result, planned_generation, difficulty):
        plan, frontier = result
        if difficulty != self.difficulty:
            self.planning_locked_steps = []
            if self.piece is not None and self.resolution_phase is None:
                self._request_placement()
            elif self.resolution_phase == "garbage_falling":
                self._request_garbage_fall_plan()
            return
        if frontier is not None:
            self.planning_frontier = frontier
            if (
                self.piece is not None
                and self.resolution_phase is None
                and planned_generation == self.piece_generation
            ):
                self._apply_placement_plan(plan)
            elif (
                self.piece is None
                and planned_generation == self.piece_generation
            ):
                self.planned_followups = plan
            elif (
                self.piece is None
                and self.resolution_phase == "garbage_falling"
                and planned_generation == self.piece_generation + 1
            ):
                self.planned_followups = plan
            else:
                self.planning_frontier = None
                self.planned_followups = []
                if self.piece is not None and self.resolution_phase is None:
                    self._request_placement()
                return
            self.placement_replan_pending = False
            return

        if (
            self.piece is not None
            and self.resolution_phase is None
            and planned_generation == self.piece_generation
        ):
            self._apply_placement_plan(plan)
            self.placement_replan_pending = False
        elif self.piece is not None and self.resolution_phase is None:
            self._request_placement()
        elif (
            self.piece is None
            and (
                planned_generation == self.piece_generation
                or (
                    self.resolution_phase == "garbage_falling"
                    and planned_generation == self.piece_generation + 1
                )
            )
        ):
            self.planned_followups = plan
        elif self.resolution_phase == "garbage_falling":
            self._request_garbage_fall_plan()

    def _apply_placement_plan(self, plan):
        if not plan:
            self.game_over = True
            self.piece = None
            self.planned_followups = []
            return
        self._apply_placement(plan[0])
        self.planned_followups = plan[1:]

    def _apply_placement(self, target):
        if target is None:
            self.game_over = True
            self.piece = None
            return
        if (self.target_x, self.target_rot) != target:
            self.fall_timer = 0
            self.piece_age = 0
            self.current_fall_interval = FALL_INTERVAL
        self.target_x, self.target_rot = target
        self.placement_ready = False

    def _start_chain(self, groups):
        self.chain_count += 1
        self.clearing_groups = groups
        self.clearing_elapsed = 0
        self.resolution_phase = "chain_starting"
        self._invalidate_search_state()
        self.planned_followups = []
        self.last_locked_target = None

    def _lock_piece(self):
        self.last_locked_target = (self.piece.x, self.piece.rot)
        if (
            self.garbage_response_pending
            and self.garbage_response_piece_generation
            == self.piece_generation
        ):
            self.garbage_response_piece_generation = None
            self.garbage_response_consumed = True
        game_logic.lock_piece(self.piece, self.board)
        if self.incoming_attack_lockout_active:
            self.needs_post_delivery_lock = True
        self.top_out_pending = self.board[0][2] is not None
        self.top_out_drop_done = False
        self.piece = None
        self.target_x = None
        self.target_rot = None
        self.placement_ready = False
        self.chain_count = 0
        self.chain_attack_event = None
        self.resolution_phase = "falling"
        self.fall_timer = 0

    def _animate_rotation(self, direction, old_x, old_y, old_blocks):
        new_x, new_y, _ = self.piece.get_blocks()[1]
        self.rotation_animation = {
            "start_x": old_blocks[0] - old_x,
            "start_y": old_blocks[1] - old_y,
            "end_x": new_x - self.piece.x,
            "end_y": new_y - self.piece.y,
            "pivot_offset_x": old_x - self.piece.x,
            "pivot_offset_y": old_y - self.piece.y,
            "direction": direction,
            "steps": 1,
            "elapsed": 0,
        }

    def _take_planned_action(self):
        if self.piece is None:
            return
        action = self._route_action_to_target(self.piece, self.board)
        if action is None:
            self.target_x = None
            self.target_rot = None
            self.placement_ready = False
            self.planned_followups = []
            self.placement_replan_pending = True
            self._request_placement()
            return
        if action in ("done", "down"):
            return
        if action in ("rotate_left", "rotate_right"):
            direction = -1 if action == "rotate_left" else 1
            old_x, old_y = self.piece.x, self.piece.y
            old_blocks = self.piece.get_blocks()[1][:2]
            if game_logic.rotate_piece(self.piece, direction, target_board=self.board):
                self._animate_rotation(direction, old_x, old_y, old_blocks)
        elif action in ("left", "right"):
            self.piece.x += -1 if action == "left" else 1

    def update(
        self,
        dt,
        incoming_garbage_in_flight=False,
        incoming_garbage_traveling=False,
        opponent_chain_in_progress=False,
        deferred_garbage_value=0,
        attack_orbs=(),
    ):
        self.chain_attack_event = None
        if self.game_over:
            return
        self.incoming_attack_lockout_active = (
            incoming_garbage_in_flight
            or incoming_garbage_traveling
            or opponent_chain_in_progress
        )
        hidden_garbage_value = attack_system.garbage_value(
            self.hidden_garbage
        )
        garbage_pressure = (
            hidden_garbage_value >= 1
            or deferred_garbage_value >= 1
            or incoming_garbage_in_flight
            or incoming_garbage_traveling
        )
        pressure_signature = (
            hidden_garbage_value,
            deferred_garbage_value,
            incoming_garbage_in_flight,
            incoming_garbage_traveling,
        )
        pressure_changed = (
            pressure_signature != self.garbage_pressure_signature
        )
        self.garbage_pressure_signature = pressure_signature
        if garbage_pressure:
            if not self.garbage_response_pending:
                self.garbage_response_consumed = False
                self.garbage_response_piece_generation = (
                    self.piece_generation
                    if self.piece is not None
                    else None
                )
            self.garbage_response_pending = True
        self.garbage_pressure = garbage_pressure
        if pressure_changed:
            self.prioritize_max_chain = (
                garbage_pressure
                or self.garbage_response_pending
                or self._is_urgent_mode(self.board)
            )
            self._invalidate_search_state()
            self.planned_followups = []
            if self.piece is not None:
                self.target_x = None
                self.target_rot = None
                self.placement_ready = False
                self._request_placement()

        if self.planning_future is not None:
            if self.planning_future.done():
                result = self.planning_future.result()
                planned_generation = self.planning_piece_generation
                planned_difficulty = self.planning_difficulty
                planned_task_kind = self.planning_task_kind
                self.planning_future = None
                self.planning_piece_generation = None
                self.planning_difficulty = None
                self.planning_task_kind = None
                if planned_generation is not None:
                    if self.planning_locked_steps:
                        locked_steps = self.planning_locked_steps[:]
                        self.planning_locked_steps = []
                        if result[1] is not None:
                            self._request_frontier_advance(
                                locked_steps,
                                result[1],
                            )
                        elif self.piece is not None and self.resolution_phase is None:
                            self._request_placement()
                    elif planned_task_kind == "advance" and result[1] is None:
                        self.planning_frontier = None
                        if self.piece is not None and self.resolution_phase is None:
                            self._request_placement()
                    else:
                        if planned_task_kind == "garbage":
                            self.prioritize_max_chain = True
                        self._apply_search_result(
                            result,
                            planned_generation,
                            planned_difficulty,
                        )
                    if self.game_over:
                        return
                elif self.piece is not None and self.resolution_phase is None:
                    self._request_placement()
                elif self.resolution_phase == "garbage_falling":
                    self._request_garbage_fall_plan()

        if self.resolution_phase == "chain_starting":
            self.clearing_elapsed += dt
            delay = (
                CHAIN_START_DELAY
                if self.chain_count == 1
                else CHAIN_CONTINUE_START_DELAY
            )
            if self.clearing_elapsed >= delay:
                self.resolution_phase = "clearing"
                self.clearing_elapsed = 0
        elif self.resolution_phase == "clearing":
            self.clearing_elapsed += dt
            if self.clearing_elapsed >= CLEAR_DURATION:
                self.chain_attack_event = (
                    self.chain_count,
                    [group[:] for group in self.clearing_groups],
                )
                game_logic.clear_groups_with_adjacent_garbage(
                    self.board,
                    self.clearing_groups,
                )
                self.clearing_groups = []
                self.resolution_phase = "falling"
                self.fall_timer = 0
        elif self.resolution_phase == "garbage_falling":
            self.garbage_fall_elapsed += dt
            drop_complete = game_logic.advance_garbage_drop(
                self.board,
                self.garbage_fall_blocks,
                dt,
            )
            if drop_complete is None or drop_complete:
                self.garbage_fall_blocks = []
                self.garbage_fall_elapsed = 0
                if self.board[0][2] is not None:
                    self.top_out_pending = True
                    self.top_out_drop_done = True
                    self.resolution_phase = "settling"
                    self.clearing_elapsed = 0
                else:
                    self.top_out_pending = False
                    self.top_out_drop_done = False
                    self.resolution_phase = None
                    self._spawn_piece()
        elif self.resolution_phase == "falling":
            self.fall_timer += dt
            if self.fall_timer >= 80:
                self.fall_timer = 0
                if not game_logic.apply_board_gravity(self.board):
                    groups = game_logic.find_match_groups(
                        self.board,
                        self.clear_group_size,
                    )
                    if groups:
                        self._start_chain(groups)
                    else:
                        self.resolution_phase = "settling"
                        self.clearing_elapsed = 0
        elif self.resolution_phase == "settling":
            top_out_drop_complete = (
                self.top_out_pending
                and self.board[0][2] is not None
                and self.top_out_drop_done
            )
            ready_garbage = max(
                0,
                attack_system.garbage_value(self.hidden_garbage)
                - deferred_garbage_value,
            )
            ready_garbage = game_logic.effective_garbage_drop_count(
                ready_garbage,
                self.max_garbage_drop,
            )
            stack_cancellation_in_progress = (
                attack_system.has_stack_cancellation_in_progress(
                    attack_orbs,
                    "ai",
                )
            )
            if ready_garbage and stack_cancellation_in_progress:
                self.clearing_elapsed = 0
            else:
                self.clearing_elapsed += dt

            if (
                self.clearing_elapsed >= NEXT_PIECE_DELAY
            ):
                if top_out_drop_complete:
                    self.game_over = True
                    return
                if ready_garbage:
                    garbage_count = attack_system.garbage_value(
                        self.hidden_garbage
                    )
                    drop_count = ready_garbage
                    falling_blocks = game_logic.plan_garbage_drop(
                        self.board,
                        drop_count,
                        self.garbage_type,
                    )
                    if falling_blocks is None:
                        falling_blocks = []
                    self.hidden_garbage[:] = attack_system.garbage_from_value(
                        garbage_count - drop_count
                    )
                    self.needs_post_delivery_lock = False
                    self.garbage_fall_blocks = falling_blocks
                    self.garbage_fall_elapsed = 0
                    self.resolution_phase = "garbage_falling"
                    self._begin_garbage_fall_planning()
                    return
                if (
                    self.needs_post_delivery_lock
                    and not (
                        self.top_out_pending
                        and self.board[0][2] is not None
                    )
                ):
                    self.needs_post_delivery_lock = False
                    self.resolution_phase = None
                    self.clearing_elapsed = 0
                    self._spawn_piece()
                    return
                if (
                    self.top_out_pending
                    and self.board[0][2] is not None
                    and deferred_garbage_value > 0
                ):
                    return
                if (
                    not self.top_out_pending
                    and deferred_garbage_value > 0
                    and attack_system.garbage_value(self.hidden_garbage) > 0
                ):
                    self.resolution_phase = None
                    self.clearing_elapsed = 0
                    self._spawn_piece()
                    return
                if (
                    self.top_out_pending
                    and self.board[0][2] is not None
                    and (
                        deferred_garbage_value > 0
                        or incoming_garbage_in_flight
                        or incoming_garbage_traveling
                        or opponent_chain_in_progress
                    )
                ):
                    return
                if self.top_out_pending and self.board[0][2] is not None:
                    if self.top_out_drop_done:
                        self.game_over = True
                        return
                    if not attack_system.garbage_value(self.hidden_garbage):
                        self.game_over = True
                        return
                if (
                    incoming_garbage_in_flight
                    or incoming_garbage_traveling
                    or opponent_chain_in_progress
                ):
                    self.resolution_phase = None
                    self.clearing_elapsed = 0
                    self._spawn_piece()
                else:
                    garbage_count = attack_system.garbage_value(
                        self.hidden_garbage
                    )
                    if not garbage_count:
                        if self.top_out_pending and self.board[0][2] is not None:
                            self.game_over = True
                            return
                        self.top_out_pending = False
                        self.resolution_phase = None
                        self._spawn_piece()
                        return
                    drop_count = game_logic.effective_garbage_drop_count(
                        garbage_count,
                        self.max_garbage_drop,
                    )
                    if not drop_count:
                        if (
                            self.top_out_pending
                            and self.board[0][2] is not None
                        ):
                            self.game_over = True
                            return
                        self.top_out_pending = False
                        self.resolution_phase = None
                        self._spawn_piece()
                        return
                    falling_blocks = game_logic.plan_garbage_drop(
                        self.board,
                        drop_count,
                        self.garbage_type,
                    )
                    if falling_blocks is None:
                        falling_blocks = []
                    self.hidden_garbage[:] = attack_system.garbage_from_value(
                        garbage_count - drop_count
                    )
                    self.garbage_fall_blocks = falling_blocks
                    self.garbage_fall_elapsed = 0
                    self.resolution_phase = "garbage_falling"
                    self._begin_garbage_fall_planning()
        elif self.piece is not None:
            if (
                self.planning_future is not None
                and self.planning_piece_generation == self.piece_generation
                and self.placement_replan_pending
            ):
                return
            planning_pending = (
                self.planning_future is not None
                and self.planning_piece_generation == self.piece_generation
            )
            has_placement = (
                self.target_x is not None
                and self.target_rot is not None
            )
            rotation_was_active = self.rotation_animation is not None
            if self.rotation_animation is not None:
                self.rotation_animation["elapsed"] += dt
                if self.rotation_animation["elapsed"] >= ROTATION_DURATION:
                    self.rotation_animation = None

            settings = self._difficulty_settings()
            if (
                self.target_x is not None
                and self.target_rot is not None
                and not rotation_was_active
                and self.rotation_animation is None
            ):
                self.action_elapsed += dt
                if self.action_elapsed >= settings["action_interval"]:
                    self.action_elapsed -= settings["action_interval"]
                    self._take_planned_action()

            placement_reached = (
                has_placement
                and self.piece.x == self.target_x
                and self.piece.rot == self.target_rot
                and self.rotation_animation is None
            )
            placement_just_reached = (
                placement_reached and not self.placement_ready
            )
            if placement_just_reached:
                self.placement_ready = True
                self.piece_age = 0
                self.fall_timer = 0
            elif self.placement_ready:
                self.piece_age += dt

            target_fall_interval = (
                SOFT_DROP_INTERVAL
                if self.placement_ready
                and not planning_pending
                and settings["drop_delay"] is not None
                and self.piece_age >= settings["drop_delay"]
                else FALL_INTERVAL
            )
            if target_fall_interval != self.current_fall_interval:
                self.fall_timer = round(
                    self.fall_timer
                    * target_fall_interval
                    / self.current_fall_interval
                )
                self.current_fall_interval = target_fall_interval

            if not placement_just_reached:
                self.fall_timer += dt
                if not self.can_move_down(self.piece):
                    if planning_pending:
                        self.contact_timer = 0
                    elif (
                        self.placement_ready
                        and self.current_fall_interval == SOFT_DROP_INTERVAL
                    ):
                        self._lock_piece()
                    else:
                        self.contact_timer += dt
                        if self.contact_timer >= CONTACT_DELAY:
                            self._lock_piece()
                else:
                    while self.fall_timer >= self.current_fall_interval:
                        self.piece.y += 1
                        self.fall_timer -= self.current_fall_interval
                        if not self.can_move_down(self.piece):
                            break
            else:
                self.fall_timer = 0
                self.current_fall_interval = FALL_INTERVAL
