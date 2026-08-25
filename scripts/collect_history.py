"""2000-01-01부터 전체 재수집."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline import run

if __name__ == "__main__":
    run(mode="history")
