"""Leaderboards. Every score is a ScoreEvent row; this module only adds them
up and ranks them.

Per game: teams ranked by the sum of their points in that game.
Final: placement points per game (config.scoring.placement_points: 1st gets
the first value, 2nd the second, ..., every lower place the last value),
summed across games; raw points break ties. Ties use competition ranking (1, 1, 3): tied teams share a placement
and the same placement points.
"""

import json

from extensions import db
from models import GameFinish, ScoreEvent

GAME_SLUGS = ("noise", "voices", "drawing", "runner")


class GameFinishedError(Exception):
    """Points for a game that was finished in this match: it must be reopened
    first (app.py turns this into a 409 / flash message)."""

    def __init__(self, game):
        super().__init__(f"Game {game!r} is finished in this match")
        self.game = game


def finished_games(match):
    """Slugs of the games finished in this match."""
    rows = db.session.query(GameFinish.game).filter(GameFinish.match_id == match.id).all()
    return {game for (game,) in rows}


def ensure_open(match, game):
    """Raise GameFinishedError if the game is finished in this match. Routes
    that change game state before scoring call it first, so a locked game
    never ends up half-updated."""
    if game in finished_games(match):
        raise GameFinishedError(game)


def finish_game(match, game, user):
    if game not in GAME_SLUGS:
        raise ValueError(f"Unknown game {game!r}")
    if game not in finished_games(match):
        db.session.add(GameFinish(match_id=match.id, game=game, finished_by_id=user.id))
        db.session.commit()


def reopen_game(match, game):
    GameFinish.query.filter_by(match_id=match.id, game=game).delete()
    db.session.commit()


def clean_points(value):
    """Whole numbers as int (5, not 5.0), others rounded to 2 decimals -
    float sums like 2.5 + 2.5 + 0.1 must not show up as 5.1000000001."""
    value = round(float(value), 2)
    return int(value) if value.is_integer() else value


def add_score(match, team, game, points, user, detail=None, ref=None):
    """Record points. With `ref`, any previous event with the same ref for
    this team is replaced (e.g. re-confirming the same drawing)."""
    if game not in GAME_SLUGS:
        raise ValueError(f"Unknown game {game!r}")
    ensure_open(match, game)
    if ref is not None:
        ScoreEvent.query.filter_by(match_id=match.id, team_id=team.id, ref=ref).delete()
    event = ScoreEvent(
        match_id=match.id,
        team_id=team.id,
        game=game,
        points=clean_points(points),
        ref=ref,
        detail_json=json.dumps(detail or {}),
        created_by_id=user.id,
    )
    db.session.add(event)
    db.session.commit()
    return event


def _rank(rows, key):
    """Competition ranking: rows sorted by key desc, ties share the rank."""
    rows = sorted(rows, key=key, reverse=True)
    ranked = []
    for index, row in enumerate(rows):
        if index > 0 and key(row) == key(rows[index - 1]):
            rank = ranked[-1]["rank"]
        else:
            rank = index + 1
        ranked.append({**row, "rank": rank})
    return ranked


def game_points(match):
    """{game: {team_id: points}} for every game and team (zeros included)."""
    totals = {game: {team.id: 0 for team in match.teams} for game in GAME_SLUGS}
    sums = (
        db.session.query(ScoreEvent.game, ScoreEvent.team_id, db.func.sum(ScoreEvent.points))
        .filter(ScoreEvent.match_id == match.id)
        .group_by(ScoreEvent.game, ScoreEvent.team_id)
        .all()
    )
    for game, team_id, points in sums:
        totals[game][team_id] = clean_points(points)
    return totals


def games_played(match):
    """Games that have at least one score event in this match."""
    rows = db.session.query(ScoreEvent.game).filter(ScoreEvent.match_id == match.id).distinct().all()
    return {game for (game,) in rows}


def standings(match, placement_points):
    """Everything the results pages need, in one structure.

    Games nobody has played yet are left out of the final ranking, so a
    match in progress doesn't hand out placement points for 0-0-0-0 ties.
    """
    totals = game_points(match)
    played = games_played(match)
    teams_by_id = {team.id: team for team in match.teams}

    per_game = {}
    for game in GAME_SLUGS:
        rows = [{"team": teams_by_id[tid], "points": pts} for tid, pts in totals[game].items()]
        ranked = _rank(rows, key=lambda r: r["points"])
        for row in ranked:
            row["placement_points"] = _placement_value(row["rank"], placement_points) if game in played else 0
        per_game[game] = ranked

    final_rows = []
    for team in match.teams:
        placement_total = sum(
            next(r["placement_points"] for r in per_game[game] if r["team"].id == team.id) for game in GAME_SLUGS
        )
        raw_total = clean_points(sum(totals[game][team.id] for game in GAME_SLUGS))
        final_rows.append({
            "team": team,
            "placement_total": placement_total,
            "raw_total": raw_total,
            "ranks": {game: next(r["rank"] for r in per_game[game] if r["team"].id == team.id) for game in GAME_SLUGS},
            "points": {game: totals[game][team.id] for game in GAME_SLUGS},
        })
    final = _rank(final_rows, key=lambda r: (r["placement_total"], r["raw_total"]))
    return {"per_game": per_game, "final": final, "played": played}


def _placement_value(rank, placement_points):
    return placement_points[min(rank, len(placement_points)) - 1]


def standings_json(match, placement_points):
    """JSON-safe version of standings() for the live projector view."""
    data = standings(match, placement_points)

    def team_dict(team):
        return {"id": team.id, "name": team.name, "color": team.color}

    return {
        "played": sorted(data["played"]),
        "finished": sorted(finished_games(match)),
        "per_game": {
            game: [
                {"team": team_dict(r["team"]), "points": r["points"], "rank": r["rank"],
                 "placement_points": r["placement_points"]}
                for r in rows
            ]
            for game, rows in data["per_game"].items()
        },
        "final": [
            {"team": team_dict(r["team"]), "rank": r["rank"], "placement_total": r["placement_total"],
             "raw_total": r["raw_total"], "ranks": r["ranks"], "points": r["points"]}
            for r in data["final"]
        ],
    }
