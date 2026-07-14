import json
import os
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import resend
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def get_database_path():
    if os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV"):
        return os.path.join("/tmp", "app.db")
    return os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "app.db"))


DATABASE = get_database_path()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
PASSWORD_HASH_METHOD = "pbkdf2:sha256"
SHARE_CODE_LENGTH = 4


@app.after_request
def set_cache_headers(response):
    if not request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.context_processor
def inject_asset_url():
    def asset_url(filename):
        file_path = os.path.join(BASE_DIR, "static", filename)
        try:
            version = int(os.path.getmtime(file_path))
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    return {"asset_url": asset_url}


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


def utc_now():
    return datetime.now(timezone.utc)


def serialize_datetime_now():
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso_datetime(value):
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def ensure_column(db, table_name, column_name, definition_sql):
    columns = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    if column_name in {row["name"] for row in columns}:
        return
    db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}")


def generate_share_code(db):
    max_codes = 10**SHARE_CODE_LENGTH

    for _ in range(300):
        code = f"{random.randint(0, max_codes - 1):0{SHARE_CODE_LENGTH}d}"
        exists = db.execute("SELECT 1 FROM brackets WHERE share_code = ?", (code,)).fetchone()
        if not exists:
            return code

    # Deterministic fallback when random attempts collide.
    for value in range(max_codes):
        code = f"{value:0{SHARE_CODE_LENGTH}d}"
        exists = db.execute("SELECT 1 FROM brackets WHERE share_code = ?", (code,)).fetchone()
        if not exists:
            return code

    raise RuntimeError("All 4-digit share codes are currently in use.")


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

        CREATE TABLE IF NOT EXISTS bracket_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bracket_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'voter',
            created_at TEXT NOT NULL,
            UNIQUE(bracket_id, user_id),
            FOREIGN KEY(bracket_id) REFERENCES brackets(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS bracket_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bracket_id INTEGER NOT NULL,
            invited_by INTEGER NOT NULL,
            email TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            accepted_at TEXT,
            FOREIGN KEY(bracket_id) REFERENCES brackets(id),
            FOREIGN KEY(invited_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS match_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bracket_id INTEGER NOT NULL,
            round_index INTEGER NOT NULL,
            match_index INTEGER NOT NULL,
            voter_user_id INTEGER NOT NULL,
            voted_team TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(bracket_id, round_index, match_index, voter_user_id),
            FOREIGN KEY(bracket_id) REFERENCES brackets(id),
            FOREIGN KEY(voter_user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS account_recovery_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )

    ensure_column(db, "users", "email", "TEXT")
    ensure_column(db, "brackets", "base_rounds_json", "TEXT")

    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users(email)")
    db.execute(
        """
        UPDATE brackets
        SET base_rounds_json = rounds_json
        WHERE base_rounds_json IS NULL OR base_rounds_json = ''
        """
    )

    rows = db.execute("SELECT id, share_code FROM brackets").fetchall()
    for row in rows:
        share_code = (row["share_code"] or "").strip()
        if len(share_code) == SHARE_CODE_LENGTH and share_code.isdigit():
            continue
        db.execute(
            "UPDATE brackets SET share_code = ? WHERE id = ?",
            (generate_share_code(db), row["id"]),
        )

    db.commit()


@app.before_request
def ensure_db_initialized():
    init_db()


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
    return [line for line in lines if line]


def build_first_round(teams, bracket_size, bye_teams, seeding_mode):
    seeded_teams = teams[:]
    if seeding_mode == "random":
        random.shuffle(seeded_teams)

    byes_in_seed_order = [team for team in seeded_teams if team in bye_teams]
    non_byes_in_seed_order = [team for team in seeded_teams if team not in bye_teams]

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

    for idx in range(0, len(seed_order), 2):
        team1 = seed_to_team[seed_order[idx]] or "BYE"
        team2 = seed_to_team[seed_order[idx + 1]] or "BYE"

        winner = None
        if team1 != "BYE" and team2 == "BYE":
            winner = team1
        elif team2 != "BYE" and team1 == "BYE":
            winner = team2

        matches.append({"team1": team1, "team2": team2, "winner": winner})

    return matches


def build_rounds(first_round):
    rounds = [first_round]
    current_round = first_round

    while len(current_round) > 1:
        next_round = []
        for idx in range(0, len(current_round), 2):
            left_winner = current_round[idx].get("winner")
            right_winner = current_round[idx + 1].get("winner")
            next_round.append({"team1": left_winner, "team2": right_winner, "winner": None})
        rounds.append(next_round)
        current_round = next_round

    return rounds


def get_bracket(bracket_id):
    db = get_db()
    return db.execute(
        """
        SELECT b.*, u.username AS owner_name
        FROM brackets b
        JOIN users u ON b.owner_id = u.id
        WHERE b.id = ?
        """,
        (bracket_id,),
    ).fetchone()


def user_can_access_bracket(bracket_row, user_id):
    if not bracket_row:
        return False
    if bracket_row["owner_id"] == user_id:
        return True

    db = get_db()
    member = db.execute(
        "SELECT 1 FROM bracket_members WHERE bracket_id = ? AND user_id = ?",
        (bracket_row["id"], user_id),
    ).fetchone()
    return member is not None


def get_bracket_or_accessible(bracket_id):
    row = get_bracket(bracket_id)
    if row is None:
        return None, False
    has_access = user_can_access_bracket(row, session.get("user_id"))
    return row, has_access


def parse_rounds_json(rounds_json):
    return json.loads(rounds_json)


def parse_rounds(row):
    return parse_rounds_json(row["rounds_json"])


def get_vote_counts_by_match(bracket_id):
    db = get_db()
    rows = db.execute(
        """
        SELECT round_index, match_index, voted_team, COUNT(*) AS vote_count
        FROM match_votes
        WHERE bracket_id = ?
        GROUP BY round_index, match_index, voted_team
        """,
        (bracket_id,),
    ).fetchall()

    vote_map = {}
    for row in rows:
        key = f"{row['round_index']}:{row['match_index']}"
        match_votes = vote_map.setdefault(key, {})
        match_votes[row["voted_team"]] = row["vote_count"]
    return vote_map


def compute_match_winner(team1, team2, vote_counts):
    if team1 and team2:
        if team1 == "BYE" and team2 != "BYE":
            return team2
        if team2 == "BYE" and team1 != "BYE":
            return team1
        if team1 == "BYE" and team2 == "BYE":
            return None

    if not team1 or not team2:
        return None

    team1_votes = vote_counts.get(team1, 0)
    team2_votes = vote_counts.get(team2, 0)

    if team1_votes == team2_votes:
        return None
    return team1 if team1_votes > team2_votes else team2


def apply_votes_to_rounds(rounds, vote_map):
    if not rounds:
        return rounds

    for round_index in range(len(rounds)):
        if round_index > 0:
            previous_round = rounds[round_index - 1]
            for match_index, match in enumerate(rounds[round_index]):
                left_winner = previous_round[match_index * 2].get("winner")
                right_winner = previous_round[match_index * 2 + 1].get("winner")
                match["team1"] = left_winner
                match["team2"] = right_winner

        for match_index, match in enumerate(rounds[round_index]):
            key = f"{round_index}:{match_index}"
            vote_counts = vote_map.get(key, {})
            match["winner"] = compute_match_winner(match.get("team1"), match.get("team2"), vote_counts)

    return rounds


def save_recomputed_bracket_state(bracket_row):
    db = get_db()
    rounds = parse_rounds(bracket_row)
    vote_map = get_vote_counts_by_match(bracket_row["id"])
    rounds = apply_votes_to_rounds(rounds, vote_map)

    db.execute(
        "UPDATE brackets SET rounds_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(rounds), serialize_datetime_now(), bracket_row["id"]),
    )
    db.commit()
    return rounds, vote_map


def get_user_votes(bracket_id, user_id):
    if not user_id:
        return {}
    db = get_db()
    rows = db.execute(
        """
        SELECT round_index, match_index, voted_team
        FROM match_votes
        WHERE bracket_id = ? AND voter_user_id = ?
        """,
        (bracket_id, user_id),
    ).fetchall()

    return {f"{row['round_index']}:{row['match_index']}": row["voted_team"] for row in rows}


def summarize_votes_for_rounds(rounds, vote_map, user_votes):
    standings = {}
    for round_index, round_matches in enumerate(rounds):
        for match_index, match in enumerate(round_matches):
            key = f"{round_index}:{match_index}"
            counts = vote_map.get(key, {})
            team1 = match.get("team1")
            team2 = match.get("team2")
            standings[key] = {
                "team1": team1,
                "team2": team2,
                "team1_votes": counts.get(team1, 0) if team1 else 0,
                "team2_votes": counts.get(team2, 0) if team2 else 0,
                "my_vote": user_votes.get(key),
            }
    return standings


def add_member_if_possible(bracket_id, user_id):
    db = get_db()
    db.execute(
        """
        INSERT OR IGNORE INTO bracket_members (bracket_id, user_id, role, created_at)
        VALUES (?, ?, 'voter', ?)
        """,
        (bracket_id, user_id, serialize_datetime_now()),
    )


def send_email(to_email, subject, html_body, text_body):
    resend_api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev").strip()

    if not resend_api_key:
        print("Email skipped: set RESEND_API_KEY to enable delivery.")
        print(f"To: {to_email}\nSubject: {subject}\n{text_body}")
        return False

    resend.api_key = resend_api_key

    try:
        resend.Emails.send(
            {
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
                "text": text_body,
            }
        )
        return True
    except Exception as err:
        print(f"Resend error: {err}")
    return False


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Username, email, and password are required.")
            return render_template("register.html")

        db = get_db()
        try:
            db.execute(
                """
                INSERT INTO users (username, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    generate_password_hash(password, method=PASSWORD_HASH_METHOD),
                    serialize_datetime_now(),
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Username or email is already in use.")
            return render_template("register.html")

        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        session.clear()
        session["user_id"] = user["id"]
        flash("Account created and signed in.")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identity = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? OR lower(email) = lower(?)",
            (identity, identity),
        ).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid credentials.")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Email is required.")
            return render_template("forgot_password.html")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()
        if user:
            token = uuid.uuid4().hex
            expires_at = (utc_now() + timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z")

            db.execute(
                """
                INSERT INTO account_recovery_tokens (user_id, token, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user["id"], token, expires_at, serialize_datetime_now()),
            )
            db.commit()

            reset_url = url_for("recover_password", token=token, _external=True)
            send_email(
                to_email=user["email"],
                subject="Reset your Bates Brackets password",
                html_body=f"<p>Use this link to reset your password:</p><p><a href='{reset_url}'>{reset_url}</a></p>",
                text_body=f"Reset your password with this link: {reset_url}",
            )

        flash("If that email exists, a reset link has been sent.")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/recover/<token>", methods=["GET", "POST"])
def recover_password(token):
    db = get_db()
    row = db.execute(
        """
        SELECT t.*, u.email
        FROM account_recovery_tokens t
        JOIN users u ON t.user_id = u.id
        WHERE t.token = ?
        """,
        (token,),
    ).fetchone()

    if row is None:
        flash("Invalid recovery link.")
        return redirect(url_for("login"))

    if row["used_at"]:
        flash("That recovery link was already used.")
        return redirect(url_for("login"))

    expires_at = parse_iso_datetime(row["expires_at"])
    if expires_at and expires_at < utc_now():
        flash("That recovery link has expired.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if not password:
            flash("Password is required.")
            return render_template("recover_password.html", token=token, email=row["email"])

        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password, method=PASSWORD_HASH_METHOD), row["user_id"]),
        )
        db.execute("UPDATE account_recovery_tokens SET used_at = ? WHERE id = ?", (serialize_datetime_now(), row["id"]))
        db.commit()
        flash("Password updated. Please log in.")
        return redirect(url_for("login"))

    return render_template("recover_password.html", token=token, email=row["email"])


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
        SELECT DISTINCT b.*, u.username AS owner_name,
               CASE WHEN b.owner_id = ? THEN 'owner' ELSE 'collaborator' END AS access_role
        FROM brackets b
        JOIN users u ON b.owner_id = u.id
        LEFT JOIN bracket_members bm ON b.id = bm.bracket_id
        WHERE b.owner_id = ? OR bm.user_id = ?
        ORDER BY b.updated_at DESC
        """,
        (session["user_id"], session["user_id"], session["user_id"]),
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
                "access_role": row["access_role"],
            }
        )

    return render_template("dashboard.html", cards=bracket_cards, user=current_user())


@app.route("/join", methods=["POST"])
@login_required
def join_by_share_code():
    share_code = request.form.get("share_code", "").strip()
    mode = request.form.get("mode", "filled").strip().lower()
    if not share_code:
        flash("Enter a share code.")
        return redirect(url_for("dashboard"))

    return redirect(url_for("add_shared_bracket", share_code=share_code, mode=mode))


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

    db.execute(
        """
        INSERT INTO brackets (
            owner_id, name, size, teams_json, seeding_mode, bye_teams_json,
            rounds_json, base_rounds_json, share_code, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            name,
            bracket_size,
            json.dumps(teams),
            seeding_mode,
            json.dumps(bye_teams),
            json.dumps(rounds),
            json.dumps(rounds),
            generate_share_code(db),
            now,
            now,
        ),
    )
    db.commit()

    bracket_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return redirect(url_for("view_bracket", bracket_id=bracket_id))


