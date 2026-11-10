# ТЗ: RhythmAnalyzer v1 (детерминированный слой)

Статус: к реализации. Исполнитель: агент `deepseek`. Ревью: архитектор + владелец.
Контекст и мотивация: `docs/rhythm_analyzer_notes.md` (прочитать целиком до начала).

## 0. Цель и границы

Добавить детерминированный ритмический анализ MIDI-клипа: лейны, интервалы и циклы, отклонения
от сетки (свинг / сдвиг / разброс), velocity, плотность по тактам. Всё выдаётся как **нейтральные
наблюдения с числом и confidence**, без оценок «правильно/неправильно».

**В скоупе:**
- новый модуль `agents/agents/rhythm_analyzer.py` с точкой входа `run_deterministic_rhythm_analysis`;
- расширение офлайн-харнесса `agents/scripts/analyze_midi_file.py` (режим ритма, новые флаги, темп);
- тесты: синтетические фикстуры, собранные mido прямо в тестах, + реальный клип
  `agents/tests/midi/real_2_twin_peaks_drums.mid`.

**Вне скоупа (не делать):**
- LLM-слой, промпты, `intent`, советы — только детерминированные факты;
- интеграция в LangGraph-workflow и в `api-layer`;
- длительности нот (харнесс сейчас ставит всем `duration="1:0"` — оставить как есть);
- свинг 16-х, перебор периодов полиритмии, half-time, роли пэдов;
- любые изменения гармонического пайплайна и его поведения по умолчанию.

## 1. Принципы (обязательны)

1. Детерминированный слой сам всё классифицирует; LLM здесь не участвует.
2. Описывать, не предписывать. Код наблюдения — нейтральный факт (`CYCLE`, `LOOSE`), никогда
   `ERROR`/`WRONG`/`MISTAKE`. Текстовые описания тоже без оценок
   («клэп идёт циклом в 3 доли», а не «клэп не в сетке»).
3. Мало данных → наблюдение не выдаётся или выдаётся с низким confidence. Не угадывать.
4. Все пороги — в одном `RhythmConfig` (dataclass, frozen) с дефолтами из раздела 4.
   Никаких магических чисел в теле функций.

## 2. API модуля

```python
def run_deterministic_rhythm_analysis(
    notes: list[Note],
    beats_per_bar: int,
    *,
    clip_length_beats: float | None = None,
    material: Literal["percussion", "pitched", "auto"] = "auto",
    lane_names: dict[int, str] | None = None,
    config: RhythmConfig | None = None,
) -> DeterministicRhythmAnalysis: ...
```

- `notes` — тот же `api_layer.models.Note`, что и в гармонии. Позиция в долях:
  `chord_grouping.parse_start_to_beats`. MIDI-номер: `harmony_pipeline.pitch_to_midi`
  (конвенция Ableton, C3 = 60). Не писать свои конвертеры.
- Пустой `notes` → `ValueError`, как в гармонии.
- Доли = четверти, отсчёт от 0 с начала клипа. Compound-размеры (6/8) обрабатываются как сейчас
  в гармонии: долей в такте = числитель. Ограничение записать в docstring.

### 2.1 Модели результата (Pydantic)

Имена полей — как ниже; можно добавлять поля, нельзя переименовывать.

```python
class Observation(BaseModel):
    code: Literal["CYCLE", "SWING_8TH", "LAID_BACK", "PUSHED", "LOOSE", "UNQUANTIZED",
                  "UNIFORM_VELOCITY", "ACCENTS", "GHOST_NOTES", "EMPTY_BARS", "TRAILING_EMPTY"]
    lane_id: str | None          # None для наблюдений уровня клипа
    value: dict[str, Any]        # числа, на которых основано наблюдение
    confidence: float            # 0..1
    text: str                    # короткое нейтральное описание по-английски

class CycleInfo(BaseModel):
    interval_mean: float
    interval_cv: float
    period_beats: float          # округлено до 0.5 доли
    aligns_with_bar: bool
    realign_bars: int            # через сколько тактов цикл снова совпадает с тактом

class TimingStats(BaseModel):
    dev_mean: float              # среднее знаковое отклонение от ближайшей 16-й, в долях
    dev_std: float               # population std
    unquantized_ratio: float
    buckets: dict[int, BucketStats]   # 0..3 = позиция 16-й внутри доли; только непустые
                                      # BucketStats: count, dev_mean, dev_std

class VelocityStats(BaseModel):
    min: int; max: int; median: float; mean: float; std: float

class LaneAnalysis(BaseModel):
    lane_id: str                 # "all" или str(midi_pitch)
    pitch: int | None
    pitch_name: str | None       # Ableton-имя, например "C1"
    label: str | None            # из lane_names
    onsets: list[float]
    count: int
    intervals: list[float]
    cycle: CycleInfo | None
    timing: TimingStats
    velocity: VelocityStats
    hits_per_bar: list[int]

class RoutingInfo(BaseModel):
    material: Literal["percussion", "pitched"]
    source: Literal["explicit", "auto"]
    monophonic_ratio: float
    distinct_pitches: int
    chromatic_neighbor_ratio: float

class DeterministicRhythmAnalysis(BaseModel):
    beats_per_bar: int
    clip_length_beats: float
    clip_length_inferred: bool
    routing: RoutingInfo
    lanes: list[LaneAnalysis]    # первым всегда "all", дальше по возрастанию pitch
    observations: list[Observation]
```

