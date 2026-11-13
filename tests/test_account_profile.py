from src.core.account_profile import AccountProfile, enabled_games, load_profile, save_profile


def test_missing_profile_returns_defaults(tmp_path):
    profile = load_profile(str(tmp_path))
    assert profile.shop_mode is False
    assert profile.enabled_games == ['yugioh']
    assert profile.shop.currency == 'EUR' and profile.shop.name == ''


def test_corrupt_profile_returns_defaults(tmp_path):
    (tmp_path / 'profile.json').write_text('{oops', encoding='utf-8')
    assert load_profile(str(tmp_path)) == AccountProfile()


def test_save_and_load_round_trip(tmp_path):
    profile = AccountProfile(shop_mode=True, enabled_games=['yugioh', 'magic'])
    profile.shop.name = 'Cartas Suils'
    profile.shop.email = 'tienda@example.com'
    save_profile(profile, str(tmp_path))
    assert load_profile(str(tmp_path)) == profile


def test_enabled_games_always_includes_yugioh_and_drops_unknown():
    assert enabled_games(AccountProfile(enabled_games=['magic', 'nope'])) == ['yugioh', 'magic']
