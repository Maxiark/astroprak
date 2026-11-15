import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

TASKS_DIR = Path("/app/data/tasks")


class TaskLoader:
    def __init__(self):
        self.manifests: Dict[str, Any] = {}
        self.generators: Dict[str, Any] = {}

    def scan(self):
        """Сканирует директорию хранилища, загружает манифесты и генераторы без падений."""
        logger.info("Сканирование каталога задач: %s", TASKS_DIR)
        self.manifests.clear()
        self.generators.clear()

        if not TASKS_DIR.exists():
            logger.warning("Директория %s не найдена. Создание директории.", TASKS_DIR)
            TASKS_DIR.mkdir(parents=True, exist_ok=True)
            return

        for task_path in sorted(TASKS_DIR.iterdir()):
            if not task_path.is_dir() or task_path.name.startswith(("_", ".")):
                continue

            task_id = task_path.name
            manifest_path = task_path / "manifest.json"

            if not manifest_path.exists():
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

                manifest["id"] = task_id
                # По умолчанию задача видима, если явно не указано "hidden": true
                manifest.setdefault("hidden", False)

                generator_script = manifest.get("generator_script", "generator.py")
                script_path = task_path / generator_script

                generator_module = None
                if script_path.exists():
                    spec = importlib.util.spec_from_file_location(f"task_{task_id}", script_path)
                    if spec and spec.loader:
                        generator_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(generator_module)

                self.manifests[task_id] = manifest
                if generator_module:
                    self.generators[task_id] = generator_module

                logger.info("Задача '%s' зарегистрирована (hidden=%s).", task_id, manifest["hidden"])

            except Exception as e:
                logger.error("Задача '%s' проигнорирована из-за внутренней ошибки: %s", task_id, e)
                continue

    def get(self, task_id: str) -> Any | None:
        """Возвращает модуль генератора задачи (для вызовов registry.get(task_id))."""
        return self.generators.get(task_id)

    def get_manifest(self, task_id: str) -> dict | None:
        return self.manifests.get(task_id)

    def get_generator(self, task_id: str) -> Any | None:
        return self.generators.get(task_id)

    def grade(self, task_id: str, seed: int, answers: dict) -> dict | None:
        """Безопасно вызывает проверку решения у генератора задачи."""
        gen = self.get_generator(task_id)
        if gen and hasattr(gen, "grade"):
            try:
                return gen.grade(seed, answers)
            except Exception as e:
                logger.error("Ошибка при проверке задачи '%s': %s", task_id, e)
        return None

    def get_all_manifests(self, include_hidden: bool = False) -> list[dict]:
        """Отдает список манифестов. Для публичного каталога скрытые исключаются."""
        if include_hidden:
            return list(self.manifests.values())
        return [m for m in self.manifests.values() if not m.get("hidden", False)]


registry = TaskLoader()
