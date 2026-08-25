"""일일 증분 수집 + 재학습 + 추천 저장."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline import run

if __name__ == "__main__":
    run(mode="daily")
