import math

import pygame

from game_logic import (
    FROZEN_GARBAGE_BLOCK,
    GARBAGE_BLOCK,
    can_move_down,
    frozen_color_value,
    is_frozen_color,
    rotation_position,
    rotation_progress,
)
from settings import (
    BOARD_H,
    BOARD_W,
    BOARD_X,
    BOARD_Y,
    CELL,
    COLORS,
    FLASH_INTERVAL,
    HEIGHT,
    WIDTH,
)


chain_font = None
preview_font = None
menu_font = None
menu_title_font = None
GARBAGE_TYPE_LABELS = {
    "garbage": "방해블럭",
    "frozen_garbage": "얼어붙은 방해블럭",
    "frozen_red": "얼어붙은 빨강블럭",
    "frozen_yellow": "얼어붙은 노랑블럭",
    "frozen_green": "얼어붙은 초록블럭",
    "frozen_blue": "얼어붙은 파랑블럭",
    "frozen_purple": "얼어붙은 보라블럭",
}


def initialize_fonts():
    global chain_font, preview_font, menu_font, menu_title_font
    chain_font = pygame.font.SysFont("malgungothic", 28, bold=True)
    preview_font = pygame.font.SysFont("malgungothic", 22, bold=True)
    menu_font = pygame.font.SysFont("malgungothic", 32, bold=True)
    menu_title_font = pygame.font.SysFont("malgungothic", 54, bold=True)


