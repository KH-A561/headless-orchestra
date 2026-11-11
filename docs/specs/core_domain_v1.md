# ТЗ: нейтральное ядро v1 (доменная модель + адаптеры)

Статус: к реализации. Исполнитель: агент `deepseek`. Ревью: архитектор + владелец.
Обязательно прочитать: `docs/DECISIONS.md` (разделы «DAW-agnostic core», «Libraries stay behind
boundaries», «Open questions»).

## 0. Цель и границы

Убрать из ядра модель ноты Producer Pal (`api_layer.models.Note`: строки `"C3"`, `"1|2.5"`) и
Ableton-специфику. Ядро работает с нейтральной моделью; всё про Live — в адаптере Ableton, всё про
`.mid` — в файловом адаптере; music21 — только внутри гармонического анализатора.

**Это рефакторинг с сохранением поведения.** Числа анализа (ритм, гармония) на всех существующих
фикстурах не меняются. Меняются только типы на входе и, где явно сказано ниже, форматы вывода.

**Вне скоупа:** граф v2, аудио, новые анализы, перебор интерфейса адаптера «на вырост»,
микротональность/точные дроби (это открытые вопросы в DECISIONS.md — не решать).

## 1. Доменная модель — `agents/agents/domain.py`

```python
class NoteEvent(BaseModel, frozen=True):
    pitch: int                 # MIDI 0..127
    start: float               # в четвертях от начала клипа (может быть < 0 — не отбрасывать)
    duration: float            # в четвертях, >= 0
    velocity: float            # 0..127, дробная допустима
    probability: float = 1.0
    mute: bool = False

class TimeSignature(BaseModel, frozen=True):
    numerator: int
    denominator: int
    # beats_per_bar = numerator (как сейчас; compound-размеры — известное ограничение)

class ClipRef(BaseModel, frozen=True):
    id: str                    # непрозрачен для ядра: "ableton:t7/s8", "file:<path>#all", "file:<path>#t0"
    track_name: str
    clip_name: str

class ClipData(BaseModel, frozen=True):
    ref: ClipRef
    notes: tuple[NoteEvent, ...]           # все ноты клипа, позиции от начала клипа
    window: tuple[float, float] | None     # петля/маркеры; None — границ нет (файл)
    time_signature: TimeSignature
    tempo_bpm: float | None
    pad_map: dict[int, str] | None         # None — инструмент не «кит»; {} — кит без имён

class ClipSummary(BaseModel, frozen=True):
    ref: ClipRef
    length: float | None
    is_playing: bool | None
    has_kit: bool
```

Функции ядра (там же):
- `windowed(clip, region: Literal["loop","clip"]) -> WindowedClip` — единственное место, где
  считается окно. `WindowedClip`: `notes` (сдвинутые к 0 для `"loop"`, без muted), `length`
  (`window[1]-window[0]` или `None`), счётчики `total`, `in_region`, `outside_region`, `muted_skipped`,
  `probability_below_1`, `pitches_without_pad` (только если `pad_map is not None`, иначе `[]`).
  Логика и порядок подсчёта — **ровно как сейчас в `clip_source.load_clip`**. `"loop"` при
  `window is None` → то же, что `"clip"`.
- `pitch_name(midi: int, convention: Literal["scientific","ableton"] = "scientific") -> str` —
  scientific: C4 = 60; ableton: C3 = 60. Диезы как сейчас.
- `beats_per_bar(ts) -> int`.

## 2. Адаптеры — `agents/agents/adapters/`

```python
class DawAdapter(Protocol):          # adapters/base.py
    def list_clips(self, query: str = "") -> list[ClipSummary]: ...
    def read_clip(self, ref_id: str) -> ClipData: ...
```
Больше методов не добавлять (аудио добавит своё ТЗ).

### 2.1 `adapters/ableton.py` — `AbletonAdapter(bridge: LiveBridge | None = None)`
- Переносит логику `clip_source.py` (`get_session_snapshot`, `get_track_info`, `get_clip_info`,
  `get_clip_notes`, `get_drum_pads`) и `find_midi_clips` из `mcp_server.py`.
- `ref_id` формата `ableton:t{track_index}/s{clip_index}`; разбор с понятной ошибкой на мусор.
- `window`: `(loop_start, loop_end)` если `looping`, иначе `(start_marker, end_marker)`.
- `pad_map`: Drum Rack (`class_name == "DrumGroupDevice"`) → `{note: name}`; нет кита → `None`.
- `velocity` — **без округления** (float как пришла). `mute`, `probability` — как пришли.
- `live_bridge.py` остаётся как есть (переместить в `adapters/` допустимо, белый список не трогать).
- `clip_source.py` удалить (логика переехала).

### 2.2 `adapters/midi_file.py` — `MidiFileAdapter(path, track: int | None = None, skip_drum_channel: bool | None = None)`
- Переносит загрузку из `scripts/analyze_midi_file.py` (mido, сырые тики, первый time_signature,
  первый set_tempo, track_name, логика `skip_drum_channel` как сейчас).
- **Новое: реальные длительности.** Пары note_on → ближайший последующий note_off / note_on vel 0
  того же питча и канала. Незакрытая нота → длительность до конца трека.
