# AI Agents Theory & Implementation Guide

## Для кого этот документ

Для senior разработчиков, которые хотят понять **как работают AI агенты** на концептуальном и практическом уровне, чтобы не просто копировать код, а осознанно принимать архитектурные решения.

---

## Часть 1: Что такое AI Agent (концептуально)

### **Определение**

**AI Agent** — это программа, которая:
1. Воспринимает окружение (perceive)
2. Принимает решения (reason)
3. Выполняет действия (act)
4. **Итеративно повторяет** цикл до достижения цели

**Ключевое отличие от LLM:**
```
LLM:   prompt → [model] → response          (one-shot)
Agent: goal → [perceive → reason → act]* → goal achieved
```

---

### **Классификация агентов (Russell & Norvig, "AI: A Modern Approach")**

| Тип | Описание | Пример |
|-----|----------|--------|
| **Simple Reflex** | if-then rules | Термостат |
| **Model-Based Reflex** | Учитывает состояние мира | Робот-пылесос |
| **Goal-Based** | Планирует путь к цели | GPS навигатор |
| **Utility-Based** | Оптимизирует метрику | AlphaGo |
| **Learning** | Улучшается со временем | Рекомендательная система |

**Наш HarmonyAnalyzer = Goal-Based + Learning потенциально**

---

### **AI Agent в 2024-2026 (LLM Era)**

**Современный паттерн:**
```python
class AIAgent:
    def __init__(self, llm, tools):
        self.llm = llm          # Language model (Claude, GPT)
        self.tools = tools      # Functions agent can call
        self.memory = []        # Conversation history
        
    def run(self, goal):
        while not goal_achieved:
            # 1. Perceive: получить текущее состояние
            observation = self.perceive()
            
            # 2. Reason: LLM решает что делать
            thought = self.llm.generate(
                prompt=f"Goal: {goal}\nObservation: {observation}\nWhat to do next?"
            )
            
            # 3. Act: выполнить действие через tool
            action = self.parse_action(thought)
            result = self.tools[action.name](action.args)
            
            # 4. Update memory
            self.memory.append({
                "observation": observation,
                "thought": thought,
                "action": action,
                "result": result
            })
```

**Аналогия с Java:**
```java
// ReAct pattern (Reason + Act)
while (!goalAchieved) {
    State observation = environment.perceive();
    Action decision = llm.reason(observation, memory);
    Result outcome = environment.act(decision);
    memory.add(observation, decision, outcome);
}
```

---

## Часть 2: Frameworks для AI Agents

### **LangGraph (наш выбор)**

**Что это:**
- Библиотека от LangChain для **stateful multi-agent workflows**
- Graph-based execution (StateGraph)
- Built-in persistence, checkpointing, streaming

**Ключевые концепции:**

#### **1. State (состояние)**
```python
from typing import TypedDict, Annotated
from operator import add

class AgentState(TypedDict):
    messages: Annotated[list, add]  # История сообщений
    clip_data: dict                 # Данные клипа для анализа
    corrections: list               # Найденные проблемы
    next_agent: str                 # Кто следующий
```

**Annotated[list, add]** = reducer function
- При merge state: `new_messages = old + new` (append, не replace)

#### **2. Nodes (узлы графа)**
```python
def harmony_analyzer_node(state: AgentState):
    """Анализирует гармонию в клипе."""
    clip = state["clip_data"]
    
    # LLM анализ
    analysis = llm.invoke([
        ("system", "You are a music theory expert."),
        ("user", f"Analyze harmony in this clip: {clip}")
    ])
    
    # Обновляем state
    return {
        "messages": [analysis],
        "corrections": state["corrections"] + [find_issues(analysis)]
    }

def rhythm_analyzer_node(state: AgentState):
    """Анализирует ритм."""
    # Similar logic
    pass
```

**Node = функция, которая:**
- Принимает state
- Делает работу (LLM call, computation, tool call)
- Возвращает обновлённый state

#### **3. Edges (рёбра графа)**

