from auction_etl.browser.manager import BrowserManager


def test_manager_starts_empty():
    manager = BrowserManager()

    assert manager._contexts == {}