@app.route("/brackets/<int:bracket_id>")
@login_required
def view_bracket(bracket_id):
    row, has_access = get_bracket_or_accessible(bracket_id)
    if row is None:
        flash("Bracket not found.")
        return redirect(url_for("dashboard"))
    if not has_access:
        flash("You do not have access to that bracket.")
        return redirect(url_for("dashboard"))

    rounds, vote_map = save_recomputed_bracket_state(row)
    user_votes = get_user_votes(bracket_id, session["user_id"])
    standings = summarize_votes_for_rounds(rounds, vote_map, user_votes)

    db = get_db()
    collaborator_count = db.execute(
        "SELECT COUNT(*) AS total FROM bracket_members WHERE bracket_id = ?",
        (bracket_id,),
    ).fetchone()["total"]

    return render_template(
        "view_bracket.html",
        bracket=row,
        rounds=rounds,
        teams=json.loads(row["teams_json"]),
        bye_teams=json.loads(row["bye_teams_json"]),
        user=current_user(),
        is_owner=row["owner_id"] == session["user_id"],
        vote_standings=standings,
        collaborator_count=collaborator_count,
    )


@app.route("/brackets/<int:bracket_id>/delete", methods=["POST"])
@login_required
def delete_bracket(bracket_id):
    row = get_bracket(bracket_id)
    if row is None:
        flash("Bracket not found.")
        return redirect(url_for("dashboard"))

    if row["owner_id"] != session["user_id"]:
        flash("Only the bracket owner can delete it.")
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute("DELETE FROM match_votes WHERE bracket_id = ?", (bracket_id,))
    db.execute("DELETE FROM bracket_members WHERE bracket_id = ?", (bracket_id,))
    db.execute("DELETE FROM bracket_invites WHERE bracket_id = ?", (bracket_id,))
    db.execute("DELETE FROM brackets WHERE id = ?", (bracket_id,))
    db.commit()

    flash("Bracket deleted.")
    return redirect(url_for("dashboard"))


