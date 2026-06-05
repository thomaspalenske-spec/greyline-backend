from pathlib import Path


def test_main_py_is_bootstrap_only():
    main_text = Path("main.py").read_text()

    assert "@app.get" not in main_text
    assert "@app.post" not in main_text
    assert "from app.services." not in main_text
    assert "include_router" in main_text
