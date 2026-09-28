"""Model kinds: the sections of the page."""
from ..i18n import tr

KIND_IDS = ["llm", "decision", "tts", "stt", "embedding", "image", "video"]

# Hugging Face task (pipeline_tag) -> kind
TASK_KIND = {
    "text-generation": "llm", "image-text-to-text": "llm", "audio-text-to-text": "llm",
    "video-text-to-text": "llm", "any-to-any": "llm", "visual-question-answering": "llm",
    "text-classification": "decision", "zero-shot-classification": "decision", "token-classification": "decision",
    "text-to-speech": "tts", "text-to-audio": "tts",
    "automatic-speech-recognition": "stt",
    "feature-extraction": "embedding", "sentence-similarity": "embedding", "text-ranking": "embedding",
    "text-to-image": "image", "image-to-image": "image", "text-to-video": "video", "image-to-video": "video",
}


def kind_labels():
    return {k: tr(f"kind.{k}") for k in KIND_IDS}
