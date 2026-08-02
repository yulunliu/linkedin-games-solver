"""
Entry point 進入點: python run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from linkedin_games_solver.ui.app import main

if __name__ == "__main__":
    main()
