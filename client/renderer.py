"""Board rendering — loads PNG piece images from client/assets/pieces/.

Expected files (in client/assets/pieces/):
    wK.png wQ.png wR.png wB.png wN.png wP.png
    bK.png bQ.png bR.png bB.png bN.png bP.png

Falls back to letter-based rendering if any image is missing.
"""

from __future__ import annotations

import os
from typing import Optional

import chess
import pygame

# -- Colors -------------------------------------------------------------------

COLOR_LIGHT = (240, 217, 181)
COLOR_DARK = (181, 136, 99)
COLOR_HIGHLIGHT = (186, 202, 68, 160)      # selected square
COLOR_LEGAL_MOVE = (130, 151, 105, 140)    # legal move dot
COLOR_LAST_MOVE = (205, 210, 106, 120)     # last move highlight
COLOR_CHECK = (235, 97, 80, 180)           # king in check
COLOR_PROMO_BG = (50, 50, 50, 230)
COLOR_PROMO_HOVER = (80, 80, 80)

# Fallback colors (used only if PNGs fail to load)
COLOR_WHITE_PIECE = (255, 255, 240)
COLOR_WHITE_PIECE_BORDER = (100, 100, 80)
COLOR_WHITE_PIECE_TEXT = (40, 40, 40)
COLOR_BLACK_PIECE = (60, 60, 60)
COLOR_BLACK_PIECE_BORDER = (30, 30, 30)
COLOR_BLACK_PIECE_TEXT = (230, 230, 220)

# -- Piece name map -----------------------------------------------------------

PIECE_LETTERS: dict[int, str] = {
    chess.KING: "K",
    chess.QUEEN: "Q",
    chess.ROOK: "R",
    chess.BISHOP: "B",
    chess.KNIGHT: "N",
    chess.PAWN: "P",
}

PROMO_PIECES = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "assets", "pieces")


