# Руководство по интеграции задач `astrosite_base` (`astrosim`) в модульную платформу `astroprak`

## 1. Карта ядра старого сайта (`astrosite_base`)

В старом проекте логика задач разделена между тремя жёстко сцепленными слоями:

1. **Пакет физических моделей и генераторов (`packages/astrosim/astrosim/`)**:
   - `constants.py` — табличные константы из справочного листа ВсОШ (`G`, `C`, `AU`, `PC`, `M_SUN`, `R_SUN`, `YEAR_TROPICAL`, `DAY`, `ARCSEC`).
   - `models/binary_rv.py` (`Sb2Circular`, `from_masses`, `propagate`) и `models/sky_field.py` (`trail_offsets`, `tangential_velocity_kms`, `parabolic_speed_kms`, `small_angle_separation_deg`) — физические расчёты.
   - `analysis/sinefit.py` (`fit_sine`, `SineFit`) — линейный МНК для оценки нижней границы погрешности полуамплитуд в `rv-binary`.
   - `definitions.py` (`load_definition`, `list_definitions`, `render_text`, `render_content`) — чтение инвариантных JSON-описаний из `content/definitions/<id>.json` и безопасная подстановка вычисленных величин в шаблоны условия (`statement_template`) и пошагового разбора (`solution_template`).
   - `tasks/base.py` — ядро структур данных (`FieldSpec`, `KeyEntry`, `TaskPackage`, `FieldVerdict`, `Verdict`) и олимпиадной проверки `grade_fields`:
     - полный балл в пределах `±tolerance`, половина баллов (округление вниз) в пределах `±2·tolerance`;
     - штраф `−1` балл за избыточную точность (`precision_excessive`), если значащих цифр больше `sigfig_allowed` и цена младшего разряда мельче `tolerance / 20`;
     - проверка полей с погрешностью `number_with_error` (`0,056 ± 0,002`): начисление `points_error`, если указанная погрешность попадает в `[σ/3, 3σ]`;
     - проверка качественных ответов `yesno` («да»/«нет»/«разрешима»/«не разрешима»);
     - русское форматирование чисел `fmt(x, sig)` с запятой и порядками `1,10·10³¹`.
   - `tasks/observed.py` (`assemble`, `grade`) — компактная фабрика сборки задач для новых генераторов (`parallax_motion`, `rotation_mass`, `hubble_diagram`).
   - `tasks/registry.py` (`FAMILIES`, `get_family`) — статический реестр из 11 модулей задач (`rv_binary`, `cepheid_pl`, `transit_depth`, `comet_trails`, `jet_superluminal`, `descent_profile`, `galaxy_redshift`, `parallax_motion`, `rotation_mass`, `hubble_diagram`, `power_vertical`).
2. **Серверное ядро (`services/core/core/`)**:
   - `tasks.py` (`build_instance`, `store_instance`, `grade_instance`, `released_solution`) — напрямую импортирует `astrosim`, вызывает `module.generate(seed)`, валидирует совпадение полей с `Definition`, сохраняет неизменяемые снимки `Package` и `Solution` в таблицы `task_definitions`, `task_instances`, `task_assets` и проверяет ответы через `astrosim.tasks.base.grade_fields`.
3. **Монолитный React-клиент (`apps/web/src/components/`)**:
   - `Workbench.tsx` — жёстко зашитый экран задачи (таймер 100 мин, условие, вопросы `A..D`, инструменты, табло, журнал снятий, бланк и вердикт).
   - `Plot.tsx` — SVG-график с поддержкой серий `dot`/`ring`/`line`, треков звёзд `segments`, сферической метрики `spherical` ($\cos\delta$), лупы, многосерийного детектора экстремумов и отрезков.
   - `Sheet.tsx`, `Verdict.tsx`, `Content.tsx`, `ArchiveTask.tsx`, `FigurePanel.tsx` — рендеринг полей (`number`, `number_with_error`, `yesno`, `text`), формул KaTeX, таблицы вердикта, пошагового решения и линейки по изображениям архивных задач.

---

## 2. Почему ручная поштучная адаптация в `astroprak` работала посредственно

