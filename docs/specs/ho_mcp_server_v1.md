# ТЗ: MCP-сервер Headless Orchestra v1 (анализ клипов из живого Live)

Статус: к реализации. Исполнитель: агент `deepseek`. Ревью: архитектор + владелец.

## 0. Цель и границы

Свой MCP-сервер, через который Claude может попросить: «найди клип» и «проанализируй клип».
Сервер **сам** читает данные из Live через мост `mcp-server-ableton-live` (Remote Script,
TCP 127.0.0.1:9877), прогоняет их через существующие детерминированные пайплайны
(`run_deterministic_rhythm_analysis`, `run_deterministic_harmony_analysis`) и возвращает
**компактные посчитанные факты**. Ноты через LLM-контекст не проходят — это главный смысл задачи.

**В скоупе:**
- `agents/agents/live_bridge.py` — минимальный read-only клиент сокета моста;
- `agents/agents/clip_source.py` — превращение данных клипа из Live в `list[Note]` + контекст;
- `agents/agents/mcp_server.py` — MCP-сервер (официальный Python SDK `mcp`, FastMCP) с двумя инструментами;
- зависимость `mcp` (последняя 1.x) в `agents/pyproject.toml`; скрипт `ho-mcp` в `[tool.poetry.scripts]`;
- тесты с фейковым мостом (локальный TCP-сервер в тесте), без Live;
- раздел в README: как подключить сервер в Claude Desktop.

**Вне скоупа (не делать):**
- любые команды, меняющие сет (запись, удаление, playback, выбор) — сервер строго read-only;
- клипы Arrangement view (мост не отдаёт их ноты), аудиоклипы;
- LLM-вызовы внутри сервера, `intent`, советы;
- изменения `rhythm_analyzer.py`, гармонического пайплайна и харнесса;
- `api-layer` (Producer Pal) — не трогать и не использовать.

## 1. Протокол моста (проверено по исходникам `ableton_live_mcp` 1.8.1)

- TCP, `ABLETON_HOST` (по умолчанию `127.0.0.1`), `ABLETON_PORT` (по умолчанию `9877`) из env.
- Запрос: один JSON-объект `{"type": "<command>", "params": {...}}`, UTF-8, без разделителя.
- Ответ: один JSON-объект. Читать чанками, пока буфер не распарсится как JSON
  (как в `ableton_live_mcp/connection.py::receive_full_response`).
  `{"status": "success", "result": {...}}` или `{"status": "error", "message": "..."}`.
- Мост принимает несколько клиентов одновременно; наш сервер открывает соединение на каждый вызов
  инструмента и закрывает его. Таймаут на команду: 15 с.

### 1.1 Белый список команд (жёстко в коде)
`get_session_snapshot`, `get_session_info`, `get_track_info`, `get_clip_notes`, `get_clip_info`,
`get_drum_pads`. Любая другая команда → `ValueError` **до** отправки. Тест на это обязателен.

### 1.2 Форматы ответов (реальные, сняты с сета владельца 10.11.2026)
- `get_session_snapshot` → `tempo`, `time_signature` ("4/4"), `tracks[]`: `index`, `name`,
  `type` ("midi"/"audio"), `clips` (кол-во), `devices` (имена).
- `get_track_info(track_index)` → `clip_slots[]`: `index`, `has_clip`, `clip{name,length,is_playing}`;
  `devices[]`: `index`, `name`, `class_name` (Drum Rack = `"DrumGroupDevice"`), `type`.
- `get_clip_notes(track_index, clip_index)` → `notes[]`: `pitch`, `start_time` (доли от начала клипа),
  `duration`, `velocity` (**float**, бывает 104.140625), `mute`, `probability`, `velocity_deviation`.
- `get_clip_info(track_index, clip_index)` → `length` (**= длина петли, не содержимого**),
  `looping`, `loop_start`, `loop_end`, `start_marker`, `end_marker`,
  `signature_numerator`, `signature_denominator`.
- `get_drum_pads(track_index, device_index)` → `pads[]`: `note`, `name` (только занятые пэды).

## 2. `live_bridge.py`

```python
class BridgeError(Exception): ...            # нет соединения / таймаут / status=error
class LiveBridge:
    def __init__(self, host: str | None = None, port: int | None = None, timeout: float = 15.0): ...
    def call(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
```
Сообщение `BridgeError` при отказе соединения должно подсказывать: Live запущен? В Settings →
Tempo & MIDI выбран Control Surface `AbletonMCP`? Модальный диалог в Live блокирует мост.

## 3. `clip_source.py`

