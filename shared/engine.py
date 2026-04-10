"""Chess rules engine wrapping python-chess behind an overridable interface.

The default implementation delegates entirely to python-chess for standard
chess rules. Every public method is designed to be overridden for future mods
without touching client or server code.
"""

from __future__ import annotations

from typing import Optional

import chess


class GameResult:
    """Describes how and why a game ended."""

    def __init__(self, winner: Optional[bool], reason: str) -> None:
        """
        Args:
            winner: True = white wins, False = black wins, None = draw.
            reason: Human-readable explanation (e.g. "checkmate", "stalemate").
        """
        self.winner = winner
        self.reason = reason

    def __repr__(self) -> str:
        side = {True: "White", False: "Black", None: "Draw"}[self.winner]
        return f"GameResult({side}, {self.reason!r})"


class ChessEngine:
    """Abstraction layer over python-chess.

    Subclass and override methods to change rules, board shape, turn
    structure, or win/draw conditions for mods.
    """

    def __init__(self, fen: Optional[str] = None) -> None:
        self._board = chess.Board(fen) if fen else chess.Board()

    # -- Board state ----------------------------------------------------------

    def fen(self) -> str:
        """Return the current position as a FEN string."""
        return self._board.fen()

    def set_fen(self, fen: str) -> None:
        """Load a position from a FEN string."""
        self._board.set_fen(fen)

    @property
    def turn(self) -> bool:
        """True if it is white's turn, False for black."""
        return self._board.turn

    @property
    def fullmove_number(self) -> int:
        return self._board.fullmove_number

    @property
    def halfmove_clock(self) -> int:
        return self._board.halfmove_clock

    def piece_at(self, square: int) -> Optional[chess.Piece]:
        """Return the piece on *square*, or None if empty."""
        return self._board.piece_at(square)

    def piece_map(self) -> dict[int, chess.Piece]:
        """Return {square: Piece} for every occupied square."""
        return self._board.piece_map()

    # -- Move generation / validation -----------------------------------------

    def legal_moves(self) -> list[chess.Move]:
        """Return all legal moves for the side to move."""
        return list(self._board.legal_moves)

    def is_legal(self, move: chess.Move) -> bool:
        """Check whether *move* is legal in the current position."""
        return move in self._board.legal_moves

    def parse_uci(self, uci: str) -> Optional[chess.Move]:
        """Parse a UCI string (e.g. 'e2e4') into a Move, or None if invalid."""
        try:
            return chess.Move.from_uci(uci)
        except ValueError:
            return None

    def push(self, move: chess.Move) -> None:
        """Apply *move* to the board. Raises ValueError if illegal."""
        if not self.is_legal(move):
            raise ValueError(f"Illegal move: {move.uci()}")
        self._board.push(move)

    def push_uci(self, uci: str) -> chess.Move:
        """Parse and apply a UCI move string. Raises ValueError if illegal."""
        move = self.parse_uci(uci)
        if move is None:
            raise ValueError(f"Invalid UCI string: {uci!r}")
        self.push(move)
        return move

    # -- Undo -----------------------------------------------------------------

    def pop(self) -> chess.Move:
        """Undo the last move and return it."""
        return self._board.pop()

    def move_stack(self) -> list[chess.Move]:
        """Return the list of moves played so far."""
        return list(self._board.move_stack)

    # -- Game-ending conditions -----------------------------------------------

    def is_check(self) -> bool:
        return self._board.is_check()

    def is_checkmate(self) -> bool:
        return self._board.is_checkmate()

    def is_stalemate(self) -> bool:
        return self._board.is_stalemate()

    def is_insufficient_material(self) -> bool:
        return self._board.is_insufficient_material()

    def is_fifty_moves(self) -> bool:
        """Return True if the 50-move rule allows a draw claim."""
        return self._board.is_fifty_moves()

    def is_threefold_repetition(self) -> bool:
        return self._board.is_repetition(3)

    def is_fivefold_repetition(self) -> bool:
        return self._board.is_repetition(5)

    def is_seventyfive_moves(self) -> bool:
        """Return True if 75-move automatic draw applies."""
        return self._board.is_seventyfive_moves()

    def can_claim_draw(self) -> bool:
        """Return True if the side to move can claim a draw (50-move or threefold)."""
        return self._board.can_claim_draw()

    def is_game_over(self) -> bool:
        """Return True if the game has ended by any standard rule."""
        return self._board.is_game_over(claim_draw=False)

    def game_result(self) -> Optional[GameResult]:
        """Return a GameResult if the game is over, else None.

        This does NOT count claimable draws — only forced endings.
        """
        if self.is_checkmate():
            # Side to move is in checkmate, so the *other* side wins.
            winner = not self.turn
            return GameResult(winner, "checkmate")
        if self.is_stalemate():
            return GameResult(None, "stalemate")
        if self.is_insufficient_material():
            return GameResult(None, "insufficient material")
        if self.is_fivefold_repetition():
            return GameResult(None, "fivefold repetition")
        if self.is_seventyfive_moves():
            return GameResult(None, "seventy-five move rule")
        return None

    # -- Promotion helpers ----------------------------------------------------

    def is_promotion_move(self, from_sq: int, to_sq: int) -> bool:
        """Return True if moving from *from_sq* to *to_sq* would be a pawn promotion."""
        piece = self._board.piece_at(from_sq)
        if piece is None or piece.piece_type != chess.PAWN:
            return False
        rank = chess.square_rank(to_sq)
        if piece.color == chess.WHITE and rank == 7:
            return True
        if piece.color == chess.BLACK and rank == 0:
            return True
        return False

    def promotion_move(self, from_sq: int, to_sq: int, promotion: int) -> chess.Move:
        """Build a promotion move. *promotion* should be e.g. chess.QUEEN."""
        return chess.Move(from_sq, to_sq, promotion=promotion)

    # -- Castling info --------------------------------------------------------

    def has_kingside_castling_rights(self, color: bool) -> bool:
        return self._board.has_kingside_castling_rights(color)

    def has_queenside_castling_rights(self, color: bool) -> bool:
        return self._board.has_queenside_castling_rights(color)

    # -- Square helpers (static, but here for override-ability) ---------------

    @staticmethod
    def square_name(square: int) -> str:
        return chess.square_name(square)

    @staticmethod
    def square_from_name(name: str) -> int:
        return chess.parse_square(name)

    @staticmethod
    def square(file: int, rank: int) -> int:
        return chess.square(file, rank)

    @staticmethod
    def square_file(square: int) -> int:
        return chess.square_file(square)

    @staticmethod
    def square_rank(square: int) -> int:
        return chess.square_rank(square)