**Обычный edge:**
```python
graph.add_edge("harmony_analyzer", "rhythm_analyzer")
# После harmony → всегда идём в rhythm
```

**Conditional edge:**
```python
def router(state: AgentState):
    """Решает, куда идти дальше."""
    if state["corrections"]:
        return "apply_corrections"
    else:
        return "finish"

graph.add_conditional_edges(
    "rhythm_analyzer",
    router,
    {
        "apply_corrections": "correction_agent",
        "finish": END
    }
)
```

#### **4. Полный пример графа:**
```python
from langgraph.graph import StateGraph, END

# Создаём граф
workflow = StateGraph(AgentState)

# Добавляем nodes
workflow.add_node("harmony_analyzer", harmony_analyzer_node)
workflow.add_node("rhythm_analyzer", rhythm_analyzer_node)
workflow.add_node("orchestrator", orchestrator_node)

# Добавляем edges
workflow.add_edge("harmony_analyzer", "orchestrator")
workflow.add_edge("rhythm_analyzer", "orchestrator")

# Conditional edge
workflow.add_conditional_edges(
    "orchestrator",
    should_continue,
    {
        "continue": "harmony_analyzer",  # Loop back
        "finish": END
    }
)

# Entry point
workflow.set_entry_point("harmony_analyzer")

# Compile
app = workflow.compile()

# Run
result = app.invoke({
    "messages": [],
    "clip_data": clip,
    "corrections": []
})
```

---

### **Альтернативы LangGraph:**

| Framework | Плюсы | Минусы | Когда использовать |
|-----------|-------|--------|-------------------|
| **LangGraph** | Stateful, graphs, checkpoints | Новый, меньше docs | Сложные workflows |
| **CrewAI** | Role-based, быстрый старт | Меньше контроля | Прототипы |
| **AutoGen** | Multi-agent conversations | Merged в MS framework | Legacy проекты |
| **Semantic Kernel** | Microsoft, C#/Python | Меньше AI focus | .NET экосистема |
| **Custom** | Полный контроль | Велосипед | Простые случаи |

---

## Часть 3: Наш HarmonyAnalyzer (конкретика)

### **Цель агента:**
Проанализировать MIDI clip и найти гармонические проблемы.

### **Архитектура:**

```
┌─────────────────────────────────────────┐
│  HarmonyAnalyzer Agent                  │
│  ┌───────────────────────────────────┐  │
│  │  1. Perception Layer              │  │
│  │  - Получить clip через API        │  │
│  │  - Извлечь ноты                   │  │
│  │  - Построить chord progression    │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │  2. Reasoning Layer (LLM)         │  │
│  │  - Claude API + music theory skill│  │
│  │  - Анализ harmony                 │  │
│  │  - Генерация suggestions          │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │  3. Action Layer                  │  │
│  │  - Применить corrections          │  │
│  │  - Обновить clip через API        │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

---

### **Пошаговый процесс:**

#### **Step 1: Perception (получение данных)**

```python
from api_layer.client import ProducerPalClient

class HarmonyAnalyzer:
    def __init__(self, client: ProducerPalClient):
        self.client = client
    
    def perceive(self, track_id: int, clip_id: int):
        """Получить и обработать MIDI данные."""
        # 1. Получить clip
        clip = self.client.get_clip(track_id, clip_id)
        
        # 2. Извлечь ноты
        notes = clip.notes  # List[Note]
        
        # 3. Построить chord progression
        chords = self._notes_to_chords(notes)
        
        # 4. Определить key
        key = self._detect_key(notes)
        
        return {
            "clip_id": clip_id,
            "notes": notes,
            "chords": chords,
            "key": key
        }
    
    def _notes_to_chords(self, notes):
        """Группировать ноты в аккорды."""
        # Группируем по времени start
        # Если несколько нот начинаются в одном месте → chord
        
        chords = []
        # TODO: implement chord detection
        return chords
    
    def _detect_key(self, notes):
        """Определить тональность."""
        # Алгоритм Krumhansl-Schmuckler
        # Или простой: посчитать частоту pitch classes
        
        pitch_classes = [note.pitch for note in notes]
        # TODO: implement key detection
        return "C major"  # placeholder
