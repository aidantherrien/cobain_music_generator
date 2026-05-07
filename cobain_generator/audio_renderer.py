from __future__ import annotations
import os
import shutil
import subprocess
from dataclasses import dataclass

SOUNDFONT_SEARCH_PATHS = [
    r"C:\Users\aidan\VSCode Projects\MUSC448C Final Project\assets\soundfonts",
    r"C:\Program Files\FluidSynth\share\soundfonts",
    r"C:\fluidsynth\share\soundfonts",
    r"C:\soundfonts",
]

FLUIDSYNTH_PATHS = [
    r"C:\fluidsynth\fluidsynth-v2.5.4-win10-x64-cpp11\bin\fluidsynth.exe",
    r"C:\Program Files\FluidSynth\bin\fluidsynth.exe",
    r"C:\fluidsynth\bin\fluidsynth.exe",
    r"C:\Users\aidan\fluidsynth\bin\fluidsynth.exe",
]

PREFERRED_SOUNDFONTS = ["GeneralUser", "FluidR3", "TimGM", "default"]


@dataclass
class AudioConfig:
    soundfont_path: str | None = None
    sample_rate: int = 44100
    gain: float = 0.8
    reverb: bool = True


class AudioRenderer:
    """
    Renders MIDI to WAV via FluidSynth. Degrades gracefully when not installed.
    """

    def __init__(self, config: AudioConfig | None = None):
        self.config = config or AudioConfig()
        self.fluidsynth_path = self._find_fluidsynth()
        self.soundfont_path = self.config.soundfont_path or self._find_soundfont()

    def _find_fluidsynth(self) -> str | None:
        if found := shutil.which("fluidsynth"):
            return found
        for path in FLUIDSYNTH_PATHS:
            if os.path.exists(path):
                return path
        return None

    def _find_soundfont(self) -> str | None:
        for directory in SOUNDFONT_SEARCH_PATHS:
            if not os.path.isdir(directory):
                continue
            sf2_files = [f for f in os.listdir(directory) if f.lower().endswith(".sf2")]
            # Prefer known good soundfonts
            for pref in PREFERRED_SOUNDFONTS:
                for sf in sf2_files:
                    if pref.lower() in sf.lower():
                        return os.path.join(directory, sf)
            if sf2_files:
                return os.path.join(directory, sf2_files[0])
        return None

    def is_available(self) -> bool:
        return self.fluidsynth_path is not None and self.soundfont_path is not None

    def render(self, midi_path: str, output_wav_path: str) -> str | None:
        if not self.is_available():
            self._print_install_instructions()
            return None

        cmd = [
            self.fluidsynth_path,
            "-ni",
            "-F", output_wav_path,
            "-r", str(self.config.sample_rate),
            "-g", str(self.config.gain),
        ]
        if self.config.reverb:
            cmd += ["--reverb", "yes"]
        cmd += [self.soundfont_path, midi_path]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"[AudioRenderer] FluidSynth error:\n{result.stderr}")
            return None
        return output_wav_path

    def _print_install_instructions(self):
        print(
            "\n[AudioRenderer] FluidSynth or soundfont not found -- WAV output skipped.\n"
            "MIDI files are still generated and can be opened in any DAW or media player.\n\n"
            "To enable WAV rendering:\n\n"
            "1. Download FluidSynth for Windows:\n"
            "   https://github.com/FluidSynth/fluidsynth/releases\n"
            "   Download fluidsynth-2.x.x-win10-x64.zip, extract to C:\\fluidsynth,\n"
            "   and add C:\\fluidsynth\\bin to your system PATH.\n\n"
            "2. Download a free soundfont (.sf2):\n"
            "   GeneralUser GS: https://schristiancollins.com/generaluser.php\n"
            "   Place the .sf2 file in: assets/soundfonts/\n"
        )
