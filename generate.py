"""
Cobain-Inspired Harmonic Ambiguity Generator
============================================
Generates power-chord progressions and melody variations inspired by Kurt Cobain's
songwriting style (power chords only — no thirds = no declared major/minor tonality).

Usage examples:
  python generate.py --key E --style grunge --bars 8 --variations 5
  python generate.py --key A --style chromatic --scale phrygian --temperature 1.5
  python generate.py --key E --compare
  python generate.py --key D --scale dorian --density 2.0 --step-weight 0.3
"""

import argparse
import os
from pathlib import Path

from cobain_generator.config import ProgressionConfig, MelodyConfig, MidiBuilderConfig, AudioConfig
from cobain_generator.chord_generator import PowerChordProgressionGenerator
from cobain_generator.melody_generator import MelodyGenerator
from cobain_generator.midi_builder import MidiBuilder
from cobain_generator.audio_renderer import AudioRenderer
from cobain_generator.comparison import ComparisonGenerator, ComparisonConfig
from cobain_generator.song_generator import SongGenerator, DEFAULT_STRUCTURE

NOTE_TO_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

SCALE_CHOICES = [
    "pentatonic_minor", "pentatonic_major", "dorian", "mixolydian",
    "phrygian", "aeolian", "chromatic", "blues", "lydian", "locrian",
]

