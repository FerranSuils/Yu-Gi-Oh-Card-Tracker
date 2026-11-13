from datetime import date
from pathlib import Path

from src.core.account_profile import AccountProfile
from src.core.sales_models import format_money
from src.services.reports.summary import Report


def test_reports_show_in_shop_mode_only():
    from src.ui.layout import SHOP_ROUTES, nav_items

    assert '/informes' not in dict((route, label) for label, route in nav_items(AccountProfile()))
    shop_nav = dict((route, label) for label, route in nav_items(AccountProfile(shop_mode=True)))
    assert shop_nav['/informes'] == 'Informes'
    assert '/informes' in SHOP_ROUTES


def test_reports_are_private_and_registered():
    from src.services.auth_middleware import is_public_path

    assert not is_public_path('/informes')
    assert "@ui.page('/informes')" in Path('main.py').read_text(encoding='utf-8')


def test_icons_are_self_hosted():
    from src.ui.reports import ICONS

    assert ICONS
    for name in ICONS:
        assert Path('static/icons', f'{name}.svg').is_file(), name


def test_the_chart_has_one_bar_per_day_in_currency_units():
    from src.ui.reports import chart_options

    report = Report(start=date(2026, 11, 1), end=date(2026, 11, 30), by_day=[('2026-11-03', 1550), ('2026-11-04', 200)])
    options = chart_options(report)
    assert options['xAxis']['data'] == ['03/11', '04/11']
    assert options['series'][0]['data'] == [15.5, 2.0]
    assert options['series'][0]['type'] == 'bar'


def test_typed_dates_are_read_and_bad_ones_fall_back_to_the_month():
    from src.ui.reports import typed_range

    today = date(2026, 11, 13)
    assert typed_range('2026-10-05', '2026-10-20', today) == (date(2026, 10, 5), date(2026, 10, 20))
    assert typed_range('', 'mañana', today) == (date(2026, 11, 1), today)
    assert typed_range('2026-10-05', '', today) == (date(2026, 10, 5), today)


def test_method_names_are_the_ones_people_read():
    from src.ui.reports import method_rows

    assert method_rows({'card': 500, 'cash': 1000}, 'EUR') == [('Efectivo', format_money(1000, 'EUR')), ('Tarjeta (datáfono)', format_money(500, 'EUR'))]
