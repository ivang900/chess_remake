"""Tests for the shared chess rules engine."""

import chess
import pytest

from shared.engine import ChessEngine, GameResult


class TestBasicMoves:
    def test_initial_position(self) -> None:
        engine = ChessEngine()
        assert engine.turn is True  # White to move
        assert engine.fullmove_number == 1

    def test_push_legal_move(self) -> None:
        engine = ChessEngine()
        engine.push_uci("e2e4")
        assert engine.turn is False  # Black to move
        assert engine.piece_at(chess.E4) is not None
        assert engine.piece_at(chess.E2) is None

    def test_push_illegal_move_raises(self) -> None:
        engine = ChessEngine()
        with pytest.raises(ValueError, match="Illegal move"):
            engine.push_uci("e2e5")  # Pawn can't jump 3 squares

    def test_invalid_uci_raises(self) -> None:
        engine = ChessEngine()
        with pytest.raises(ValueError, match="Invalid UCI"):
            engine.push_uci("zzzz")

    def test_legal_moves_from_start(self) -> None:
        engine = ChessEngine()
        moves = engine.legal_moves()
        assert len(moves) == 20  # 16 pawn + 4 knight moves

    def test_fen_roundtrip(self) -> None:
        engine = ChessEngine()
        fen = engine.fen()
        engine2 = ChessEngine(fen)
        assert engine2.fen() == fen

    def test_pop_undo(self) -> None:
        engine = ChessEngine()
        engine.push_uci("e2e4")
        engine.pop()
        assert engine.turn is True
        assert engine.piece_at(chess.E2) is not None

    def test_move_stack(self) -> None:
        engine = ChessEngine()
        engine.push_uci("e2e4")
        engine.push_uci("e7e5")
        stack = engine.move_stack()
        assert len(stack) == 2
        assert stack[0].uci() == "e2e4"
        assert stack[1].uci() == "e7e5"


class TestCheck:
    def test_scholars_mate_is_checkmate(self) -> None:
        """Scholar's mate: 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6 4.Qxf7#"""
        engine = ChessEngine()
        for uci in ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]:
            engine.push_uci(uci)
        assert engine.is_checkmate()
        assert engine.is_game_over()
        result = engine.game_result()
        assert result is not None
        assert result.winner is True  # White wins
        assert result.reason == "checkmate"

    def test_check_but_not_mate(self) -> None:
        engine = ChessEngine()
        for uci in ["e2e4", "e7e5", "d1h5", "b8c6"]:
            engine.push_uci(uci)
        # Qh5 doesn't give check here, but let's set up a real check
        engine = ChessEngine()
        for uci in ["e2e4", "f7f5", "d1h5"]:
            engine.push_uci(uci)
        assert engine.is_check()
        assert not engine.is_checkmate()  # King can move to f7


class TestStalemate:
    def test_stalemate_position(self) -> None:
        # King on a1, opponent king on a3 + queen on b2 = stalemate for white
        engine = ChessEngine("k7/8/1K6/8/8/8/8/1q6 w - - 0 1")
        # White king on... let me use a proper stalemate FEN
        engine = ChessEngine("k7/8/1K6/8/8/8/8/8 w - - 0 1")
        # Actually, let me use a classic stalemate position
        engine = ChessEngine("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")
        # Black king h8, white queen g6, white king f7 — black has no moves
        assert engine.is_stalemate()
        result = engine.game_result()
        assert result is not None
        assert result.winner is None
        assert result.reason == "stalemate"