## 3. Алгоритмы

### 3.1 Онсеты и длина клипа
- Онсет = (позиция в долях, midi_pitch, velocity) на каждую ноту.
- `clip_length_beats` задан → используется, `clip_length_inferred=False`.
- Не задан → `ceil((last_onset + 1e-9) / beats_per_bar) * beats_per_bar`,
  `clip_length_inferred=True`. Онсет ровно на границе такта начинает следующий такт.
- Онсеты за пределами заданной длины клипа: не отбрасывать, добавить предупреждение в лог
  (`logger.warning`), такты считать по фактической длине.

### 3.2 Роутинг (материал)
Признаки считаются всегда, решение `auto` — только если `material="auto"`:
- **monophonic_ratio**: онсеты группируются в «события» по допуску `simultaneity_tol`
  (сортировка по времени; онсет входит в текущую группу, если он не дальше `simultaneity_tol`
  от **первого** онсета группы). Доля групп, где ровно один уникальный питч.
- **distinct_pitches**: число уникальных питчей.
- **chromatic_neighbor_ratio**: доля уникальных питчей, у которых в наборе есть сосед ±1 полутон.
- `auto` → `percussion`, если `monophonic_ratio >= routing_mono_min` **и**
  `chromatic_neighbor_ratio >= routing_chrom_min`; иначе `pitched`.

Это эвристика-гипотеза: признаки обязательно попадают в результат, чтобы потом калибровать.

### 3.3 Лейны
- Лейн `all`: все онсеты, всегда.
- `percussion`: дополнительно по лейну на каждый уникальный питч.
- `pitched`: только `all`.
- `pitch_name` через существующую функцию харнесса `midi_to_ableton_pitch` — если импорт из
  `scripts` в `agents` создаёт неправильную зависимость, перенести функцию в `agents/agents/`
  и импортировать её в харнессе оттуда (без изменения поведения).

### 3.4 Интервалы и циклы
Для каждого лейна: `intervals` = разности соседних онсетов (по сортированным позициям).
Цикл определяется, если `len(intervals) >= cycle_min_intervals` и
`cv = pstdev(intervals) / mean(intervals) <= cycle_cv_max`:
- `period_beats = round(mean * 2) / 2` (**среднее, не медиана** — медиана на реальном клипе
  уводит период 44-го пэда на 3.5);
- в полудолях: `h = period_beats*2`, `b = beats_per_bar*2`;
  `aligns_with_bar = (b % h == 0) or (h % b == 0)`; `realign_bars = lcm(h, b) / b`;
- `confidence = 1 - cv / cycle_cv_max`, округлить до 2 знаков;
- наблюдение `CYCLE` с `value={"period_beats", "realign_bars", "aligns_with_bar", "interval_cv"}`.
  Текст для невыравненного: `"repeats every 3.0 beats against 4/4, realigns every 3 bars"`.

### 3.5 Тайминг
Для онсета: `frac = pos - floor(pos)`; ближайшая 16-я `g = round(frac*4)/4`;
`dev = frac - g` (знак: + позже сетки); корзина `round(frac*4) % 4`.
`buckets` всегда считаются по сырому `dev`.

Для лейна с `count >= timing_min_onsets` (иначе статистика считается, но наблюдений нет),
**строго в этом порядке**:
1. `SWING_8TH`: кандидаты — онсеты с `frac` в `[swing_window_lo, swing_window_hi]`.
   Нужно `>= swing_min_onsets` кандидатов, `pstdev(frac кандидатов) <= swing_std_max` и
   `mean(frac) >= swing_ratio_min`. `value={"ratio": mean_frac}`; если
   `|ratio - 2/3| <= 0.03`, текст отмечает `triplet feel`.
   Свинг считается по позиции внутри доли, а **не** по корзинам 16-х
   (при сильном свинге запоздавшая 8-я ближе к следующей 16-й).
2. **Остаточные отклонения** `res`: если свинг найден, для кандидатов свинга
   `res = frac - ratio`, для остальных `res = dev`; если свинга нет, `res = dev`.
   Свинг — это структура, а не разброс: он не должен делать лейн «рыхлым» или «неквантованным».
   `TimingStats.dev_mean` / `dev_std` / `unquantized_ratio` считаются по `res`;
   в `TimingStats` добавить `swing_ratio: float | None`.
