from ..cli_utils import get_user_input, pause, print_error, print_info, print_success
from ..scraping.player import PLAYER_EXTRACTORS, test_all_scrapers_verbose


def handle_dev_scraper_test() -> None:
    """Prompt for an embed URL and test every scraper with timings."""
    url = get_user_input("Paste embed URL to test")
    if not url:
        return

    print_info(f"Testing {len(PLAYER_EXTRACTORS)} scrapers...")
    results = test_all_scrapers_verbose(url, {})

    for name, res in results.items():
        elapsed = res["elapsed"]
        if res["ok"]:
            print_success(f"{name} [{elapsed:.1f}s] -> {res['stream_url']}")
        else:
            print_error(f"{name} [{elapsed:.1f}s] failed: {res['error']}")

    working = [n for n, r in results.items() if r["ok"]]
    if working:
        print_success(f"{len(working)} working scraper(s): {', '.join(working)}")
    else:
        print_info("No scraper extracted a stream from this URL.")
    pause()