def menu_buttons(screen_state):
    center_x = WIDTH // 2
    if screen_state == "menu":
        return {
            "start": (pygame.Rect(center_x - 130, 340, 260, 70), "시작"),
            "settings": (pygame.Rect(center_x - 130, 430, 260, 70), "설정"),
        }

    if screen_state == "pause":
        return {
            "resume": (
                pygame.Rect(center_x - 150, 360, 300, 64),
                "계속하기",
            ),
            "pause_menu": (
                pygame.Rect(center_x - 150, 450, 300, 64),
                "메뉴로 나가기",
            ),
        }

    if screen_state == "settings":
        return {
            "ai_settings": (
                pygame.Rect(center_x - 170, 350, 340, 70),
                "AI 설정",
            ),
            "player_settings": (
                pygame.Rect(center_x - 170, 445, 340, 70),
                "플레이어 설정",
            ),
            "margin_time_settings": (
                pygame.Rect(center_x - 170, 535, 340, 60),
                "마진타임 설정",
            ),
            "back": (pygame.Rect(center_x - 100, 625, 200, 56), "뒤로"),
        }

    if screen_state == "player_settings":
        return {
            "player_clear_down": (
                pygame.Rect(center_x - 145, 230, 80, 56),
                "<",
            ),
            "player_clear_up": (
                pygame.Rect(center_x + 65, 230, 80, 56),
                ">",
            ),
            "player_ratio_down": (
                pygame.Rect(center_x - 145, 370, 80, 56),
                "<",
            ),
            "player_ratio_up": (
                pygame.Rect(center_x + 65, 370, 80, 56),
                ">",
            ),
            "player_garbage_type_down": (
                pygame.Rect(center_x - 205, 500, 80, 56),
                "<",
            ),
            "player_garbage_type_up": (
                pygame.Rect(center_x + 125, 500, 80, 56),
                ">",
            ),
            "player_garbage_drop_down": (
                pygame.Rect(center_x - 145, 610, 80, 56),
                "<",
            ),
            "player_garbage_drop_up": (
                pygame.Rect(center_x + 65, 610, 80, 56),
                ">",
            ),
            "back": (
                pygame.Rect(center_x - 100, 700, 200, 56),
                "뒤로",
            ),
        }

    if screen_state == "ai_settings":
        buttons = {
            f"colors_{count}": (
                pygame.Rect(center_x - 150 + (count - 3) * 110, 190, 90, 48),
                str(count),
            )
            for count in (3, 4, 5)
        }
        buttons.update({
            "ai_clear_down": (
                pygame.Rect(center_x - 145, 265, 80, 56),
                "<",
            ),
            "ai_clear_up": (
                pygame.Rect(center_x + 65, 265, 80, 56),
                ">",
            ),
            "ai_ratio_down": (
                pygame.Rect(center_x - 145, 340, 80, 56),
                "<",
            ),
            "ai_ratio_up": (
                pygame.Rect(center_x + 65, 340, 80, 56),
                ">",
            ),
            "ai_garbage_type_down": (
                pygame.Rect(center_x - 205, 415, 80, 56),
                "<",
            ),
            "ai_garbage_type_up": (
                pygame.Rect(center_x + 125, 415, 80, 56),
                ">",
            ),
            "ai_garbage_drop_down": (
                pygame.Rect(center_x - 145, 490, 80, 56),
                "<",
            ),
            "ai_garbage_drop_up": (
                pygame.Rect(center_x + 65, 490, 80, 56),
                ">",
            ),
            "ai_calculation_distance_down": (
                pygame.Rect(center_x - 145, 565, 80, 50),
                "<",
            ),
            "ai_calculation_distance_up": (
                pygame.Rect(center_x + 65, 565, 80, 50),
                ">",
            ),
        })
        difficulties = (
            ("very_easy", "매우 쉬움"),
            ("easy", "쉬움"),
            ("normal", "보통"),
            ("hard", "어려움"),
            ("very_hard", "매우 어려움"),
            ("custom", "커스텀"),
        )
        buttons.update({
            f"difficulty_{difficulty}": (
                pygame.Rect(10 + index * 148, 650, 140, 50),
                label,
            )
            for index, (difficulty, label) in enumerate(difficulties)
        })
        buttons["back"] = (
            pygame.Rect(center_x - 100, 710, 200, 56),
            "뒤로",
        )
        return buttons

    if screen_state == "margin_time_settings":
        return {
            "margin_enabled_toggle": (
                pygame.Rect(center_x - 110, 168, 220, 48),
                "ON / OFF",
            ),
            "margin_start_down": (
                pygame.Rect(center_x - 145, 265, 80, 52),
                "<",
            ),
            "margin_start_up": (
                pygame.Rect(center_x + 65, 265, 80, 52),
                ">",
            ),
            "margin_interval_down": (
                pygame.Rect(center_x - 145, 415, 80, 52),
                "<",
            ),
            "margin_interval_up": (
                pygame.Rect(center_x + 65, 415, 80, 52),
                ">",
            ),
            "margin_increase_down": (
                pygame.Rect(center_x - 145, 565, 80, 52),
                "<",
            ),
            "margin_increase_up": (
                pygame.Rect(center_x + 65, 565, 80, 52),
                ">",
            ),
            "back": (
                pygame.Rect(center_x - 100, 700, 200, 56),
                "뒤로",
            ),
        }

    if screen_state == "custom_ai_settings":
        return {
            "custom_soft_drop_down": (
                pygame.Rect(center_x - 145, 185, 80, 56),
                "<",
            ),
            "custom_soft_drop_up": (
                pygame.Rect(center_x + 65, 185, 80, 56),
                ">",
            ),
            "custom_soft_drop_toggle": (
                pygame.Rect(center_x - 110, 305, 220, 54),
                "ON / OFF",
            ),
            "custom_action_down": (
                pygame.Rect(center_x - 145, 425, 80, 56),
                "<",
            ),
            "custom_action_up": (
                pygame.Rect(center_x + 65, 425, 80, 56),
                ">",
            ),
            "custom_chain_down": (
                pygame.Rect(center_x - 145, 565, 80, 56),
                "<",
            ),
            "custom_chain_up": (
                pygame.Rect(center_x + 65, 565, 80, 56),
                ">",
            ),
            "custom_confirm": (
                pygame.Rect(center_x - 220, 700, 200, 58),
                "확인",
            ),
            "custom_back": (
                pygame.Rect(center_x + 20, 700, 200, 58),
                "뒤로",
            ),
        }

    return {}