3. `UNQUANTIZED`, если доля `|res| > unquantized_dev` ≥ `unquantized_ratio_min`.
   Если сработало — пункты 4–5 для лейна **не выдаются**.
4. `LAID_BACK` (`dev_mean > 0`) / `PUSHED` (`dev_mean < 0`), если
   `|dev_mean| >= shift_min` **и** `|dev_mean| >= dev_std`.
5. `LOOSE`, если `dev_std >= loose_std_min`.

Confidence для 1–4: `min(1, count / timing_conf_full)` — растёт с числом ударов.

### 3.6 Velocity
Для лейна с `count >= velocity_min_onsets`:
- `UNIFORM_VELOCITY`, если `max - min <= uniform_range_max`;
- `ACCENTS`: онсеты с `v >= median * accent_ratio`; `value={"positions": [...]}`;
- `GHOST_NOTES`: онсеты с `v <= median * ghost_ratio`; `value={"positions": [...]}`.
Пороги относительно медианы лейна, не абсолютные.

### 3.7 Плотность и форма (уровень клипа, `lane_id=None`)
- `hits_per_bar` для каждого лейна (длина = числу тактов клипа).
- `EMPTY_BARS`: такты (1-based) без единого онсета в лейне `all`, кроме хвостовых.
- `TRAILING_EMPTY`: число пустых тактов после последнего онсета. **Только если
  `clip_length_inferred=False`** (при выведенной длине хвоста быть не может по построению).

## 4. Дефолты `RhythmConfig`

| Параметр | Значение | | Параметр | Значение |
|---|---|---|---|---|
| simultaneity_tol | 0.06 | | swing_window_lo / hi | 0.45 / 0.72 |
| routing_mono_min | 0.75 | | swing_min_onsets | 3 |
| routing_chrom_min | 0.5 | | swing_std_max | 0.03 |
| cycle_min_intervals | 3 | | swing_ratio_min | 0.53 |
| cycle_cv_max | 0.15 | | timing_conf_full | 16 |
| timing_min_onsets | 4 | | velocity_min_onsets | 4 |
| unquantized_dev | 0.08 | | uniform_range_max | 2 |
| unquantized_ratio_min | 0.5 | | accent_ratio | 1.15 |
| shift_min | 0.02 | | ghost_ratio | 0.6 |
| loose_std_min | 0.03 | | | |

## 5. Харнесс `analyze_midi_file.py`

- Новый аргумент `--analysis {harmony,rhythm,both}`, по умолчанию `harmony`.
  **Поведение и вывод в режиме `harmony` не меняются** (включая JSON).
- Новые аргументы (влияют только на ритм): `--clip-bars N` (→ `clip_length_beats = N * beats_per_bar`),
  `--material {auto,percussion,pitched}` (по умолчанию `auto`),
  `--lane-names PATH` (JSON `{"36": "bass chop"}` → `dict[int, str]`; неверный файл → понятная ошибка).
- `load_midi_notes` получает keyword-параметр `skip_drum_channel: bool | None = None`
  (`None` = текущее поведение). Для ритма передавать `False`: ударные не выкидывать.
- `MidiLoadResult` получает поле `tempo_bpm: float | None` — первое `set_tempo`, иначе `None`.
  Печатать в отчёте как `Tempo: 141.0 BPM` или `Tempo: unknown (no tempo meta)`.
- Печатать `track_name` (первое meta `track_name`), если есть: дешёвый контекст.
- Текстовый отчёт ритма: шапка (файл, размер, темп, длина клипа + `inferred`, роутинг с признаками),
  таблица лейнов (lane, name/label, count, interval_mean, cv, dev_mean, dev_std, velocity min–max),
  hits per bar, список наблюдений с confidence.
- `--json`: `rhythm` → `DeterministicRhythmAnalysis.model_dump()`;
  `both` → `{"harmony": ..., "rhythm": ...}`; `harmony` — как сейчас.

## 6. Тесты (`agents/tests/test_rhythm_analyzer.py` + дополнения к тесту харнесса)

Синтетика строится через `mido` в `tmp_path` или напрямую списком `Note` — истина видна в коде.
Каждое наблюдение из раздела 3 — минимум один позитивный и один негативный тест.

Обязательные синтетические случаи:
1. Ровные 16-е хэты, 1 такт, velocity одинаковая → нет `LOOSE`/`UNQUANTIZED`/`SWING_8TH`,
   есть `UNIFORM_VELOCITY`.
2. Клэп каждые 3 доли в 4/4 на 3 такта (позиции 0,3,6,9) → `CYCLE`, period 3.0,
   `realign_bars=3`, `aligns_with_bar=False`.
