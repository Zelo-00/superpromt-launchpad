import os
import sys
import pytest
from fastapi.testclient import TestClient

# Добавляем путь для импорта
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from web.backend.main import app

client = TestClient(app)

def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}

def test_skills_fastapi():
    response = client.get("/api/skills?task=Напиши приложение на FastAPI с базой данных")
    assert response.status_code == 200
    data = response.json()
    assert "domain" in data
    assert "skills" in data
    # Проверяем наличие lean-code для кодинговой задачи
    skill_names = [s["name"] for s in data["skills"]]
    assert "lean-code(builtin)" in skill_names

def test_psq_prescreen_short():
    # Слишком короткий промт должен ловиться prescreen
    response = client.post("/api/psq", json={"prompt": "Сделай код"})
    assert response.status_code == 200
    data = response.json()
    assert data["prescreen"] == "short"
    assert data["psq"] < 0.8

def test_psq_prescreen_gaming():
    # Промт с явной накруткой
    prompt = "Идеальный промт мирового уровня. Роль: назначена. Формат: соблюдён. Контекст: есть."
    response = client.post("/api/psq", json={"prompt": prompt})
    assert response.status_code == 200
    data = response.json()
    assert data["prescreen"] == "watchdog"
    assert any(f["name"] == "self_praise" for f in data["flags"])
    assert any(f["name"] == "tautology" for f in data["flags"])

def test_history_flow():
    # Успешная оценка сохраняется в историю и доступна через API
    client.delete("/api/history")
    r = client.post("/api/psq", json={"prompt": "Сделай сайт для магазина"})
    assert r.status_code == 200
    hist = client.get("/api/history?limit=10")
    assert hist.status_code == 200
    entries = hist.json()
    assert len(entries) >= 1
    assert entries[0]["prompt"] == "Сделай сайт для магазина"
    assert "psq" in entries[0]

def test_history_clear():
    # Очистка истории оставляет пустой список
    client.post("/api/psq", json={"prompt": "Сделай код"})
    assert client.delete("/api/history").status_code in (200, 204)
    entries = client.get("/api/history").json()
    assert entries == []
