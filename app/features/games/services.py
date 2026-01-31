from typing import Any, Dict, List, Optional, Tuple, DefaultDict, Iterable
from collections import defaultdict
from sqlmodel import Session

import secrets
import string
import random
from collections import Counter

from app.db.repositories.games import GameRepository
from app.db.repositories.players import PlayerRepository
from app.db.repositories.rounds import RoundRepository
from app.db.repositories.grids import GridRepository
from app.db.repositories.jokers import JokerRepository
from app.db.repositories.bonus import BonusRepository
from app.db.repositories.jokers_in_games import JokerInGameRepository
from app.db.repositories.jokers_used_in_games import JokerUsedInGameRepository
from app.db.repositories.bonus_in_games import BonusInGameRepository
from app.db.repositories.colors import ColorRepository
from app.db.repositories.questions import QuestionRepository

from app.features.games.schemas import GameCreateIn, RoundCreateIn, AnswerCreateIn, JokerUseIn, GameSetupSuggestIn, GameSetupSuggestOut

from app.core.config import settings

class PermissionError(Exception):
    """Accès interdit (owner/admin)."""
    pass

class ConflictError(Exception):
    """Conflit métier (url déjà prise, case déjà répondue, joker déjà utilisé...)."""
    pass

class GameService:
    """
    Service métier Game : orchestre repos + règles.

    Conçu pour matcher les routes proposées :
    - state par game_url
    - use_joker séparé de answer_question
    - auto_next_round possible après answer_question
    """
    def __init__(
        self,
        session: Session,
        game_repo: GameRepository,
        player_repo: PlayerRepository,
        round_repo: RoundRepository,
        grid_repo: GridRepository,
        joker_repo: JokerRepository,
        joker_in_game_repo: JokerInGameRepository,
        joker_used_repo: JokerUsedInGameRepository,
        bonus_repo: BonusRepository,
        bonus_in_game_repo: BonusInGameRepository,
        color_repo: ColorRepository,
        question_repo: QuestionRepository,
    ):
        self.session = session

        self.games = game_repo
        self.players = player_repo
        self.rounds = round_repo
        self.grids = grid_repo

        self.jokers = joker_repo
        self.jokers_in_game = joker_in_game_repo
        self.jokers_used = joker_used_repo

        self.bonus = bonus_repo
        self.bonus_in_game = bonus_in_game_repo

        self.colors = color_repo

        self.questions = question_repo
        self.QUESTIONS_PAGE_SIZE = 500

        # ---------------------------------------------------------------------
        # Constantes jokers (utilisées partout)
        # ---------------------------------------------------------------------
        self.JOKER_X2 = "x2"
        self.JOKER_ALL_IN = "All-In"
        self.JOKER_FLASH = "Flash"
        self.JOKER_GAMBLE = "Gamble"
        self.JOKER_APPEL = "Appel à un ami"

    # -----------------------------------
    # Helpers: auth & ownership
    # -----------------------------------
    def _get_game_or_404(self, game_url: str):
        game = self.games.get_by_url(game_url)
        if not game:
            raise LookupError("GAME_NOT_FOUND")
        return game

    def _ensure_owner_or_admin(self, game, *, user_id: int, is_admin: bool) -> None:
        if (game.owner_id != user_id) and (not is_admin):
            raise PermissionError("FORBIDDEN")

    # -----------------------------------
    # Helpers: url games
    # -----------------------------------
    def _generate_game_url(self) -> str:
        """
        Génère une url/slug courte, safe pour URL.
        Exemple: g-8f3k1p9z
        """
        alphabet = string.ascii_lowercase + string.digits
        token = "".join(secrets.choice(alphabet) for _ in range(8))
        return f"g-{token}"
    
    # -----------------------------------
    # Helpers: question selection for new games
    # -----------------------------------
    def _load_all_question_ids_for_theme(self, theme_id: int) -> List[int]:
        """Charge tous les IDs de questions pour un thème via pagination."""
        ids: List[int] = []
        offset = 0
        while True:
            batch = self.questions.list_by_theme(
                theme_id,
                offset=offset,
                limit=self.QUESTIONS_PAGE_SIZE,
                newest_first=False,  # stable
            )
            if not batch:
                break
            ids.extend([q.id for q in batch])
            offset += len(batch)
            if len(batch) < self.QUESTIONS_PAGE_SIZE:
                break
        return ids

    # -----------------------------------
    # Helpers: pawn movement (with_pawns mode)
    # -----------------------------------
    def _is_edge_cell(self, row: int, col: int, rows: int, cols: int) -> bool:
        """Check if cell is on the edge of the grid."""
        return row == 0 or row == rows - 1 or col == 0 or col == cols - 1

    def _get_valid_pawn_moves(
        self,
        player_row: Optional[int],
        player_col: Optional[int],
        rows: int,
        cols: int,
        answered_cells: set,
        other_pawn_positions: set,
        allowed_steps: int = 1,
    ) -> set:
        """
        Compute valid cells for a pawn to move to (queen-like movement with fallbacks).
        - If pawn is off-grid (None, None): can move to any unanswered edge cell
        - If pawn is on-grid: move in straight lines (8 directions like a chess queen)
          - Moving to an answered cell or cell with pawn costs 0 steps (free traversal)
          - Moving to an unanswered cell costs 1 step
          - Can only stop on unanswered cells without pawns
        - Fallback 1: if no moves, allow any unanswered edge cell
        - Fallback 2: if no edge cells, allow any unanswered cell on the board
        """
        valid = set()

        if player_row is None or player_col is None:
            for r in range(rows):
                for c in range(cols):
                    if self._is_edge_cell(r, c, rows, cols):
                        if (r, c) not in answered_cells and (r, c) not in other_pawn_positions:
                            valid.add((r, c))
        else:
            directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

            for dr, dc in directions:
                steps_used = 0
                nr, nc = player_row + dr, player_col + dc

                while 0 <= nr < rows and 0 <= nc < cols:
                    has_other_pawn = (nr, nc) in other_pawn_positions
                    is_answered = (nr, nc) in answered_cells

                    is_free = is_answered or has_other_pawn
                    step_cost = 0 if is_free else 1
                    steps_used += step_cost

                    if steps_used > allowed_steps:
                        break

                    if not is_free:
                        valid.add((nr, nc))

                    nr += dr
                    nc += dc

            if not valid:
                for r in range(rows):
                    for c in range(cols):
                        if self._is_edge_cell(r, c, rows, cols):
                            if (r, c) not in answered_cells and (r, c) not in other_pawn_positions:
                                valid.add((r, c))

            if not valid:
                for r in range(rows):
                    for c in range(cols):
                        if (r, c) not in answered_cells and (r, c) not in other_pawn_positions:
                            valid.add((r, c))

        return valid

    def _validate_pawn_move(
        self,
        game,
        player,
        target_row: int,
        target_col: int,
        grid_cells,
    ) -> None:
        """
        Validate that a pawn move is legal.
        Raises ConflictError if invalid.
        """
        if not game.with_pawns:
            return

        answered_cells = set()
        for cell in grid_cells:
            if cell.round_id is not None:
                answered_cells.add((cell.row, cell.column))

        players = self.players.list_by_game(game.id)
        other_pawn_positions = set()
        for p in players:
            if p.id != player.id and p.pawn_row is not None and p.pawn_col is not None:
                other_pawn_positions.add((p.pawn_row, p.pawn_col))

        valid_moves = self._get_valid_pawn_moves(
            player.pawn_row,
            player.pawn_col,
            game.rows_number,
            game.columns_number,
            answered_cells,
            other_pawn_positions,
            player.allowed_steps,
        )

        if (target_row, target_col) not in valid_moves:
            raise ConflictError("INVALID_PAWN_MOVE")

    # ---------------------------------------------------------------------
    # Catalogues jokers / bonus
    # ---------------------------------------------------------------------

    def list_all_jokers(self) -> List[Dict[str, Any]]:
        rows = self.jokers.list_name_description()
        return [{"id": r[0], "name": r[1], "description": r[2], "requires_target_player": r[3], "requires_target_grid": r[4]} for r in rows]

    def list_all_bonus(self) -> List[Dict[str, Any]]:
        rows = self.bonus.list_name_description()
        return [{"id": r[0], "name": r[1], "description": r[2]} for r in rows]

    # ---------------------------------------------------------------------
    # Parties d'un user + joueurs + couleur(hex) + thème
    # ---------------------------------------------------------------------

    def list_user_games_with_players(self, owner_id: int) -> List[Dict[str, Any]]:
        flat = self.games.list_by_owner_with_players_color_theme(owner_id)

        # Remap plat -> hiérarchie
        by_game: Dict[int, Dict[str, Any]] = {}
        for r in flat:
            gid = r.game_id
            if gid not in by_game:
                by_game[gid] = {
                    "id": gid,
                    "url": r.game_url,
                    "seed": r.seed,
                    "rows_number": r.rows_number,
                    "columns_number": r.columns_number,
                    "finished": r.finished,
                    "with_pawns": r.with_pawns,
                    "players": [],
                }

            # si partie sans players encore
            if r.player_id is not None:
                by_game[gid]["players"].append(
                    {
                        "id": r.player_id,
                        "name": r.player_name,
                        "order": r.player_order,
                        "color": {"id": r.color_id, "hex_code": r.color_hex_code},
                        "theme": {"id": r.theme_id, "name": r.theme_name},
                    }
                )

        return list(by_game.values())

    # ---------------------------------------------------------------------
    # Create game
    # ---------------------------------------------------------------------

    def create_game(self, payload: GameCreateIn, *, owner_id: int) -> Any:
        # Fixed random
        rng = random.Random(payload.seed)

        # 1) génère une url unique avec retry
        url = self._generate_game_url()
        tries = 0
        while self.games.get_by_url(url):
            tries += 1
            if tries >= 10:
                raise ConflictError("GAME_URL_GENERATION_FAILED")
            url = self._generate_game_url()

        # thèmes joueurs uniques
        theme_ids = [p.theme_id for p in payload.players]
        if len(theme_ids) != len(set(theme_ids)):
            raise ConflictError("DUPLICATE_PLAYER_THEMES_NOT_ALLOWED")
    
        # Transaction globale
        game = self.games.create(
            commit=False,
            owner_id=owner_id,
            seed=payload.seed,
            url=url,
            rows_number=payload.rows_number,
            columns_number=payload.columns_number,
            finished=False,
            with_pawns=payload.with_pawns,
        )

        # Players
        players_payload = list(payload.players)
        rng.shuffle(players_payload)

        created_players = []
        for idx, p in enumerate(players_payload, start=1):
            created_players.append(
                self.players.create(
                    commit=False,
                    game_id=game.id,
                    color_id=p.color_id,
                    theme_id=p.theme_id,
                    name=p.name,
                    order=idx,
                )
            )

        # Attach jokers/bonus (optionnel)
        if payload.joker_ids:
            for jid in payload.joker_ids:
                # unique constraint côté DB (joker_id, game_id)
                self.jokers_in_game.create(commit=False, joker_id=jid, game_id=game.id)

        if payload.bonus_ids:
            for bid in payload.bonus_ids:
                self.bonus_in_game.create(commit=False, bonus_id=bid, game_id=game.id)

        # init grille (cells + question_id) selon seed
        rows = payload.rows_number
        cols = payload.columns_number
        grid_size = rows * cols

        nb_players = len(payload.players)
        player_q_total = nb_players * payload.number_of_questions_by_player
        general_q_total = grid_size - player_q_total
        if general_q_total < 0:
            raise ConflictError("GRID_TOO_SMALL_FOR_REQUESTED_PLAYER_QUESTIONS")

        if not payload.general_theme_ids:
            raise ConflictError("GENERAL_THEMES_REQUIRED")


        player_theme_ids = [p.theme_id for p in created_players]
        general_theme_ids = list(payload.general_theme_ids)

        # Interdire qu'un thème joueur soit aussi culture G :
        general_theme_ids = [tid for tid in general_theme_ids if tid not in set(player_theme_ids)]
        if not general_theme_ids: raise ConflictError("GENERAL_THEMES_REQUIRED")

        theme_ids_needed = sorted(set(player_theme_ids) | set(general_theme_ids))

        # 1) pool d'IDs par thème
        pool: Dict[int, List[int]] = {}
        for tid in theme_ids_needed:
            qids = self._load_all_question_ids_for_theme(tid)
            rng.shuffle(qids)  # déterministe
            pool[tid] = qids

        # 2) tirer questions joueurs
        player_selected_qids: List[int] = []
        for tid in player_theme_ids:
            need = payload.number_of_questions_by_player
            if len(pool.get(tid, [])) < need:
                raise ConflictError("NOT_ENOUGH_QUESTIONS_FOR_PLAYER_THEME")
            for _ in range(need):
                player_selected_qids.append(pool[tid].pop())

        # 3) tirer questions culture G (répartition random sur themes)
        general_selected_qids: List[int] = []
        for _ in range(general_q_total):
            tid = rng.choice(general_theme_ids)
            if not pool.get(tid):
                # fallback: prendre un autre thème non vide
                non_empty = [x for x in general_theme_ids if pool.get(x)]
                if not non_empty:
                    raise ConflictError("NOT_ENOUGH_QUESTIONS_FOR_GENERAL_THEMES")
                tid = rng.choice(non_empty)
            general_selected_qids.append(pool[tid].pop())

        # 4) placement
        coords = [(r, c) for r in range(rows) for c in range(cols)]
        rng.shuffle(coords)

        # Mélange des questions pour éviter "bloc joueur puis bloc culture G"
        all_qids = player_selected_qids + general_selected_qids
        rng.shuffle(all_qids)

        if len(all_qids) != grid_size:
            raise ConflictError("GRID_FILL_COUNT_MISMATCH")

        grids_to_create = []
        for (r, c), qid in zip(coords, all_qids):
            grids_to_create.append(
                self.grids.create(
                    commit=False,
                    game_id=game.id,
                    round_id=None,
                    question_id=qid,
                    correct_answer=False,
                    skip_answer=False,
                    row=r,
                    column=c,
                )
            )

        # 6) créer le first round (round_number=1) pour le premier joueur
        first_player = self.players.get_next_player_in_game(game.id, current_order=0)
        if not first_player:
            raise ConflictError("GAME_HAS_NO_PLAYERS")

        first_round = self.rounds.create(
            commit=False,          # important: même transaction
            player_id=first_player.id,
            round_number=1,
        )

        self.session.commit()
        self.session.refresh(game)
        return game
    
    # ---------------------------------------------------------------------
    # Etat d'une partie
    # ---------------------------------------------------------------------

    def get_game_state(self, game_url: str, *, user_id: int, is_admin: bool) -> Dict[str, Any]:
        game = self._get_game_or_404(game_url)
        self._ensure_owner_or_admin(game, user_id=user_id, is_admin=is_admin)

        players = self.players.list_by_game(game.id)
        nb_players = len(players)
        if nb_players <= 0:
            raise ConflictError("GAME_HAS_NO_PLAYERS")

        # ✅ Mapping round_id -> player_id (pour savoir qui a répondu)
        rounds_flat = self.rounds.list_by_game(game.id)
        round_to_player_id: Dict[int, int] = {r.round_id: r.player_id for r in rounds_flat}

        # 1) grille complète : cases + question(theme+points)
        grid_rows = self.grids.list_grid_questions_with_theme_and_points(game.id)
        grid = [
            {
                "grid_id": r.grid_id,
                "row": r.row,
                "column": r.column,
                "round_id": r.round_id,
                "player_id": round_to_player_id.get(r.round_id) if r.round_id else None,
                "correct_answer": r.correct_answer,
                "skip_answer": r.skip_answer,
                "question": {
                    "id": r.question_id,
                    "theme": {"id": r.question_theme_id, "name": r.question_theme_name},
                    "points": int(r.question_points or 0),
                },
            }
            for r in grid_rows
        ]

        # ------------------------------------------------------------------
        # ✅ NOUVELLE RÈGLE FIN DE PARTIE
        # fin quand on ne peut plus faire un tour complet
        # ------------------------------------------------------------------
        grid_size = len(grid_rows)  # = rows*cols
        max_full_turns = grid_size // nb_players          # quotient
        max_rounds = max_full_turns * nb_players          # nb rounds jouables (rotation complète only)

        answered_count = sum(1 for r in grid_rows if r.round_id is not None)

        finished_by_rule = answered_count >= max_rounds

        # ✅ Marquer la partie comme terminée si nécessaire
        if finished_by_rule and not game.finished:
            game = self.games.update(game, commit=True, finished=True)

        # 2) dernier round à jouer (= dernier round ajouté à rounds pas encore dans la grille)
        last_pending_round = self.rounds.get_last_round_not_in_grid(game.id)

        current_turn = None
        current_full_turn_number = 0

        if (not game.finished) and last_pending_round:
            if last_pending_round.round_number <= max_rounds:
                current_turn = {
                    "round_id": last_pending_round.round_id,
                    "round_number": last_pending_round.round_number,
                    "player": {
                        "id": last_pending_round.player_id,
                        "name": last_pending_round.player_name,
                        "order": last_pending_round.player_order,
                        "theme_id": last_pending_round.player_theme_id,
                    },
                }

                # ✅ bool : est-on sur le dernier tour complet ?
                current_full_turn_number = ((last_pending_round.round_number - 1) // nb_players) + 1

        # 3) jokers dispo pour le joueur du tour (disponible = pas utilisé avant ce round)
        all_jig = self.jokers_in_game.list_for_game(game.id)  # jokers au niveau partie
        used_by_player = self.jokers_used.list_used_joker_in_game_ids_grouped_by_player_for_game(game.id)

        available_jokers: Dict[int, List[Dict[str, Any]]] = {}
        for p in players:
            used_set = used_by_player.get(p.id, set())

            available_jokers[p.id] = [
                {
                    "joker_in_game_id": r.joker_in_game_id,
                    "joker": {
                        "id": r.joker_id,
                        "name": r.name,
                        "description": r.description,
                        "requires_target_player": bool(r.requires_target_player),
                        "requires_target_grid": bool(r.requires_target_grid),
                    },
                    "available": (r.joker_in_game_id not in used_set),
                }
                for r in all_jig
            ]

        # 4) scores
        scores, last_round_delta = self._compute_scores(game_id=game.id, players=players)

        # 5) bonus attachés au game
        bonus = [
            {
                "bonus_in_game_id": r.bonus_in_game_id,
                "bonus": {"id": r.bonus_id, "name": r.name, "description": r.description},
            }
            for r in self.bonus_in_game.list_for_game(game.id)
        ]

        return {
            "game": {
                "id": game.id,
                "url": game.url,
                "seed": game.seed,
                "rows_number": game.rows_number,
                "columns_number": game.columns_number,
                "finished": game.finished,
                "with_pawns": game.with_pawns,
                "owner_id": game.owner_id
            },
            "players": [
                {
                    "id": p.id,
                    "name": p.name,
                    "order": p.order,
                    "theme_id": p.theme_id,
                    "color_id": p.color_id,
                    "pawn_row": p.pawn_row,
                    "pawn_col": p.pawn_col,
                    "allowed_steps": p.allowed_steps,
                }
                for p in players
            ],
            "grid": grid,
            "current_turn": current_turn,
            "available_jokers": available_jokers,
            "bonus": bonus,
            "scores": scores,
            "last_round_delta": last_round_delta,
            "max_full_turns": max_full_turns,
            "current_full_turn_number": current_full_turn_number,
        }

    # ---------------------------------------------------------------------
    # Helpers scoring (factorisés)
    # ---------------------------------------------------------------------

    def _build_round_indexes(self, game_id: int) -> Tuple[Dict[int, int], Dict[int, int]]:
        rounds_flat = self.rounds.list_by_game(game_id)
        round_to_player_id = {r.round_id: r.player_id for r in rounds_flat}
        round_to_round_number = {r.round_id: r.round_number for r in rounds_flat}
        return round_to_player_id, round_to_round_number

    def _build_joker_indexes(self, used_rows: List[Any]) -> Tuple[DefaultDict[int, List[Any]], DefaultDict[int, List[Any]]]:
        jokers_by_round: DefaultDict[int, List[Any]] = defaultdict(list)
        gambles_by_grid: DefaultDict[int, List[Any]] = defaultdict(list)

        for u in used_rows:
            jokers_by_round[u.round_id].append(u)
            if u.joker_name == self.JOKER_GAMBLE and u.target_grid_id:
                gambles_by_grid[u.target_grid_id].append(u)

        return jokers_by_round, gambles_by_grid

    def _iter_round_jokers(
        self,
        jokers_by_round: DefaultDict[int, List[Any]],
        *,
        round_id: int,
        using_player_id: int,
        joker_name: str,
    ) -> Iterable[Any]:
        for u in jokers_by_round.get(round_id, []):
            if u.using_player_id == using_player_id and u.joker_name == joker_name:
                yield u

    def _has_round_joker(
        self,
        jokers_by_round: DefaultDict[int, List[Any]],
        *,
        round_id: int,
        using_player_id: int,
        joker_name: str,
    ) -> bool:
        return any(True for _ in self._iter_round_jokers(
            jokers_by_round,
            round_id=round_id,
            using_player_id=using_player_id,
            joker_name=joker_name,
        ))

    def _called_player_ids_for_round(
        self,
        jokers_by_round: DefaultDict[int, List[Any]],
        *,
        round_id: int,
        answering_player_id: int,
    ) -> List[int]:
        return [
            u.target_player_id
            for u in self._iter_round_jokers(
                jokers_by_round,
                round_id=round_id,
                using_player_id=answering_player_id,
                joker_name=self.JOKER_APPEL,
            )
            if u.target_player_id
        ]

    def _score_timeline(
        self,
        *,
        game_id: int,
        players_out: List[Dict[str, Any]],
        answered_cells: List[Any],
        used_rows: List[Any],
        round_to_player_id: Dict[int, int],
        round_to_round_number: Dict[int, int],
        with_history: bool,
        with_bonus_metrics: bool = False,
    ) -> Tuple[
        Dict[int, int],               # final_scores
        List[Dict[str, Any]],         # turn_scores_out
        Dict[int, Dict[int, int]],    # joker_impacts_by_usage_id
        Dict[int, Dict[int, int]],    # round_deltas_by_round_id
        Dict[str, Dict[int, int]],    # bonus_metrics
    ]:
        nb_players = len(players_out)
        all_player_ids = [p["id"] for p in players_out]

        player_theme = {p["id"]: p["theme"]["id"] for p in players_out}
        theme_owner = {p["theme"]["id"]: p["id"] for p in players_out}

        def owner_of_theme(theme_id: int) -> Optional[int]:
            return theme_owner.get(theme_id)

        jokers_by_round, gambles_by_grid = self._build_joker_indexes(used_rows)

        # Tri stable seulement pour l'historique
        cells = answered_cells
        if with_history:
            def _cell_sort_key(cell: Any):
                rn = round_to_round_number.get(getattr(cell, "round_id", None) or -1, 10**9)
                return (rn, int(getattr(cell, "id", 0)))
            cells = sorted(answered_cells, key=_cell_sort_key)

        cumulative_scores: Dict[int, int] = {pid: 0 for pid in all_player_ids}

        turn_deltas: Dict[int, Dict[int, int]] = {}
        turn_cumulatives: Dict[int, Dict[int, int]] = {}
        round_deltas_by_round_id: Dict[int, Dict[int, int]] = {}

        joker_impacts_by_usage_id: Dict[int, Dict[int, int]] = (
            {u.usage_id: {pid: 0 for pid in all_player_ids} for u in used_rows}
            if with_history else {}
        )

        # ✅ métriques bonus (collectées sur le même passage)
        inflicted_loss_by_player: Dict[int, int] = {pid: 0 for pid in all_player_ids}   # Sniper
        suffered_loss_by_player: Dict[int, int] = {pid: 0 for pid in all_player_ids}    # Victime
        attempted_difficulty_by_player: Dict[int, int] = {pid: 0 for pid in all_player_ids}  # Game addict

        def add_score(pid: int, d: int) -> None:
            cumulative_scores[pid] = cumulative_scores.get(pid, 0) + d

        def ensure_turn(turn_number: int) -> None:
            if not with_history:
                return
            turn_deltas.setdefault(turn_number, {pid: 0 for pid in all_player_ids})

        def add_turn_delta(turn_number: int, pid: int, d: int) -> None:
            if not with_history:
                return
            ensure_turn(turn_number)
            turn_deltas[turn_number][pid] += d

        def snapshot_turn(turn_number: int) -> None:
            if not with_history:
                return
            turn_cumulatives[turn_number] = dict(cumulative_scores)

        def add_joker_delta(usage_id: int, pid: int, d: int) -> None:
            if not with_history:
                return
            joker_impacts_by_usage_id.setdefault(usage_id, {p: 0 for p in all_player_ids})
            joker_impacts_by_usage_id[usage_id][pid] += d

        # helpers bonus
        def bonus_inflict_loss(attacker: int, victim: int, pts: int) -> None:
            if not with_bonus_metrics:
                return
            if attacker == victim:
                return  # on ignore les pertes auto-infligées pour Sniper/Victime
            inflicted_loss_by_player[attacker] += pts
            suffered_loss_by_player[victim] += pts

        def bonus_attempt(player_id: int, pts: int) -> None:
            if not with_bonus_metrics:
                return
            attempted_difficulty_by_player[player_id] += pts

        # -----------------------------
        # Main loop : 1 cell = 1 round résolu
        # -----------------------------
        for cell in cells:
            round_id = getattr(cell, "round_id", None)
            if not round_id:
                continue

            answering_player_id = round_to_player_id.get(round_id)
            if not answering_player_id:
                continue

            round_number = int(round_to_round_number.get(round_id, 1))
            turn_number = ((round_number - 1) // max(nb_players, 1)) + 1

            ensure_turn(turn_number)

            # delta net de CE round (scores + jokers + effets décalés)
            delta: Dict[int, int] = {pid: 0 for pid in all_player_ids}

            # Skip => aucun effet (ni jokers, ni gamble)
            if bool(getattr(cell, "skip_answer", False)):
                if with_history:
                    round_deltas_by_round_id[round_id] = dict(delta)
                    snapshot_turn(turn_number)
                continue

            points = int(getattr(cell, "question_points", 0) or 0)
            question_theme_id = getattr(cell, "question_theme_id", None)
            is_correct = bool(getattr(cell, "correct_answer", False))

            # ✅ Game addict : tentative = non-skip, quel que soit correct/incorrect
            bonus_attempt(answering_player_id, points)

            called_player_ids = self._called_player_ids_for_round(
                jokers_by_round,
                round_id=round_id,
                answering_player_id=answering_player_id,
            )
            owner_id = owner_of_theme(question_theme_id) if question_theme_id is not None else None
            owner_penalty_blocked = (owner_id is not None and owner_id in called_player_ids)

            # -------- scoring normal
            if is_correct:
                delta[answering_player_id] += points

                # thème adverse => owner perd (sauf blocage)
                if player_theme.get(answering_player_id) != question_theme_id:
                    if owner_id and not owner_penalty_blocked:
                        delta[owner_id] -= points
                        # ✅ bonus sniper/victime : perte infligée à owner
                        bonus_inflict_loss(answering_player_id, owner_id, points)

            # -------- x2
            if is_correct and self._has_round_joker(
                jokers_by_round,
                round_id=round_id,
                using_player_id=answering_player_id,
                joker_name=self.JOKER_X2,
            ):
                delta[answering_player_id] += points

                if player_theme.get(answering_player_id) != question_theme_id:
                    if owner_id and not owner_penalty_blocked:
                        delta[owner_id] -= points
                        # ✅ bonus sniper/victime : perte infligée doublée (x2)
                        bonus_inflict_loss(answering_player_id, owner_id, points)

                if with_history:
                    for u in self._iter_round_jokers(
                        jokers_by_round,
                        round_id=round_id,
                        using_player_id=answering_player_id,
                        joker_name=self.JOKER_X2,
                    ):
                        add_joker_delta(u.usage_id, answering_player_id, +points)
                        if owner_id and not owner_penalty_blocked:
                            add_joker_delta(u.usage_id, owner_id, -points)

            # -------- all-in
            if self._has_round_joker(
                jokers_by_round,
                round_id=round_id,
                using_player_id=answering_player_id,
                joker_name=self.JOKER_ALL_IN,
            ):
                for u in self._iter_round_jokers(
                    jokers_by_round,
                    round_id=round_id,
                    using_player_id=answering_player_id,
                    joker_name=self.JOKER_ALL_IN,
                ):
                    uid = u.usage_id
                    if is_correct:
                        for pid in all_player_ids:
                            if pid == answering_player_id:
                                continue
                            delta[pid] -= points
                            # ✅ bonus sniper/victime : le joueur inflige une perte à tous les autres
                            bonus_inflict_loss(answering_player_id, pid, points)
                            add_joker_delta(uid, pid, -points)
                    else:
                        # incorrect => perte auto-infligée => pas Sniper/Victime
                        delta[answering_player_id] -= points
                        add_joker_delta(uid, answering_player_id, -points)

            # -------- appel à un ami
            for u in self._iter_round_jokers(
                jokers_by_round,
                round_id=round_id,
                using_player_id=answering_player_id,
                joker_name=self.JOKER_APPEL,
            ):
                if not u.target_player_id:
                    continue
                uid = u.usage_id
                if is_correct:
                    delta[u.target_player_id] += points
                    add_joker_delta(uid, u.target_player_id, +points)
                else:
                    delta[u.target_player_id] -= points
                    # ✅ bonus sniper/victime : si incorrect, l'ami perd à cause du joueur
                    bonus_inflict_loss(answering_player_id, u.target_player_id, points)
                    add_joker_delta(uid, u.target_player_id, -points)

            # -------- gamble (déclenché sur résolution de la case ciblée)
            # (ne compte pas pour Sniper/Victime car n'inflige pas une perte à un autre joueur)
            for u in gambles_by_grid.get(getattr(cell, "id", None), []):
                gambler_id = u.using_player_id
                uid = u.usage_id

                if gambler_id == answering_player_id:
                    continue

                if is_correct:
                    delta[gambler_id] += points
                    add_joker_delta(uid, gambler_id, +points)
                else:
                    delta[gambler_id] -= points
                    add_joker_delta(uid, gambler_id, -points)

            # -------- appliquer delta au cumul + historique
            for pid, d in delta.items():
                if d:
                    add_score(pid, d)
                    add_turn_delta(turn_number, pid, d)

            if with_history:
                round_deltas_by_round_id[round_id] = dict(delta)
                snapshot_turn(turn_number)

        # construire turn_scores_out
        turn_scores_out: List[Dict[str, Any]] = []
        if with_history:
            for t in sorted(turn_cumulatives.keys()):
                turn_scores_out.append(
                    {
                        "turn_number": t,
                        "scores": turn_cumulatives[t],
                        "delta": turn_deltas.get(t, {pid: 0 for pid in all_player_ids}),
                    }
                )

        bonus_metrics = {
            "sniper": inflicted_loss_by_player,
            "victime": suffered_loss_by_player,
            "game_addict": attempted_difficulty_by_player,
        }

        return cumulative_scores, turn_scores_out, joker_impacts_by_usage_id, round_deltas_by_round_id, bonus_metrics

    # ---------------------------------------------------------------------
    # Scoring
    # ---------------------------------------------------------------------

    def _compute_scores(self, game_id: int, players) -> Tuple[Dict[int, int], Optional[Dict[str, Any]]]:
        """
        Wrapper sur le moteur unique _score_timeline.
        Retourne :
        - scores finaux (cumulés)
        - last_round_delta : delta net du dernier round résolu (incluant Gamble au bon moment)
        """
        # players_out minimal requis par _score_timeline
        players_out_min = [{"id": p.id, "theme": {"id": p.theme_id}} for p in players]

        answered_cells = self.grids.list_answered_cells_for_scoring(game_id)
        used_rows = self.jokers_used.list_used_for_game_for_scoring(game_id)
        round_to_player_id, round_to_round_number = self._build_round_indexes(game_id)

        scores, _, _, round_deltas_by_round_id, _ = self._score_timeline(
            game_id=game_id,
            players_out=players_out_min,
            answered_cells=answered_cells,
            used_rows=used_rows,
            round_to_player_id=round_to_player_id,
            round_to_round_number=round_to_round_number,
            with_history=True,  # on veut round_deltas_by_round_id
        )

        last_round_delta = None
        if round_deltas_by_round_id:
            last_round_id = max(
                round_deltas_by_round_id.keys(),
                key=lambda rid: round_to_round_number.get(rid, 0),
            )
            last_round_delta = {
                "round_id": last_round_id,
                "round_number": int(round_to_round_number.get(last_round_id, 1)),
                "delta": round_deltas_by_round_id[last_round_id],
            }

        return scores, last_round_delta
    
    # ---------------------------------------------------------------------
    # Joker usage (process séparé)
    # ---------------------------------------------------------------------

    def use_joker(self, game_url: str, payload: JokerUseIn, *, user_id: int, is_admin: bool) -> Any:
        game = self._get_game_or_404(game_url)
        self._ensure_owner_or_admin(game, user_id=user_id, is_admin=is_admin)

        # JokerInGame doit appartenir à la partie
        jig = self.jokers_in_game.get(payload.joker_in_game_id)
        if not jig or jig.game_id != game.id:
            raise LookupError("JOKER_IN_GAME_NOT_FOUND")

        # Vérifier round appartient à la partie
        round_ctx = self.rounds.get_round_context(payload.round_id)
        if not round_ctx:
            raise LookupError("ROUND_NOT_FOUND")
        if round_ctx.game_id != game.id:
            raise LookupError("ROUND_NOT_IN_GAME")

        player_id = round_ctx.player_id

        used_before = set(
            self.jokers_used.list_used_joker_in_game_ids_for_player_before_round(
                game.id, player_id, payload.round_id
            )
        )
        if payload.joker_in_game_id in used_before:
            raise ConflictError("Joker already used by this player")

        usage = self.jokers_used.create(
            commit=True,
            joker_in_game_id=payload.joker_in_game_id,
            round_id=payload.round_id,
            target_player_id=payload.target_player_id,
            target_grid_id=payload.target_grid_id,
        )

        # Placeholder effets immédiats
        self._apply_joker_effects_after_use_placeholder(game_id=game.id, usage_id=usage.id)
        return usage

    def _apply_joker_effects_after_use_placeholder(self, game_id: int, usage_id: int) -> None:
        # Ici tu implémenteras des jokers qui modifient l'état dès l'usage
        # (ex: révéler question, bloquer une case, etc.)
        return

    # ---------------------------------------------------------------------
    # Answer (process séparé) + auto-next-round
    # ---------------------------------------------------------------------

    def answer_question(
        self,
        game_url: str,
        payload: AnswerCreateIn,
        *,
        user_id: int,
        is_admin: bool,
        auto_next_round: bool = True,
    ) -> Tuple[Any, Optional[Any]]:
        game = self._get_game_or_404(game_url)
        self._ensure_owner_or_admin(game, user_id=user_id, is_admin=is_admin)

        grid = self.grids.get(payload.grid_id)
        if not grid or grid.game_id != game.id:
            raise LookupError("GRID_NOT_FOUND")

        # empêcher double réponse
        if grid.round_id is not None:
            raise ConflictError("GRID_ALREADY_ANSWERED")

        # Vérifier round appartient à la partie + récupérer contexte
        round_ctx = self.rounds.get_round_context(payload.round_id)
        if not round_ctx:
            raise LookupError("ROUND_NOT_FOUND")
        if round_ctx.game_id != game.id:
            raise LookupError("ROUND_NOT_IN_GAME")

        # Validate pawn move if with_pawns mode is enabled
        if game.with_pawns:
            player = self.players.get(round_ctx.player_id)
            if not player:
                raise LookupError("PLAYER_NOT_FOUND")

            all_grid_cells = self.grids.list_by_game(game.id)
            self._validate_pawn_move(game, player, grid.row, grid.column, all_grid_cells)

            # Update pawn position
            self.players.update_pawn_position(player, grid.row, grid.column, commit=False)

            # Update allowed_steps for next turn based on answer result
            if payload.correct_answer and not payload.skip_answer:
                question_points = self.grids.get_question_points(payload.grid_id)
                new_allowed_steps = question_points if question_points and question_points > 0 else 1
            else:
                new_allowed_steps = 1
            self.players.update_allowed_steps(player, new_allowed_steps, commit=False)

        updated = self.grids.update(
            grid,
            commit=True,
            round_id=payload.round_id,
            correct_answer=payload.correct_answer,
            skip_answer=payload.skip_answer,
        )

        next_round = None
        if auto_next_round:
            next_round = self._maybe_create_next_round_after_answer(game_id=game.id, just_played_round_id=payload.round_id)

        return updated, next_round

    def _maybe_create_next_round_after_answer(self, *, game_id: int, just_played_round_id: int) -> Optional[Any]:
        """
        Crée un next round (round_number+1) pour le prochain joueur (ordre circulaire).
        - Dépend de l'ordre des players dans la partie.
        - Empêche création si déjà existant.
        """
        ctx = self.rounds.get_round_context(just_played_round_id)
        if not ctx or ctx.game_id != game_id:
            return None

        current_round_number = ctx.round_number
        current_player_order = ctx.player_order

        # joueur suivant (ordre circulaire)
        next_player = self.players.get_next_player_in_game(game_id, current_player_order)
        if not next_player:
            return None

        next_round_number = current_round_number + 1

        # éviter doublon (player_id, round_number)
        if self.rounds.exists_for_player_round_number(next_player.id, next_round_number):
            return None

        created = self.rounds.create(
            commit=True,
            player_id=next_player.id,
            round_number=next_round_number,
        )
        return created
    
    # ---------------------------------------------------------------------
    # Public: colors
    # ---------------------------------------------------------------------
    def list_public_colors(self, *, offset: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
        rows = self.colors.list_public(offset=offset, limit=limit)
        return [{"id": r[0], "name": r[1], "hex_code": r[2]} for r in rows]
    
    # ---------------------------------------------------------------------
    # Suggestion de setup
    # ---------------------------------------------------------------------
    def suggest_setup(self, payload: GameSetupSuggestIn) -> GameSetupSuggestOut:
        theme_ids = [p.theme_id for p in payload.players]

        counts = Counter(theme_ids)
        duplicates = [tid for tid, c in counts.items() if c > 1]
        if duplicates:
            # tu peux aussi inclure duplicates dans le detail si tu veux
            raise ConflictError("DUPLICATE_PLAYER_THEMES_NOT_ALLOWED")

        # 1) compter questions dispo par thème joueur
        counts = [self.questions.count_by_theme(tid) for tid in theme_ids]

        # cas extrêmes
        if not counts:
            raise ConflictError("NO_PLAYERS")

        min_available = min(counts)
        if min_available <= 0:
            # pas jouable : au moins un thème n'a aucune question
            raise ConflictError("THEME_HAS_NO_QUESTIONS")

        # 2) conseillé = min_available capé à 10
        n_by_player = min(min_available, 10)

        # 3) taille de grille minimale
        needed_cells = len(theme_ids) * n_by_player

        # 4) choisir la plus petite grille autorisée qui fit
        chosen: Tuple[int, int] | None = None
        for (r, c) in settings.ALLOWED_GRIDS:
            if r * c >= needed_cells:
                chosen = (r, c)
                break

        if chosen is None:
            raise ConflictError("NO_ALLOWED_GRID_CAN_FIT_REQUEST")

        rows, cols = chosen

        return GameSetupSuggestOut(
            number_of_questions_by_player=n_by_player,
            rows_number=rows,
            columns_number=cols,
            general_theme_ids=settings.GENERAL_THEME_IDS,
            joker_ids=settings.DEFAULT_JOKER_IDS,
            bonus_ids=settings.DEFAULT_BONUS_IDS,
        )
    
    # ---------------------------------------------------------------------
    # Fin de partie
    # ---------------------------------------------------------------------
    def get_game_results(self, game_url: str, *, user_id: int, is_admin: bool) -> Dict[str, Any]:
        game = self._get_game_or_404(game_url)
        self._ensure_owner_or_admin(game, user_id=user_id, is_admin=is_admin)

        # ✅ Infos globales via list_user_games_with_players (couleurs/thèmes inclus)
        games_for_owner = self.list_user_games_with_players(owner_id=game.owner_id)
        game_with_players = next((g for g in games_for_owner if g["id"] == game.id), None)
        if not game_with_players:
            raise LookupError("GAME_NOT_FOUND")

        players_out = [
            {
                "id": p["id"],
                "name": p["name"],
                "order": p["order"],
                "theme": p["theme"],
                "color": p["color"],
            }
            for p in game_with_players.get("players", [])
        ]

        nb_players = len(players_out)
        if nb_players <= 0:
            raise ConflictError("GAME_HAS_NO_PLAYERS")

        all_player_ids = [p["id"] for p in players_out]
        zeros_by_player = {pid: 0 for pid in all_player_ids}

        # -----------------------------
        # Data existante (réutilisation)
        # -----------------------------
        answered_cells = self.grids.list_answered_cells_for_scoring(game.id)
        used_rows = self.jokers_used.list_used_for_game_for_scoring(game.id)
        round_to_player_id, round_to_round_number = self._build_round_indexes(game.id)

        # ✅ Moteur unique : scores finaux + scores par tour + deltas jokers + métriques bonus
        final_scores, turn_scores_out, joker_impacts_by_usage_id, _, bonus_metrics = self._score_timeline(
            game_id=game.id,
            players_out=players_out,
            answered_cells=answered_cells,
            used_rows=used_rows,
            round_to_player_id=round_to_player_id,
            round_to_round_number=round_to_round_number,
            with_history=True,
            with_bonus_metrics=True,
        )

        # -----------------------------
        # jokers_impacts list (ordonnée)
        # -----------------------------
        used_rows_sorted = sorted(
            used_rows,
            key=lambda u: (round_to_round_number.get(u.round_id, 10**9), u.usage_id),
        )

        jokers_impacts_out = []
        for u in used_rows_sorted:
            round_number = round_to_round_number.get(u.round_id, 1)
            turn_number = ((round_number - 1) // nb_players) + 1

            jokers_impacts_out.append(
                {
                    "usage_id": u.usage_id,
                    "turn_number": turn_number,
                    "round_id": u.round_id,
                    "round_number": round_number,
                    "using_player_id": u.using_player_id,
                    "joker_in_game_id": u.joker_in_game_id,
                    "joker_id": u.joker_id,
                    "joker_name": u.joker_name,
                    "target_player_id": u.target_player_id,
                    "target_grid_id": u.target_grid_id,
                    "points_delta_by_player": joker_impacts_by_usage_id.get(u.usage_id, dict(zeros_by_player)),
                }
            )

        # -----------------------------
        # bonus attachés (effets fin de partie)
        # -----------------------------
        BONUS_RANK_POINTS = {1: 5, 2: 3, 3: 1}

        def bonus_key_from_name(name: str) -> Optional[str]:
            n = (name or "").strip().lower()
            if n == "sniper":
                return "sniper"
            if n == "victime":
                return "victime"
            if n == "game addict":
                return "game_addict"
            return None

        def _rank_points_from_metric(metric: Dict[int, int]) -> Tuple[List[Dict[str, Any]], Dict[int, int]]:
            """
            Classement "competition ranking":
            ex: [10,10,7,7,2] => ranks [1,1,3,3,5]
            Points : 1er=5, 2e=3, 3e=1
            """
            items = sorted(metric.items(), key=lambda kv: (-kv[1], kv[0]))

            ranking: List[Dict[str, Any]] = []
            points_delta = {pid: 0 for pid in metric.keys()}

            prev_value = None
            rank = 0
            index = 0
            for pid, value in items:
                index += 1
                if prev_value is None or value != prev_value:
                    rank = index
                    prev_value = value

                ranking.append({"rank": rank, "player_id": pid, "value": value})

                pts = BONUS_RANK_POINTS.get(rank, 0)
                if pts:
                    points_delta[pid] += pts

            return ranking, points_delta

        bonus_rows = self.bonus_in_game.list_for_game(game.id)
        bonus_out: List[Dict[str, Any]] = []

        bonus_total_delta = {pid: 0 for pid in all_player_ids}

        for r in bonus_rows:
            key = bonus_key_from_name(getattr(r, "name", None))
            metric = bonus_metrics.get(key, None) if key else None

            effect = None
            points_delta_by_player = dict(zeros_by_player)

            if key and metric is not None:
                metric_full = {pid: int(metric.get(pid, 0)) for pid in all_player_ids}
                ranking, points_delta_by_player = _rank_points_from_metric(metric_full)

                effect = {
                    "key": key,
                    # ✅ métriques brutes (ex: victime => points perdus)
                    "metric_by_player": metric_full,
                    # ✅ classement exploitable front
                    "ranking": ranking,
                    # ✅ points bonus (5/3/1)
                    "points_delta_by_player": dict(points_delta_by_player),
                }

                for pid, d in points_delta_by_player.items():
                    bonus_total_delta[pid] += d

            bonus_out.append(
                {
                    "bonus_in_game_id": r.bonus_in_game_id,
                    "bonus": {"id": r.bonus_id, "name": r.name, "description": r.description},
                    "effect": effect,
                    "points_delta_by_player": dict(points_delta_by_player),
                }
            )

        scores_with_bonus = {
            pid: int(final_scores.get(pid, 0)) + int(bonus_total_delta.get(pid, 0))
            for pid in all_player_ids
        }

        return {
            "game": {
                "id": game.id,
                "url": game.url,
                "seed": game.seed,
                "rows_number": game.rows_number,
                "columns_number": game.columns_number,
                "finished": game.finished,
                "with_pawns": game.with_pawns,
                "owner_id": game.owner_id,
            },
            "players": players_out,
            "scores": final_scores,  # score final (avant bonus)
            "scores_with_bonus": scores_with_bonus,  # ✅ score final (avec bonus)
            "turn_scores": turn_scores_out,
            "jokers_impacts": jokers_impacts_out,
            "bonus": bonus_out,
        }