@app.route("/api/brackets/<int:bracket_id>/vote", methods=["POST"])
@login_required
def vote_for_match(bracket_id):
    row, has_access = get_bracket_or_accessible(bracket_id)
    if row is None:
        return jsonify({"error": "Bracket not found."}), 404
    if not has_access:
        return jsonify({"error": "No access."}), 403

    payload = request.get_json(silent=True) or {}
    round_index = int(payload.get("round_index", -1))
    match_index = int(payload.get("match_index", -1))
    voted_team_raw = payload.get("team")
    voted_team = voted_team_raw.strip() if isinstance(voted_team_raw, str) else None

    rounds = parse_rounds(row)
    if round_index < 0 or round_index >= len(rounds):
        return jsonify({"error": "Invalid round."}), 400
    if match_index < 0 or match_index >= len(rounds[round_index]):
        return jsonify({"error": "Invalid match."}), 400

    match = rounds[round_index][match_index]
    allowed = {match.get("team1"), match.get("team2")}
    allowed.discard(None)
    allowed.discard("BYE")

    clear_vote = voted_team in {None, "", "none"}
    if not clear_vote and voted_team not in allowed:
        return jsonify({"error": "Vote must be one of the active teams."}), 400

    db = get_db()
    if clear_vote:
        db.execute(
            """
            DELETE FROM match_votes
            WHERE bracket_id = ? AND round_index = ? AND match_index = ? AND voter_user_id = ?
            """,
            (bracket_id, round_index, match_index, session["user_id"]),
        )
    else:
        db.execute(
            """
            INSERT INTO match_votes (bracket_id, round_index, match_index, voter_user_id, voted_team, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(bracket_id, round_index, match_index, voter_user_id)
            DO UPDATE SET voted_team = excluded.voted_team, created_at = excluded.created_at
            """,
            (
                bracket_id,
                round_index,
                match_index,
                session["user_id"],
                voted_team,
                serialize_datetime_now(),
            ),
        )
    db.commit()

    refreshed = get_bracket(bracket_id)
    rounds, vote_map = save_recomputed_bracket_state(refreshed)
    user_votes = get_user_votes(bracket_id, session["user_id"])
    standings = summarize_votes_for_rounds(rounds, vote_map, user_votes)
    champion = rounds[-1][0].get("winner") if rounds and rounds[-1] else None

    return jsonify(
        {
            "ok": True,
            "rounds": rounds,
            "champion": champion,
            "standings": standings,
        }
    )