```python
class ClipContext(BaseModel):
    track_index: int; track_name: str
    clip_index: int; clip_name: str
    tempo_bpm: float
    time_signature: str                  # из клипа (signature_*), иначе из сета
    beats_per_bar: int
    region: Literal["loop", "clip"]
    region_start: float; region_end: float | None   # в долях клипа; None для "clip"
    notes_total: int
    notes_in_region: int
    notes_outside_region: int
    notes_muted_skipped: int
    notes_with_probability_below_1: int
    has_drum_rack: bool
    pad_names: dict[int, str]            # пусто, если Drum Rack нет
    pitches_without_pad: list[int]       # питчи в анализируемых нотах, для которых нет пэда
    material_reason: str                 # почему выбран material (см. 3.3)

def load_clip(bridge: LiveBridge, track_index: int, clip_index: int,
              region: Literal["loop", "clip"] = "loop") -> tuple[list[Note], ClipContext, float | None]:
    """Возвращает (ноты для анализа, контекст, clip_length_beats для ритма или None)."""
```

### 3.1 Окно анализа
- `region="loop"`: окно `[loop_start, loop_end)` если `looping`, иначе `[start_marker, end_marker)`.
  В анализ идут ноты с `region_start <= start_time < region_end`; **позиции сдвигаются**:
  `pos = start_time - region_start`. `clip_length_beats = region_end - region_start`.
- `region="clip"`: все ноты, без сдвига, `clip_length_beats=None` (выведется по последней ноте).
- `notes_outside_region` — ноты, не попавшие в окно (для `"clip"` всегда 0).

### 3.2 Конвертация в `Note`
- `mute=True` → не анализировать, считать в `notes_muted_skipped`.
- `pitch` → `midi_to_ableton_pitch` (из `agents.midi_utils`).
- `start` → `beats_to_start(pos, beats_per_bar)`.
- `duration` → строка `"bars:beats"` из длительности в долях (поле пока не используется анализом,
  но формат валидный).
- `velocity` → `round()`, затем ограничить `1..127`.
- `probability` в анализ не идёт, только счётчик в контексте.

### 3.3 Пэды и материал
- Drum Rack = первое устройство трека с `class_name == "DrumGroupDevice"`. Если есть —
  `get_drum_pads` → `pad_names`, `pitches_without_pad`.
- `material` для ритма при `"auto"`: если Drum Rack есть → `"percussion"`,
  `material_reason="drum_rack_on_track"`; иначе передать `"auto"` в анализатор,
  `material_reason="heuristic"`. Явный `material` пользователя → как есть, `"explicit"`.
- `pad_names` передаются в ритм как `lane_names`.

## 4. Инструменты MCP (`mcp_server.py`)

Оба — read-only (`ToolAnnotations(readOnlyHint=True)`), возвращают JSON-строку.

### 4.1 `find_midi_clips(query: str = "")`
Список MIDI-клипов Session view. Для каждого MIDI-трека (`type == "midi"`) с клипами —
`get_track_info`. Фильтр: подстрока `query` (без учёта регистра) в имени трека **или** клипа;
пустой `query` → все. Элемент: `track_index`, `track_name`, `clip_index`, `clip_name`,
`length`, `is_playing`, `has_drum_rack`. Плюс в корне `tempo`, `time_signature`.

### 4.2 `analyze_clip(track_index: int, clip_index: int, analysis: "rhythm"|"harmony"|"both" = "both", region: "loop"|"clip" = "loop", material: "auto"|"percussion"|"pitched" = "auto", detail: bool = False)`
Ответ:
```json
{"context": {...ClipContext...},
 "rhythm": {...} | null,
 "harmony": {...} | null,
 "errors": {"harmony": "No notes to analyze"}}
```
- Если в окне 0 нот → анализов нет, `errors` объясняет, `context` всё равно возвращается.
- Ошибка одного анализа (`ValueError`) не валит другой — пишется в `errors`.
- **Компактный вид (`detail=False`)**, цель — до ~4 КБ на типичный клип:
  - rhythm: `routing`, `clip_length_beats`, `clip_length_inferred`, `observations`,
    и по лейнам только `lane_id`, `label`, `pitch_name`, `count`, `interval_mean`, `interval_cv`,
    `timing.dev_mean`, `timing.dev_std`, `timing.swing_ratio`, `velocity.min/max/median`, `hits_per_bar`;
  - harmony: `key`, `key_confidence`, `tonal_mode`, `tonal_mode_reason`, и по событиям только
    `nominal_pos`, `roman_numeral`, `function`, флаги.
  - Никаких `onsets`, `intervals`, `raw_notes`, `buckets` в компактном виде.
- `detail=True` → полные `model_dump()` обоих результатов.
- Все числа float в ответе округлять до 4 знаков (на этапе сериализации).

## 5. Тесты (`agents/tests/test_live_bridge.py`, `test_clip_source.py`, `test_mcp_server.py`)

Фейковый мост: pytest-фикстура поднимает `socketserver.TCPServer` на `127.0.0.1:0` в потоке,
отвечает по словарю `{command: result}` и записывает полученные команды. Инструменты MCP
тестировать вызовом функций-обработчиков напрямую (не через stdio).

