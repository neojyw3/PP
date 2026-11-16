import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import pygame

from ai_player import AIPlayer
import attack_system
import game_logic as game
import rendering
from settings import (
    AI_BOARD_X,
    BOARD_X,
    CONTACT_DELAY,
    CLEAR_DURATION,
    CHAIN_CONTINUE_START_DELAY,
    CHAIN_START_DELAY,
    FALL_INTERVAL,
    HEIGHT,
    HORIZONTAL_REPEAT_DELAY,
    HORIZONTAL_REPEAT_INTERVAL,
    NEXT_PIECE_DELAY,
    ROTATION_DURATION,
    SOFT_DROP_INTERVAL,
    WIDTH,
)


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("PP")
    clock = pygame.time.Clock()
    rendering.initialize_fonts()
    ai_planner = ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    )
    ai_game = AIPlayer(planner_executor=ai_planner)
    attack_orbs = []
    visual_garbage = {
        "player": game.hidden_garbage[:],
        "ai": ai_game.hidden_garbage[:],
    }
    deferred_garbage = {"player": 0, "ai": 0}
    field_shakes = {
        "player": {"elapsed": attack_system.SHAKE_DURATION, "strength": 0},
        "ai": {"elapsed": attack_system.SHAKE_DURATION, "strength": 0},
    }
    garbage_landing_shakes = {
        "player": {"elapsed": 0, "strength": 0},
        "ai": {"elapsed": 0, "strength": 0},
    }
    garbage_landing_shake_cooldowns = {
        "player": attack_system.GARBAGE_LANDING_SHAKE_DURATION,
        "ai": attack_system.GARBAGE_LANDING_SHAKE_DURATION,
    }
    garbage_landing_shake_enabled = {"player": False, "ai": False}

    running = True
    screen_state = "menu"
    margin_time_return_state = "settings"
    horizontal_held_key = None
    horizontal_hold_elapsed = 0
    horizontal_repeat_elapsed = 0
    horizontal_repeat_started = False
    player_top_out_pending = False
    player_top_out_drop_done = False
    player_locked_before_incoming_delivery = False

    def clear_field_shakes():
        for state in field_shakes.values():
            state["elapsed"] = attack_system.SHAKE_DURATION
            state["strength"] = 0
        for side in garbage_landing_shakes:
            garbage_landing_shakes[side]["elapsed"] = 0
            garbage_landing_shakes[side]["strength"] = 0
            garbage_landing_shake_cooldowns[side] = (
                attack_system.GARBAGE_LANDING_SHAKE_DURATION
            )
            garbage_landing_shake_enabled[side] = False

    def update_garbage_landing_shake(side, falling_blocks, landed_before, dt):
        if not garbage_landing_shake_enabled[side]:
            return

        cooldown = garbage_landing_shake_cooldowns[side]
        cooldown = min(
            attack_system.GARBAGE_LANDING_SHAKE_DURATION,
            cooldown + dt,
        )
        just_landed = any(
            not was_landed and block["landed"]
            for block, was_landed in zip(falling_blocks, landed_before)
        )
        if (
            just_landed
            and cooldown >= attack_system.GARBAGE_LANDING_SHAKE_DURATION
        ):
            attack_system.start_garbage_landing_shake(
                garbage_landing_shakes[side]
            )
            cooldown = 0
        garbage_landing_shake_cooldowns[side] = cooldown

    def reset_visual_garbage():
        visual_garbage["player"][:] = game.hidden_garbage
        visual_garbage["ai"][:] = ai_game.hidden_garbage

    def restart_match():
        nonlocal player_top_out_pending
        nonlocal player_top_out_drop_done
        nonlocal player_locked_before_incoming_delivery
        game.restart_game()
        ai_game.restart()
        attack_orbs.clear()
        reset_visual_garbage()
        deferred_garbage["player"] = 0
        deferred_garbage["ai"] = 0
        clear_field_shakes()
        player_top_out_pending = False
        player_top_out_drop_done = False
        player_locked_before_incoming_delivery = False

    def begin_player_garbage_fall(ready_count):
        nonlocal player_top_out_drop_done
        nonlocal player_locked_before_incoming_delivery
        garbage_count = attack_system.garbage_value(game.hidden_garbage)
        drop_count = game.effective_garbage_drop_count(
            min(ready_count, garbage_count),
            game.player_max_garbage_drop,
        )
        if not drop_count:
            return False

        garbage_landing_shake_enabled["player"] = drop_count >= 6
        garbage_landing_shake_cooldowns["player"] = (
            attack_system.GARBAGE_LANDING_SHAKE_DURATION
        )
        player_locked_before_incoming_delivery = False
        previous_stack = attack_system.normalize_garbage(game.hidden_garbage)
        falling_blocks = game.plan_garbage_drop(
            game.board,
            drop_count,
            game.player_garbage_type,
        )
        if falling_blocks is None:
            falling_blocks = []

        game.hidden_garbage[:] = attack_system.garbage_from_value(
            garbage_count - drop_count
        )
        visual_garbage["player"][:] = attack_system.normalize_garbage(
            game.hidden_garbage
        )
        attack_orbs.extend(attack_system.start_stack_reorganization(
            attack_orbs,
            BOARD_X,
            "player",
            previous_stack,
            game.hidden_garbage,
        ))
        game.garbage_fall_blocks = falling_blocks
        game.garbage_fall_elapsed = 0
        game.resolution_phase = "garbage_falling"
        return True

    def register_attack_events(events):
        for side, attack_blocks in events:
            attack_system.start_field_shake(
                field_shakes[side],
                attack_blocks,
            )

    def cycle_garbage_type(side, direction):
        types = tuple(game.GARBAGE_TYPE_BLOCKS)
        current_type = (
            game.player_garbage_type
            if side == "player"
            else game.ai_garbage_type
        )
        current_index = types.index(current_type)
        next_type = types[(current_index + direction) % len(types)]
        game.set_garbage_type(side, next_type)
        if side == "ai":
            ai_game.set_garbage_type(next_type)

    def move_horizontally(direction):
        if (
            game.piece is None
            or game.rotation_animation is not None
            or game.resolution_phase is not None
        ):
            return

        game.piece.x += direction
        if not game.valid(game.piece):
            game.piece.x -= direction

    while running:
        dt = clock.tick(60)
        if screen_state != "game":
            buttons = rendering.menu_buttons(screen_state)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif (
                    event.type == pygame.KEYDOWN
                    and event.key == pygame.K_ESCAPE
                    and screen_state == "pause"
                ):
                    screen_state = "game"
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for key, (rect, _) in buttons.items():
                        if not rect.collidepoint(event.pos):
                            continue
                        if key == "start":
                            restart_match()
                            screen_state = "game"
                        elif key == "resume":
                            screen_state = "game"
                        elif key == "pause_menu":
                            restart_match()
                            screen_state = "menu"
                        elif key == "settings":
                            screen_state = "settings"
                        elif key == "ai_settings":
                            screen_state = "ai_settings"
                        elif key == "ai_calculation_distance_down":
                            distance = max(
                                0,
                                game.ai_calculation_distance - 1,
                            )
                            game.set_ai_calculation_distance(distance)
                            ai_game.set_calculation_distance(distance)
                        elif key == "ai_calculation_distance_up":
                            distance = min(
                                30,
                                game.ai_calculation_distance + 1,
                            )
                            game.set_ai_calculation_distance(distance)
                            ai_game.set_calculation_distance(distance)
                        elif key == "player_garbage_drop_down":
                            game.set_max_garbage_drop(
                                "player",
                                max(1, game.player_max_garbage_drop - 1),
                            )
                        elif key == "player_garbage_drop_up":
                            game.set_max_garbage_drop(
                                "player",
                                min(101, game.player_max_garbage_drop + 1),
                            )
                        elif key == "ai_garbage_drop_down":
                            count = max(1, game.ai_max_garbage_drop - 1)
                            ai_game.set_max_garbage_drop(count)
                        elif key == "ai_garbage_drop_up":
                            count = min(101, game.ai_max_garbage_drop + 1)
                            ai_game.set_max_garbage_drop(count)
                        elif key == "player_settings":
                            screen_state = "player_settings"
                        elif key == "margin_time_settings":
                            margin_time_return_state = screen_state
                            screen_state = "margin_time_settings"
                        elif key == "margin_enabled_toggle":
                            game.set_margin_time_setting(
                                "enabled",
                                not game.margin_time_settings["enabled"],
                            )
                        elif key == "margin_start_down":
                            game.set_margin_time_setting(
                                "start_seconds",
                                max(
                                    0,
                                    game.margin_time_settings["start_seconds"]
                                    - 10,
                                ),
                            )
                        elif key == "margin_start_up":
                            game.set_margin_time_setting(
                                "start_seconds",
                                min(
                                    1000,
                                    game.margin_time_settings["start_seconds"]
                                    + 10,
                                ),
                            )
                        elif key == "margin_interval_down":
                            game.set_margin_time_setting(
                                "interval_seconds",
                                max(
                                    1,
                                    game.margin_time_settings[
                                        "interval_seconds"
                                    ]
                                    - 1,
                                ),
                            )
                        elif key == "margin_interval_up":
                            game.set_margin_time_setting(
                                "interval_seconds",
                                min(
                                    100,
                                    game.margin_time_settings[
                                        "interval_seconds"
                                    ]
                                    + 1,
                                ),
                            )
                        elif key == "margin_increase_down":
                            game.set_margin_time_setting(
                                "increase_amount",
                                max(
                                    0.1,
                                    round(
                                        game.margin_time_settings[
                                            "increase_amount"
                                        ]
                                        - 0.1,
                                        1,
                                    ),
                                ),
                            )
                        elif key == "margin_increase_up":
                            game.set_margin_time_setting(
                                "increase_amount",
                                min(
                                    10.0,
                                    round(
                                        game.margin_time_settings[
                                            "increase_amount"
                                        ]
                                        + 0.1,
                                        1,
                                    ),
                                ),
                            )
                        elif key == "difficulty_custom":
                            screen_state = "custom_ai_settings"
                        elif key == "custom_confirm":
                            game.set_ai_difficulty("custom")
                            ai_game.set_difficulty("custom")
                            screen_state = "ai_settings"
                        elif key == "custom_back":
                            screen_state = "ai_settings"
                        elif key == "back":
                            if screen_state == "margin_time_settings":
                                screen_state = margin_time_return_state
                            else:
                                screen_state = (
                                    "menu"
                                    if screen_state == "settings"
                                    else "settings"
                                )
                        elif key == "custom_soft_drop_down":
                            current_soft_drop = game.custom_ai_settings[
                                "soft_drop_seconds"
                            ]
                            game.set_custom_ai_setting(
                                "soft_drop_seconds",
                                0
                                if current_soft_drop <= 0.1
                                else round(current_soft_drop - 0.1, 1),
                            )
                            ai_game.set_custom_settings(
                                game.custom_ai_settings
                            )
                        elif key == "custom_soft_drop_up":
                            current_soft_drop = game.custom_ai_settings[
                                "soft_drop_seconds"
                            ]
                            game.set_custom_ai_setting(
                                "soft_drop_seconds",
                                0.1
                                if current_soft_drop == 0
                                else min(
                                    10.0,
                                    round(current_soft_drop + 0.1, 1),
                                ),
                            )
                            ai_game.set_custom_settings(
                                game.custom_ai_settings
                            )
                        elif key == "custom_soft_drop_toggle":
                            game.set_custom_ai_setting(
                                "soft_drop_enabled",
                                not game.custom_ai_settings[
                                    "soft_drop_enabled"
                                ],
                            )
                            ai_game.set_custom_settings(
                                game.custom_ai_settings
                            )
                        elif key == "custom_action_down":
                            current_action_interval = (
                                game.custom_ai_settings[
                                    "action_interval_seconds"
                                ]
                            )
                            game.set_custom_ai_setting(
                                "action_interval_seconds",
                                0
                                if current_action_interval <= 0.1
                                else round(current_action_interval - 0.1, 1),
                            )
                            ai_game.set_custom_settings(
                                game.custom_ai_settings
                            )
                        elif key == "custom_action_up":
                            current_action_interval = (
                                game.custom_ai_settings[
                                    "action_interval_seconds"
                                ]
                            )
                            game.set_custom_ai_setting(
                                "action_interval_seconds",
                                0.1
                                if current_action_interval == 0
                                else min(
                                    10.0,
                                    round(current_action_interval + 0.1, 1),
                                ),
                            )
                            ai_game.set_custom_settings(
                                game.custom_ai_settings
                            )
                        elif key == "custom_chain_down":
                            game.set_custom_ai_setting(
                                "chain_goal",
                                max(
                                    1,
                                    game.custom_ai_settings["chain_goal"] - 1,
                                ),
                            )
                            ai_game.set_custom_settings(
                                game.custom_ai_settings
                            )
                        elif key == "custom_chain_up":
                            game.set_custom_ai_setting(
                                "chain_goal",
                                min(
                                    50,
                                    game.custom_ai_settings["chain_goal"] + 1,
                                ),
                            )
                            ai_game.set_custom_settings(
                                game.custom_ai_settings
                            )
                        elif key.startswith("colors_"):
                            game.set_color_count(int(key.removeprefix("colors_")))
                        elif key.startswith("difficulty_"):
                            difficulty = key.removeprefix("difficulty_")
                            game.set_ai_difficulty(difficulty)
                            ai_game.set_difficulty(difficulty)
                        elif key == "player_clear_down":
                            game.set_clear_group_size(
                                max(2, game.player_clear_group_size - 1)
                            )
                        elif key == "player_clear_up":
                            game.set_clear_group_size(
                                min(6, game.player_clear_group_size + 1)
                            )
                        elif key == "ai_clear_down":
                            ai_game.set_clear_group_size(
                                max(2, ai_game.clear_group_size - 1)
                            )
                            game.set_ai_clear_group_size(
                                ai_game.clear_group_size
                            )
                        elif key == "ai_clear_up":
                            ai_game.set_clear_group_size(
                                min(6, ai_game.clear_group_size + 1)
                            )
                            game.set_ai_clear_group_size(
                                ai_game.clear_group_size
                            )
                        elif key == "player_ratio_down":
                            game.set_garbage_ratio(
                                "player",
                                max(0.1, game.player_garbage_ratio - 0.1),
                            )
                        elif key == "player_ratio_up":
                            game.set_garbage_ratio(
                                "player",
                                min(10.0, game.player_garbage_ratio + 0.1),
                            )
                        elif key == "ai_ratio_down":
                            game.set_garbage_ratio(
                                "ai",
                                max(0.1, game.ai_garbage_ratio - 0.1),
                            )
                        elif key == "ai_ratio_up":
                            game.set_garbage_ratio(
                                "ai",
                                min(10.0, game.ai_garbage_ratio + 0.1),
                            )
                        elif key == "player_garbage_type_down":
                            cycle_garbage_type("player", -1)
                        elif key == "player_garbage_type_up":
                            cycle_garbage_type("player", 1)
                        elif key == "ai_garbage_type_down":
                            cycle_garbage_type("ai", -1)
                        elif key == "ai_garbage_type_up":
                            cycle_garbage_type("ai", 1)
                        break

            if screen_state != "game":
                rendering.draw_menu(
                    screen,
                    screen_state,
                    game.color_count,
                    game.ai_difficulty,
                    game.player_clear_group_size,
                    game.ai_clear_group_size,
                    game.player_garbage_ratio,
                    game.ai_garbage_ratio,
                    game.player_garbage_type,
                    game.ai_garbage_type,
                    game.custom_ai_settings,
                    game.ai_calculation_distance,
                    game.margin_time_settings,
                    game.player_max_garbage_drop,
                    game.ai_max_garbage_drop,
                )
                pygame.display.flip()
                continue

        game.advance_margin_time(dt)

        if not (
            ai_game.chain_count > 0
            and ai_game.resolution_phase in (
                "chain_starting",
                "clearing",
                "falling",
            )
        ) and not attack_system.has_delivery_in_progress(
            attack_orbs,
            "player",
        ):
            deferred_garbage["player"] = 0
        if not (
            game.chain_count > 0
            and game.resolution_phase in (
                "chain_starting",
                "clearing",
                "falling",
            )
        ) and not attack_system.has_delivery_in_progress(
            attack_orbs,
            "ai",
        ):
            deferred_garbage["ai"] = 0

        soft_drop_pressed = False
        soft_drop_held = pygame.key.get_pressed()[pygame.K_s]
        target_fall_interval = (
            SOFT_DROP_INTERVAL if soft_drop_held else FALL_INTERVAL
        )
        if target_fall_interval != game.current_fall_interval:
            game.fall_timer = round(
                game.fall_timer
                * target_fall_interval
                / game.current_fall_interval
            )
            game.current_fall_interval = target_fall_interval
        game.fall_timer += dt

        if game.rotation_animation is not None:
            game.rotation_animation["elapsed"] += dt
            if game.rotation_animation["elapsed"] >= ROTATION_DURATION:
                game.rotation_animation = None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                restart_match()

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                screen_state = "pause"

            if event.type == pygame.KEYDOWN and event.key in (
                pygame.K_a,
                pygame.K_d,
            ):
                if event.key != horizontal_held_key:
                    horizontal_held_key = event.key
                    horizontal_hold_elapsed = 0
                    horizontal_repeat_elapsed = 0
                    horizontal_repeat_started = False
                    move_horizontally(
                        -1 if event.key == pygame.K_a else 1
                    )

            if event.type == pygame.KEYUP and event.key == horizontal_held_key:
                horizontal_held_key = None
                horizontal_hold_elapsed = 0
                horizontal_repeat_elapsed = 0
                horizontal_repeat_started = False

            if event.type == pygame.KEYDOWN and event.key == pygame.K_s:
                soft_drop_pressed = True

            if (
                event.type == pygame.KEYDOWN
                and game.piece is not None
                and game.rotation_animation is None
                and game.resolution_phase is None
            ):
                if event.key in (pygame.K_j, pygame.K_l):
                    direction = -1 if event.key == pygame.K_j else 1
                    pending_direction = game.piece.blocked_rotation_direction
                    if pending_direction is not None and direction != pending_direction:
                        game.piece.blocked_rotation_direction = None
                    else:
                        steps = 2 if pending_direction == direction else 1
                        old_piece_x, old_piece_y = game.piece.x, game.piece.y
                        old_x, old_y, _ = game.piece.get_blocks()[1]

                        if game.rotate_piece(game.piece, direction, steps):
                            game.piece.blocked_rotation_direction = None
                            new_x, new_y, _ = game.piece.get_blocks()[1]
                            game.rotation_animation = {
                                "start_x": old_x - old_piece_x,
                                "start_y": old_y - old_piece_y,
                                "end_x": new_x - game.piece.x,
                                "end_y": new_y - game.piece.y,
                                "pivot_offset_x": old_piece_x - game.piece.x,
                                "pivot_offset_y": old_piece_y - game.piece.y,
                                "direction": direction,
                                "steps": steps,
                                "elapsed": 0,
                            }
                        elif pending_direction is None:
                            game.piece.blocked_rotation_direction = direction

        if screen_state != "game":
            rendering.draw_menu(
                screen,
                screen_state,
                game.color_count,
                game.ai_difficulty,
                game.player_clear_group_size,
                game.ai_clear_group_size,
                game.player_garbage_ratio,
                game.ai_garbage_ratio,
                game.player_garbage_type,
                game.ai_garbage_type,
                game.custom_ai_settings,
                game.ai_calculation_distance,
                game.margin_time_settings,
                game.player_max_garbage_drop,
                game.ai_max_garbage_drop,
            )
            pygame.display.flip()
            continue

        if horizontal_held_key is not None:
            if pygame.key.get_pressed()[horizontal_held_key]:
                horizontal_hold_elapsed += dt
                if (
                    horizontal_hold_elapsed >= HORIZONTAL_REPEAT_DELAY
                    and game.piece is not None
                    and game.rotation_animation is None
                    and game.resolution_phase is None
                ):
                    if not horizontal_repeat_started:
                        move_horizontally(
                            -1 if horizontal_held_key == pygame.K_a else 1
                        )
                        horizontal_repeat_started = True
                    else:
                        horizontal_repeat_elapsed += dt
                    while (
                        horizontal_repeat_elapsed
                        >= HORIZONTAL_REPEAT_INTERVAL
                    ):
                        move_horizontally(
                            -1 if horizontal_held_key == pygame.K_a else 1
                        )
                        horizontal_repeat_elapsed -= HORIZONTAL_REPEAT_INTERVAL
            else:
                horizontal_held_key = None
                horizontal_hold_elapsed = 0
                horizontal_repeat_elapsed = 0
                horizontal_repeat_started = False

        if game.resolution_phase == "chain_starting":
            game.clearing_elapsed += dt
            chain_start_delay = (
                CHAIN_START_DELAY
                if game.chain_count == 1
                else CHAIN_CONTINUE_START_DELAY
            )
            if game.clearing_elapsed >= chain_start_delay:
                game.resolution_phase = "clearing"
                game.clearing_elapsed = 0

        elif game.resolution_phase == "clearing":
            game.clearing_elapsed += dt
            if game.clearing_elapsed >= CLEAR_DURATION:
                attack_system.launch_attacks(
                    attack_orbs,
                    game.clearing_groups,
                    game.chain_count,
                    BOARD_X,
                    AI_BOARD_X,
                    "ai",
                    {
                        "player": game.hidden_garbage,
                        "ai": ai_game.hidden_garbage,
                    },
                    visual_garbage,
                    game.effective_garbage_ratio("player"),
                    deferred_garbage,
                    defer_target=True,
                )
                game.clear_groups_with_adjacent_garbage(
                    game.board,
                    game.clearing_groups,
                )
                game.clearing_groups = []
                game.resolution_phase = "falling"
                game.fall_timer = 0

        elif game.resolution_phase == "garbage_falling":
            game.garbage_fall_elapsed += dt
            falling_blocks = game.garbage_fall_blocks[:]
            landed_before = [block["landed"] for block in falling_blocks]
            drop_complete = game.advance_garbage_drop(
                game.board,
                game.garbage_fall_blocks,
                dt,
            )
            update_garbage_landing_shake(
                "player",
                falling_blocks,
                landed_before,
                dt,
            )
            if drop_complete is None or drop_complete:
                game.garbage_fall_blocks = []
                game.garbage_fall_elapsed = 0
                garbage_landing_shake_enabled["player"] = False
                if game.board[0][2] is not None:
                    player_top_out_pending = True
                    player_top_out_drop_done = True
                    game.resolution_phase = "settling"
                    game.clearing_elapsed = 0
                else:
                    game.resolution_phase = None
                    game.spawn_piece()
                    game.fall_timer = game.current_fall_interval

        elif game.resolution_phase == "falling":
            if game.fall_timer >= 80:
                game.fall_timer = 0
                if not game.apply_board_gravity():
                    groups = game.find_match_groups()
                    if groups:
                        game.start_chain_clear(groups)
                    else:
                        game.resolution_phase = "settling"
                        game.clearing_elapsed = 0

        elif game.resolution_phase == "settling":
            incoming_garbage_in_flight = attack_system.has_pending_delivery(
                attack_orbs,
                "player",
            )
            incoming_garbage_traveling = attack_system.has_delivery_in_flight(
                attack_orbs,
                "player",
            )
            top_out_drop_complete = (
                player_top_out_pending
                and game.board[0][2] is not None
                and player_top_out_drop_done
            )
            player_ready_garbage = max(
                0,
                attack_system.garbage_value(game.hidden_garbage)
                - deferred_garbage["player"],
            )
            stack_cancellation_in_progress = (
                attack_system.has_stack_cancellation_in_progress(
                    attack_orbs,
                    "player",
                )
            )
            if player_ready_garbage and stack_cancellation_in_progress:
                game.clearing_elapsed = 0
            else:
                game.clearing_elapsed += dt

            if game.clearing_elapsed >= NEXT_PIECE_DELAY:
                opponent_chain_in_progress = (
                    ai_game.chain_count > 0
                    and ai_game.resolution_phase in (
                        "chain_starting",
                        "clearing",
                        "falling",
                    )
                )
                if top_out_drop_complete:
                    restart_match()
                elif (
                    player_ready_garbage
                    and game.player_max_garbage_drop > 1
                ):
                    begin_player_garbage_fall(player_ready_garbage)
                elif (
                    player_locked_before_incoming_delivery
                    and not (
                        player_top_out_pending
                        and game.board[0][2] is not None
                    )
                ):
                    player_locked_before_incoming_delivery = False
                    game.resolution_phase = None
                    game.clearing_elapsed = 0
                    game.spawn_piece()
                    game.fall_timer = game.current_fall_interval
                elif (
                    player_top_out_pending
                    and game.board[0][2] is not None
                    and (
                        deferred_garbage["player"] > 0
                        or incoming_garbage_in_flight
                        or incoming_garbage_traveling
                        or opponent_chain_in_progress
                    )
                ):
                    pass
                elif (
                    incoming_garbage_in_flight
                    or incoming_garbage_traveling
                    or opponent_chain_in_progress
                ):
                    game.resolution_phase = None
                    game.clearing_elapsed = 0
                    game.spawn_piece()
                    game.fall_timer = game.current_fall_interval
                elif (
                    player_top_out_pending
                    and game.board[0][2] is not None
                    and deferred_garbage["player"] > 0
                ):
                    pass
                elif (
                    attack_system.garbage_value(game.hidden_garbage) > 0
                    and deferred_garbage["player"] > 0
                ):
                    game.resolution_phase = None
                    game.clearing_elapsed = 0
                    game.spawn_piece()
                    game.fall_timer = game.current_fall_interval
                elif (
                    player_top_out_pending
                    and game.board[0][2] is not None
                    and (
                        attack_system.garbage_value(game.hidden_garbage) == 0
                        or game.player_max_garbage_drop <= 1
                    )
                ):
                    restart_match()
                else:
                    player_top_out_pending = False
                    player_top_out_drop_done = False
                    game.resolution_phase = None
                    game.spawn_piece()
                    game.fall_timer = game.current_fall_interval

        elif game.piece is not None:
            if not game.can_move_down(game.piece):
                game.fall_timer = 0
                game.contact_timer += dt
                if (
                    game.contact_timer >= CONTACT_DELAY
                    or soft_drop_held
                    or soft_drop_pressed
                ):
                    game.lock_piece(game.piece)
                    opponent_chain_in_progress = (
                        ai_game.chain_count > 0
                        and ai_game.resolution_phase in (
                            "chain_starting",
                            "clearing",
                            "falling",
                        )
                    )
                    if (
                        opponent_chain_in_progress
                        or attack_system.has_delivery_in_progress(
                            attack_orbs,
                            "player",
                        )
                    ):
                        player_locked_before_incoming_delivery = True
                    player_top_out_pending = game.board[0][2] is not None
                    player_top_out_drop_done = False
                    game.piece = None
                    game.rotation_animation = None
                    game.chain_count = 0
                    game.resolution_phase = "falling"
                    game.fall_timer = 0
            elif game.fall_timer >= game.current_fall_interval:
                game.piece.y += 1
                game.fall_timer -= game.current_fall_interval

        ai_resolution_before_update = ai_game.resolution_phase
        ai_falling_blocks_before_update = (
            ai_game.garbage_fall_blocks[:]
            if ai_resolution_before_update == "garbage_falling"
            else []
        )
        ai_landed_before_update = [
            block["landed"] for block in ai_falling_blocks_before_update
        ]
        ai_game.update(
            dt,
            incoming_garbage_in_flight=attack_system.has_pending_delivery(
                attack_orbs,
                "ai",
            ),
            incoming_garbage_traveling=attack_system.has_delivery_in_flight(
                attack_orbs,
                "ai",
            ),
            opponent_chain_in_progress=(
                game.chain_count > 0
                and game.resolution_phase in (
                    "chain_starting",
                    "clearing",
                    "falling",
                )
            ),
            deferred_garbage_value=deferred_garbage["ai"],
            attack_orbs=attack_orbs,
        )
        if ai_resolution_before_update == "garbage_falling":
            update_garbage_landing_shake(
                "ai",
                ai_falling_blocks_before_update,
                ai_landed_before_update,
                dt,
            )
            if ai_game.resolution_phase != "garbage_falling":
                garbage_landing_shake_enabled["ai"] = False
        elif ai_game.resolution_phase == "garbage_falling":
            garbage_landing_shake_enabled["ai"] = (
                len(ai_game.garbage_fall_blocks) >= 6
            )
            garbage_landing_shake_cooldowns["ai"] = (
                attack_system.GARBAGE_LANDING_SHAKE_DURATION
            )
        if ai_game.chain_attack_event is not None:
            chain_count, groups = (
                ai_game.chain_attack_event
            )
            attack_system.launch_attacks(
                attack_orbs,
                groups,
                chain_count,
                AI_BOARD_X,
                BOARD_X,
                "player",
                {
                    "player": game.hidden_garbage,
                    "ai": ai_game.hidden_garbage,
                },
                visual_garbage,
                game.effective_garbage_ratio("ai"),
                deferred_garbage,
                defer_target=True,
            )
        if ai_game.resolution_phase == "garbage_falling":
            if ai_resolution_before_update != "garbage_falling":
                previous_stack = attack_system.normalize_garbage(
                    visual_garbage["ai"]
                )
                attack_orbs.extend(
                    attack_system.start_stack_reorganization(
                        attack_orbs,
                        AI_BOARD_X,
                        "ai",
                        previous_stack,
                        ai_game.hidden_garbage,
                    )
                )
            visual_garbage["ai"][:] = attack_system.normalize_garbage(
                ai_game.hidden_garbage
            )
        if ai_game.game_over:
            restart_match()
        register_attack_events(
            attack_system.update_attacks(
                attack_orbs,
                dt,
                {
                    "player": game.hidden_garbage,
                    "ai": ai_game.hidden_garbage,
                },
                visual_garbage,
            )
        )
        shake_offsets = {}
        for side, state in field_shakes.items():
            attack_offset = attack_system.update_field_shake(state, dt)
            landing_offset = attack_system.update_garbage_landing_shake(
                garbage_landing_shakes[side],
                dt,
            )
            shake_offsets[side] = (
                attack_offset[0] + landing_offset[0],
                attack_offset[1] + landing_offset[1],
            )
        rendering.draw_frame(
            screen,
            game.board,
            game.piece,
            game.piece_queue,
            game.rotation_animation,
            game.fall_timer,
            game.current_fall_interval,
            game.resolution_phase,
            game.clearing_groups,
            game.clearing_elapsed,
            game.chain_count,
            shake_offset=shake_offsets["player"],
            garbage_fall_blocks=game.garbage_fall_blocks,
            garbage_fall_elapsed=game.garbage_fall_elapsed,
        )
        rendering.draw_frame(
            screen,
            ai_game.board,
            ai_game.piece,
            ai_game.piece_queue,
            ai_game.rotation_animation,
            ai_game.fall_timer,
            ai_game.current_fall_interval,
            ai_game.resolution_phase,
            ai_game.clearing_groups,
            ai_game.clearing_elapsed,
            ai_game.chain_count,
            board_x=AI_BOARD_X,
            label={
                "very_easy": "AI - VERY EASY",
                "easy": "AI - EASY",
                "normal": "AI - NORMAL",
                "hard": "AI - HARD",
                "very_hard": "AI - VERY HARD",
                "custom": "AI - CUSTOM",
            }[ai_game.difficulty],
            valid_fn=ai_game.can_move_down,
            clear_screen=False,
            shake_offset=shake_offsets["ai"],
            garbage_fall_blocks=ai_game.garbage_fall_blocks,
            garbage_fall_elapsed=ai_game.garbage_fall_elapsed,
        )
        attack_system.draw_garbage_stacks(
            screen,
            (
                (BOARD_X, visual_garbage["player"]),
                (AI_BOARD_X, visual_garbage["ai"]),
            ),
            shake_offsets={
                BOARD_X: shake_offsets["player"],
                AI_BOARD_X: shake_offsets["ai"],
            },
            hidden_boards={
                attack.get("visual_layout", {}).get("board_x")
                for attack in attack_orbs
                if attack.get("visual_layout") is not None
            } | {
                attack["target_board_x"]
                for attack in attack_orbs
                if attack["phase"] == "reorganize"
            } | {
                attack["source_board_x"]
                for attack in attack_orbs
                if attack["phase"] == "cancel_reorganize"
            },
        )
        attack_system.draw_attacks(screen, attack_orbs)
        controls = rendering.preview_font.render(
            "A/D: move   J/L: rotate   S: drop   R: restart",
            True,
            (180, 180, 180),
        )
        screen.blit(
            controls,
            controls.get_rect(center=(WIDTH // 2, HEIGHT - 25)),
        )
        pygame.display.flip()

    ai_planner.shutdown(wait=False, cancel_futures=True)
    pygame.quit()


if __name__ == "__main__":
    main()