```

---

#### **Step 2: Reasoning (LLM анализ)**

```python
from anthropic import Anthropic

class HarmonyAnalyzer:
    def __init__(self, client: ProducerPalClient, anthropic_key: str):
        self.client = client
        self.llm = Anthropic(api_key=anthropic_key)
        self.skill = self._load_skill()
    
    def _load_skill(self):
        """Загрузить music theory skill."""
        with open("agents/skills/harmony_theory.md") as f:
            return f.read()
    
    def reason(self, perception):
        """Анализировать через Claude API."""
        prompt = f"""
You are a music theory expert analyzing a MIDI clip.

<music_theory_knowledge>
{self.skill}
</music_theory_knowledge>

<clip_data>
Key: {perception['key']}
Chord Progression: {perception['chords']}
Notes: {perception['notes']}
</clip_data>

Analyze the harmony and identify issues:
1. Voice leading problems
2. Parallel fifths/octaves
3. Unresolved dissonances
4. Awkward chord progressions

For each issue, provide:
- Description
- Location (bar:beat)
- Suggested fix
- Music theory explanation

Return JSON format:
{{
  "issues": [
    {{
      "type": "voice_leading",
      "location": "2|1",
      "description": "Large leap in soprano voice",
      "suggestion": "Move E4 to D4 instead of G4",
      "theory": "Minimize voice movement (Rule #1 from skill)"
    }}
  ]
}}
"""
        
        response = self.llm.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        # Parse response
        analysis = json.loads(response.content[0].text)
        return analysis
```

---

#### **Step 3: Action (применение изменений)**

```python
class HarmonyAnalyzer:
    def act(self, perception, analysis):
        """Применить corrections к clip."""
        track_id = perception["track_id"]
        clip_id = perception["clip_id"]
        
        # Для каждой correction
        for issue in analysis["issues"]:
            if issue["type"] == "voice_leading":
                # Применить исправление
                self._fix_voice_leading(
                    track_id,
                    clip_id,
                    issue["location"],
                    issue["suggestion"]
                )
    
    def _fix_voice_leading(self, track_id, clip_id, location, suggestion):
        """Применить конкретное исправление."""
        # 1. Получить текущие ноты
        clip = self.client.get_clip(track_id, clip_id)
        
        # 2. Найти ноту в location
        target_note = [n for n in clip.notes if n.start == location][0]
        
        # 3. Изменить pitch согласно suggestion
        # Parse "Move E4 to D4" → change pitch
        new_pitch = self._parse_suggestion(suggestion)
        target_note.pitch = new_pitch
        
        # 4. Обновить clip
        self.client.update_clip(track_id, clip_id, clip.notes)
```

---

### **Полный workflow с LangGraph:**

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class HarmonyAgentState(TypedDict):
    track_id: int
    clip_id: int
    perception: dict
    analysis: dict
    corrections_applied: bool

def perceive_node(state):
    """Node 1: Perception."""
    analyzer = HarmonyAnalyzer(client)
    perception = analyzer.perceive(state["track_id"], state["clip_id"])
    return {"perception": perception}

def reason_node(state):
    """Node 2: Reasoning."""
    analyzer = HarmonyAnalyzer(client, anthropic_key)
    analysis = analyzer.reason(state["perception"])
    return {"analysis": analysis}

def act_node(state):
    """Node 3: Action."""
    analyzer = HarmonyAnalyzer(client)
    analyzer.act(state["perception"], state["analysis"])
    return {"corrections_applied": True}

# Build graph
workflow = StateGraph(HarmonyAgentState)
workflow.add_node("perceive", perceive_node)
workflow.add_node("reason", reason_node)
workflow.add_node("act", act_node)

workflow.add_edge("perceive", "reason")
workflow.add_edge("reason", "act")
workflow.add_edge("act", END)

workflow.set_entry_point("perceive")
app = workflow.compile()

# Run
result = app.invoke({
    "track_id": 0,
    "clip_id": 0,
    "corrections_applied": False
})
```

