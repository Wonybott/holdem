"""Run with python -m src.main or python src/main.py from the checkout."""
import sys
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="자체 모의 화면 전용 Hold'em Analyzer")
    parser.add_argument("--analyze", metavar="IMAGE", help="GUI 없이 모의 이미지를 분석")
    parser.add_argument("--iterations", type=int, default=3000)
    parser.add_argument("--range", default="random", dest="range_text")
    args = parser.parse_args()
    if args.analyze:
        import json
        from dataclasses import asdict
        from src.capture.sources import load_image
        from src.vision.recognizer import MockRecognizer
        from src.poker.equity import estimate, parse_range
        from src.strategy.scenarios import pot_odds, call_ev
        try:
            observation = MockRecognizer().analyze(load_image(args.analyze))
            if observation.state is None:
                print(json.dumps({"errors": observation.errors}, ensure_ascii=False))
                return 2
            state = observation.state
            equity = estimate(state, [parse_range(args.range_text)] * state.opponents,
                              args.iterations, seed=42)
            print(json.dumps({"state": asdict(state), "equity": asdict(equity),
                              "pot_odds": pot_odds(state.pot, state.to_call),
                              "showdown_call_ev": call_ev(equity.equity, state.pot, state.to_call),
                              "confidence": observation.confidence}, ensure_ascii=False, indent=2))
            return 0
        except (ValueError, OSError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 2
    from PySide6.QtWidgets import QApplication
    from src.gui.window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("Holdem Vision Analyzer")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
