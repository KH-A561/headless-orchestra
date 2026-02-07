# Harmony Analysis Skill

## 1. Key Detection

### Rules:
- Collect all unique pitch classes from the notes
- Compare with major and minor scale patterns
- Most likely key = maximum note match

### Major Scale Pattern:
- Formula: W-W-H-W-W-W-H (W=whole step, H=half step)
- Example C major: C D E F G A B
- Interval structure: 1 2 3 4 5 6 7

### Natural Minor Scale Pattern:
- Formula: W-H-W-W-H-W-W
- Example A minor: A B C D E F G
- Interval structure: 1 2 b3 4 5 b6 b7

### Detection Algorithm:
1. Extract all unique pitch classes (ignore octaves)
2. For each possible root note (C, C#, D, ..., B):
   - Test major scale: count matching notes
   - Test minor scale: count matching notes
3. Highest match = detected key
4. Confidence = (matching notes / total unique notes)

---

## 2. Chord Recognition

### Triad Types:
- **Major**: Root + M3 (4 semitones) + P5 (7 semitones)
  - Example: C major = C, E, G
- **Minor**: Root + m3 (3 semitones) + P5 (7 semitones)
  - Example: A minor = A, C, E
- **Diminished**: Root + m3 + d5 (6 semitones)
  - Example: B dim = B, D, F
- **Augmented**: Root + M3 + A5 (8 semitones)
  - Example: C aug = C, E, G#

### Seventh Chords:
- **Major 7**: Major triad + M7 (11 semitones from root)
  - Example: Cmaj7 = C, E, G, B
- **Dominant 7**: Major triad + m7 (10 semitones)
  - Example: G7 = G, B, D, F
- **Minor 7**: Minor triad + m7
  - Example: Am7 = A, C, E, G
- **Half-diminished**: Diminished triad + m7
  - Example: Bø7 = B, D, F, A

### Recognition Algorithm:
1. Group simultaneous or overlapping notes
2. Extract pitch classes (ignore octaves)
3. Find root note (usually lowest or most prominent)
4. Calculate intervals from root
5. Match interval pattern to chord type

---

## 3. Common Progressions

### Functional Harmony:
- **Tonic (I)**: Stable, resolution point
- **Subdominant (IV)**: Pre-dominant, tension
- **Dominant (V, V7)**: Maximum tension, wants to resolve to I

### Popular Progressions:
- **I-IV-V-I**: Classic cadence (C-F-G-C)
- **I-vi-IV-V**: 50s progression (C-Am-F-G)
- **I-V-vi-IV**: Pop progression (C-G-Am-F)
- **ii-V-I**: Jazz turnaround (Dm-G-C)
- **I-bVII-IV**: Rock progression (C-Bb-F)

### Circle of Fifths Movement:
- Moving down by 5ths: strong, natural progression
- Example: C → F → Bb → Eb → ...

---

## 4. Analysis Guidelines

### When analyzing a clip:
1. **First pass**: Identify all notes and their timing
2. **Key detection**: Apply key detection algorithm
3. **Chord identification**: Group notes, recognize chords
4. **Progression analysis**: Identify chord sequence
5. **Functional analysis**: Determine tonic/dominant/subdominant roles
6. **Confidence scoring**: Based on:
   - How well notes fit detected key
   - How clearly chords are defined
   - Whether progression follows common patterns

### Quality Indicators:
- ✅ Good: Notes clearly form recognizable chords
- ✅ Good: Progression follows functional harmony
- ✅ Good: High percentage of scale notes
- ⚠️ Ambiguous: Multiple possible keys with similar scores
- ⚠️ Ambiguous: Non-chord tones or passing tones present
- ❌ Poor: Notes don't fit any clear key
- ❌ Poor: Random note combinations

---

## 5. MIDI Pitch to Note Name Mapping

### Middle C = 60
- C4 (middle C) = 60
- C3 = 48, C5 = 72
- A4 (440Hz) = 69

### Chromatic Scale (starting from C):
- C=0, C#/Db=1, D=2, D#/Eb=3, E=4, F=5, F#/Gb=6
- G=7, G#/Ab=8, A=9, A#/Bb=10, B=11

### Conversion:
- Pitch class = MIDI pitch % 12
- Example: pitch 64 → 64 % 12 = 4 → E

---

END OF SKILL FILE