---

## Часть 4: Skills — Music Theory Knowledge

**Skills** — это markdown файлы с знаниями, которые LLM читает для контекста.

### **Пример: `harmony_theory.md`**

```markdown
# Harmony Analysis Skill

## Voice Leading Rules

### Rule 1: Minimize Voice Movement
Each voice should move by the smallest possible interval.

Good:
C → D (step)
E → F (step)

Bad:
C → G (fifth leap)

### Rule 2: Avoid Parallel Fifths and Octaves
Parallel motion by perfect fifths or octaves between voices sounds hollow.

Example (BAD):
Soprano: C → D
Bass:    F → G  (parallel fifths)

### Rule 3: Resolve Tendency Tones
- Leading tone (7th scale degree) → Tonic
- 4th scale degree → 3rd scale degree

In C major:
B (leading tone) → C
F (subdominant) → E

## Common Chord Progressions

### Pop/Rock
- I - V - vi - IV (C - G - Am - F)
- I - IV - V - I (C - F - G - C)

### Jazz
- ii - V - I (Dm7 - G7 - Cmaj7)
- I - VI - ii - V (Cmaj7 - A7 - Dm7 - G7)

## Detection Algorithms

### Key Detection (Krumhansl-Schmuckler)
1. Count frequency of each pitch class
2. Correlate with major/minor key profiles
3. Highest correlation = detected key

### Chord Recognition
1. Group notes by start time (±16th note tolerance)
2. Extract pitch classes
3. Match against chord templates:
   - Major: [0, 4, 7]
   - Minor: [0, 3, 7]
   - Dominant 7th: [0, 4, 7, 10]
```

**LLM видит это и использует как справочник.**

---

## Часть 5: План Phase 2 (пошагово)

### **Milestone 1: Простой HarmonyAnalyzer (без LangGraph)**

**Цель:** Один файл, работающий агент.

**Задачи:**
1. Создать `agents/agents/harmony_analyzer.py`
2. Реализовать `perceive()` — получение clip
3. Реализовать `reason()` — Claude API call
4. Реализовать `act()` — применение изменений (опционально)
5. Написать `test_harmony_analyzer.py`

**Время:** 4-6 часов

---

### **Milestone 2: Music Theory Skill**

**Цель:** Создать knowledge base для LLM.

**Задачи:**
1. Создать `agents/agents/skills/harmony_theory.md`
2. Заполнить voice leading rules
3. Заполнить chord progressions
4. Добавить detection algorithms

**Время:** 2-3 часа

---

### **Milestone 3: LangGraph Integration**

**Цель:** Превратить в stateful workflow.

**Задачи:**
1. Установить `langgraph`
2. Создать `HarmonyAgentState`
3. Конвертировать методы в nodes
4. Построить граф
5. Тесты с checkpointing

**Время:** 3-4 часа

---

### **Milestone 4: Real-world Testing**

**Цель:** Протестировать на реальном Ableton проекте.

**Задачи:**
1. Создать test clip с известными проблемами
2. Запустить агента
3. Проверить suggestions
4. Применить corrections
5. Оценить качество

**Время:** 2 часа

---

## Часть 6: Теория — Паттерны AI Agents

### **ReAct Pattern (Reason + Act)**

Агент чередует рассуждение и действие:

```
Thought 1: I need to analyze the clip
Action 1: get_clip(track_id=0, clip_id=0)
Observation 1: Clip has 12 notes in C major

Thought 2: I notice parallel fifths between bars 2-3
Action 2: get_detailed_notes(location="2|1")
Observation 2: Soprano C5, Bass F3 moving to D5, G3

Thought 3: This is a parallel fifth, violates voice leading
Action 3: suggest_fix(move_soprano_to="B4")
Observation 3: Fix applied successfully
```

