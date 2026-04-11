"""Wheel of Fate overlay for the Pygame client.

Server is authoritative on the outcome; this module just animates a
wheel that lands on the slice the server chose. The wheel is modal:
while active it dims the background and blocks input.
"""

from __future__ import annotations

import math
import random
from typing import Literal, Optional

import pygame

Outcome = Literal["go_again", "end_turn"]


class WheelOverlay:
    """Spinning wheel shown after a capture.

    40% of the face is green ("GO AGAIN"), 60% red ("END TURN"). The
    server dictates which side wins; this class just picks a random
    visual landing angle inside that slice and eases into it.
    """

    # Slice geometry, in degrees measured clockwise from the top pointer.
    GO_AGAIN_ARC = 144.0   # 40% of 360°
    END_TURN_ARC = 216.0   # 60% of 360°
    GO_AGAIN_CENTER = 0.0          # top
    END_TURN_CENTER = 180.0        # bottom

    # Animation timing in milliseconds.
    SPIN_DURATION_MS = 2000
    HOLD_DURATION_MS = 1000

    # Number of full rotations baked into the spin for drama.
    SPIN_TURNS = 5

    def __init__(self, radius: int = 170) -> None:
        self.radius = radius
        self.active = False
        self.outcome: Optional[Outcome] = None
        self.spinner: str = ""  # "white" or "black"
        self._start_ms = 0
        self._start_rotation = 0.0
        self._target_rotation = 0.0
        self._current_rotation = 0.0
        self._wheel_surface: Optional[pygame.Surface] = None
        self._last_spin_id: Optional[str] = None

    # -- Public API -----------------------------------------------------------

    def trigger(self, outcome: Outcome, spinner: str, spin_id: str) -> None:
        """Start a new spin landing on *outcome*.

        Dedupes on *spin_id* so replayed messages don't stack.
        """
        if spin_id == self._last_spin_id:
            return
        self._last_spin_id = spin_id
        self.active = True
        self.outcome = outcome
        self.spinner = spinner
        self._start_ms = pygame.time.get_ticks()
        self._start_rotation = 0.0

        if outcome == "go_again":
            center = self.GO_AGAIN_CENTER
            half = self.GO_AGAIN_ARC / 2 - 8  # margin so we don't hug the edge
        else:
            center = self.END_TURN_CENTER
            half = self.END_TURN_ARC / 2 - 8

        landing = center + random.uniform(-half, half)
        # Pygame rotate is counter-clockwise for positive angles, so we
        # negate to spin clockwise and add full turns for drama.
        self._target_rotation = -(landing + 360.0 * self.SPIN_TURNS)

    def update(self) -> None:
        if not self.active:
            return
        now = pygame.time.get_ticks()
        elapsed = now - self._start_ms
        if elapsed < self.SPIN_DURATION_MS:
            t = elapsed / self.SPIN_DURATION_MS
            eased = 1 - (1 - t) ** 3  # ease-out cubic
            self._current_rotation = (
                self._start_rotation
                + (self._target_rotation - self._start_rotation) * eased
            )
        elif elapsed < self.SPIN_DURATION_MS + self.HOLD_DURATION_MS:
            self._current_rotation = self._target_rotation
        else:
            self.active = False
            self.outcome = None

    def draw(self, screen: pygame.Surface, center_x: int, center_y: int,
             window_w: int, window_h: int) -> None:
        if not self.active:
            return

        if self._wheel_surface is None:
            self._wheel_surface = self._build_wheel_surface()

        # Dim the whole window
        dim = pygame.Surface((window_w, window_h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        screen.blit(dim, (0, 0))

        rotated = pygame.transform.rotate(self._wheel_surface, self._current_rotation)
        rect = rotated.get_rect(center=(center_x, center_y))
        screen.blit(rotated, rect)

        # Fixed pointer at the top of the wheel (triangle pointing down).
        tip_y = center_y - self.radius - 6
        base_y = tip_y - 26
        pts = [
            (center_x, tip_y),
            (center_x - 18, base_y),
            (center_x + 18, base_y),
        ]
        pygame.draw.polygon(screen, (240, 220, 60), pts)
        pygame.draw.polygon(screen, (20, 20, 20), pts, 3)

        # Center hub on top of the rotated wheel
        pygame.draw.circle(screen, (30, 30, 30), (center_x, center_y), 20)
        pygame.draw.circle(screen, (210, 210, 210), (center_x, center_y), 15)

        # Result banner after the spin finishes
        elapsed = pygame.time.get_ticks() - self._start_ms
        if elapsed >= self.SPIN_DURATION_MS and self.outcome is not None:
            font = pygame.font.SysFont("arial,helvetica", 38, bold=True)
            if self.outcome == "go_again":
                text = "BONUS MOVE!"
                color = (110, 230, 130)
            else:
                text = "TURN ENDS"
                color = (230, 110, 110)
            label = font.render(text, True, color)
            label_rect = label.get_rect(center=(center_x, center_y + self.radius + 60))
            bg = pygame.Rect(
                label_rect.x - 14, label_rect.y - 8,
                label_rect.width + 28, label_rect.height + 16,
            )
            pygame.draw.rect(screen, (18, 18, 18), bg, border_radius=8)
            pygame.draw.rect(screen, color, bg, width=3, border_radius=8)
            screen.blit(label, label_rect)

    # -- Internals ------------------------------------------------------------

    def _build_wheel_surface(self) -> pygame.Surface:
        size = self.radius * 2 + 24
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        center = (size // 2, size // 2)

        # Outer rim
        pygame.draw.circle(surf, (20, 20, 20), center, self.radius + 10)
        pygame.draw.circle(surf, (235, 230, 210), center, self.radius + 6)
        pygame.draw.circle(surf, (40, 40, 40), center, self.radius + 2)

        def wedge(start_deg: float, end_deg: float, color: tuple[int, int, int]) -> None:
            pts: list[tuple[float, float]] = [center]
            steps = max(12, int(abs(end_deg - start_deg) / 2))
            for i in range(steps + 1):
                t = start_deg + (end_deg - start_deg) * i / steps
                rad = math.radians(t - 90.0)  # 0° = top
                x = center[0] + math.cos(rad) * self.radius
                y = center[1] + math.sin(rad) * self.radius
                pts.append((x, y))
            pygame.draw.polygon(surf, color, pts)

        half_go = self.GO_AGAIN_ARC / 2
        wedge(-half_go, half_go, (60, 175, 85))                    # green top
        wedge(half_go, half_go + self.END_TURN_ARC, (200, 65, 65)) # red rest

        # Divider lines between slices
        for angle in (-half_go, half_go):
            rad = math.radians(angle - 90.0)
            x = center[0] + math.cos(rad) * self.radius
            y = center[1] + math.sin(rad) * self.radius
            pygame.draw.line(surf, (20, 20, 20), center, (x, y), 3)

        # Slice labels
        font = pygame.font.SysFont("arial,helvetica", 22, bold=True)
        go_label = font.render("GO AGAIN", True, (255, 255, 255))
        surf.blit(
            go_label,
            go_label.get_rect(center=(center[0], center[1] - self.radius * 0.58)),
        )
        end_label = font.render("END TURN", True, (255, 255, 255))
        surf.blit(
            end_label,
            end_label.get_rect(center=(center[0], center[1] + self.radius * 0.58)),
        )

        return surf
