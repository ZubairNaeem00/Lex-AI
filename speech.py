"""Speech-to-text and text-to-speech helpers.

Speech-to-text uses Groq's Whisper-compatible transcription endpoint and
requires ``GROQ_API_KEY`` in the environment or a local ``.env`` file.
Text-to-speech uses Google Text-to-Speech and saves the generated audio as an
MP3 file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

from dotenv import load_dotenv
from gtts import gTTS
from groq import Groq


PathLike = Union[str, os.PathLike[str]]

load_dotenv()


def speech_to_text(
    audio_file: PathLike,
    *,
    model: str = "whisper-large-v3-turbo",
    language: str | None = None,
) -> str:
    """Transcribe an audio file using Groq's Whisper-compatible API.

    Args:
        audio_file: Path to an audio file supported by the transcription API.
        model: Groq transcription model name.
        language: Optional ISO-639-1 language code, such as ``"en"``.

    Returns:
        The transcribed text.

    Raises:
        FileNotFoundError: If ``audio_file`` does not exist.
        ValueError: If the file is not a regular file or the API key is absent.
    """
    audio_path = Path(audio_file)
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is required for speech-to-text. "
            "Add it to the environment or .env file."
        )

    client = Groq(api_key=api_key)
    request: dict[str, object] = {
        "file": (audio_path.name, audio_path.read_bytes()),
        "model": model,
        "response_format": "text",
    }
    if language:
        request["language"] = language

    transcription = client.audio.transcriptions.create(**request)
    text = getattr(transcription, "text", None)
    if not isinstance(text, str):
        raise RuntimeError("The transcription service returned no text.")
    return text.strip()


def text_to_speech(
    text: str,
    output_file: PathLike = "speech.mp3",
    *,
    language: str = "en",
    slow: bool = False,
) -> Path:
    """Convert text to speech and save it as an MP3 file.

    Args:
        text: Text to synthesize. It must not be empty.
        output_file: Destination MP3 path.
        language: gTTS language code, such as ``"en"`` or ``"ur"``.
        slow: Whether to use gTTS's slower speaking rate.

    Returns:
        The path of the generated MP3 file.

    Raises:
        ValueError: If ``text`` is empty.
        OSError: If the destination directory cannot be created or written.
    """
    if not text or not text.strip():
        raise ValueError("text must not be empty.")

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    speech = gTTS(text=text, lang=language, slow=slow)
    speech.save(str(output_path))
    return output_path


if __name__ == "__main__":
    print("Import speech_to_text and text_to_speech from speech.py to use them.")