1. **Урезанный `astroplot.js`**: при переносе `Plot.tsx` в `data/tasks/_shared/astroplot.js` пропали поддержка треков звёзд (`segments`), сферической поправки $\cos\delta$ (`spherical: true`), полых маркеров второй компоненты (`marker: 'ring'`), многосерийного поиска экстремума (`nearestSeries` — искал только в `series[0]`) и измерения наклонов/полных длин отрезков (осталась только проекция $\Delta t$ на ось X).
2. **Утрата олимпиадной проверки и пошаговых решений**: при ручном переписывании `generator.py` под каждую задачу терялись проверка значащих цифр (`precision_excessive`), проверка погрешностей `±σ` (`number_with_error`), поля `yesno` и самое главное — **пошаговый авторский разбор (`solution_template`)** с подставленными числами конкретного `seed`.
3. **Зависимость от `numpy`**: все генераторы `astrosim` используют `numpy`, которого по умолчанию нет в `services/core/pyproject.toml` нового сайта `astroprak`.

---

## 3. Архитектура библиотеки совместимости

В `/data/tasks/_shared/` добавляются 4 компонента (а существующий `astroplot.js` обновляется до v2.0 с полной обратной совместимостью):

- **`/data/tasks/_shared/astrosim/`** — оригинальный пакет `astrosim` целиком без правок кода задач.
- **`/data/tasks/_shared/np_compat.py`** — автоматический чисто-питоновский полифилл для подмножества NumPy, используемого в `astrosim`. Если в контейнере установлен `numpy`, используется он; если нет — `np_compat` прозрачно регистрируется в `sys.modules["numpy"]` без пересборки Docker-образа.
- **`/data/tasks/_shared/legacy_adapter.py`** — серверный мост:
  - `generate_legacy_task(task_id, seed)` вызывает `astrosim` и формирует публичный пакет для `astroprak` (без утечки `truth`, `key` и `solution` до сдачи).
  - `grade_legacy_task(task_id, seed, answers)` выполняет проверку по правилам ВсОШ (`grade_fields` + поддержка `choice`/`text`), возвращает `details` для протокола в админ-панели учителя (`/admin`) и раскрывает `verdict` + пошаговое решение `solution_steps` + `solution_results` для виджета ученика после сдачи.
- **`/data/tasks/_shared/astroplot.js` (v2.0) + `legacy_widget.js` + `legacy_widget.css`** — клиентский движок, который внутри `<iframe>` автоматически рендерит условие, формулы и индексы, график со всеми инструментами (`segments`, `spherical`, `ring`, `extremum`, `segment`, `loupe`), таблицу «Снятые значения» (с автосохранением отметок в `_marks`), универсальный бланк ответов (`number`, `number_with_error`, `yesno`, `choice`, `text`), а для архивных задач — масштабируемые рисунки с пиксельной линейкой (`FigurePanel`). После сдачи выводит таблицу «Вердикт» и полный пошаговый «Разбор задачи».

---

## 4. Способы подключения и загрузки задач (включая 3-файловые ZIP)

### Вариант А: Модульная установка через том `data/tasks/` (режим `shared`)
1. Скопируйте содержимое `data/tasks/_shared/` и папки задач `data/tasks/<task_id>/` в директорию `data/tasks/` вашего сервера `astroprak`.
2. В админ-панели `/admin` нажмите **«⟳ Пересканировать хранилище»** (или загрузите любой легковесный 1.5 КБ архив из `zip_bundles_shared/<task_id>.zip`).

### Вариант Б: Прямая загрузка автономных 3-файловых ZIP через веб-админку (режим `hybrid`)
Архивы в папке `zip_bundles_hybrid/<task_id>.zip` содержат **ровно 3 файла** (`manifest.json`, `generator.py`, `widget.html`) и работают по гибридной схеме:
- если на сервере уже есть `/data/tasks/_shared/legacy_adapter.py`, пакет использует общую библиотеку;
- если архив загружен через веб-форму **«Загрузка пакета (.zip)»** в `/admin` на совершенно чистый сервер `astroprak`, `generator.py` автоматически распаковывает встроенный микро-рантайм `astrosim` в кэш и работает сразу без ручного копирования файлов на сервер и без пересборки контейнеров.

### Пересборка пакетов скриптом `pack_legacy_tasks.py`
```bash
python3 tools/pack_legacy_tasks.py \
  --astrosim-dir /path/to/astrosite_base/packages/astrosim/astrosim \
  --shared-src /path/to/data/tasks/_shared \
  --tasks-out /path/to/astroprak/data/tasks \
  --zips-out /path/to/output_zips \
  --mode hybrid
```
