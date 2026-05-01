import os
import json
import time
import random
import threading
import concurrent.futures
import requests
from flask import Flask, request, redirect, url_for, render_template_string, jsonify

# --- Configuration ---
API_BASE_URL = ""
DB_FILE = "data.json"
CONCURRENT_THREADS = 20  # Number of parallel requests happening at the exact same time

app = Flask(__name__)

# Locks for thread safety
db_lock = threading.Lock()
ram_lock = threading.Lock()

# In-memory stats for high-speed counting (prevents disk bottleneck)
ram_stats = {"total": 0, "success": 0}

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

# --- Parallel API Requester ---
def make_api_call(target_url):
    global ram_stats
    request_url = f"{API_BASE_URL}{target_url}"
    
    # Increment total in RAM
    with ram_lock:
        ram_stats["total"] += 1

    success = False
    try:
        # 5-second timeout keeps threads from hanging so they can move to the next request instantly
        response = requests.get(request_url, timeout=5)
        if response.status_code == 200:
            success = True
    except requests.RequestException:
        pass

    # Increment success in RAM
    if success:
        with ram_lock:
            ram_stats["success"] += 1

def parallel_worker():
    """Maintains a continuous pool of active threads bombarding the API."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_THREADS) as executor:
        while True:
            # 1. Fetch active links from DB
            with db_lock:
                data = read_db()
                links = [link['url'] for link in data.get("links", [])]
            
            if not links:
                time.sleep(2)
                continue

            # 2. Fire off a batch of parallel requests
            futures = []
            for _ in range(CONCURRENT_THREADS):
                target = random.choice(links)
                futures.append(executor.submit(make_api_call, target))
            
            # 3. Wait for the batch to finish, then immediately loop again (No Sleep)
            concurrent.futures.wait(futures)

def disk_sync_worker():
    """Saves RAM stats to the JSON file every 3 seconds to prevent data loss."""
    global ram_stats
    while True:
        time.sleep(3)
        with ram_lock:
            if ram_stats["total"] == 0 and ram_stats["success"] == 0:
                continue
            
            # Copy and instantly reset RAM stats
            to_add_total = ram_stats["total"]
            to_add_success = ram_stats["success"]
            ram_stats["total"] = 0
            ram_stats["success"] = 0
        
        # Save to disk safely
        with db_lock:
            data = read_db()
            data["stats"]["total"] += to_add_total
            data["stats"]["success"] += to_add_success
            write_db(data)

# Start workers only once
init_db()
if not hasattr(app, 'workers_started'):
    app.workers_started = True
    threading.Thread(target=parallel_worker, daemon=True).start()
    threading.Thread(target=disk_sync_worker, daemon=True).start()

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
        .pulse { animation: pulse-animation 2s infinite; }
        @keyframes pulse-animation {
            0% { transform: scale(1); }
            50% { transform: scale(1.02); }
            100% { transform: scale(1); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h2 class="mb-4">🚀 High-Speed API Controller <span class="badge bg-danger fs-6 pulse">Parallel Mode Active</span></h2>
        
        <div class="row mb-4">
            <div class="col-md-6 mb-2">
                <div class="stat-card bg-total shadow">
                    <h5>Total Requests Sent</h5>
                    <h2 id="total-count">Loading...</h2>
                </div>
            </div>
            <div class="col-md-6 mb-2">
                <div class="stat-card bg-success-stat shadow">
                    <h5>Successful Requests (200 OK)</h5>
                    <h2 id="success-count">Loading...</h2>
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
        }, 1000);
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
    return render_template_string(HTML_TEMPLATE, links=links_reversed)

@app.route('/add', methods=['POST'])
def add_link():
    url = request.form.get('url')
    if url:
        url = url.strip()
        with db_lock:
            data = read_db()
            
            # Check if URL already exists
            if not any(link['url'] == url for link in data["links"]):
                new_id = 1 if not data["links"] else max(link["id"] for link in data["links"]) + 1
                data["links"].append({"id": new_id, "url": url})
                write_db(data)
                
    return redirect(url_for('index'))

@app.route('/delete/<int:link_id>', methods=['POST'])
def delete_link(link_id):
    with db_lock:
        data = read_db()
        data["links"] = [link for link in data["links"] if link["id"] != link_id]
        write_db(data)
        
    return redirect(url_for('index'))

@app.route('/api/stats')
def api_stats():
    # Combine Database (permanent) stats with RAM (temporary fast) stats for real-time display
    with db_lock:
        data = read_db()
    with ram_lock:
        current_total = data["stats"]["total"] + ram_stats["total"]
        current_success = data["stats"]["success"] + ram_stats["success"]
        
    return jsonify({"total": current_total, "success": current_success})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
