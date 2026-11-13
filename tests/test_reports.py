from datetime import date, timezone

from src.core.order_models import Order, OrderLine
from src.core.sales_models import Sale, SaleLine
from src.core.shop_models import Purchase
from src.services.reports.summary import build, period, report_csv, stock_value

UTC = timezone.utc
NOV = (date(2026, 11, 1), date(2026, 11, 30))


def line(name='Dark Hole', quantity=1, cents=300, set_code='LOB-EN052', cls=SaleLine):
    return cls(name=name, set_code=set_code, quantity=quantity, unit_cents=cents)


def sale(day, total, method='cash', status='paid', lines=None):
    return Sale(paid_at=f'2026-11-{day:02d}T10:00:00+00:00', total_cents=total, method=method, status=status,
                lines=lines or [line(cents=total)])


def order(day, total, channel='cardmarket', status='paid', lines=None, paid=True):
    stamp = f'2026-11-{day:02d}T12:00:00+00:00'
    return Order(created_at=stamp, paid_at=stamp if paid else None, total_cents=total, channel=channel,
                 status=status, lines=lines or [line(cents=total, cls=OrderLine)])


def test_counter_sales_and_orders_add_up_to_the_revenue():
    report = build([sale(3, 1000), sale(3, 500, 'card')], [order(4, 2000)], [], *NOV, tz=UTC)
    assert (report.revenue_cents, report.count, report.average_cents) == (3500, 3, 1167)
    assert report.by_channel == {'Mostrador': 1500, 'Cardmarket': 2000}
    assert report.by_method == {'cash': 1000, 'card': 500}
    assert report.by_day == [('2026-11-03', 1500), ('2026-11-04', 2000)]


def test_refunded_cancelled_pending_and_unpaid_do_not_count():
    sales = [sale(3, 1000, status='refunded'), sale(3, 700, status='pending'), sale(3, 900, status='cancelled')]
    orders = [order(4, 2000, status='cancelled'), order(4, 2000, status='returned'),
              order(4, 800, status='new', paid=False), order(5, 600, status='shipped')]
    report = build(sales, orders, [], *NOV, tz=UTC)
    assert (report.revenue_cents, report.count) == (600, 1)


def test_only_the_days_of_the_period_count_both_ends_included():
    sales = [sale(1, 100), sale(30, 200), sale(15, 400)]
    report = build(sales, [], [], date(2026, 11, 15), date(2026, 11, 30), tz=UTC)
    assert report.revenue_cents == 600


def test_dates_the_wrong_way_round_are_swapped():
    report = build([sale(15, 400)], [], [], date(2026, 11, 30), date(2026, 11, 1), tz=UTC)
    assert (report.revenue_cents, report.start, report.end) == (400, *NOV)


def test_empty_books_give_zeros():
    report = build([], [], [], *NOV, tz=UTC)
    assert (report.revenue_cents, report.count, report.average_cents, report.units) == (0, 0, 0, 0)
    assert (report.by_day, report.by_channel, report.by_method, report.top) == ([], {}, {}, [])


def test_top_cards_merge_counter_and_orders_by_name_and_set():
    sales = [sale(3, 900, lines=[line(quantity=3)]), sale(4, 800, lines=[line('Raigeki', 1, 800, 'LOB-EN053')])]
    orders = [order(5, 600, lines=[line(quantity=2, cls=OrderLine)])]
    report = build(sales, orders, [], *NOV, tz=UTC)
    assert [(c.name, c.set_code, c.units, c.cents) for c in report.top] == [
        ('Dark Hole', 'LOB-EN052', 5, 1500), ('Raigeki', 'LOB-EN053', 1, 800)]
    assert report.units == 6


def test_top_cards_stop_at_twenty():
    lines = [line(f'Carta {n}', 1, 100, f'S-{n}') for n in range(25)]
    assert len(build([sale(3, 2500, lines=lines)], [], [], *NOV, tz=UTC).top) == 20


def test_purchases_done_in_the_period_are_spending():
    purchases = [Purchase(created_at='2026-11-05T09:00:00+00:00', total_cents=700),
                 Purchase(created_at='2026-11-06T09:00:00+00:00', total_cents=900, status='cancelled'),
                 Purchase(created_at='2026-10-06T09:00:00+00:00', total_cents=300)]
    assert build([], [], purchases, *NOV, tz=UTC).purchases_cents == 700


def test_a_stamp_that_cannot_be_read_is_left_out():
    broken = Sale(paid_at='ayer', total_cents=500)
    assert build([broken, sale(3, 100)], [], [], *NOV, tz=UTC).revenue_cents == 100


def test_an_order_without_paid_date_uses_when_it_was_created():
    assert build([], [order(9, 400, status='packed', paid=False)], [], *NOV, tz=UTC).by_day == [('2026-11-09', 400)]


def test_named_periods():
    today = date(2026, 11, 13)
    assert period('hoy', today) == (today, today)
    assert period('7d', today) == (date(2026, 11, 7), today)
    assert period('30d', today) == (date(2026, 10, 15), today)
    assert period('mes', today) == (date(2026, 11, 1), today)
    assert period('mes_pasado', today) == (date(2026, 10, 1), date(2026, 10, 31))
    assert period('ano', today) == (date(2026, 1, 1), today)
    assert period('mes_pasado', date(2026, 1, 9)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert period('no-existe', today) == (date(2026, 11, 1), today)


def test_stock_value_counts_units_and_sale_price():
    assert stock_value([line(quantity=3, cents=250), line(quantity=2, cents=0)]) == (5, 750)


def test_csv_has_days_and_cards():
    report = build([sale(3, 900, lines=[line(quantity=3)])], [], [], *NOV, tz=UTC)
    text = report_csv(report).decode('utf-8-sig')
    assert 'Día;Ingresos' in text and '2026-11-03;9,00' in text
    assert 'Carta;Set;Unidades;Ingresos' in text and 'Dark Hole;LOB-EN052;3;9,00' in text


def test_csv_cells_cannot_start_a_formula():
    report = build([sale(3, 100, lines=[line('=HYPERLINK("x")', 1, 100)])], [], [], *NOV, tz=UTC)
    assert '\n=HYPERLINK' not in report_csv(report).decode('utf-8-sig')


def test_orders_in_another_currency_are_set_apart_not_added():
    dollars = order(5, 10000).model_copy(update={'currency': 'USD'})
    report = build([sale(3, 1000)], [order(4, 2000), dollars], [], *NOV, tz=UTC, currency='EUR')
    assert (report.revenue_cents, report.count) == (3000, 2)
    assert report.by_channel == {'Mostrador': 1000, 'Cardmarket': 2000}
    assert report.by_day == [('2026-11-03', 1000), ('2026-11-04', 2000)]
    assert report.foreign == {'USD': 10000}
    assert 'USD' in report_csv(report).decode('utf-8-sig')


def test_a_damaged_month_of_sales_stops_the_report_instead_of_reading_as_zero(tmp_path):
    import os
    import pytest
    from src.services.reports.summary import gather
    from src.services.sales.store import SalesStore, SalesUnreadable
    from src.services.shop.desk import desk_for

    desk = desk_for(str(tmp_path))
    os.makedirs(tmp_path / 'sales')
    (tmp_path / 'sales' / '2026-11.json').write_text('{not json', encoding='utf-8')
    assert SalesStore(str(tmp_path)).month('2026-11') == []      # the counter keeps opening
    with pytest.raises(SalesUnreadable):
        SalesStore(str(tmp_path)).month('2026-11', strict=True)
    with pytest.raises(SalesUnreadable):
        gather(desk, *NOV)
