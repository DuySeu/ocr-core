def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: runs a real model or a real document; skipped by -m 'not slow'"
    )
