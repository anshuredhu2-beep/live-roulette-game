import os
import sqlite3
import time
from flask import Flask, render_template, request, session, redirect, url_for, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_roulette_key_2026")

DB_NAME = "roulette.db"

RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK_NUMS = {2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35}

# In-memory storage for current round bets and last round result
current_bets = []
last_round_result = {"num": 0, "color": "GREEN", "winners": []}
last_settled_round = None

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        points INTEGER DEFAULT 0
    )''')
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users (username, password, role, points) VALUES ('admin', 'admin123', 'admin', 0)")
    conn.commit()
    conn.close()

init_db()

def calculate_lowest_winner(bets_list):
    if not bets_list:
        return 0, "GREEN", 0
    payouts = {num: 0 for num in range(37)}
    for bet in bets_list:
        amt = bet['amount']
        b_type = bet['type']
        val = bet['value']
        for num in range(37):
            if b_type == 'number' and int(val) == num:
                payouts[num] += amt * 36
            elif b_type == 'color':
                if val == 'RED' and num in RED_NUMS: payouts[num] += amt * 2
                elif val == 'BLACK' and num in BLACK_NUMS: payouts[num] += amt * 2
            elif b_type == 'parity' and num != 0:
                if val == 'EVEN' and num % 2 == 0: payouts[num] += amt * 2
                elif val == 'ODD' and num % 2 != 0: payouts[num] += amt * 2

    min_payout = min(payouts.values())
    lowest_nums = [n for n, p in payouts.items() if p == min_payout]
    winning_num = lowest_nums[0]
    win_color = "GREEN" if winning_num == 0 else ("RED" if winning_num in RED_NUMS else "BLACK")
    return winning_num, win_color, min_payout

def check_and_settle_rounds():
    global current_bets, last_round_result, last_settled_round
    now = time.time()
    round_duration = 60
    betting_duration = 48
    
    current_round_id = int(now // round_duration)
    elapsed = int(now % round_duration)
    
    if elapsed < betting_duration:
        status = "BETTING"
        timer = betting_duration - elapsed
    else:
        status = "LOCKED"
        timer = round_duration - elapsed
        
        # If we entered locked state and haven't settled this round yet
        if last_settled_round != current_round_id:
            win_num, win_color, _ = calculate_lowest_winner(current_bets)
            conn = get_db()
            winners_log = []
            
            for bet in current_bets:
                won_amt = 0
                if bet["type"] == "number" and int(bet["value"]) == win_num:
                    won_amt = bet["amount"] * 36
                elif bet["type"] == "color" and bet["value"] == win_color:
                    won_amt = bet["amount"] * 2
                elif bet["type"] == "parity" and win_num != 0:
                    if (bet["value"] == "EVEN" and win_num % 2 == 0) or (bet["value"] == "ODD" and win_num % 2 != 0):
                        won_amt = bet["amount"] * 2
                
                if won_amt > 0:
                    conn.execute("UPDATE users SET points = points + ? WHERE username = ?", (won_amt, bet["username"]))
                    winners_log.append(f"{bet['username']} (+{won_amt})")
                    
            conn.commit()
            conn.close()
            
            last_round_result = {"num": win_num, "color": win_color, "winners": winners_log}
            last_settled_round = current_round_id
            current_bets = [] # Reset bets for next round

    return status, timer

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
        conn.close()
        if user:
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        return render_template("index.html", error="Galat ID ya Password!")
    if "username" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    if "username" not in session: return redirect(url_for("login"))
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=?", (session["username"],)).fetchone()
    users = conn.execute("SELECT username, role, points FROM users WHERE role='player'").fetchall() if session["role"] == "admin" else []
    conn.close()
    if not user:
        session.clear()
        return redirect(url_for("login"))
    return render_template("index.html", user=user, users=users)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin/create_user", methods=["POST"])
def create_user():
    if session.get("role") != "admin": return jsonify({"status": "error"})
    data = request.json
    try:
        conn = get_db()
        conn.execute("INSERT INTO users (username, password, role, points) VALUES (?, ?, 'player', ?)",
                     (data["username"], data["password"], int(data["points"])))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})
    except:
        return jsonify({"status": "error", "msg": "Username pehle se maujood hai!"})

@app.route("/admin/update_points", methods=["POST"])
def update_points():
    if session.get("role") != "admin": return jsonify({"status": "error"})
    data = request.json
    conn = get_db()
    conn.execute("UPDATE users SET points = points + ? WHERE username = ?", (int(data["amount"]), data["username"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/place_bet", methods=["POST"])
def place_bet():
    status, _ = check_and_settle_rounds()
    if status != "BETTING":
        return jsonify({"status": "error", "msg": "Betting locked hai!"})
    
    username = session.get("username")
    if not username or session.get("role") != "player":
        return jsonify({"status": "error", "msg": "Unauthorized"})
        
    data = request.json
    amount = int(data.get("amount", 0))
    b_type = data.get("type")
    val = data.get("value")
    
    conn = get_db()
    user = conn.execute("SELECT points FROM users WHERE username=?", (username,)).fetchone()
    
    if user and user["points"] >= amount and amount > 0:
        new_points = user["points"] - amount
        conn.execute("UPDATE users SET points=? WHERE username=?", (new_points, username))
        conn.commit()
        
        current_bets.append({"username": username, "type": b_type, "value": val, "amount": amount})
        conn.close()
        return jsonify({"status": "ok", "points": new_points})
    
    conn.close()
    return jsonify({"status": "error", "msg": "Insufficient points!"})

@app.route("/api/gamestate")
def api_gamestate():
    status, timer = check_and_settle_rounds()
    win_num, win_color, min_pay = calculate_lowest_winner(current_bets)
    
    # Get user points if logged in
    user_points = 0
    if "username" in session:
        conn = get_db()
        u = conn.execute("SELECT points FROM users WHERE username=?", (session["username"],)).fetchone()
        if u: user_points = u["points"]
        
        # Also fetch all players points for admin
        all_players = []
        if session.get("role") == "admin":
            players_db = conn.execute("SELECT username, points FROM users WHERE role='player'").fetchall()
            all_players = [{"username": p["username"], "points": p["points"]} for p in players_db]
        conn.close()
    else:
        all_players = []

    return jsonify({
        "status": status,
        "timer": timer,
        "predicted_num": win_num,
        "predicted_color": win_color,
        "min_payout": min_pay,
        "bets": current_bets,
        "last_result": last_round_result,
        "my_points": user_points,
        "all_players": all_players
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