- `list_clips` → один `ClipSummary`; `read_clip` → `ClipData` с `window=None`, `pad_map=None`.
- `ref_id`: `file:<path>#all` или `file:<path>#t<N>`.

## 3. Миграция потребителей на `NoteEvent`

- **`rhythm_analyzer.run_deterministic_rhythm_analysis(notes: Sequence[NoteEvent], ...)`.**
  Убрать `parse_start_to_beats`/`pitch_to_midi` из анализатора. Новый параметр
  `pitch_names: Literal["scientific","ableton"] = "scientific"` для `LaneAnalysis.pitch_name`.
  `VelocityStats.min/max` → `float`.
  **`routing.source`:** добавить значение `"hint"` и параметр `material_hint: Literal["percussion","pitched"] | None = None`.
  При `material="auto"` и заданном `material_hint` → `material = hint`, `source = "hint"`.
  `"explicit"` — только когда материал задан явно.
- **`chord_grouping` / `harmony_pipeline`:** вход `Sequence[NoteEvent]`. music21-специфика
  остаётся внутри `functional_labeling`. В выводе `raw_notes` → `NoteEvent.model_dump()`;
  в `chord_events[*].notes` — `pitch` числом, `start` в четвертях (без строк Ableton).
  Ключ `time` (строка `bar|beat`) сохранить — это формат отображения, генерировать из float.
- **`mcp_server.py`:** работает через `AbletonAdapter` + `windowed()`. **Формат ответов инструментов
  не меняется**, кроме: `pitch_name` по настройке (env `HO_PITCH_NAMES`, по умолчанию `scientific`),
  `routing.source = "hint"` при наличии кита. Material: `material_hint="percussion"` если
  `pad_map is not None`; `context.material_reason` остаётся как сейчас.
  **Компактный вид:** у `ACCENTS`/`GHOST_NOTES` вместо полного `positions` — `count` и
  `positions_head` (первые 8); полный список только при `detail=True`.
- **Харнесс `scripts/analyze_midi_file.py`:** через `MidiFileAdapter`; новый флаг
  `--pitch-names {scientific,ableton}` (по умолчанию `scientific`). Остальные флаги и поведение — как сейчас.

## 4. Уборка (в этой же задаче)

- Удалить legacy на Producer Pal: `agents/agents/harmony_analyzer.py`, `agents/agents/workflows/`,
  ручные скрипты `agents/test_anthropic.py`, `agents/test_connection.py`, `agents/test_harmony_agent.py`.
  (История в git; граф v2 будет написан заново на ядре.)
- Убрать `api-layer` из зависимостей `agents/pyproject.toml`; `poetry lock` + `poetry install`.
  Каталог `api-layer/` не трогать (заморожен).
- `agents/pyproject.toml`: `[tool.pytest.ini_options] testpaths = ["tests"]`.
- Удалить корневой `pyproject.toml` (невалидная секция workspace, пакетов нет) и каталог `shared/`
  (пустая заглушка). Корневой `.venv` **не трогать**.
- README: убрать упоминания Producer Pal/`api-layer` как рабочего пути; установка — `poetry install`
  внутри `agents/`.

## 5. Тесты

- Все существующие тесты переводятся на `NoteEvent` **механически**. Утверждения о числах не менять.
  Разрешённые изменения утверждений — только:
  (а) ожидаемые `pitch_name` в научной нотации (или передать `pitch_names="ableton"` и оставить как было);
  (б) `routing.source == "hint"` там, где был кит и `material="auto"` в MCP-тестах;
  (в) тип velocity (int → float) в сравнениях.
  Любое другое изменение утверждения — остановиться и спросить.
- Реальный клип `real_2_twin_peaks_drums.mid`: все числа таблицы из `rhythm_analyzer_v1.md` §6.1 —
  без изменений.
- Новые тесты: `windowed()` (окно, сдвиг, счётчики, `pad_map=None` → `pitches_without_pad == []`);
  `pitch_name` в обеих конвенциях (60, 36, 0, 127); `MidiFileAdapter` длительности (note_off,
  note_on vel 0, незакрытая нота); разбор `ref_id` (валидный/мусор); `material_hint`;
  компактные `ACCENTS` (больше 8 позиций → `count` + 8 в `positions_head`).
- Проверка границы: тест, что в `agents/agents/` (кроме `adapters/ableton.py` и `live_bridge.py`)
  нет строк `"get_clip_notes"`, `"DrumGroupDevice"`, и нигде нет `import api_layer`.

## 6. Приёмка
- `cd agents; poetry install; poetry run pytest -v` (без пути — работает `testpaths`) — зелёный.
- Количество тестов ≥ текущих 76 минус удалённые legacy (их нет в `tests/`) плюс новые.
- Отчёт по формату агента; отдельно перечислить каждое изменённое утверждение в тестах с пунктом (а)/(б)/(в).

## 7. Не решать самому
Дополнительные методы адаптера, изменения белого списка моста, точные дроби/микротональность,
изменение формата ответов MCP сверх перечисленного — остановиться и спросить.
