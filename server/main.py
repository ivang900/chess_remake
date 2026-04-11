"""FastAPI server with WebSocket matchmaking and game session management."""

from __future__ import annotations

import random
import uuid
from collections import deque
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from shared.engine import SpinChessEngine
from shared.models import (
    DrawDeclined,
    DrawOffered,
    GameOver,
    GameStart,
    GameState,
    MoveError,
    QueueWaiting,
    ServerError,
    SpinResult,
    parse_client_message,
)

# -- Wheel of Fate mod --------------------------------------------------------

SPIN_GO_AGAIN_PROB = 0.40  # 40% bonus move, 60% end turn

app = FastAPI(title="Chess Server")


# -- Game session -------------------------------------------------------------

class PlayerConnection:
    """A player in a game session."""

    def __init__(self, ws: WebSocket, color: bool) -> None:
        self.ws = ws
        self.color = color  # True = white, False = black

    async def send(self, msg: dict) -> None:  # type: ignore[type-arg]
        await self.ws.send_json(msg)


class GameSession:
    """Holds the state for one active game between two players."""

    def __init__(self, game_id: str, white: WebSocket, black: WebSocket) -> None:
        self.game_id = game_id
        self.engine = SpinChessEngine()
        self.white = PlayerConnection(white, True)
        self.black = PlayerConnection(black, False)
        self.draw_offer_from: Optional[bool] = None  # color that offered a draw

    def player(self, ws: WebSocket) -> Optional[PlayerConnection]:
        if ws is self.white.ws:
            return self.white
        if ws is self.black.ws:
            return self.black
        return None

    def opponent(self, player: PlayerConnection) -> PlayerConnection:
        return self.black if player.color else self.white

    def _game_state_msg(self) -> dict:  # type: ignore[type-arg]
        return GameState(
            fen=self.engine.fen(),
            last_move=self.engine.move_stack()[-1].uci() if self.engine.move_stack() else None,
            is_check=self.engine.is_check(),
            turn="white" if self.engine.turn else "black",
            legal_moves=[m.uci() for m in self.engine.legal_moves()],
            move_stack=[m.uci() for m in self.engine.move_stack()],
            can_claim_draw=self.engine.can_claim_draw(),
        ).model_dump()

    def _game_over_msg(self, winner: Optional[bool], reason: str) -> dict:  # type: ignore[type-arg]
        from typing import Literal
        w: Optional[Literal["white", "black"]] = None
        if winner is True:
            w = "white"
        elif winner is False:
            w = "black"
        return GameOver(winner=w, reason=reason, fen=self.engine.fen()).model_dump()

    async def _send_to(self, player: "PlayerConnection", msg: dict) -> None:  # type: ignore[type-arg]
        """Send to one player, swallowing failures so the other still gets it."""
        try:
            await player.send(msg)
        except Exception:
            pass

    async def broadcast(self, msg: dict) -> None:  # type: ignore[type-arg]
        await self._send_to(self.white, msg)
        await self._send_to(self.black, msg)

    async def broadcast_state(self) -> None:
        await self.broadcast(self._game_state_msg())

    async def broadcast_game_over(self, winner: Optional[bool], reason: str) -> None:
        await self.broadcast(self._game_over_msg(winner, reason))


# -- Global state -------------------------------------------------------------

waiting_queue: deque[WebSocket] = deque()
active_games: dict[str, GameSession] = {}
ws_to_game: dict[int, str] = {}  # id(ws) → game_id


# -- Matchmaking --------------------------------------------------------------

async def try_pair() -> None:
    """If two players are waiting, pair them into a game."""
    while len(waiting_queue) >= 2:
        white_ws = waiting_queue.popleft()
        black_ws = waiting_queue.popleft()

        game_id = uuid.uuid4().hex[:12]
        session = GameSession(game_id, white_ws, black_ws)
        active_games[game_id] = session
        ws_to_game[id(white_ws)] = game_id
        ws_to_game[id(black_ws)] = game_id

        start_fen = session.engine.fen()
        await white_ws.send_json(
            GameStart(color="white", fen=start_fen, game_id=game_id).model_dump()
        )
        await black_ws.send_json(
            GameStart(color="black", fen=start_fen, game_id=game_id).model_dump()
        )
        await session.broadcast_state()


def cleanup_game(game_id: str) -> None:
    session = active_games.pop(game_id, None)
    if session:
        ws_to_game.pop(id(session.white.ws), None)
        ws_to_game.pop(id(session.black.ws), None)


# -- Message handling ---------------------------------------------------------