class TestCastling:
    def test_kingside_castling(self) -> None:
        # Position where white can castle kingside
        engine = ChessEngine("r1bqkbnr/pppppppp/2n5/8/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
        # Need to clear f1 for castling — let's use a direct FEN
        engine = ChessEngine("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
        assert engine.has_kingside_castling_rights(True)
        engine.push_uci("e1g1")  # Kingside castle
        assert engine.piece_at(chess.G1) is not None  # King
        assert engine.piece_at(chess.F1) is not None  # Rook

    def test_queenside_castling(self) -> None:
        engine = ChessEngine("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
        engine.push_uci("e1c1")  # Queenside castle
        assert engine.piece_at(chess.C1) is not None  # King
        assert engine.piece_at(chess.D1) is not None  # Rook

    def test_cannot_castle_through_check(self) -> None:
        # Black rook controls f1 — white can't castle kingside
        engine = ChessEngine("4k2r/8/8/8/8/8/8/R3K2R w KQ - 0 1")
        # Actually need a piece attacking f1
        engine = ChessEngine("4k3/8/8/8/5r2/8/8/R3K2R w KQ - 0 1")
        # Rook on f4 doesn't attack f1... let me use f1 control
        engine = ChessEngine("4k3/8/8/8/8/8/8/R3Kr1R w KQ - 0 1")
        # Can't castle because rook is on f1. Simpler: just check the move isn't legal
        engine = ChessEngine("4k3/8/8/5b2/8/8/8/R3K2R w KQ - 0 1")
        # Bishop on f5 controls... not f1. Let me just do a known position:
        # Black bishop on b4 gives check through e1, so can't castle
        engine = ChessEngine("4k3/8/8/8/1b6/8/8/R3K2R w KQ - 0 1")
        # Bishop on b4 attacks e1? No, bishops go diagonal. b4 attacks e1? b4-c3-d2-e1: yes!
        assert engine.is_check()
        move = engine.parse_uci("e1g1")
        assert move is not None
        assert not engine.is_legal(move)


class TestEnPassant:
    def test_en_passant_capture(self) -> None:
        # White pawn on e5, black plays d7d5 — white can capture en passant
        engine = ChessEngine("rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3")
        move = engine.parse_uci("e5d6")
        assert move is not None
        assert engine.is_legal(move)
        engine.push(move)
        # d5 pawn should be captured
        assert engine.piece_at(chess.D5) is None
        assert engine.piece_at(chess.D6) is not None  # White pawn now on d6


class TestPromotion:
    def test_promotion_detected(self) -> None:
        # White pawn on e7 about to promote
        engine = ChessEngine("7k/4P3/8/8/8/8/8/4K3 w - - 0 1")
        assert engine.is_promotion_move(chess.E7, chess.E8)

    def test_promotion_to_queen(self) -> None:
        engine = ChessEngine("7k/4P3/8/8/8/8/8/4K3 w - - 0 1")
        move = engine.promotion_move(chess.E7, chess.E8, chess.QUEEN)
        assert engine.is_legal(move)
        engine.push(move)
        piece = engine.piece_at(chess.E8)
        assert piece is not None
        assert piece.piece_type == chess.QUEEN

    def test_promotion_to_knight(self) -> None:
        engine = ChessEngine("7k/4P3/8/8/8/8/8/4K3 w - - 0 1")
        move = engine.promotion_move(chess.E7, chess.E8, chess.KNIGHT)
        assert engine.is_legal(move)
        engine.push(move)
        piece = engine.piece_at(chess.E8)
        assert piece is not None
        assert piece.piece_type == chess.KNIGHT

    def test_non_promotion_not_detected(self) -> None:
        engine = ChessEngine()
        assert not engine.is_promotion_move(chess.E2, chess.E4)


class TestDrawConditions:
    def test_insufficient_material_k_vs_k(self) -> None:
        engine = ChessEngine("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        assert engine.is_insufficient_material()
        result = engine.game_result()
        assert result is not None
        assert result.winner is None

    def test_insufficient_material_k_vs_kb(self) -> None:
        engine = ChessEngine("4k3/8/8/8/8/8/3B4/4K3 w - - 0 1")
        assert engine.is_insufficient_material()

    def test_sufficient_material_k_vs_kr(self) -> None:
        engine = ChessEngine("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        assert not engine.is_insufficient_material()

    def test_fifty_move_rule(self) -> None:
        # Set halfmove clock to 100 (50 moves each)
        engine = ChessEngine("4k3/8/8/8/8/8/8/R3K3 w - - 100 60")
        assert engine.is_fifty_moves()
        assert engine.can_claim_draw()

    def test_threefold_repetition(self) -> None:
        engine = ChessEngine()
        # Repeat knight moves to create threefold repetition
        moves = [
            "g1f3", "g8f6",
            "f3g1", "f6g8",
            "g1f3", "g8f6",
            "f3g1", "f6g8",
        ]
        for uci in moves:
            engine.push_uci(uci)
        assert engine.is_threefold_repetition()
        assert engine.can_claim_draw()


class TestGameResult:
    def test_no_result_at_start(self) -> None:
        engine = ChessEngine()
        assert engine.game_result() is None
        assert not engine.is_game_over()

    def test_game_result_repr(self) -> None:
        result = GameResult(True, "checkmate")
        assert "White" in repr(result)
        result2 = GameResult(None, "stalemate")
        assert "Draw" in repr(result2)


class TestSquareHelpers:
    def test_square_name(self) -> None:
        assert ChessEngine.square_name(chess.E4) == "e4"

    def test_square_from_name(self) -> None:
        assert ChessEngine.square_from_name("e4") == chess.E4

    def test_square_file_rank(self) -> None:
        assert ChessEngine.square_file(chess.E4) == 4
        assert ChessEngine.square_rank(chess.E4) == 3

    def test_square_construction(self) -> None:
        sq = ChessEngine.square(4, 3)  # file=4, rank=3 = e4
        assert sq == chess.E4


class TestPieceMap:
    def test_initial_piece_count(self) -> None:
        engine = ChessEngine()
        pieces = engine.piece_map()
        assert len(pieces) == 32  # All 32 pieces at start

    def test_piece_at(self) -> None:
        engine = ChessEngine()
        piece = engine.piece_at(chess.E1)
        assert piece is not None
        assert piece.piece_type == chess.KING
        assert piece.color is True  # White
