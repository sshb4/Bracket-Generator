import json
import os
import random
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "app.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
PASSWORD_HASH_METHOD = "pbkdf2:sha256"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brackets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            size INTEGER NOT NULL,
            teams_json TEXT NOT NULL,
            seeding_mode TEXT NOT NULL,
            bye_teams_json TEXT NOT NULL,
            rounds_json TEXT NOT NULL,
            share_code TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        );
        """
    )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def next_power_of_two(n):
    size = 1
    while size < n:
        size *= 2
    return size


def normalized_teams_from_text(raw_text):
    lines = [line.strip() for line in raw_text.splitlines()]
    teams = [line for line in lines if line]
    return teams


def build_first_round(teams, bracket_size, bye_teams, seeding_mode):
    seeded_teams = teams[:]
    if seeding_mode == "random":
        random.shuffle(seeded_teams)

    byes_in_seed_order = [team for team in seeded_teams if team in bye_teams]
    non_byes_in_seed_order = [team for team in seeded_teams if team not in bye_teams]

    # Seed numbers are 1..N. Lower seed numbers are higher seeds.
    seed_to_team = {seed: None for seed in range(1, bracket_size + 1)}
    forced_empty_seeds = set()

    for idx, team in enumerate(byes_in_seed_order):
        seed = idx + 1
        seed_to_team[seed] = team
        forced_empty_seeds.add(bracket_size + 1 - seed)

    fill_seeds = [
        seed
        for seed in range(1, bracket_size + 1)
        if seed_to_team[seed] is None and seed not in forced_empty_seeds
    ]

    for team, seed in zip(non_byes_in_seed_order, fill_seeds):
        seed_to_team[seed] = team

    def seeded_bracket_order(size):
        order = [1, 2]
        while len(order) < size:
            complement_base = len(order) * 2 + 1
            order = [
                item
                for pair in zip(order, [complement_base - seed for seed in order])
                for item in pair
            ]
        return order

    seed_order = seeded_bracket_order(bracket_size)
    matches = []

    for i in range(0, len(seed_order), 2):
        team1 = seed_to_team[seed_order[i]] or "BYE"
        team2 = seed_to_team[seed_order[i + 1]] or "BYE"

        if team1 != "BYE" and team2 == "BYE":
            winner = team1
        elif team2 != "BYE" and team1 == "BYE":
            winner = team2
        else:
            winner = None

        matches.append({"team1": team1, "team2": team2, "winner": winner})

    return matches


def build_rounds(first_round):
    rounds = [first_round]
    current_round = first_round

    while len(current_round) > 1:
        next_round = []
        for i in range(0, len(current_round), 2):
            left_winner = current_round[i].get("winner")
            right_winner = current_round[i + 1].get("winner")
            next_round.append(
                {
                    "team1": left_winner,
                    "team2": right_winner,
                    "winner": None,
                }
            )
        rounds.append(next_round)
        current_round = next_round

    return rounds


def recompute_downstream(rounds, changed_round_index):
    for round_index in range(max(1, changed_round_index + 1), len(rounds)):
        current_round = rounds[round_index]
        previous_round = rounds[round_index - 1]

        for match_index, match in enumerate(current_round):
            left_parent = previous_round[match_index * 2]
            right_parent = previous_round[match_index * 2 + 1]

            left_winner = left_parent.get("winner")
            right_winner = right_parent.get("winner")

            match["team1"] = left_winner
            match["team2"] = right_winner

            if match.get("winner") not in {left_winner, right_winner}:
                match["winner"] = None


def parse_rounds(row):
    rounds = json.loads(row["rounds_json"])
    return rounds


def serialize_datetime_now():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@app.before_request
def ensure_db_initialized():
    init_db()


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.")
            return render_template("register.html")

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (
                    username,
                    generate_password_hash(password, method=PASSWORD_HASH_METHOD),
                    serialize_datetime_now(),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("That username is already taken.")
            return render_template("register.html")

        flash("Account created. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    rows = db.execute(
        """
        SELECT b.*, u.username AS owner_name
        FROM brackets b
        JOIN users u ON b.owner_id = u.id
        WHERE b.owner_id = ?
        ORDER BY b.updated_at DESC
        """,
        (session["user_id"],),
    ).fetchall()

    bracket_cards = []
    for row in rows:
        rounds = json.loads(row["rounds_json"])
        champion = rounds[-1][0].get("winner") if rounds and rounds[-1] else None
        bracket_cards.append(
            {
                "id": row["id"],
                "name": row["name"],
                "size": row["size"],
                "team_count": len(json.loads(row["teams_json"])),
                "updated_at": row["updated_at"],
                "champion": champion,
                "share_code": row["share_code"],
            }
        )

    return render_template("dashboard.html", cards=bracket_cards, user=current_user())


@app.route("/brackets/new")
@login_required
def new_bracket():
    return render_template("new_bracket.html", user=current_user())


@app.route("/brackets/create", methods=["POST"])
@login_required
def create_bracket():
    name = request.form.get("name", "Untitled Bracket").strip() or "Untitled Bracket"
    teams_text = request.form.get("teams", "")
    seeding_mode = request.form.get("seeding_mode", "order")
    bye_teams = request.form.getlist("bye_teams")

    teams = normalized_teams_from_text(teams_text)
    if len(teams) < 2:
        flash("Please enter at least two teams (one per line).")
        return redirect(url_for("new_bracket"))

    bracket_size = next_power_of_two(len(teams))
    required_byes = bracket_size - len(teams)

    if required_byes > 0:
        unique_selected = []
        for team in bye_teams:
            if team in teams and team not in unique_selected:
                unique_selected.append(team)

        if len(unique_selected) != required_byes:
            flash(f"Please select exactly {required_byes} BYE team(s).")
            return redirect(url_for("new_bracket"))
        bye_teams = unique_selected
    else:
        bye_teams = []

    first_round = build_first_round(teams, bracket_size, bye_teams, seeding_mode)
    rounds = build_rounds(first_round)

    db = get_db()
    now = serialize_datetime_now()
    share_code = uuid.uuid4().hex[:10]

    db.execute(
        """
        INSERT INTO brackets (
            owner_id, name, size, teams_json, seeding_mode, bye_teams_json,
            rounds_json, share_code, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            name,
            bracket_size,
            json.dumps(teams),
            seeding_mode,
            json.dumps(bye_teams),
            json.dumps(rounds),
            share_code,
            now,
            now,
        ),
    )
    db.commit()

    bracket_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return redirect(url_for("view_bracket", bracket_id=bracket_id))


