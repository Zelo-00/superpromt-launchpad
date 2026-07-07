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

def test_stats_structure():
    # /api/stats возвращает агрегаты после оценки
    client.delete("/api/history")
    client.post("/api/psq", json={"prompt": "Сделай сайт для кофейни"})
    stats = client.get("/api/stats")
    assert stats.status_code == 200
    data = stats.json()
    assert data["total_count"] >= 1
    assert 0.0 <= data["avg_psq"] <= 1.0
    assert "modes" in data
    assert "recent_points" in data

def test_upload_file():
    # /api/upload принимает файл и возвращает метаданные
    files = {"files": ("photo.png", b"\x89PNG\r\n\x1a\nxxxxxxxx", "image/png")}
    r = client.post("/api/upload", files=files)
    assert r.status_code == 200
    data = r.json()
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "photo.png"
    assert data["files"][0]["content_type"] == "image/png"
    assert data["files"][0]["size"] > 0

def test_make_launchers():
    import tempfile
    import shutil
    from web.backend.launchers import make_launchers
    
    with tempfile.TemporaryDirectory() as tmpdir:
        make_launchers(tmpdir)
        files = os.listdir(tmpdir)
        assert "start.bat" in files
        assert "start.command" in files
        assert "start.sh" in files
        assert "README.md" in files
        
        # Проверка прав доступа (исполняемые файлы)
        if sys.platform != "win32":
            assert os.access(os.path.join(tmpdir, "start.sh"), os.X_OK)
            assert os.access(os.path.join(tmpdir, "start.command"), os.X_OK)

def test_api_demo():
    response = client.post("/api/demo")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["X-Mode"] == "demo"
    
    # Проверка содержимого ZIP
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = zf.namelist()
        assert "index.html" in names
        assert "styles.css" in names
        assert "start.bat" in names
        assert "README.md" in names

def test_api_prescreen():
    # Тест на короткий промт
    r1 = client.get("/api/prescreen?prompt=Hi")
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["psq"] < 0.5
    assert any(f["name"] == "too_short" for f in data1["flags"])
    
    # Тест на самохвал
    r2 = client.get("/api/prescreen?prompt=Напиши самый лучший идеальный код в мире")
    assert r2.status_code == 200
    data2 = r2.json()
    assert any(f["name"] == "self_praise" for f in data2["flags"])
    
    # Тест на плейсхолдеры
    r3 = client.get("/api/prescreen?prompt=Сделай [предметная область] для меня")
    assert r3.status_code == 200
    data3 = r3.json()
    assert any(f["name"] in ("placeholder", "placeholders") for f in data3["flags"])

