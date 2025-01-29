import time
import threading
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)


# --- Глобальные переменные ---
pc_data = {}                      # {"pc1": ("lobby123", timestamp), "pc2": ("lobby123", timestamp)}
current_game_state = "waiting"     # "waiting", "pending", "accept", "reject"
final_result = None                # Финальный ответ (accept/reject)
start_time = None
game_history = []                      # История игр
REQUIRED_PCS = 2                   # Ожидаем 2 ПК
lock = threading.Lock()            # Для потокобезопасности
responses_sent = set()             # Запоминаем ПК, которые уже получили ответ

# --- Встроенный HTML-шаблон ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Lobby Server</title>
    <!-- Bootstrap 5 -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <style>
        body {
            background-color: #f8f9fa;
            color: #212529;
            margin-bottom: 3rem;
        }
        .navbar-dark.bg-dark {
            margin-bottom: 2rem;
        }
        .status {
            font-size: 1.2rem;
            font-weight: 600;
        }
        .accept { color: green; }
        .reject { color: red; }
        .waiting { color: orange; }
        .card {
            margin-bottom: 1rem;
        }
        .table thead th {
            background-color: #343a40;
            color: #fff;
        }
    </style>
</head>
<body>

<nav class="navbar navbar-expand-lg navbar-dark bg-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="#">Lobby Server (2 PCs)</a>
  </div>
</nav>

<div class="container">

    <!-- Карточка со статусом -->
    <div class="card">
        <div class="card-header">
            Текущий статус
        </div>
        <div class="card-body">
            <p class="status {{ state }}">
                {{ state }}
            </p>
        </div>
    </div>

    <!-- Карточка с данными от ПК -->
    <div class="card">
        <div class="card-header">
            Данные от ПК
        </div>
        <div class="card-body">
            <table class="table table-bordered table-sm align-middle">
                <thead>
                    <tr>
                        <th>PC name</th>
                        <th>Lobby ID</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                {% for pc, (lobby, ts) in pc_data.items() %}
                    <tr>
                        <td>{{ pc }}</td>
                        <td>{{ lobby }}</td>
                        <td>{{ ts }}</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Карточка с историей игр -->
    <div class="card">
        <div class="card-header">
            История игр
        </div>
        <div class="card-body">
            <table class="table table-striped table-sm align-middle">
                <thead>
                    <tr>
                        <th>Время</th>
                        <th>Lobby ID</th>
                        <th>Статус</th>
                    </tr>
                </thead>
                <tbody>
                {% for item in game_history %}
                    <tr>
                        <td>{{ item.timestamp }}</td>
                        <td>{{ item.lobby_id }}</td>
                        <td>{{ item.status }}</td>
                    </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

</div> <!-- /container -->

</body>
</html>
"""

def reset_state():
    """Сбрасываем состояние через 10 секунд после первого ID"""
    global pc_data, current_game_state, start_time, final_result, responses_sent
    time.sleep(5)  # Ждем 5 секунд, чтобы клиенты успели запросить статус
    with lock:
        pc_data.clear()
        responses_sent.clear()  # Сбрасываем очередь запросов
        current_game_state = "waiting"
        start_time = None
        final_result = None


def check_all_in_5s_and_reset_in_10():
    """Через 5 секунд выставляем accept/reject, через 10 сбрасываем"""
    global current_game_state, final_result

    time.sleep(5)  # Ждём 5 секунд для сбора данных

    with lock:
        if len(pc_data) < REQUIRED_PCS:
            final_result = "reject"
        else:
            all_lobby_ids = {data[0] for data in pc_data.values()}
            final_result = "accept" if len(all_lobby_ids) == 1 else "reject"

        current_game_state = final_result

        # Добавляем в историю, если игра принята
        if final_result == "accept":
            game_history.insert(0, {  # Новая запись сверху
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "lobby_id": list(all_lobby_ids)[0],
                "status": "Game started"
            })

    # Ждем 10 секунд от старта перед сбросом
    elapsed = time.time() - start_time
    remain = 10 - elapsed
    if remain > 0:
        time.sleep(remain)
    reset_state()

# --- Маршрут на главную (рендерим шаблон) ---
@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        state=current_game_state,
        pc_data=pc_data,
        game_history=game_history
    )

@app.route("/send_lobby_id", methods=["POST"])
def send_lobby_id():
    """Приём лобби ID от ПК"""
    global start_time

    data = request.json
    if not data or "lobby_id" not in data or "pc" not in data:
        return jsonify({"error": "Invalid data"}), 400

    with lock:
        pc_data[data["pc"]] = (data["lobby_id"], time.time())

        if start_time is None:
            start_time = time.time()
            threading.Thread(target=check_all_in_5s_and_reset_in_10).start()

    return jsonify({"status": "received"})


@app.route("/check_status", methods=["GET"])
def check_status():
    """ПК проверяет статус"""
    pc_name = request.args.get("pc")

    with lock:
        if final_result is None:
            return jsonify({"status": "pending"})

        # Проверяем, получал ли уже этот ПК ответ
        if pc_name in responses_sent:
            return jsonify({"status": final_result})  # Если уже получил, отправляем повторно

        responses_sent.add(pc_name)  # Запоминаем, что ПК получил ответ
        return jsonify({"status": final_result})  # Всем одинаковый ответ

# --- Запуск ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
