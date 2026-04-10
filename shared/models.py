"""Pydantic models for all messages between client and server.

Every message over the WebSocket is a JSON blob with a "type" field
that determines the schema. This module defines all message types.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel

# -- Enums --------------------------------------------------------------------

class GameEndReason(str, Enum):
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    FIVEFOLD_REPETITION = "fivefold_repetition"
    SEVENTYFIVE_MOVES = "seventy_five_moves"
    THREEFOLD_REPETITION = "threefold_repetition"
    FIFTY_MOVES = "fifty_moves"
    RESIGNATION = "resignation"
    DRAW_AGREEMENT = "draw_agreement"


# -- Client → Server messages -------------------------------------------------

class JoinQueue(BaseModel):
    type: Literal["join_queue"] = "join_queue"


class MakeMove(BaseModel):
    type: Literal["make_move"] = "make_move"
    uci: str  # e.g. "e2e4" or "e7e8q" for promotion


class Resign(BaseModel):
    type: Literal["resign"] = "resign"


class OfferDraw(BaseModel):
    type: Literal["offer_draw"] = "offer_draw"


class AcceptDraw(BaseModel):
    type: Literal["accept_draw"] = "accept_draw"


class DeclineDraw(BaseModel):
    type: Literal["decline_draw"] = "decline_draw"


class ClaimDraw(BaseModel):
    """Claim a draw by threefold repetition or 50-move rule."""
    type: Literal["claim_draw"] = "claim_draw"


# -- Server → Client messages -------------------------------------------------

class QueueWaiting(BaseModel):
    type: Literal["queue_waiting"] = "queue_waiting"


class GameStart(BaseModel):
    type: Literal["game_start"] = "game_start"
    color: Literal["white", "black"]
    fen: str
    game_id: str


class GameState(BaseModel):
    type: Literal["game_state"] = "game_state"
    fen: str
    last_move: Optional[str] = None  # UCI of the move just played
    is_check: bool = False
    turn: Literal["white", "black"]
    legal_moves: list[str]  # list of UCI strings
    move_stack: list[str] = []  # all moves played so far
    can_claim_draw: bool = False


class GameOver(BaseModel):
    type: Literal["game_over"] = "game_over"
    winner: Optional[Literal["white", "black"]] = None  # None = draw
    reason: str
    fen: str


class MoveError(BaseModel):
    type: Literal["move_error"] = "move_error"
    message: str


class DrawOffered(BaseModel):
    """Notify opponent that a draw has been offered."""
    type: Literal["draw_offered"] = "draw_offered"


class DrawDeclined(BaseModel):
    type: Literal["draw_declined"] = "draw_declined"


class ServerError(BaseModel):
    type: Literal["server_error"] = "server_error"
    message: str


# -- Discriminated union for parsing ------------------------------------------

ClientMessage = JoinQueue | MakeMove | Resign | OfferDraw | AcceptDraw | DeclineDraw | ClaimDraw
ServerMessage = (
    QueueWaiting | GameStart | GameState | GameOver
    | MoveError | DrawOffered | DrawDeclined | ServerError
)


def parse_client_message(data: dict) -> ClientMessage:  # type: ignore[return]
    """Parse a raw dict into the correct client message model."""
    msg_type = data.get("type")
    _map: dict[str, type[BaseModel]] = {
        "join_queue": JoinQueue,
        "make_move": MakeMove,
        "resign": Resign,
        "offer_draw": OfferDraw,
        "accept_draw": AcceptDraw,
        "decline_draw": DeclineDraw,
        "claim_draw": ClaimDraw,
    }
    model = _map.get(msg_type or "")
    if model is None:
        raise ValueError(f"Unknown client message type: {msg_type!r}")
    return model.model_validate(data)  # type: ignore[return-value]
