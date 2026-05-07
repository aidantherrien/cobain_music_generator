from __future__ import annotations

PITCH_CLASS_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Semitone intervals from root for each scale/mode
SCALE_INTERVALS: dict[str, list[int]] = {
    "pentatonic_minor": [0, 3, 5, 7, 10],
    "pentatonic_major": [0, 2, 4, 7, 9],
    "ionian":           [0, 2, 4, 5, 7, 9, 11],   # major
    "dorian":           [0, 2, 3, 5, 7, 9, 10],
    "phrygian":         [0, 1, 3, 5, 7, 8, 10],
    "lydian":           [0, 2, 4, 6, 7, 9, 11],
    "mixolydian":       [0, 2, 4, 5, 7, 9, 10],
    "aeolian":          [0, 2, 3, 5, 7, 8, 10],   # natural minor
    "locrian":          [0, 1, 3, 5, 6, 8, 10],
    "chromatic":        list(range(12)),
    "blues":            [0, 3, 5, 6, 7, 10],
    "major":            [0, 2, 4, 5, 7, 9, 11],
    "minor":            [0, 2, 3, 5, 7, 8, 10],
}

# Diatonic chord qualities (for comparison module)
# Index = scale degree (0-based), value = chord type
MAJOR_SCALE_QUALITIES = ["major", "minor", "minor", "major", "major", "minor", "dim"]
MINOR_SCALE_QUALITIES = ["minor", "dim", "major", "minor", "minor", "major", "major"]

# MIDI intervals for chord types (above root)
CHORD_INTERVALS: dict[str, list[int]] = {
    "power": [0, 7],
    "major": [0, 4, 7],
    "minor": [0, 3, 7],
    "dim":   [0, 3, 6],
}


def get_scale_pitches(root_pc: int, scale_name: str, octave_low: int = 4, octave_high: int = 5) -> list[int]:
    intervals = SCALE_INTERVALS.get(scale_name, SCALE_INTERVALS["pentatonic_minor"])
    pitches = []
    for octave in range(octave_low, octave_high + 1):
        for interval in intervals:
            midi = octave * 12 + root_pc + interval
            # Normalize: if interval pushes past octave boundary, it lands in next octave naturally
            if octave_low * 12 + root_pc <= midi <= (octave_high + 1) * 12 + root_pc:
                pitches.append(midi)
    # Deduplicate and sort
    return sorted(set(pitches))


PARALLEL_BORROW_MODES = ("dorian", "aeolian")


def get_key_blend_pitches(
    key_root: int,
    primary_scale: str,
    octave_low: int = 4,
    octave_high: int = 5,
    wander_prob: float = 0.18,
) -> tuple[list[int], list[float]]:
    """
    Build a pitch pool anchored to a global key_root, blending primary scale notes
    (weight 1.0) with parallel-mode borrowed notes (weight = wander_prob).
    Returns (sorted_midi_pitches, normalized_weights).

    Example: key_root=4 (E), primary_scale="pentatonic_minor", wander_prob=0.18
    -> Primary pitches (E pent minor): weight 1.0
    -> Borrowed from Dorian/Aeolian/Mixolydian etc.: weight 0.18
    The melody stays mostly in E pentatonic minor but occasionally lands on
    borrowed scale tones, creating the modal-wandering quality of Cobain verses.
    """
    primary_ivs = set(SCALE_INTERVALS.get(primary_scale, SCALE_INTERVALS["pentatonic_minor"]))

    borrow_ivs: set[int] = set()
    for mode in PARALLEL_BORROW_MODES:
        borrow_ivs |= set(SCALE_INTERVALS[mode])
    borrow_only = borrow_ivs - primary_ivs

    midi_lo = octave_low * 12 + key_root
    midi_hi = (octave_high + 1) * 12 + key_root
    seen: dict[int, float] = {}

    for octave in range(octave_low, octave_high + 1):
        for iv in primary_ivs:
            midi = octave * 12 + key_root + iv
            if midi_lo <= midi <= midi_hi:
                seen[midi] = 1.0
        for iv in borrow_only:
            midi = octave * 12 + key_root + iv
            if midi_lo <= midi <= midi_hi and midi not in seen:
                seen[midi] = wander_prob

    pitches = sorted(seen.keys())
    weights = [seen[p] for p in pitches]
    total = sum(weights)
    weights = [w / total for w in weights]
    return pitches, weights


def pitch_class_name(pc: int) -> str:
    return PITCH_CLASS_NAMES[pc % 12]


def midi_to_name(midi: int) -> str:
    pc = midi % 12
    octave = midi // 12 - 1
    return f"{PITCH_CLASS_NAMES[pc]}{octave}"
