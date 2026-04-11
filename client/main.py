"""Pygame chess client with WebSocket connection to the server."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Optional

import chess
import pygame
import websockets
from websockets.asyncio.client import ClientConnection

from client.renderer import BoardRenderer
from client.wheel import WheelOverlay
from shared.engine import ChessEngine
from shared.models import (
    AcceptDraw,
    ClaimDraw,
    DeclineDraw,
    JoinQueue,
    MakeMove,
    OfferDraw,
    Resign,
)

# -- Constants ----------------------------------------------------------------

SQUARE_SIZE = 80
BOARD_PX = SQUARE_SIZE * 8
SIDEBAR_W = 220
WINDOW_W = BOARD_PX + SIDEBAR_W
WINDOW_H = BOARD_PX
FPS = 60
DEFAULT_SERVER_URI = "ws://192.168.0.86:8000/ws"

COLOR_BG = (40, 40, 40)
COLOR_SIDEBAR = (30, 30, 30)
COLOR_TEXT = (210, 210, 210)
COLOR_ACCENT = (100, 180, 100)
COLOR_BTN = (60, 60, 60)
COLOR_BTN_HOVER = (80, 80, 80)
COLOR_BTN_TEXT = (220, 220, 220)
COLOR_DRAW_OFFER_BG = (60, 50, 20)


# -- UI helpers ---------------------------------------------------------------

class Button:
    def __init__(self, rect: pygame.Rect, label: str) -> None:
        self.rect = rect
        self.label = label
        self.visible = True

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             mouse_pos: tuple[int, int]) -> None:
        if not self.visible:
            return
        color = COLOR_BTN_HOVER if self.rect.collidepoint(mouse_pos) else COLOR_BTN
        pygame.draw.rect(surface, color, self.rect, border_radius=4)
        text = font.render(self.label, True, COLOR_BTN_TEXT)
        surface.blit(text, (self.rect.centerx - text.get_width() // 2,
                            self.rect.centery - text.get_height() // 2))

    def clicked(self, pos: tuple[int, int]) -> bool:
        return self.visible and self.rect.collidepoint(pos)


# -- Client state machine ----------------------------------------------------

class ChessClient:
    """Main client class managing game state, rendering, and networking."""

    def __init__(self, server_uri: str = DEFAULT_SERVER_URI) -> None:
        self.server_uri = server_uri
        pygame.init()
        pygame.display.set_caption("Chess")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self.clock = pygame.time.Clock()
        self.renderer = BoardRenderer(SQUARE_SIZE)
        self.renderer.load_assets()

        # Fonts
        self.font = pygame.font.SysFont("arial,helvetica", 16)
        self.font_big = pygame.font.SysFont("arial,helvetica", 22, bold=True)
        self.font_small = pygame.font.SysFont("arial,helvetica", 13)

        # Network
        self.ws: Optional[ClientConnection] = None
        self.connected = False

        # Game state
        self.my_color: Optional[bool] = None  # True=white, False=black
        self.engine = ChessEngine()
        self.game_active = False
        self.game_over_msg: Optional[str] = None
        self.status_text = "Connecting..."
        self.game_id: Optional[str] = None

        # Interaction
        self.selected_sq: Optional[int] = None
        self.dragging_sq: Optional[int] = None
        self.dragging_piece: Optional[chess.Piece] = None
        self.legal_targets: list[int] = []

        # Promotion
        self.pending_promo_from: Optional[int] = None
        self.pending_promo_to: Optional[int] = None
        self.showing_promo_dialog = False

        # Draw offers
        self.draw_offered_by_us = False
        self.draw_offered_to_us = False
        self.can_claim_draw = False

        # Move list
        self.move_stack: list[str] = []
        self.last_move_uci: Optional[str] = None

        # Wheel of Fate overlay
        self.wheel = WheelOverlay(radius=170)

        # Blocks duplicate MakeMove sends while waiting for the server's
        # response (spin_result / game_state / move_error). Without this,
        # a rapid second click lands on the pre-response state where the
        # client still thinks it's our turn, and the server then rejects
        # the stale move with "Not your turn".
        self.move_in_flight = False

        # Buttons
        btn_x = BOARD_PX + 10
        btn_w = SIDEBAR_W - 20
        self.btn_resign = Button(pygame.Rect(btn_x, WINDOW_H - 110, btn_w, 32), "Resign")
        self.btn_draw = Button(pygame.Rect(btn_x, WINDOW_H - 70, btn_w, 32), "Offer Draw")
        self.btn_claim = Button(pygame.Rect(btn_x, WINDOW_H - 70, btn_w, 32), "Claim Draw")
        self.btn_accept = Button(pygame.Rect(btn_x, WINDOW_H - 150, btn_w, 32), "Accept Draw")
        self.btn_decline = Button(pygame.Rect(btn_x, WINDOW_H - 110, btn_w, 32), "Decline Draw")
        self.btn_new_game = Button(pygame.Rect(btn_x, WINDOW_H - 70, btn_w, 32), "New Game")

    @property
    def flipped(self) -> bool:
        return self.my_color is False

    @property
    def is_my_turn(self) -> bool:
        return self.game_active and self.engine.turn == self.my_color

    # -- Networking -----------------------------------------------------------

    async def connect(self) -> None:
        try:
            self.ws = await websockets.connect(self.server_uri)
            self.connected = True
            self.status_text = "Connected. Joining queue..."
            await self.ws.send(json.dumps(JoinQueue().model_dump()))
        except Exception as e:
            self.status_text = f"Connection failed: {e}"
            self.connected = False

    async def send_msg(self, msg: dict) -> None:  # type: ignore[type-arg]
        if self.ws:
            await self.ws.send(json.dumps(msg))

    async def recv_messages(self) -> None:
        """Non-blocking receive: get all pending messages."""
        if not self.ws:
            return
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(self.ws.recv(), timeout=0.001)
                    data = json.loads(raw)
                    await self.handle_server_msg(data)
                except asyncio.TimeoutError:
                    break
        except websockets.ConnectionClosed:
            self.connected = False
            self.game_active = False
            self.status_text = "Disconnected from server"

    async def handle_server_msg(self, data: dict) -> None:  # type: ignore[type-arg]
        msg_type = data.get("type")

        if msg_type == "queue_waiting":
            self.status_text = "Waiting for opponent..."

        elif msg_type == "game_start":
            self.my_color = data["color"] == "white"
            self.engine.set_fen(data["fen"])
            self.game_id = data["game_id"]
            self.game_active = True
            self.game_over_msg = None
            self.draw_offered_by_us = False
            self.draw_offered_to_us = False
            color_name = "White" if self.my_color else "Black"
            self.status_text = f"Game started! You are {color_name}"

        elif msg_type == "game_state":
            self.engine.set_fen(data["fen"])
            self.last_move_uci = data.get("last_move")
            self.move_stack = data.get("move_stack", [])
            self.can_claim_draw = data.get("can_claim_draw", False)
            self.move_in_flight = False
            turn = "White" if data["turn"] == "white" else "Black"
            if self.is_my_turn:
                self.status_text = "Your turn"
            else:
                self.status_text = f"{turn}'s turn"

        elif msg_type == "game_over":
            self.game_active = False
            self.move_in_flight = False
            winner = data.get("winner")
            reason = data.get("reason", "")
            self.engine.set_fen(data["fen"])
            if winner is None:
                self.game_over_msg = f"Draw — {reason}"
            elif (winner == "white") == self.my_color:
                self.game_over_msg = f"You win! ({reason})"
            else:
                self.game_over_msg = f"You lose. ({reason})"
            self.status_text = self.game_over_msg
            self.selected_sq = None
            self.legal_targets = []

        elif msg_type == "move_error":
            self.move_in_flight = False
            self.status_text = f"Error: {data.get('message', '')}"

        elif msg_type == "draw_offered":
            self.draw_offered_to_us = True
            self.status_text = "Opponent offers a draw"

        elif msg_type == "draw_declined":
            self.draw_offered_by_us = False
            self.status_text = "Draw offer declined"

        elif msg_type == "server_error":
            self.status_text = f"Server: {data.get('message', '')}"

        elif msg_type == "spin_result":
            outcome = data.get("outcome", "end_turn")
            spinner = data.get("spinner", "white")
            spin_id = data.get("spin_id", "")
            self.wheel.trigger(outcome, spinner, spin_id)
            # Clear any drag state — the board is locked while the wheel spins.
            self.selected_sq = None
            self.legal_targets = []
            self.dragging_sq = None
            self.dragging_piece = None

    # -- Input handling -------------------------------------------------------

    def get_legal_targets(self, from_sq: int) -> list[int]:
        """Return list of target squares for legal moves from *from_sq*."""
        targets: list[int] = []
        for move in self.engine.legal_moves():
            if move.from_square == from_sq:
                if move.to_square not in targets:
                    targets.append(move.to_square)
        return targets

    async def handle_click(self, pos: tuple[int, int]) -> None:
        x, y = pos

        # Wheel of Fate overlay blocks all input while spinning
        if self.wheel.active:
            return

        # Promotion dialog takes priority
        if self.showing_promo_dialog:
            return  # handled separately in promotion click

        # Sidebar buttons
        if x >= BOARD_PX:
            await self.handle_sidebar_click(pos)
            return

        if not self.is_my_turn:
            return

        # Waiting on the server to acknowledge our previous move. Without
        # this guard, a fast double-click sends a second move against a
        # stale "still my turn" view and the server rejects it.
        if self.move_in_flight:
            return

        sq = self.renderer.pixel_to_square(x, y, self.flipped)
        if sq is None:
            self.selected_sq = None
            self.legal_targets = []
            return

        # If a square is already selected, try to move there
        if self.selected_sq is not None and sq in self.legal_targets:
            await self.try_move(self.selected_sq, sq)
            return

        # Select a piece
        piece = self.engine.piece_at(sq)
        if piece and piece.color == self.my_color:
            self.selected_sq = sq
            self.legal_targets = self.get_legal_targets(sq)
            # Start drag
            self.dragging_sq = sq
            self.dragging_piece = piece
        else:
            self.selected_sq = None
            self.legal_targets = []

    async def handle_mouse_up(self, pos: tuple[int, int]) -> None:
        if self.wheel.active or self.move_in_flight:
            self.dragging_sq = None
            self.dragging_piece = None
            return
        if self.dragging_sq is None:
            return

        x, y = pos
        drop_sq = self.renderer.pixel_to_square(x, y, self.flipped)

        from_sq = self.dragging_sq
        self.dragging_sq = None
        self.dragging_piece = None

        if drop_sq is not None and drop_sq != from_sq and drop_sq in self.legal_targets:
            await self.try_move(from_sq, drop_sq)

    async def try_move(self, from_sq: int, to_sq: int) -> None:
        if self.engine.is_promotion_move(from_sq, to_sq):
            self.pending_promo_from = from_sq
            self.pending_promo_to = to_sq
            self.showing_promo_dialog = True
            self.selected_sq = None
            self.legal_targets = []
            return

        uci = chess.Move(from_sq, to_sq).uci()
        self.move_in_flight = True
        await self.send_msg(MakeMove(uci=uci).model_dump())
        self.selected_sq = None
        self.legal_targets = []

    async def handle_promo_click(self, pos: tuple[int, int]) -> None:
        if not self.showing_promo_dialog or self.pending_promo_to is None:
            return

        file = chess.square_file(self.pending_promo_to)
        promo_rects = self.renderer.draw_promotion_dialog(
            self.screen, self.my_color or True, file, self.flipped, pos
        )
        for rect, piece_type in promo_rects:
            if rect.collidepoint(pos):
                move = chess.Move(self.pending_promo_from or 0,
                                  self.pending_promo_to, promotion=piece_type)
                self.move_in_flight = True
                await self.send_msg(MakeMove(uci=move.uci()).model_dump())
                self.showing_promo_dialog = False
                self.pending_promo_from = None
                self.pending_promo_to = None
                return

    async def handle_sidebar_click(self, pos: tuple[int, int]) -> None:
        if self.game_active:
            if self.btn_resign.clicked(pos):
                await self.send_msg(Resign().model_dump())
            elif self.draw_offered_to_us:
                if self.btn_accept.clicked(pos):
                    await self.send_msg(AcceptDraw().model_dump())
                    self.draw_offered_to_us = False
                elif self.btn_decline.clicked(pos):
                    await self.send_msg(DeclineDraw().model_dump())
                    self.draw_offered_to_us = False
            elif self.can_claim_draw and self.is_my_turn and self.btn_claim.clicked(pos):
                await self.send_msg(ClaimDraw().model_dump())
            elif not self.draw_offered_by_us and self.btn_draw.clicked(pos):
                await self.send_msg(OfferDraw().model_dump())
                self.draw_offered_by_us = True
                self.status_text = "Draw offered"
        elif self.game_over_msg and self.btn_new_game.clicked(pos):
            # Re-queue for a new game
            self.game_over_msg = None
            self.move_stack = []
            self.last_move_uci = None
            self.engine = ChessEngine()
            self.status_text = "Joining queue..."
            await self.send_msg(JoinQueue().model_dump())

    # -- Rendering ------------------------------------------------------------

    def draw(self) -> None:
        mouse_pos = pygame.mouse.get_pos()
        self.screen.fill(COLOR_BG)

        # Find king square if in check
        check_sq: Optional[int] = None
        if self.game_active and self.engine.is_check():
            for sq, piece in self.engine.piece_map().items():
                if piece.piece_type == chess.KING and piece.color == self.engine.turn:
                    check_sq = sq
                    break

        # Board
        self.renderer.draw_board(self.screen, self.flipped, self.last_move_uci, check_sq)

        # Selection + legal moves
        if self.selected_sq is not None:
            self.renderer.draw_highlights(self.screen, self.selected_sq,
                                          self.legal_targets, self.flipped)

        # Pieces
        self.renderer.draw_pieces(self.screen, self.engine.piece_map(),
                                  self.flipped, self.dragging_sq)

        # Dragging piece
        if self.dragging_piece is not None:
            mx, my = mouse_pos
            self.renderer.draw_dragging_piece(self.screen, self.dragging_piece, mx, my)

        # Promotion dialog
        if self.showing_promo_dialog and self.pending_promo_to is not None:
            file = chess.square_file(self.pending_promo_to)
            self.renderer.draw_promotion_dialog(
                self.screen, self.my_color or True, file, self.flipped, mouse_pos
            )

        # Sidebar
        self.draw_sidebar(mouse_pos)

        # Wheel of Fate overlay — drawn LAST so it sits on top of everything
        self.wheel.update()
        if self.wheel.active:
            cx = BOARD_PX // 2
            cy = BOARD_PX // 2
            self.wheel.draw(self.screen, cx, cy, WINDOW_W, WINDOW_H)

        pygame.display.flip()

    def draw_sidebar(self, mouse_pos: tuple[int, int]) -> None:
        sidebar_rect = pygame.Rect(BOARD_PX, 0, SIDEBAR_W, WINDOW_H)
        pygame.draw.rect(self.screen, COLOR_SIDEBAR, sidebar_rect)

        x = BOARD_PX + 10
        y = 10

        # Status
        status = self.font_big.render(self.status_text[:28], True, COLOR_ACCENT)
        self.screen.blit(status, (x, y))
        y += 35

        # Move list
        move_label = self.font.render("Moves:", True, COLOR_TEXT)
        self.screen.blit(move_label, (x, y))
        y += 22

        # Show moves in pairs (1. e4 e5  2. Nf3 Nc6 ...)
        for i in range(0, len(self.move_stack), 2):
            move_num = i // 2 + 1
            white_move = self.move_stack[i] if i < len(self.move_stack) else ""
            black_move = self.move_stack[i + 1] if i + 1 < len(self.move_stack) else ""
            line = f"{move_num}. {white_move}  {black_move}"
            text = self.font_small.render(line, True, COLOR_TEXT)
            self.screen.blit(text, (x, y))
            y += 16
            if y > WINDOW_H - 200:
                # Scroll indicator
                more = self.font_small.render("...", True, COLOR_TEXT)
                self.screen.blit(more, (x, y))
                break

        # Buttons
        if self.game_active:
            self.btn_resign.draw(self.screen, self.font, mouse_pos)

            if self.draw_offered_to_us:
                # Draw offer banner
                banner = pygame.Rect(BOARD_PX + 5, WINDOW_H - 190, SIDEBAR_W - 10, 28)
                pygame.draw.rect(self.screen, COLOR_DRAW_OFFER_BG, banner, border_radius=4)
                dt = self.font_small.render("Opponent offers a draw", True, COLOR_ACCENT)
                self.screen.blit(dt, (banner.x + 8, banner.y + 6))
                self.btn_accept.draw(self.screen, self.font, mouse_pos)
                self.btn_decline.draw(self.screen, self.font, mouse_pos)
            elif self.can_claim_draw and self.is_my_turn:
                self.btn_claim.draw(self.screen, self.font, mouse_pos)
            elif not self.draw_offered_by_us:
                self.btn_draw.draw(self.screen, self.font, mouse_pos)

        elif self.game_over_msg:
            self.btn_new_game.draw(self.screen, self.font, mouse_pos)

    # -- Main loop ------------------------------------------------------------

    async def run(self) -> None:
        await self.connect()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.showing_promo_dialog:
                        await self.handle_promo_click(event.pos)
                    else:
                        await self.handle_click(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    await self.handle_mouse_up(event.pos)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self.showing_promo_dialog:
                            self.showing_promo_dialog = False
                            self.pending_promo_from = None
                            self.pending_promo_to = None

            if self.connected:
                await self.recv_messages()

            self.draw()
            self.clock.tick(FPS)

        if self.ws:
            await self.ws.close()
        pygame.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chess client")
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER_URI,
        help=f"WebSocket server URI (default: {DEFAULT_SERVER_URI})",
    )
    args = parser.parse_args()
    client = ChessClient(server_uri=args.server)
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