**Реализация:**
```python
while not done:
    thought = llm("What should I do next?")
    action = parse_action(thought)
    observation = execute(action)
    context += f"Thought: {thought}\nAction: {action}\nObservation: {observation}\n"
```

---

### **Plan-and-Execute Pattern**

Сначала план, потом выполнение:

```
1. Plan:
   Step 1: Analyze harmony
   Step 2: Analyze rhythm
   Step 3: Prioritize issues
   Step 4: Apply fixes

2. Execute each step
```

**Реализация:**
```python
# Planning phase
plan = llm("Create a plan to analyze this clip")

# Execution phase
for step in plan:
    result = execute_step(step)
    if result.failed:
        replan()
```

---

### **Tool Use Pattern**

Агент может вызывать функции (tools):

```python
tools = {
    "get_clip": lambda id: client.get_clip(id),
    "analyze_harmony": lambda notes: analyze(notes),
    "apply_fix": lambda fix: client.update_clip(fix)
}

# LLM decides which tool to use
response = llm("Which tool to use? {tools}")
tool_name = parse_tool(response)
result = tools[tool_name](args)
```

---

### **Multi-Agent Collaboration**

Несколько агентов работают вместе:

```
Orchestrator
├─> HarmonyAnalyzer (finds chord issues)
├─> RhythmAnalyzer (finds timing issues)
└─> PriorityAgent (decides what to fix first)
```

**Coordination patterns:**
- **Sequential:** A → B → C
- **Parallel:** A + B → C (merge results)
- **Hierarchical:** Manager delegates to workers

---

## Часть 7: Метрики качества агентов

Как измерить, что агент работает хорошо?

### **Accuracy Metrics:**
- **Precision:** Из найденных проблем, сколько реальных?
- **Recall:** Из всех проблем, сколько нашёл?
- **F1 Score:** Гармоническое среднее precision и recall

### **Quality Metrics:**
- **Suggestion Acceptance Rate:** Пользователь применяет fix?
- **Time Saved:** Быстрее ли чем вручную?
- **Error Rate:** Создаёт ли новые проблемы?

### **Cost Metrics:**
- **LLM API calls:** Сколько запросов к Claude?
- **Latency:** Время от запроса до результата
- **Token usage:** Сколько токенов используется

---

## Часть 8: Debugging AI Agents

### **Техники отладки:**

#### **1. Verbose logging**
```python
def reason(self, perception):
    print(f"[PERCEPTION] {perception}")
    
    response = llm(prompt)
    print(f"[LLM RESPONSE] {response}")
    
    analysis = parse(response)
    print(f"[ANALYSIS] {analysis}")
    
    return analysis
```

#### **2. Trace каждый шаг**
```python
trace = []
def node(state):
    trace.append({
        "node": "harmony_analyzer",
        "input": state,
        "timestamp": time.now()
    })
    result = process(state)
    trace.append({
        "node": "harmony_analyzer",
        "output": result,
        "timestamp": time.now()
    })
    return result
```

#### **3. Checkpointing (LangGraph)**
```python
# Сохраняет state после каждого node
checkpointer = MemorySaver()
app = workflow.compile(checkpointer=checkpointer)

# Можно восстановить из checkpoint
state = checkpointer.get(thread_id="123")
```

---

## Резюме

### **Ключевые концепции:**
1. **Agent = Perceive + Reason + Act loop**
2. **LangGraph = Stateful graph workflow**
3. **Skills = Knowledge base для LLM**
4. **ReAct Pattern = Чередование мысли и действия**
5. **Multi-agent = Специализированные агенты + координация**

### **Наш путь:**
```
Phase 2.1: Simple agent (без LangGraph)
  → Понимаем основы
  → Быстрый результат

Phase 2.2: Add skills
  → Улучшаем качество
  → Reproducible reasoning

Phase 2.3: LangGraph integration
  → Stateful workflows
  → Production-ready

Phase 3: Multi-agent system
  → Harmony + Rhythm + Orchestrator
  → Complex workflows
```

### **Дальше:**
Готов обсудить каждую часть подробнее или начать реализацию?
