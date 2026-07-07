import os
import stat

def make_launchers(target_dir, entry='index.html', port=8080):
    """
    Создает файлы запуска (лаунчеры) для Windows, macOS и Linux в target_dir.
    Также создает README.md с инструкциями.
    """
    os.makedirs(target_dir, exist_ok=True)

    # 1. start.bat (Windows)
    bat_content = f"@echo off\nstart http://localhost:{port}/{entry}\npython -m http.server {port}\n"
    with open(os.path.join(target_dir, "start.bat"), "w", encoding="utf-8") as f:
        f.write(bat_content)

    # 2. start.command (macOS)
    command_content = f"#!/bin/bash\ncd \"$(dirname \"$0\")\"\nopen \"http://localhost:{port}/{entry}\"\npython3 -m http.server {port}\n"
    command_path = os.path.join(target_dir, "start.command")
    with open(command_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(command_content)
    os.chmod(command_path, os.stat(command_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # 3. start.sh (Linux)
    sh_content = f"#!/bin/bash\nxdg-open \"http://localhost:{port}/{entry}\" || sensible-browser \"http://localhost:{port}/{entry}\" || x-www-browser \"http://localhost:{port}/{entry}\"\npython3 -m http.server {port}\n"
    sh_path = os.path.join(target_dir, "start.sh")
    with open(sh_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(sh_content)
    os.chmod(sh_path, os.stat(sh_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # 4. README.md
    readme_content = f"""# Инструкция по запуску

Этот архив содержит мини-сайт и лаунчеры для локального запуска.

## Как запустить:

### Windows
Дважды щелкните по файлу `start.bat`.

### macOS
Дважды щелкните по файлу `start.command`. Если система выдаст предупреждение о безопасности, разрешите запуск в настройках или через контекстное меню (правой кнопкой мыши -> Открыть).

### Linux
Запустите скрипт `start.sh` в терминале:
```bash
chmod +x start.sh
./start.sh
```

Сайт будет доступен по адресу: http://localhost:{port}/{entry}
"""
    with open(os.path.join(target_dir, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme_content)