def get_bracket_or_404(bracket_id):
    db = get_db()
    row = db.execute(
        "SELECT b.*, u.username AS owner_name FROM brackets b JOIN users u ON b.owner_id = u.id WHERE b.id = ?",
        (bracket_id,),
    ).fetchone()
    if row is None:
        return None
    return row


@app.route("/brackets/<int:bracket_id>")
@login_required
def view_bracket(bracket_id):
    row = get_bracket_or_404(bracket_id)
    if row is None:
        flash("Bracket not found.")
        return redirect(url_for("dashboard"))

    if row["owner_id"] != session["user_id"]:
        flash("You do not have access to that bracket.")
        return redirect(url_for("dashboard"))

    rounds = parse_rounds(row)
    return render_template(
        "view_bracket.html",
        bracket=row,
        rounds=rounds,
        teams=json.loads(row["teams_json"]),
        bye_teams=json.loads(row["bye_teams_json"]),
        user=current_user(),
    )


@app.route("/api/brackets/<int:bracket_id>/winner", methods=["POST"])
@login_required
def set_winner(bracket_id):
    row = get_bracket_or_404(bracket_id)
    if row is None:
        return jsonify({"error": "Bracket not found."}), 404

    if row["owner_id"] != session["user_id"]:
        return jsonify({"error": "No access."}), 403

    payload = request.get_json(silent=True) or {}
    round_index = int(payload.get("round_index", -1))
    match_index = int(payload.get("match_index", -1))
    winner = payload.get("winner")
    if winner == "":
        winner = None

    rounds = parse_rounds(row)

    if round_index < 0 or round_index >= len(rounds):
        return jsonify({"error": "Invalid round."}), 400
    if match_index < 0 or match_index >= len(rounds[round_index]):
        return jsonify({"error": "Invalid match."}), 400

    match = rounds[round_index][match_index]
    allowed = {match.get("team1"), match.get("team2")}
    allowed.discard(None)

    if winner is not None and winner not in allowed:
        return jsonify({"error": "Winner must be one of the two teams."}), 400

    match["winner"] = winner
    recompute_downstream(rounds, round_index)

    db = get_db()
    db.execute(
        "UPDATE brackets SET rounds_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(rounds), serialize_datetime_now(), bracket_id),
    )
    db.commit()

    champion = rounds[-1][0].get("winner") if rounds and rounds[-1] else None
    return jsonify({"ok": True, "rounds": rounds, "champion": champion})


