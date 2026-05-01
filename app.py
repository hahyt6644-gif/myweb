import os
import json
import time
import random
import threading
import requests
from flask import Flask, request, redirect, url_for, render_template_string, jsonify

# --- Configuration ---
API_BASE_URL = "https://shy-snow-cd49.amitkr545545.workers.dev/?url="
DB_FILE = "data.json"
TARGET_RPM = 50  # Requests per minute
SECONDS_PER_REQUEST = 60.0 / TARGET_RPM

app = Flask(__name__)

# Thread lock to prevent file corruption when reading/writing at the same time
db_lock = threading.Lock()

# --- JSON Database Setup & Helpers ---
def init_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f:
            json.dump({"stats": {"total": 0, "success": 0}, "links": []}, f)

def read_db():
    with open(DB_FILE, 'r') as f:
        return json.load(f)

def write_db(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# --- Background Worker ---
def background_requester():
    while True:
        start_time = time.time()
        
        try:
            # Safely read links from JSON
            with db_lock:
                data = read_db()
                links = data.get("links", [])
                
            if not links:
                # If no links added yet, sleep and wait
                time.sleep(2)
                continue

            # Pick a random Terabox link
            target = random.choice(links)
            request_url = f"{API_BASE_URL}{target['url']}"

            # Increment Total Count safely
            with db_lock:
                data = read_db()
                data["stats"]["total"] += 1
                write_db(data)

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
                with db_lock:
                    data = read_db()
                    data["stats"]["success"] += 1
                    write_db(data)

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
                    <h2 id="total-count">{{ stats.total }}</h2>
                </div>
            </div>
            <div class="col-md-6 mb-2">
                <div class="stat-card bg-success-stat shadow">
                    <h5>Successful Requests (200 OK)</h5>
                    <h2 id="success-count">{{ stats.success }}</h2>
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
                            <td>{{ link.id }}</td>
                            <td class="text-break">{{ link.url }}</td>
                            <td class="text-end">
                                <form action="/delete/{{ link.id }}" method="POST" style="display:inline;">
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
    with db_lock:
        data = read_db()
    
    # Reverse links so newest show at the top
    links_reversed = list(reversed(data["links"]))
    return render_template_string(HTML_TEMPLATE, stats=data["stats"], links=links_reversed)

@app.route('/add', methods=['POST'])
def add_link():
    url = request.form.get('url')
    if url:
        url = url.strip()
        with db_lock:
            data = read_db()
            
            # Check if URL already exists to avoid duplicates
            if not any(link['url'] == url for link in data["links"]):
                # Generate a simple auto-incrementing ID
                new_id = 1 if not data["links"] else max(link["id"] for link in data["links"]) + 1
                data["links"].append({"id": new_id, "url": url})
                write_db(data)
                
    return redirect(url_for('index'))

@app.route('/delete/<int:link_id>', methods=['POST'])
def delete_link(link_id):
    with db_lock:
        data = read_db()
        # Filter out the deleted link
        data["links"] = [link for link in data["links"] if link["id"] != link_id]
        write_db(data)
        
    return redirect(url_for('index'))

@app.route('/api/stats')
def api_stats():
    with db_lock:
        data = read_db()
    return jsonify({"total": data["stats"]["total"], "success": data["stats"]["success"]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