class BoardRenderer:
    """Renders the chess board and pieces from PNG image assets."""

    def __init__(self, square_size: int = 80) -> None:
        self.square_size = square_size
        self.board_px = square_size * 8
        self._label_font: Optional[pygame.font.Font] = None
        self._fallback_font: Optional[pygame.font.Font] = None
        self._piece_images: dict[tuple[int, bool], pygame.Surface] = {}
        self._piece_size = int(square_size * 0.85)
        self._images_loaded = False

    # -- Asset loading --------------------------------------------------------

    def load_assets(self) -> None:
        """Load all 12 piece PNGs. Must be called after pygame display init."""
        if self._images_loaded:
            return

        mapping = {
            (chess.KING, True): "wK.png",
            (chess.QUEEN, True): "wQ.png",
            (chess.ROOK, True): "wR.png",
            (chess.BISHOP, True): "wB.png",
            (chess.KNIGHT, True): "wN.png",
            (chess.PAWN, True): "wP.png",
            (chess.KING, False): "bK.png",
            (chess.QUEEN, False): "bQ.png",
            (chess.ROOK, False): "bR.png",
            (chess.BISHOP, False): "bB.png",
            (chess.KNIGHT, False): "bN.png",
            (chess.PAWN, False): "bP.png",
        }

        loaded: dict[tuple[int, bool], pygame.Surface] = {}
        for key, filename in mapping.items():
            path = os.path.join(ASSETS_DIR, filename)
            if not os.path.exists(path):
                print(f"[renderer] Missing asset: {path}")
                return  # fall back entirely
            try:
                img = pygame.image.load(path).convert_alpha()
                img = pygame.transform.smoothscale(
                    img, (self._piece_size, self._piece_size)
                )
                loaded[key] = img
            except pygame.error as e:
                print(f"[renderer] Failed to load {filename}: {e}")
                return

        self._piece_images = loaded
        self._images_loaded = True

    # -- Fonts ----------------------------------------------------------------

    def _get_label_font(self) -> pygame.font.Font:
        if self._label_font is None:
            self._label_font = pygame.font.SysFont(
                "arial,helvetica", int(self.square_size * 0.18)
            )
        return self._label_font

    def _get_fallback_font(self) -> pygame.font.Font:
        if self._fallback_font is None:
            self._fallback_font = pygame.font.SysFont(
                "arial,helvetica,sans-serif", int(self.square_size * 0.38), bold=True
            )
        return self._fallback_font

    # -- Coordinates ----------------------------------------------------------

    def square_to_pixel(self, sq: int, flipped: bool) -> tuple[int, int]:
        """Convert a chess square index to pixel (x, y) of top-left corner."""
        f = chess.square_file(sq)
        r = chess.square_rank(sq)
        if flipped:
            px = (7 - f) * self.square_size
            py = r * self.square_size
        else:
            px = f * self.square_size
            py = (7 - r) * self.square_size
        return px, py

    def pixel_to_square(self, x: int, y: int, flipped: bool) -> Optional[int]:
        """Convert pixel (x, y) to a chess square index, or None if off board."""
        if x < 0 or y < 0 or x >= self.board_px or y >= self.board_px:
            return None
        col = x // self.square_size
        row = y // self.square_size
        if flipped:
            file = 7 - col
            rank = row
        else:
            file = col
            rank = 7 - row
        return chess.square(file, rank)

    # -- Board ----------------------------------------------------------------

    def draw_board(self, surface: pygame.Surface, flipped: bool,
                   last_move_uci: Optional[str] = None,
                   check_square: Optional[int] = None) -> None:
        """Draw the 8x8 board squares, coordinate labels, and highlights."""
        label_font = self._get_label_font()
        for sq in range(64):
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            px, py = self.square_to_pixel(sq, flipped)
            is_light = (f + r) % 2 == 1
            color = COLOR_LIGHT if is_light else COLOR_DARK
            pygame.draw.rect(surface, color,
                             (px, py, self.square_size, self.square_size))

            # Rank labels on left edge
            if (flipped and f == 7) or (not flipped and f == 0):
                label_color = COLOR_DARK if is_light else COLOR_LIGHT
                lbl = label_font.render(str(r + 1), True, label_color)
                surface.blit(lbl, (px + 2, py + 2))

            # File labels on bottom edge
            if (flipped and r == 7) or (not flipped and r == 0):
                label_color = COLOR_DARK if is_light else COLOR_LIGHT
                lbl = label_font.render(chr(ord('a') + f), True, label_color)
                surface.blit(lbl, (
                    px + self.square_size - lbl.get_width() - 2,
                    py + self.square_size - lbl.get_height() - 1,
                ))

        # Last move highlight
        if last_move_uci and len(last_move_uci) >= 4:
            try:
                move = chess.Move.from_uci(last_move_uci)
                for sq in (move.from_square, move.to_square):
                    px, py = self.square_to_pixel(sq, flipped)
                    overlay = pygame.Surface(
                        (self.square_size, self.square_size), pygame.SRCALPHA
                    )
                    overlay.fill(COLOR_LAST_MOVE)
                    surface.blit(overlay, (px, py))
            except ValueError:
                pass

        # Check highlight
        if check_square is not None:
            px, py = self.square_to_pixel(check_square, flipped)
            overlay = pygame.Surface(
                (self.square_size, self.square_size), pygame.SRCALPHA
            )
            overlay.fill(COLOR_CHECK)
            surface.blit(overlay, (px, py))

    # -- Piece drawing --------------------------------------------------------

    def _draw_piece(self, surface: pygame.Surface, piece_type: int,
                    color: bool, cx: int, cy: int) -> None:
        """Draw one piece centered at (cx, cy)."""
        img = self._piece_images.get((piece_type, color)) if self._images_loaded else None
        if img is not None:
            rect = img.get_rect(center=(cx, cy))
            surface.blit(img, rect)
        else:
            # Fallback: styled circle with letter
            self._draw_fallback_glyph(surface, piece_type, color, cx, cy)

    def _draw_fallback_glyph(self, surface: pygame.Surface, piece_type: int,
                             color: bool, cx: int, cy: int) -> None:
        radius = int(self.square_size * 0.38)
        if color:
            fill = COLOR_WHITE_PIECE
            border = COLOR_WHITE_PIECE_BORDER
            text_color = COLOR_WHITE_PIECE_TEXT
        else:
            fill = COLOR_BLACK_PIECE
            border = COLOR_BLACK_PIECE_BORDER
            text_color = COLOR_BLACK_PIECE_TEXT
        pygame.draw.circle(surface, fill, (cx, cy), radius)
        pygame.draw.circle(surface, border, (cx, cy), radius, 2)
        letter = PIECE_LETTERS.get(piece_type, "?")
        text = self._get_fallback_font().render(letter, True, text_color)
        surface.blit(text, (cx - text.get_width() // 2,
                            cy - text.get_height() // 2))

    def draw_pieces(self, surface: pygame.Surface,
                    piece_map: dict[int, chess.Piece],
                    flipped: bool,
                    dragging_sq: Optional[int] = None) -> None:
        """Draw all pieces on the board. Skip *dragging_sq*."""
        half = self.square_size // 2
        for sq, piece in piece_map.items():
            if sq == dragging_sq:
                continue
            px, py = self.square_to_pixel(sq, flipped)
            self._draw_piece(surface, piece.piece_type, piece.color,
                             px + half, py + half)

    def draw_dragging_piece(self, surface: pygame.Surface,
                            piece: chess.Piece,
                            mouse_x: int, mouse_y: int) -> None:
        """Draw a piece following the mouse cursor."""
        self._draw_piece(surface, piece.piece_type, piece.color,
                         mouse_x, mouse_y)

    # -- Highlights -----------------------------------------------------------

    def draw_highlights(self, surface: pygame.Surface, selected_sq: int,
                        legal_targets: list[int],
                        flipped: bool) -> None:
        """Draw selection highlight and legal move indicators."""
        # Selected square
        px, py = self.square_to_pixel(selected_sq, flipped)
        overlay = pygame.Surface(
            (self.square_size, self.square_size), pygame.SRCALPHA
        )
        overlay.fill(COLOR_HIGHLIGHT)
        surface.blit(overlay, (px, py))

        # Legal move dots
        for sq in legal_targets:
            px, py = self.square_to_pixel(sq, flipped)
            dot_surface = pygame.Surface(
                (self.square_size, self.square_size), pygame.SRCALPHA
            )
            radius = self.square_size // 6
            pygame.draw.circle(
                dot_surface, COLOR_LEGAL_MOVE,
                (self.square_size // 2, self.square_size // 2), radius,
            )
            surface.blit(dot_surface, (px, py))

    # -- Promotion dialog -----------------------------------------------------

    def draw_promotion_dialog(
        self, surface: pygame.Surface, color: bool,
        file: int, flipped: bool,
        mouse_pos: tuple[int, int],
    ) -> list[tuple[pygame.Rect, int]]:
        """Draw promotion piece selection.

        Returns list of (rect, piece_type) for click detection.
        """
        results: list[tuple[pygame.Rect, int]] = []

        if flipped:
            start_col = 7 - file
        else:
            start_col = file

        if (color and not flipped) or (not color and flipped):
            start_row = 0
        else:
            start_row = 4

        x = start_col * self.square_size
        y = start_row * self.square_size
        w = self.square_size
        h = self.square_size * 4

        # Background
        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill(COLOR_PROMO_BG)
        surface.blit(bg, (x, y))

        half = self.square_size // 2
        for i, piece_type in enumerate(PROMO_PIECES):
            rect = pygame.Rect(x, y + i * self.square_size, w, self.square_size)
            if rect.collidepoint(mouse_pos):
                pygame.draw.rect(surface, COLOR_PROMO_HOVER, rect)

            self._draw_piece(surface, piece_type, color,
                             rect.x + half, rect.y + half)
            results.append((rect, piece_type))

        return results
