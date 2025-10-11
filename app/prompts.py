from pathlib import Path
from typing import List

def list_prompt_files(prompts_dir: Path) -> List[Path]:
    return sorted([p for p in prompts_dir.glob("*.md") if p.is_file()])

def load_prompt(prompts_dir: Path, filename: str) -> str:
    p = Path(filename)
    target = p if p.is_absolute() else (prompts_dir / filename)
    if not target.exists():
        available = ", ".join(f.name for f in list_prompt_files(prompts_dir)) or "(none)"
        raise FileNotFoundError(f"System prompt file not found: {target}. Available: {available}")
    return target.read_text(encoding="utf-8")