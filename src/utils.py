from pathlib import Path


def load_articles(path: Path, separator: str = "\n\n") -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [block.strip() for block in text.split(separator) if block.strip()]