### 5.1 Фикстура A — реальный клип «8-Drum Rack 1» (петля 0–4, 9 нот, 4 вне петли)
`get_clip_info`: `{"length": 4.0, "looping": true, "loop_start": 0.0, "loop_end": 4.0, "start_marker": 0.0, "end_marker": 4.0, "signature_numerator": 4, "signature_denominator": 4}`
`get_clip_notes` (все pitch 36, velocity 100.0, mute false, probability 1.0), `start_time`:
`0.0, 0.9101343968531469, 1.838241185897436, 2.7663487554112556, 3.7124289772727272,
4.874187791375292, 5.8921609640359645, 6.874187531218781, 7.874187531218781`.
Трек: devices `[{"index":0,"name":"Velocity","class_name":"MidiVelocity"},{"index":1,"name":"Drum Rack","class_name":"DrumGroupDevice"}]`;
пэды `[{"note":36,"name":"DBL BASS B-1"},{"note":37,"name":"DBL BASS C-2"},{"note":38,"name":"FR BASSMUTEA"},{"note":39,"name":"FR BASHAR A3"}]`.

Ожидания (`region="loop"`): `notes_total=9`, `notes_in_region=5`, `notes_outside_region=4`,
`has_drum_rack=true`, `material_reason="drum_rack_on_track"`, лейн `36` с `label="DBL BASS B-1"`,
`clip_length_beats=4.0`, `clip_length_inferred=false`.
`region="clip"`: `notes_in_region=9`, `notes_outside_region=0`, `clip_length_inferred=true`, 2 такта.

### 5.2 Фикстура B — реальная петля «8-Drum Rack 2» (петля начинается не с 0)
`get_clip_info`: `looping true`, `loop_start 53.45095815642691`, `loop_end 55.875`, `start_marker 53.45095815642691`, `end_marker 79.90760385447885`, 4/4.
Ноты (pitch, start_time, velocity, probability):
внутри петли — `(38, 53.45095815642691, 104.140625, 1.0)`, `(37, 53.847051646270394, 77.0, 0.5)`,
`(36, 54.1875, 102.0, 1.0)`, `(38, 54.509809201215454, 72.0, 1.0)`, `(39, 54.86459816225441, 100.0, 1.0)`,
`(38, 55.21440928862804, 87.0, 1.0)`, `(37, 55.56623844905095, 81.0, 0.5)`;
вне петли — `(36, 55.89501982392608, 100.0, 1.0)`, `(37, 53.14393158924409, 100.0, 1.0)`,
`(38, 52.74783783924409, 100.0, 1.0)`, `(40, 28.28447594072594, 100.0, 1.0)`.
Пэды — как в A.

Ожидания (`region="loop"`): `notes_in_region=7`, `notes_outside_region=4`,
`notes_with_probability_below_1=2`, первая нота окна на позиции `0.0` (сдвиг сработал),
velocity первой ноты `104`, `clip_length_beats≈2.4240` (±1e-4), `pitches_without_pad=[]`.
`region="clip"`: `pitches_without_pad=[40]`.

### 5.3 Остальное
- белый список: `LiveBridge.call("delete_track")` → `ValueError`, фейковый мост ничего не получил;
- мост вернул `status=error` → `BridgeError` с текстом сообщения;
- порт закрыт → `BridgeError` с подсказкой про Control Surface;
- muted-нота не анализируется и считается в `notes_muted_skipped`;
- трек без Drum Rack → `has_drum_rack=false`, `pad_names={}`, `material_reason="heuristic"`;
- `find_midi_clips("drum")` возвращает клипы только с треков/клипов, где есть «drum» в имени;
  аудиотреки не опрашиваются (`get_track_info` для них не вызывался);
- компактный `analyze_clip` на фикстуре B: в JSON нет ключей `onsets`, `raw_notes`, `buckets`;
  длина ответа < 4096 символов;
- окно без нот → `errors` заполнен, `rhythm`/`harmony` = null, исключения нет.

## 6. Подключение (README)
Описать запись для `claude_desktop_config.json` → `mcpServers`:
`"headless-orchestra": {"command": "<путь к python из poetry env agents>", "args": ["-m", "agents.mcp_server"]}`
(или через скрипт `ho-mcp`) и что мост `mcp-server-ableton-live` должен быть установлен и выбран
Control Surface. Как получить путь: `cd agents; poetry env info --path`.

## 7. Критерии приёмки
- `cd agents; poetry run pytest tests/ -v` — зелёный; старые 58 тестов не изменены.
- Ни одной команды вне белого списка в коде; сервер не импортирует ничего из `ableton_live_mcp`
  (свой маленький клиент, без зависимости от чужого пакета).
- Отчёт по формату агента. Ручную проверку на живом Live агент **не** делает — её сделает архитектор.

## 8. Не решать самому
Arrangement-клипы, запись в сет, кэширование, долгоживущие соединения, изменение моделей
`rhythm_analyzer`/гармонии, новые коды наблюдений — остановиться и спросить.