STYLE_CHOICES = ["grunge", "verse", "chorus", "chromatic", "ballad"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Cobain-style harmonic ambiguity music generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    # Progression
    p.add_argument("--key",        default="E",            help="Starting root note (default: E)")
    p.add_argument("--style",      default="verse",  choices=STYLE_CHOICES)
    p.add_argument("--bars",       default=8,   type=int,  help="Number of bars (default: 8)")
    p.add_argument("--tempo",      default=120, type=float,help="BPM (default: 120)")
    # Melody hyperparameters
    p.add_argument("--scale",      default="pentatonic_minor", choices=SCALE_CHOICES,
                   help="Scale/mode applied per chord root (default: pentatonic_minor)")
    p.add_argument("--step-weight",  default=0.65, type=float, dest="step_weight",
                   help="Stepwise motion probability 0-1 (default: 0.65)")
    p.add_argument("--density",      default=1.0,  type=float,
                   help="Notes per beat (default: 1.0 = quarter notes)")
    p.add_argument("--temperature",  default=1.0,  type=float,
                   help="Randomness of note selection (default: 1.0)")
    p.add_argument("--phrase-length",default=8.0,  type=float, dest="phrase_length",
                   help="Beats per melodic phrase (default: 8.0)")
    p.add_argument("--octave-low",   default=4,    type=int,   dest="octave_low")
    p.add_argument("--octave-high",  default=5,    type=int,   dest="octave_high")
    p.add_argument("--variations",   default=5,    type=int,
                   help="Number of melody variations to generate (default: 5)")
    p.add_argument("--rests",        default=0.08, type=float,
                   help="Rest probability per note slot (default: 0.08)")
    # Output
    p.add_argument("--output-dir",   default="output/cobain", dest="output_dir")
    p.add_argument("--soundfont",    default=None, help="Path to .sf2 soundfont file")
    p.add_argument("--seed",         default=42,   type=int)
    # Mode
    p.add_argument("--compare", action="store_true",
                   help="Run diatonic comparison pipeline (power vs diatonic chords)")
    p.add_argument("--song", action="store_true",
                   help="Generate a full song (intro/verse/chorus/bridge/outro arc)")
    p.add_argument("--loop-bars", default=4, type=int, dest="loop_bars",
                   help="Bars in the repeating chord loop (default: 4)")
    p.add_argument("--chord-count", default=None, type=int, dest="chord_count",
                   help="Exact number of chords in the loop, equal duration (e.g. 4=Teen Spirit, 6=Lithium). "
                        "None=variable-duration Markov walk (default).")
    return p.parse_args()


def main():
    args = parse_args()

    if args.key not in NOTE_TO_PC:
        print(f"Unknown key '{args.key}'. Valid keys: {list(NOTE_TO_PC.keys())}")
        return

    root_pc = NOTE_TO_PC[args.key]

    if args.compare:
        out_dir = args.output_dir.replace("cobain", "comparison")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        mel_cfg = MelodyConfig(
            scale_mode=args.scale,
            temperature=args.temperature,
            note_density=args.density,
            step_weight=args.step_weight,
            phrase_length_beats=args.phrase_length,
            octave_low=args.octave_low,
            octave_high=args.octave_high,
            rest_probability=args.rests,
        )
        cfg = ComparisonConfig(
            root=root_pc,
            tempo_bpm=args.tempo,
            length_bars=args.bars,
            style=args.style,
            melody_config=mel_cfg,
            output_dir=out_dir,
            seed=args.seed,
        )
        results = ComparisonGenerator(cfg).run()
        print(results["summary"])
        print(f"\nFiles written to: {out_dir}")
        return

    # ── Full song generation ─────────────────────────────────────────
    if args.song:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
        prog_cfg = ProgressionConfig(
            root=root_pc, tempo_bpm=args.tempo,
            length_bars=args.loop_bars, style=args.style, seed=args.seed,
            n_chords=args.chord_count,
        )
        mel_cfg = MelodyConfig(
            scale_mode=args.scale, temperature=args.temperature,
            note_density=args.density, step_weight=args.step_weight,
            phrase_length_beats=args.phrase_length,
            octave_low=args.octave_low, octave_high=args.octave_high,
            rest_probability=args.rests,
        )
        song_gen = SongGenerator(prog_cfg, mel_cfg, song_seed=args.seed)
        sections = song_gen.generate()

        # Print song map
        total_bars = sum(s.bars for s, _, _ in sections)
        print(f"\nSong structure ({total_bars} bars total):")
        bar = 0
        for s, chord_prog, _ in sections:
            hook_tag = " [HOOK]" if s.use_hook else ""
            print(f"  bar {bar:3d}  {s.type.upper():8s} ({s.bars:2d} bars)  vel x{s.velocity_scale:.2f}{hook_tag}")
            bar += s.bars

        chord_loop = PowerChordProgressionGenerator(prog_cfg).generate()
        chord_gen = PowerChordProgressionGenerator(prog_cfg)
        print(f"\nChord loop: {chord_gen.describe(chord_loop)}")

        tag = f"{args.key}_{args.style}_{args.scale}_song"
        mid_path = os.path.join(args.output_dir, f"{tag}.mid")
        wav_path = os.path.join(args.output_dir, f"{tag}.wav")

        MidiBuilder(prog_cfg).build_song(sections, mid_path)
        print(f"\nMIDI: {mid_path}")

        renderer = AudioRenderer(AudioConfig(soundfont_path=args.soundfont))
        if renderer.is_available():
            renderer.render(mid_path, wav_path)
            print(f" WAV: {wav_path}")
        else:
            renderer._print_install_instructions()
        print("\nDone.")
        return

    # ── Standard generation ──────────────────────────────────────────
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    prog_cfg = ProgressionConfig(
        root=root_pc,
        tempo_bpm=args.tempo,
        length_bars=args.bars,
        style=args.style,
        seed=args.seed,
        n_chords=args.chord_count,
    )
    mel_cfg = MelodyConfig(
        scale_mode=args.scale,
        temperature=args.temperature,
        note_density=args.density,
        step_weight=args.step_weight,
        phrase_length_beats=args.phrase_length,
        octave_low=args.octave_low,
        octave_high=args.octave_high,
        n_variations=args.variations,
        rest_probability=args.rests,
    )

    # Generate progression
    chord_gen = PowerChordProgressionGenerator(prog_cfg)
    chord_prog = chord_gen.generate()
    print(f"\nChord progression ({len(chord_prog)} chords):")
    print("  " + chord_gen.describe(chord_prog))
    print(f"  Total duration: {sum(d for _, d in chord_prog):.1f} beats")

    # Generate melodies
    melody_gen = MelodyGenerator(mel_cfg)
    melody_variations = melody_gen.generate_all_variations(chord_prog)

    # Build MIDI + render audio
    builder = MidiBuilder(prog_cfg)
    renderer = AudioRenderer(AudioConfig(soundfont_path=args.soundfont))
    if not renderer.is_available():
        renderer._print_install_instructions()

    tag_base = f"{args.key}_{args.style}_{args.scale}"
    print(f"\nGenerating {args.variations} variation(s) -> {args.output_dir}/\n")

    for i, melody in enumerate(melody_variations):
        tag = f"{tag_base}_var{i+1:02d}"
        mid_path = os.path.join(args.output_dir, f"{tag}.mid")
        wav_path = os.path.join(args.output_dir, f"{tag}.wav")

        builder.build(chord_prog, melody, mid_path)
        print(f"  [{i+1}/{args.variations}] MIDI: {mid_path}")

        if renderer.is_available():
            result = renderer.render(mid_path, wav_path)
            if result:
                print(f"  [{i+1}/{args.variations}]  WAV: {wav_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