3. Бэкбит на 2 и 4 → `CYCLE` с period 2.0, `aligns_with_bar=True`.
4. 8-е со свингом 0.6 (доли на x.0, оффбиты на x.60), ≥4 оффбита → `SWING_8TH` ratio≈0.60,
   **и при этом нет `UNQUANTIZED` и `LOOSE`**; с 0.667 → текст `triplet feel`, тоже без `UNQUANTIZED`.
5. Все удары +0.03 доли от сетки → `LAID_BACK`, нет `LOOSE`.
6. Детерминированный джиттер ±0.05 (фиксированный список, не random) → `LOOSE`, нет `LAID_BACK`.
7. Удары ровно между 16-ми (x.125, x.375, x.625, x.875, ровно 8 ударов — по 2 на позицию; при 3+ ударах на x.625
   они бы законно прошли как свинг 0.625) → `UNQUANTIZED`,
   и при этом нет `LOOSE`/`LAID_BACK`/`SWING_8TH`.
   (Квинтоли для этого теста не годятся: у них далеко от 16-х только 2 из 5 позиций, 0.4 < 0.5.)
8. Акценты/гост-ноты относительно медианы лейна.
9. Пустой такт в середине → `EMPTY_BARS`; пустой хвост с `clip_length_beats` → `TRAILING_EMPTY`;
   тот же клип без длины → `clip_length_inferred=True`, нет `TRAILING_EMPTY`.
10. Аккорды (полифония) с `material="auto"` → `pitched`, единственный лейн `all`.
11. Меньше порогов (3 удара) → статистика есть, наблюдений тайминга/velocity нет.
12. Пустой `notes` → `ValueError`.

### 6.1 Реальный клип `real_2_twin_peaks_drums.mid` (эталон, посчитан заранее)
Файл: 4/4, PPQ 96, один трек, канал 0, 16 note-on, нет `set_tempo`, track_name
`2-twin_peaks [2026-07-14 142341] 1`. Запуск с `clip_length_beats=16`.
Сравнение float — с допуском `1e-3`, если не сказано иное.

| Проверка | Ожидание |
|---|---|
| tempo_bpm | `None` |
| routing (auto) | `percussion`; monophonic_ratio = 10/13 ≈ 0.769; distinct_pitches = 4; chromatic_neighbor_ratio = 0.5 |
| лейны | `all`, `36`, `41`, `42`, `44`; count 16 / 5 / 3 / 4 / 4 |
| лейн 42 | `CYCLE`: period 3.0, realign_bars 3, aligns False, interval_cv ≈ 0.043 (допуск 0.005), confidence ≈ 0.71 (±0.02) |
| лейн 44 | `CYCLE`: period 3.0, realign_bars 3, interval_cv ≈ 0.127 (±0.005), confidence ≈ 0.15 (±0.03) |
| лейны 36, 41 | нет `CYCLE` (cv ≈ 0.22 и 0.47) |
| hits_per_bar (all) | `[6, 4, 6, 0]` |
| форма | `TRAILING_EMPTY` = 1 такт; `EMPTY_BARS` нет |
| тайминг `all` | dev_std ≈ 0.039 (±0.003) → `LOOSE`; нет `UNQUANTIZED`, `SWING_8TH`, `LAID_BACK`, `PUSHED` |
| velocity | нет `UNIFORM_VELOCITY` ни в одном лейне |

Позиции в файле — тики/96 (например 2/96 = 0.0208); не округлять при загрузке.
Если реализация расходится с таблицей — **не подгонять пороги**, остановиться и сообщить
расчёт: таблица могла быть посчитана с ошибкой, это решает ревью.

### 6.2 Регрессия
Все существующие тесты `agents/tests/` проходят без изменений. Отдельный тест: вывод харнесса
в режиме по умолчанию (`harmony`) на `1_clean_functional.mid` не изменился по ключам JSON.

## 7. Критерии приёмки
- `cd agents; poetry run pytest tests/ -v` — зелёный, новые тесты покрывают разделы 3.2–3.7 и 6.1.
- `poetry run python scripts/analyze_midi_file.py tests/midi/real_2_twin_peaks_drums.mid --analysis rhythm --clip-bars 4`
  печатает отчёт, где видны оба `CYCLE` (42, 44), `LOOSE` и `TRAILING_EMPTY`.
- Ни одного кода/текста с оценочной лексикой (error, wrong, fix, should).
- Отчёт агента по формату из `.github/agents/deepseek.agent.md`.

## 8. Открытые вопросы, которые агент НЕ решает сам
Если по ходу появится потребность в чём-то из этого — остановиться и спросить:
длительности нот, свинг 16-х, изменение порогов, новые коды наблюдений, правки гармонического пайплайна.
