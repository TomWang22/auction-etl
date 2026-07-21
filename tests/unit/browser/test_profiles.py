from auction_etl.browser.profiles import (
    list_profiles,
    profile_exists,
    profile_path,
)


def test_profile_path_creates_directory():
    path = profile_path("pytest-profile")

    assert path.exists()
    assert path.is_dir()


def test_profile_exists():
    profile_path("pytest-profile-2")

    assert profile_exists("pytest-profile-2")


def test_list_profiles():
    profile_path("alpha")
    profile_path("beta")

    profiles = list_profiles()

    assert "alpha" in profiles
    assert "beta" in profiles