def draw_menu(
    screen,
    screen_state,
    color_count,
    ai_difficulty="normal",
    player_clear_group_size=4,
    ai_clear_group_size=4,
    player_garbage_ratio=1.0,
    ai_garbage_ratio=1.0,
    player_garbage_type="garbage",
    ai_garbage_type="garbage",
    custom_ai_settings=None,
    ai_calculation_distance=2,
    margin_time_settings=None,
    player_max_garbage_drop=30,
    ai_max_garbage_drop=30,
):
    if custom_ai_settings is None:
        custom_ai_settings = {
            "soft_drop_seconds": 1.0,
            "soft_drop_enabled": True,
            "action_interval_seconds": 0.1,
            "chain_goal": 3,
        }
    if margin_time_settings is None:
        margin_time_settings = {
            "enabled": True,
            "start_seconds": 100,
            "interval_seconds": 50,
            "increase_amount": 0.5,
        }
    screen.fill((30, 30, 30))
    title = menu_title_font.render("PP", True, (245, 245, 245))
    title_y = 220 if screen_state == "menu" else 80
    screen.blit(title, title.get_rect(center=(WIDTH // 2, title_y)))

    if screen_state == "settings":
        subtitle = menu_font.render("설정", True, (220, 220, 220))
        screen.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, 205)))
    elif screen_state == "pause":
        subtitle = menu_font.render("일시정지", True, (220, 220, 220))
        screen.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, 230)))
    elif screen_state == "ai_settings":
        subtitle = menu_font.render("AI 설정", True, (220, 220, 220))
        screen.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, 135)))
        description = preview_font.render(
            f"색상 개수: {color_count}", True, (180, 180, 180)
        )
        screen.blit(description, description.get_rect(center=(WIDTH // 2, 170)))
        clear_title = preview_font.render(
            "몇 개가 모이면 블럭을 없앨까요?", True, (220, 220, 220)
        )
        screen.blit(clear_title, clear_title.get_rect(center=(WIDTH // 2, 245)))
        count_value = menu_font.render(
            str(ai_clear_group_size), True, (245, 245, 245)
        )
        screen.blit(count_value, count_value.get_rect(center=(WIDTH // 2, 293)))
        ratio_title = preview_font.render(
            "방해블럭 비율", True, (220, 220, 220)
        )
        screen.blit(ratio_title, ratio_title.get_rect(center=(WIDTH // 2, 320)))
        ratio_value = menu_font.render(
            f"{ai_garbage_ratio:.1f}", True, (245, 245, 245)
        )
        screen.blit(ratio_value, ratio_value.get_rect(center=(WIDTH // 2, 368)))
        difficulty_title = menu_font.render(
            "AI 난이도", True, (220, 220, 220)
        )
        screen.blit(
            difficulty_title,
            difficulty_title.get_rect(center=(WIDTH // 2, 630)),
        )
        garbage_type_title = preview_font.render(
            "방해블럭 종류", True, (220, 220, 220)
        )
        screen.blit(
            garbage_type_title,
            garbage_type_title.get_rect(center=(WIDTH // 2, 395)),
        )
        garbage_type_label = GARBAGE_TYPE_LABELS[ai_garbage_type]
        garbage_type_text = preview_font.render(
            garbage_type_label, True, (245, 245, 245)
        )
        screen.blit(
            garbage_type_text,
            garbage_type_text.get_rect(center=(WIDTH // 2, 443)),
        )
        garbage_drop_title = preview_font.render(
            "방해블럭 최대 낙하 개수", True, (220, 220, 220)
        )
        screen.blit(
            garbage_drop_title,
            garbage_drop_title.get_rect(center=(WIDTH // 2, 470)),
        )
        garbage_drop_label = (
            "없음"
            if ai_max_garbage_drop <= 1
            else (
                "전부"
                if ai_max_garbage_drop > 100
                else f"{ai_max_garbage_drop}개"
            )
        )
        garbage_drop_value = menu_font.render(
            garbage_drop_label, True, (245, 245, 245)
        )
        screen.blit(
            garbage_drop_value,
            garbage_drop_value.get_rect(center=(WIDTH // 2, 518)),
        )
        calculation_title = preview_font.render(
            "계산 거리 (미리보기 블록)", True, (220, 220, 220)
        )
        screen.blit(
            calculation_title,
            calculation_title.get_rect(center=(WIDTH // 2, 545)),
        )
        calculation_value = menu_font.render(
            f"{ai_calculation_distance}개", True, (245, 245, 245)
        )
        screen.blit(
            calculation_value,
            calculation_value.get_rect(center=(WIDTH // 2, 593)),
        )
    elif screen_state == "player_settings":
        subtitle = menu_font.render("플레이어 설정", True, (220, 220, 220))
        screen.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, 135)))
        clear_title = preview_font.render(
            "몇 개가 모이면 블럭을 없앨까요?", True, (220, 220, 220)
        )
        screen.blit(clear_title, clear_title.get_rect(center=(WIDTH // 2, 200)))
        count_value = menu_font.render(
            str(player_clear_group_size), True, (245, 245, 245)
        )
        screen.blit(count_value, count_value.get_rect(center=(WIDTH // 2, 258)))
        ratio_title = preview_font.render(
            "방해블럭 비율", True, (220, 220, 220)
        )
        screen.blit(ratio_title, ratio_title.get_rect(center=(WIDTH // 2, 340)))
        ratio_value = menu_font.render(
            f"{player_garbage_ratio:.1f}", True, (245, 245, 245)
        )
        screen.blit(ratio_value, ratio_value.get_rect(center=(WIDTH // 2, 398)))
        garbage_type_title = preview_font.render(
            "방해블럭 종류", True, (220, 220, 220)
        )
        screen.blit(
            garbage_type_title,
            garbage_type_title.get_rect(center=(WIDTH // 2, 465)),
        )
        garbage_type_text = preview_font.render(
            GARBAGE_TYPE_LABELS[player_garbage_type],
            True,
            (245, 245, 245),
        )
        screen.blit(
            garbage_type_text,
            garbage_type_text.get_rect(center=(WIDTH // 2, 528)),
        )
        garbage_drop_title = preview_font.render(
            "방해블럭 최대 낙하 개수", True, (220, 220, 220)
        )
        screen.blit(
            garbage_drop_title,
            garbage_drop_title.get_rect(center=(WIDTH // 2, 580)),
        )
        garbage_drop_label = (
            "없음"
            if player_max_garbage_drop <= 1
            else (
                "전부"
                if player_max_garbage_drop > 100
                else f"{player_max_garbage_drop}개"
            )
        )
        garbage_drop_value = menu_font.render(
            garbage_drop_label, True, (245, 245, 245)
        )
        screen.blit(
            garbage_drop_value,
            garbage_drop_value.get_rect(center=(WIDTH // 2, 638)),
        )
    elif screen_state == "margin_time_settings":
        subtitle = menu_font.render("마진타임 설정", True, (220, 220, 220))
        screen.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, 135)))
        rows = (
            ("시작 시간", f"{margin_time_settings['start_seconds']}초", 240),
            (
                "증가 시간 간격",
                f"{margin_time_settings['interval_seconds']}초",
                390,
            ),
            (
                "증가 배율 간격",
                f"{margin_time_settings['increase_amount']:.1f}",
                540,
            ),
        )
        for label, value, y in rows:
            label_surface = preview_font.render(label, True, (220, 220, 220))
            screen.blit(
                label_surface,
                label_surface.get_rect(center=(WIDTH // 2, y)),
            )
            value_surface = menu_font.render(value, True, (245, 245, 245))
            screen.blit(
                value_surface,
                value_surface.get_rect(center=(WIDTH // 2, y + 45)),
            )
        enabled_title = preview_font.render(
            "마진타임 사용", True, (220, 220, 220)
        )
        screen.blit(
            enabled_title,
            enabled_title.get_rect(center=(WIDTH // 2, 158)),
        )
    elif screen_state == "custom_ai_settings":
        subtitle = menu_font.render("커스텀 AI 설정", True, (220, 220, 220))
        screen.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, 135)))
        soft_drop_label = (
            "즉시"
            if custom_ai_settings["soft_drop_seconds"] == 0
            else f"{custom_ai_settings['soft_drop_seconds']:.1f}초"
        )
        rows = (
            ("소프트 드롭 시간", soft_drop_label, 170),
            (
                "회전 + 이동 간격",
                (
                    "즉시"
                    if custom_ai_settings["action_interval_seconds"] == 0
                    else (
                        f"{custom_ai_settings['action_interval_seconds']:.1f}초"
                    )
                ),
                410,
            ),
            ("연쇄 목표", f"{custom_ai_settings['chain_goal']}연쇄", 550),
        )
        for label, value, y in rows:
            label_surface = preview_font.render(label, True, (220, 220, 220))
            screen.blit(
                label_surface,
                label_surface.get_rect(center=(WIDTH // 2, y)),
            )
            value_surface = menu_font.render(value, True, (245, 245, 245))
            screen.blit(
                value_surface,
                value_surface.get_rect(center=(WIDTH // 2, y + 44)),
            )
        disabled_title = preview_font.render(
            "소프트 드롭", True, (220, 220, 220)
        )
        screen.blit(
            disabled_title,
            disabled_title.get_rect(center=(WIDTH // 2, 285)),
        )

    buttons = menu_buttons(screen_state)
    for key, (rect, label) in buttons.items():
        selected = (
            key == f"colors_{color_count}"
            or key == f"difficulty_{ai_difficulty}"
        )
        if key == "custom_soft_drop_toggle":
            label = "ON" if custom_ai_settings["soft_drop_enabled"] else "OFF"
            selected = custom_ai_settings["soft_drop_enabled"]
        if key == "margin_enabled_toggle":
            label = "ON" if margin_time_settings["enabled"] else "OFF"
            selected = margin_time_settings["enabled"]
        fill = (65, 110, 150) if selected else (55, 55, 55)
        pygame.draw.rect(screen, fill, rect, border_radius=10)
        pygame.draw.rect(
            screen,
            (100, 190, 255) if selected else (110, 110, 110),
            rect,
            width=2,
            border_radius=10,
        )
        font = (
            preview_font
            if key.startswith("difficulty_")
            or "garbage_type_" in key
            or key == "margin_time_settings"
            else menu_font
        )
        text = font.render(label, True, (245, 245, 245))
        screen.blit(text, text.get_rect(center=rect.center))


def draw_connected_blocks(
    screen,
    blocks,
    hidden_positions=(),
    fading_positions=(),
    fade_alpha=128,
    board_x=BOARD_X,
):
    hidden_positions = set(hidden_positions)
    fading_positions = set(fading_positions)
    centers = [
        (
            board_x + x * CELL + CELL // 2,
            BOARD_Y + y * CELL + CELL // 2,
            color,
        )
        for x, y, color in blocks
        if (x, y) not in hidden_positions
    ]
    normal_centers = [
        center for center in centers
        if (
            round((center[0] - board_x - CELL // 2) / CELL),
            round((center[1] - BOARD_Y - CELL // 2) / CELL),
        ) not in fading_positions
    ]
    fading_centers = [
        center for center in centers
        if (
            round((center[0] - board_x - CELL // 2) / CELL),
            round((center[1] - BOARD_Y - CELL // 2) / CELL),
        ) in fading_positions
    ]

    def draw_group(group_centers, target, alpha=255):
        for index, (x1, y1, color1) in enumerate(group_centers):
            for x2, y2, color2 in group_centers[index + 1:]:
                if (
                    color1 < 0
                    or color2 < 0
                    or color1 != color2
                ):
                    continue
                if (
                    math.isclose(abs(x1 - x2), CELL, abs_tol=1e-6)
                    and math.isclose(y1, y2, abs_tol=1e-6)
                ) or (
                    math.isclose(abs(y1 - y2), CELL, abs_tol=1e-6)
                    and math.isclose(x1, x2, abs_tol=1e-6)
                ):
                    pygame.draw.line(
                        target,
                        (*COLORS[color1], alpha),
                        (round(x1), round(y1)),
                        (round(x2), round(y2)),
                        CELL - 6,
                    )

        for x, y, color in group_centers:
            center = (round(x), round(y))
            if color == GARBAGE_BLOCK:
                color_value = (145, 145, 145)
            elif color == FROZEN_GARBAGE_BLOCK:
                pygame.draw.circle(
                    target,
                    (125, 215, 232, alpha),
                    center,
                    CELL // 2 - 1,
                )
                color_value = (145, 145, 145)
            elif is_frozen_color(color):
                pygame.draw.circle(
                    target,
                    (125, 215, 232, alpha),
                    center,
                    CELL // 2 - 1,
                )
                color_value = COLORS[frozen_color_value(color)]
            else:
                color_value = COLORS[color]
            pygame.draw.circle(
                target,
                (*color_value, alpha),
                center,
                CELL // 2 - 5 if color < 0 else CELL // 2 - 3,
            )

    draw_group(normal_centers, screen)
    if fading_centers:
        fading_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        draw_group(fading_centers, fading_surface, fade_alpha)
        screen.blit(fading_surface, (0, 0))


def draw_preview_piece(screen, preview_piece, x, y):
    preview_cell = 20
    centers = (
        (x + preview_cell // 2, y + preview_cell // 2, preview_piece.c2),
        (x + preview_cell // 2, y + preview_cell + preview_cell // 2, preview_piece.c1),
    )
    for center_x, center_y, color in centers:
        pygame.draw.circle(
            screen,
            COLORS[color],
            (center_x, center_y),
            preview_cell // 2 - 2,
        )


def draw_chain_labels(screen, groups, chain, board_x=BOARD_X):
    positions = [position for group in groups for position in group]
    if not positions:
        return

    center_x = sum(x for x, _ in positions) / len(positions)
    center_y = sum(y for _, y in positions) / len(positions)
    label = chain_font.render(f"{chain}연쇄", True, (255, 255, 255))
    label_rect = label.get_rect(
        center=(
            round(board_x + (center_x + 0.5) * CELL),
            round(BOARD_Y + (center_y + 0.5) * CELL),
        )
    )
    outline = chain_font.render(f"{chain}연쇄", True, (30, 30, 30))
    for offset_x, offset_y in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        screen.blit(outline, label_rect.move(offset_x, offset_y))
    screen.blit(label, label_rect)


def draw_game_over_marker(screen, board_x=BOARD_X):
    center = (
        board_x + 2 * CELL + CELL // 2,
        BOARD_Y + CELL // 2,
    )
    radius = CELL // 2 - 8
    pygame.draw.line(
        screen,
        (255, 0, 0),
        (center[0] - radius, center[1] - radius),
        (center[0] + radius, center[1] + radius),
        5,
    )
    pygame.draw.line(
        screen,
        (255, 0, 0),
        (center[0] + radius, center[1] - radius),
        (center[0] - radius, center[1] + radius),
        5,
    )


def draw_frame(
    screen,
    board,
    piece,
    piece_queue,
    rotation_animation,
    fall_timer,
    fall_interval,
    resolution_phase,
    clearing_groups,
    clearing_elapsed,
    chain_count,
    board_x=BOARD_X,
    label="PLAYER",
    valid_fn=None,
    clear_screen=True,
    shake_offset=(0, 0),
    garbage_fall_blocks=(),
    garbage_fall_elapsed=0,
):
    frame_surface = screen
    if shake_offset != (0, 0):
        if clear_screen:
            screen.fill((30, 30, 30))
        frame_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        frame_surface.fill((0, 0, 0, 0))
    elif clear_screen:
        screen.fill((30, 30, 30))
    panel_label = menu_font.render(label, True, (230, 230, 230))
    frame_surface.blit(
        panel_label,
        panel_label.get_rect(center=(board_x + BOARD_W * CELL // 2, 20)),
    )
    next_label = preview_font.render("NEXT", True, (180, 180, 180))
    frame_surface.blit(
        next_label,
        next_label.get_rect(center=(board_x + 35, 57)),
    )
    draw_preview_piece(frame_surface, piece_queue[0], board_x + 85, 38)
    draw_preview_piece(frame_surface, piece_queue[1], board_x + 155, 38)
    for y in range(BOARD_H):
        for x in range(BOARD_W):
            pygame.draw.rect(
                frame_surface,
                (70, 70, 70),
                (board_x + x * CELL, BOARD_Y + y * CELL, CELL, CELL),
                1,
            )

    settled_blocks = [
        (x, y, board[y][x])
        for y in range(BOARD_H)
        for x in range(BOARD_W)
        if board[y][x] is not None
    ]
    falling_blocks = []
    if piece is not None:
        fall_progress = (
            min(fall_timer / fall_interval, 1)
            if (valid_fn or can_move_down)(piece)
            else 0
        )
        for index, (x, y, color) in enumerate(piece.get_blocks()):
            if index == 1 and rotation_animation is not None:
                x, y = rotation_position(rotation_animation, piece)
            elif index == 0 and rotation_animation is not None:
                eased = rotation_progress(rotation_animation)
                x = piece.x + rotation_animation["pivot_offset_x"] * (1 - eased)
                y = piece.y + rotation_animation["pivot_offset_y"] * (1 - eased)
            y += fall_progress
            falling_blocks.append((x, y, color))

    for block in garbage_fall_blocks:
        if not block.get("landed", False) and not block.get("hidden", False):
            falling_blocks.append(
                (
                    block["x"],
                    block["current_y"],
                    block.get("block", GARBAGE_BLOCK),
                )
            )

    fading_positions = [
        position for group in clearing_groups for position in group
    ]
    flash_alpha = (
        128 if int(clearing_elapsed / FLASH_INTERVAL) % 2 == 0 else 255
    ) if resolution_phase == "clearing" else 255
    draw_connected_blocks(
        frame_surface,
        settled_blocks,
        fading_positions=fading_positions,
        fade_alpha=flash_alpha,
        board_x=board_x,
    )
    previous_clip = frame_surface.get_clip()
    frame_surface.set_clip(
        pygame.Rect(board_x, BOARD_Y, BOARD_W * CELL, BOARD_H * CELL)
    )
    for block in falling_blocks:
        draw_connected_blocks(frame_surface, [block], board_x=board_x)
    frame_surface.set_clip(previous_clip)

    draw_game_over_marker(frame_surface, board_x=board_x)

    if resolution_phase == "clearing":
        draw_chain_labels(
            frame_surface,
            clearing_groups,
            chain_count,
            board_x=board_x,
        )

    if frame_surface is not screen:
        screen.blit(frame_surface, shake_offset)
