# Спецификация автономного пакета задачи (Task Bundle v1.0.2)

Каждая задача представляет собой изолированную директорию в хранилище `/app/data/tasks/<task_id>/`[cite: 30].

## 1. Состав директории задачи

```text
data/tasks/<task_id>/
├── manifest.json       # Метаданные для каталога и проверок[cite: 30]
├── generator.py        # Физическая модель, генерация варианта и функция автопроверки
├── widget.html         # Автономный веб-интерфейс (HTML/CSS/JS)[cite: 30]
└── assets/             # (Опционально) Локальные датасеты, рисунки, спектры[cite: 30]

```

---

## 2. Спецификация `manifest.json`

```json
{
  "schema_version": "2.0",
  "id": "cepheid-pl",
  "title": "Кривая блеска цефеиды: период и расстояние",
  "kind": "generated",
  "version": "1.0.0",
  "hidden": false,
  "tags": {
    "class": [10, 11],
    "topic": "переменные звёзды",
    "skills": ["фотометрия", "период-светимость"]
  },
  "max_score": 10.0,
  "entry_point": "widget.html",
  "generator_script": "generator.py"
}

```

* `id` — строковый идентификатор (обязан совпадать с именем папки).


* `hidden` — флаг скрытия из публичного каталога (по умолчанию `false`).


* `entry_point` — основной HTML-файл для песочницы iframe (по умолчанию `widget.html`).


* `generator_script` — имя Python-файла с алгоритмом генерации (по умолчанию `generator.py`).



---

## 3. Спецификация `generator.py`

Файл содержит две обязательные функции: `generate()` и `grade()`:

```python
import random

def generate(seed: int | None = None) -> dict:
    actual_seed = seed if seed is not None else 42
    rng = random.Random(actual_seed)
    
    # 1. Расчет наблюдательных величин
    # ...
    return {
        "id": "task-id",
        "title": "Название задачи",
        "max_score": 10.0,
        "entry_point": "widget.html",
        "data": {
            "statement": "Условие задачи...",
            "series": [
                {"id": "main", "marker": "dot", "points": [[0.1, 2.3], [0.2, 2.5]]}
            ],
            "axes": {
                "x": {"label": "X", "min": 0.0, "max": 10.0, "tick": 1.0},
                "y": {"label": "Y", "min": 0.0, "max": 5.0, "tick": 0.5, "inverted": false}
            }
        },
        "schema": {
            "fields": [
                {"id": "p_val", "kind": "number", "label": "Параметр", "unit": "сут"}
            ]
        }
    }

def grade(seed: int, answers: dict) -> dict:
    """Функция автоматической оценки решения участника."""
    # 1. Вычисляем эталоны по seed
    true_val = 5.25
    tol = 0.15
    weight = 10.0

    raw = answers.get("p_val")
    try:
        val = float(str(raw).replace(",", ".").strip())
        ok = abs(val - true_val) <= tol
        earned = weight if ok else 0.0
    except (ValueError, TypeError):
        val = None
        ok = False
        earned = 0.0

    return {
        "score": earned,
        "max_score": 10.0,
        "details": {
            "p_val": {
                "user": val,
                "truth": true_val,
                "tol": tol,
                "score": earned,
                "max": weight,
                "ok": ok
            }
        }
    }

```

---

## 4. Спецификация `widget.html` и шина сообщений

Интерфейс тренажёра исполняется внутри `<iframe sandbox="allow-scripts allow-same-origin">`.

### Подключение общей библиотеки AstroPlot

В секции `<head>` подключаются общие модули:

```html
<link rel="stylesheet" href="/static/tasks/_shared/astroplot.css">
<script src="/static/tasks/_shared/astroplot.js"></script>

```

### События PostMessage

1. **`ASTROSITE_INIT_DATA` (Host $\rightarrow$ Iframe):**
Передаёт `data`, `draft`, `session_code`, `is_submitted`, а также объект результатов `grading` (если задача уже сдана).


2. **`ASTROSITE_ANSWER_CHANGE` (Iframe $\rightarrow$ Host):**
Передаёт промежуточные ответы для автосохранения:


```javascript
window.parent.postMessage({ type: 'ASTROSITE_ANSWER_CHANGE', answers: { ... } }, '*');

```


3. **`ASTROSITE_SUBMIT_ATTEMPT` (Iframe $\rightarrow$ Host):**
Инициирует сдачу работы на сервере.


4. **`ASTROSITE_SUBMIT_SUCCESS` (Host $\rightarrow$ Iframe):**
Передаёт результаты автопроверки `score`, `max_score`, `grading` для подсветки полей в виджете.


5. **`ASTROSITE_FRAME_RESIZE` (Iframe $\rightarrow$ Host):**
Передаёт физическую высоту контейнера `#widget-root` с демпфером для исключения полос прокрутки.



```