@app.route("/api/brackets/<int:bracket_id>/share", methods=["POST"])
@login_required
def get_share_link(bracket_id):
    row = get_bracket(bracket_id)
    if row is None:
        return jsonify({"error": "Bracket not found."}), 404
    if row["owner_id"] != session["user_id"]:
        return jsonify({"error": "Only the owner can share this bracket."}), 403

    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "filled").strip().lower()
    if mode not in {"filled", "empty"}:
        mode = "filled"

    share_url = url_for("add_shared_bracket", share_code=row["share_code"], mode=mode, _external=True)
    return jsonify({"share_code": row["share_code"], "share_url": share_url, "mode": mode})


@app.route("/api/brackets/<int:bracket_id>/invite", methods=["POST"])
@login_required
def invite_to_bracket(bracket_id):
    row = get_bracket(bracket_id)
    if row is None:
        return jsonify({"error": "Bracket not found."}), 404
    if row["owner_id"] != session["user_id"]:
        return jsonify({"error": "Only the owner can invite people."}), 403

    payload = request.get_json(silent=True) or {}
    invite_email = payload.get("email", "").strip().lower()
    if not invite_email:
        return jsonify({"error": "Invite email is required."}), 400

    db = get_db()
    now = serialize_datetime_now()
    token = uuid.uuid4().hex

    invited_user = db.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (invite_email,)).fetchone()
    if invited_user:
        if invited_user["id"] == row["owner_id"]:
            return jsonify({"error": "Owner is already part of this bracket."}), 400
        add_member_if_possible(bracket_id, invited_user["id"])

    db.execute(
        """
        INSERT INTO bracket_invites (bracket_id, invited_by, email, token, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (bracket_id, session["user_id"], invite_email, token, now),
    )
    db.commit()

    invite_url = url_for("accept_invite", token=token, _external=True)
    sent = send_email(
        to_email=invite_email,
        subject=f"You are invited to vote in {row['name']}",
        html_body=(
            f"<p>You were invited to collaborate on <strong>{row['name']}</strong>.</p>"
            f"<p>Accept invite: <a href='{invite_url}'>{invite_url}</a></p>"
        ),
        text_body=f"You were invited to {row['name']}. Accept here: {invite_url}",
    )

    return jsonify({"ok": True, "invite_url": invite_url, "email_sent": sent})


@app.route("/invite/<token>/accept", methods=["GET"])
@login_required
def accept_invite(token):
    db = get_db()
    invite = db.execute("SELECT * FROM bracket_invites WHERE token = ?", (token,)).fetchone()
    if invite is None:
        flash("Invite link is invalid.")
        return redirect(url_for("dashboard"))

    user = current_user()
    if not user or not user["email"]:
        flash("Add an email to your account before accepting invites.")
        return redirect(url_for("dashboard"))

    if user["email"].lower() != invite["email"].lower():
        flash("This invite is tied to a different email address.")
        return redirect(url_for("dashboard"))

    add_member_if_possible(invite["bracket_id"], user["id"])
    db.execute(
        "UPDATE bracket_invites SET status = 'accepted', accepted_at = ? WHERE id = ?",
        (serialize_datetime_now(), invite["id"]),
    )
    db.commit()
    flash("Invite accepted. You can now vote in that bracket.")
    return redirect(url_for("view_bracket", bracket_id=invite["bracket_id"]))


@app.route("/api/brackets/<int:bracket_id>/reset", methods=["POST"])
@login_required
def reset_bracket(bracket_id):
    row = get_bracket(bracket_id)
    if row is None:
        return jsonify({"error": "Bracket not found."}), 404
    if row["owner_id"] != session["user_id"]:
        return jsonify({"error": "Only the owner can reset this bracket."}), 403

    db = get_db()
    db.execute("DELETE FROM match_votes WHERE bracket_id = ?", (bracket_id,))

    base_rounds = parse_rounds_json(row["base_rounds_json"] or row["rounds_json"])
    db.execute(
        "UPDATE brackets SET rounds_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(base_rounds), serialize_datetime_now(), bracket_id),
    )
    db.commit()

    refreshed = get_bracket(bracket_id)
    rounds = parse_rounds(refreshed)
    champion = rounds[-1][0].get("winner") if rounds and rounds[-1] else None
    standings = summarize_votes_for_rounds(rounds, {}, {})

    return jsonify({"ok": True, "rounds": rounds, "champion": champion, "standings": standings})


@app.route("/share/<share_code>/add", methods=["GET", "POST"])
@login_required
def add_shared_bracket(share_code):
    mode = request.args.get("mode", "filled").strip().lower()
    if mode not in {"filled", "empty"}:
        mode = "filled"

    db = get_db()
    original = db.execute("SELECT * FROM brackets WHERE share_code = ?", (share_code,)).fetchone()
    if original is None:
        flash("Invalid share link.")
        return redirect(url_for("dashboard"))

    if original["owner_id"] == session["user_id"]:
        flash("That bracket is already yours.")
        return redirect(url_for("view_bracket", bracket_id=original["id"]))

    rounds_json = original["rounds_json"] if mode == "filled" else (original["base_rounds_json"] or original["rounds_json"])
    existing_name = f"Copy of {original['name']} ({mode})"
    now = serialize_datetime_now()

    db.execute(
        """
        INSERT INTO brackets (
            owner_id, name, size, teams_json, seeding_mode, bye_teams_json,
            rounds_json, base_rounds_json, share_code, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            existing_name,
            original["size"],
            original["teams_json"],
            original["seeding_mode"],
            original["bye_teams_json"],
            rounds_json,
            original["base_rounds_json"] or original["rounds_json"],
            generate_share_code(db),
            now,
            now,
        ),
    )
    db.commit()

    new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    flash(f"Bracket added to your account ({mode} mode).")
    return redirect(url_for("view_bracket", bracket_id=new_id))


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
