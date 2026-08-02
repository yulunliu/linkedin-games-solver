"""
Entry point for the console version 命令列版進入點: python run_cli.py --image shot.png

Same engine as run.py, no window. Defaults to a dry run - it prints the plan
without moving the mouse unless --go is given.
與 run.py 同一套引擎，只是沒有視窗。預設是預演 —— 只印出計畫，
除非加上 --go 才會操作滑鼠。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from linkedin_games_solver.ui.cli import main

if __name__ == "__main__":
    main()