@app.route("/api/brackets/<int:bracket_id>/share", methods=["POST"])
@login_required
def get_share_link(bracket_id):
    row = get_bracket_or_404(bracket_id)
    if row is None:
        return jsonify({"error": "Bracket not found."}), 404
    if row["owner_id"] != session["user_id"]:
        return jsonify({"error": "No access."}), 403

    share_url = url_for("add_shared_bracket", share_code=row["share_code"], _external=True)
    return jsonify({"share_code": row["share_code"], "share_url": share_url})


@app.route("/api/brackets/<int:bracket_id>/reset", methods=["POST"])
@login_required
def reset_bracket(bracket_id):
    row = get_bracket_or_404(bracket_id)
    if row is None:
        return jsonify({"error": "Bracket not found."}), 404
    if row["owner_id"] != session["user_id"]:
        return jsonify({"error": "No access."}), 403

    rounds = parse_rounds(row)
    if not rounds:
        return jsonify({"error": "Bracket has no rounds."}), 400

    first_round = rounds[0]
    for match in first_round:
        team1 = match.get("team1")
        team2 = match.get("team2")
        if team1 != "BYE" and team2 == "BYE":
            match["winner"] = team1
        elif team2 != "BYE" and team1 == "BYE":
            match["winner"] = team2
        else:
            match["winner"] = None

    for round_index in range(1, len(rounds)):
        for match in rounds[round_index]:
            match["winner"] = None

    recompute_downstream(rounds, 0)

    db = get_db()
    db.execute(
        "UPDATE brackets SET rounds_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(rounds), serialize_datetime_now(), bracket_id),
    )
    db.commit()

    return jsonify({"ok": True, "rounds": rounds, "champion": None})


@app.route("/share/<share_code>/add", methods=["GET", "POST"])
@login_required
def add_shared_bracket(share_code):
    db = get_db()
    original = db.execute("SELECT * FROM brackets WHERE share_code = ?", (share_code,)).fetchone()
    if original is None:
        flash("Invalid share link.")
        return redirect(url_for("dashboard"))

    if original["owner_id"] == session["user_id"]:
        flash("That bracket is already yours.")
        return redirect(url_for("view_bracket", bracket_id=original["id"]))

    existing_name = f"Copy of {original['name']}"
    now = serialize_datetime_now()

    db.execute(
        """
        INSERT INTO brackets (
            owner_id, name, size, teams_json, seeding_mode, bye_teams_json,
            rounds_json, share_code, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            existing_name,
            original["size"],
            original["teams_json"],
            original["seeding_mode"],
            original["bye_teams_json"],
            original["rounds_json"],
            uuid.uuid4().hex[:10],
            now,
            now,
        ),
    )
    db.commit()

    new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    flash("Bracket added to your account.")
    return redirect(url_for("view_bracket", bracket_id=new_id))


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