async def handle_move(session: GameSession, player: PlayerConnection, uci: str) -> None:
    if session.engine.turn != player.color:
        await player.send(MoveError(message="Not your turn").model_dump())
        return

    move = session.engine.parse_uci(uci)
    if move is None or not session.engine.is_legal(move):
        await player.send(MoveError(message=f"Illegal move: {uci}").model_dump())
        return

    # Detect capture BEFORE pushing (board state is needed).
    was_capture = session.engine.is_capture(move)

    session.engine.push(move)
    session.draw_offer_from = None  # clear any pending draw offer after a move

    # Check for game end first — captures on the final move don't spin.
    result = session.engine.game_result()
    if result:
        await session.broadcast_game_over(result.winner, result.reason)
        cleanup_game(session.game_id)
        return

    # Wheel of Fate: spin only on captures.
    if was_capture:
        outcome = "go_again" if random.random() < SPIN_GO_AGAIN_PROB else "end_turn"
        spin_msg = SpinResult(
            spinner="white" if player.color else "black",
            outcome=outcome,  # type: ignore[arg-type]
            triggered_by_uci=uci,
            spin_id=uuid.uuid4().hex[:12],
        ).model_dump()
        await session.broadcast(spin_msg)

        if outcome == "go_again":
            session.engine.keep_turn()

    await session.broadcast_state()


async def handle_resign(session: GameSession, player: PlayerConnection) -> None:
    winner = not player.color
    await session.broadcast_game_over(winner, "resignation")
    cleanup_game(session.game_id)


async def handle_draw_offer(session: GameSession, player: PlayerConnection) -> None:
    if session.draw_offer_from is not None:
        await player.send(
            ServerError(message="A draw offer is already pending").model_dump()
        )
        return
    session.draw_offer_from = player.color
    opponent = session.opponent(player)
    await opponent.send(DrawOffered().model_dump())


async def handle_accept_draw(session: GameSession, player: PlayerConnection) -> None:
    if session.draw_offer_from is None or session.draw_offer_from == player.color:
        await player.send(ServerError(message="No draw offer to accept").model_dump())
        return
    await session.broadcast_game_over(None, "draw agreement")
    cleanup_game(session.game_id)


async def handle_decline_draw(session: GameSession, player: PlayerConnection) -> None:
    if session.draw_offer_from is None or session.draw_offer_from == player.color:
        await player.send(ServerError(message="No draw offer to decline").model_dump())
        return
    session.draw_offer_from = None
    opponent = session.opponent(player)
    await opponent.send(DrawDeclined().model_dump())


async def handle_claim_draw(session: GameSession, player: PlayerConnection) -> None:
    if session.engine.turn != player.color:
        await player.send(MoveError(message="Not your turn to claim draw").model_dump())
        return
    if not session.engine.can_claim_draw():
        await player.send(MoveError(message="No draw claim available").model_dump())
        return
    if session.engine.is_threefold_repetition():
        reason = "threefold repetition"
    else:
        reason = "fifty-move rule"
    await session.broadcast_game_over(None, reason)
    cleanup_game(session.game_id)


async def handle_message(ws: WebSocket, data: dict) -> None:  # type: ignore[type-arg]
    try:
        msg = parse_client_message(data)
    except ValueError as e:
        await ws.send_json(ServerError(message=str(e)).model_dump())
        return

    if msg.type == "join_queue":
        if id(ws) not in ws_to_game and ws not in waiting_queue:
            waiting_queue.append(ws)
            await ws.send_json(QueueWaiting().model_dump())
            await try_pair()
        return

    game_id = ws_to_game.get(id(ws))
    if not game_id or game_id not in active_games:
        await ws.send_json(ServerError(message="Not in a game").model_dump())
        return

    session = active_games[game_id]
    player = session.player(ws)
    if player is None:
        return

    if msg.type == "make_move":
        await handle_move(session, player, msg.uci)  # type: ignore[union-attr]
    elif msg.type == "resign":
        await handle_resign(session, player)
    elif msg.type == "offer_draw":
        await handle_draw_offer(session, player)
    elif msg.type == "accept_draw":
        await handle_accept_draw(session, player)
    elif msg.type == "decline_draw":
        await handle_decline_draw(session, player)
    elif msg.type == "claim_draw":
        await handle_claim_draw(session, player)


# -- WebSocket endpoint -------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            data = await ws.receive_json()
            await handle_message(ws, data)
    except WebSocketDisconnect:
        # Clean up: remove from queue or forfeit game
        if ws in waiting_queue:
            waiting_queue.remove(ws)

        game_id = ws_to_game.get(id(ws))
        if game_id and game_id in active_games:
            session = active_games[game_id]
            player = session.player(ws)
            if player:
                opponent = session.opponent(player)
                try:
                    await opponent.send(
                        GameOver(
                            winner="white" if opponent.color else "black",
                            reason="opponent disconnected",
                            fen=session.engine.fen(),
                        ).model_dump()
                    )
                except Exception:
                    pass
            cleanup_game(game_id)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
