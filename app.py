import os
import time
import random
import sqlite3
import threading
import requests
from flask import Flask, request, redirect, url_for, render_template_string, jsonify

# --- Configuration ---
API_BASE_URL = "https://shy-snow-cd49.amitkr545545.workers.dev/?url="
DB_FILE = "data.db"
TARGET_RPM = 50  # Requests per minute
SECONDS_PER_REQUEST = 60.0 / TARGET_RPM

app = Flask(__name__)

# --- Database Setup ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        # Table for Terabox links
        c.execute('''CREATE TABLE IF NOT EXISTS links (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        url TEXT UNIQUE)''')
        # Table for stats tracking
        c.execute('''CREATE TABLE IF NOT EXISTS stats (
                        id INTEGER PRIMARY KEY CHECK (id = 1), 
                        total INTEGER DEFAULT 0, 
                        success INTEGER DEFAULT 0)''')
        c.execute('INSERT OR IGNORE INTO stats (id, total, success) VALUES (1, 0, 0)')
        conn.commit()

# --- Background Worker ---
def background_requester():
    while True:
        start_time = time.time()
        
        try:
            with sqlite3.connect(DB_FILE) as conn:
                c = conn.cursor()
                c.execute("SELECT url FROM links")
                links = [row[0] for row in c.fetchall()]
                
            if not links:
                # If no links added yet, sleep and wait
                time.sleep(2)
                continue

            # Pick a random Terabox link
            target_link = random.choice(links)
            request_url = f"{API_BASE_URL}{target_link}"

            # Increment Total Count
            with sqlite3.connect(DB_FILE) as conn:
                c = conn.cursor()
                c.execute("UPDATE stats SET total = total + 1 WHERE id = 1")
                conn.commit()

            # Make the API Request
            success = False
            try:
                response = requests.get(request_url, timeout=10)
                if response.status_code == 200:
                    success = True
            except requests.RequestException:
                pass

            # Increment Success Count if request succeeded
            if success:
                with sqlite3.connect(DB_FILE) as conn:
                    c = conn.cursor()
                    c.execute("UPDATE stats SET success = success + 1 WHERE id = 1")
                    conn.commit()

        except Exception as e:
            print(f"Worker error: {e}")

        # Calculate time taken and sleep exactly enough to maintain 50 requests/min
        elapsed = time.time() - start_time
        sleep_time = max(0, SECONDS_PER_REQUEST - elapsed)
        time.sleep(sleep_time)

# Start background worker only once
init_db()
if not hasattr(app, 'worker_started'):
    app.worker_started = True
    threading.Thread(target=background_requester, daemon=True).start()

# --- HTML Web Panel Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Traffic Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; padding-top: 2rem; }
        .stat-card { border-radius: 10px; padding: 20px; color: white; }
        .bg-total { background: linear-gradient(45deg, #0d6efd, #0dcaf0); }
        .bg-success-stat { background: linear-gradient(45deg, #198754, #20c997); }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="mb-4">⚡ API Traffic Controller</h2>
        
        <div class="row mb-4">
            <div class="col-md-6 mb-2">
                <div class="stat-card bg-total shadow">
                    <h5>Total Requests Sent</h5>
                    <h2 id="total-count">{{ stats[0] }}</h2>
                </div>
            </div>
            <div class="col-md-6 mb-2">
                <div class="stat-card bg-success-stat shadow">
                    <h5>Successful Requests (200 OK)</h5>
                    <h2 id="success-count">{{ stats[1] }}</h2>
                </div>
            </div>
        </div>

        <div class="card shadow-sm mb-4">
            <div class="card-body">
                <form action="/add" method="POST" class="d-flex">
                    <input type="url" name="url" class="form-control me-2" placeholder="Enter Terabox Link (e.g., https://1024terabox.com/...)" required>
                    <button type="submit" class="btn btn-primary">Add Link</button>
                </form>
            </div>
        </div>

        <div class="card shadow-sm">
            <div class="card-header bg-white">
                <h5 class="mb-0">Active Terabox Links</h5>
            </div>
            <div class="card-body p-0">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>ID</th>
                            <th>Terabox URL</th>
                            <th class="text-end">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for link in links %}
                        <tr>
                            <td>{{ link[0] }}</td>
                            <td class="text-break">{{ link[1] }}</td>
                            <td class="text-end">
                                <form action="/delete/{{ link[0] }}" method="POST" style="display:inline;">
                                    <button type="submit" class="btn btn-sm btn-danger">Delete</button>
                                </form>
                            </td>
                        </tr>
                        {% else %}
                        <tr>
                            <td colspan="3" class="text-center text-muted py-3">No links added yet. Add one above!</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        setInterval(() => {
            fetch('/api/stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('total-count').innerText = data.total;
                    document.getElementById('success-count').innerText = data.success;
                })
                .catch(err => console.error(err));
        }, 2000);
    </script>
</body>
</html>
"""

# --- Web Routes ---
@app.route('/')
def index():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT total, success FROM stats WHERE id = 1")
        stats = c.fetchone()
        c.execute("SELECT id, url FROM links ORDER BY id DESC")
        links = c.fetchall()
    return render_template_string(HTML_TEMPLATE, stats=stats, links=links)

@app.route('/add', methods=['POST'])
def add_link():
    url = request.form.get('url')
    if url:
        try:
            with sqlite3.connect(DB_FILE) as conn:
                c = conn.cursor()
                c.execute("INSERT INTO links (url) VALUES (?)", (url.strip(),))
                conn.commit()
        except sqlite3.IntegrityError:
            pass # Ignore duplicate links
    return redirect(url_for('index'))

@app.route('/delete/<int:link_id>', methods=['POST'])
def delete_link(link_id):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM links WHERE id = ?", (link_id,))
        conn.commit()
    return redirect(url_for('index'))

@app.route('/api/stats')
def api_stats():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute("SELECT total, success FROM stats WHERE id = 1")
        stats = c.fetchone()
    return jsonify({"total": stats[0], "success": stats[1]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
