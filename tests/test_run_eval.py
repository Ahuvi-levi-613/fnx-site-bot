import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parents[1] / "scripts" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def test_provider_counts_most_common_first_and_names_no_model():
    results = [{"provider": "gemini:a"}, {"provider": "gemini:a"}, {"provider": "groq"}, {"provider": None}]
    assert run_eval.provider_counts(results) == "gemini:a 2, groq 1, no model 1"
