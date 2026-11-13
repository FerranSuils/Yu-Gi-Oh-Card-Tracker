import json
import os

import pytest

from src.core.catalog_models import GameCollection, GameCollectionCard, GameCollectionVariant
from src.core.game_collections import GameCollectionStore
from src.core.models import Collection, CollectionCard, CollectionEntry, CollectionVariant
from src.core.persistence import PersistenceManager
from src.core.sales_models import Discount, OutOfStock, SaleLine
from src.services.sales.checkout import Checkout, SaleError
from src.services.sales.inventory import Inventory, line_key, search
from src.services.sales.store import SalesStore, sales_csv


@pytest.fixture
def shop(tmp_path):
    persistence = PersistenceManager(str(tmp_path / 'collections'), str(tmp_path / 'decks'))
    games = GameCollectionStore(lambda: str(tmp_path))
    ygo = Collection(name='Vitrina', cards=[
        CollectionCard(card_id=89631139, name='Blue-Eyes White Dragon', variants=[
            CollectionVariant(variant_id='v1', set_code='LOB-EN001', rarity='Ultra Rare', image_id=89631139, entries=[
                CollectionEntry(quantity=3, list_price=25.0, storage_location='Caja A'),
                CollectionEntry(quantity=1, condition='Played'),
            ])]),
        CollectionCard(card_id=46986414, name='Dark Magician', variants=[
            CollectionVariant(variant_id='v2', set_code='SDY-006', rarity='Ultra Rare', entries=[
                CollectionEntry(quantity=2, list_price=9.99, language='DE', first_edition=True)])]),
    ])
    persistence.save_collection(ygo, 'vitrina.json')
    magic = GameCollection(game='magic', name='Magic', cards=[
        GameCollectionCard(card_id='c1', name='Ragavan, Nimble Pilferer', variants=[
            GameCollectionVariant(printing_id='p1', set_code='MH2', number='138', rarity='mythic', finish='foil',
                                  entries=[CollectionEntry(quantity=2, list_price=40.0)])])])
    games.save('magic', magic, 'magic.json')
    inventory = Inventory(persistence, games)
    store = SalesStore(str(tmp_path))
    return type('Shop', (), dict(persistence=persistence, games=games, inventory=inventory, store=store,
                                 checkout=Checkout(inventory, store), root=tmp_path))


def find(items, name, **fields):
    return next(i for i in items if i.name.startswith(name) and all(getattr(i, k) == v for k, v in fields.items()))


def qty(shop, name, **fields):
    try:
        return find(shop.inventory.items(['yugioh', 'magic']), name, **fields).quantity
    except StopIteration:
        return 0


# --- inventory -----------------------------------------------------------------------------

def test_items_lists_every_pile_with_its_price(shop):
    items = shop.inventory.items(['yugioh', 'magic'])
    assert len(items) == 4
    blue = find(items, 'Blue-Eyes', condition='Near Mint')
    assert (blue.game, blue.collection, blue.card_id, blue.variant_id) == ('yugioh', 'vitrina.json', '89631139', 'v1')
    assert (blue.quantity, blue.unit_cents, blue.list_price, blue.storage_location) == (3, 2500, 25.0, 'Caja A')
    assert find(items, 'Blue-Eyes', condition='Played').unit_cents == 0
    ragavan = find(items, 'Ragavan')
    assert (ragavan.game, ragavan.finish, ragavan.number, ragavan.unit_cents) == ('magic', 'foil', '138', 4000)


def test_items_only_for_enabled_games(shop):
    assert all(i.game == 'yugioh' for i in shop.inventory.items(['yugioh']))


def test_items_skip_unreadable_collections(shop):
    with open(os.path.join(shop.persistence.data_dir, 'rota.json'), 'w', encoding='utf-8') as file:
        file.write('{no json')
    assert len(shop.inventory.items(['yugioh'])) == 3


def test_search_by_name_set_and_number(shop):
    items = shop.inventory.items(['yugioh', 'magic'])
    assert [i.name for i in search(items, 'dark')] == ['Dark Magician']
    assert [i.set_code for i in search(items, 'lob-en')] == ['LOB-EN001', 'LOB-EN001']
    assert [i.name for i in search(items, 'ragavan mh2')] == ['Ragavan, Nimble Pilferer']
    assert [i.name for i in search(items, '138')] == ['Ragavan, Nimble Pilferer']
    assert search(items, 'zzz') == []
    assert len(search(items, '')) == 4
    assert len(search(items, '', limit=2)) == 2


def test_line_key_tells_piles_apart(shop):
    items = shop.inventory.items(['yugioh', 'magic'])
    assert len({line_key(i) for i in items}) == 4


def test_take_is_all_or_nothing(shop):
    items = shop.inventory.items(['yugioh', 'magic'])
    good = find(items, 'Ragavan').model_copy(update={'quantity': 1})
    bad = find(items, 'Dark').model_copy(update={'quantity': 3})
    with pytest.raises(OutOfStock):
        shop.inventory.take([good, bad])
    assert qty(shop, 'Ragavan') == 2 and qty(shop, 'Dark') == 2


def test_take_counts_two_lines_of_the_same_pile(shop):
    line = find(shop.inventory.items(['yugioh']), 'Dark').model_copy(update={'quantity': 2})
    with pytest.raises(OutOfStock):
        shop.inventory.take([line, line.model_copy(update={'quantity': 1})])
    shop.inventory.take([line.model_copy(update={'quantity': 1}), line.model_copy(update={'quantity': 1})])
    assert qty(shop, 'Dark') == 0


def test_take_missing_collection_is_out_of_stock(shop):
    line = find(shop.inventory.items(['yugioh']), 'Dark').model_copy(update={'collection': 'borrada.json'})
    with pytest.raises(OutOfStock):
        shop.inventory.take([line])


def test_give_back_restores(shop):
    line = find(shop.inventory.items(['magic']), 'Ragavan')
    shop.inventory.take([line])
    assert qty(shop, 'Ragavan') == 0
    shop.inventory.give_back([line])
    assert qty(shop, 'Ragavan') == 2


# --- store ---------------------------------------------------------------------------------

def test_store_numbers_and_months(shop):
    first = shop.checkout.charge([SaleLine(kind='custom', name='Fundas', unit_cents=500)], Discount(), 'cash', 'EUR',
                                 received_cents=1000)
    second = shop.checkout.charge([SaleLine(kind='custom', name='Sobre', unit_cents=450)], Discount(), 'card', 'EUR')
    assert (first.number, second.number) == (1, 2)
    assert first.label == '000001'
    month = first.created_at[:7]
    assert shop.store.months() == [month]
    assert [s.number for s in shop.store.month(month)] == [2, 1]
    assert shop.store.get(first.id).change_cents == 500
    assert shop.store.get('nope') is None
    assert os.path.exists(shop.root / 'sales' / f'{month}.json')


def test_store_is_per_root(shop, tmp_path):
    shop.checkout.charge([SaleLine(kind='custom', name='Fundas', unit_cents=500)], Discount(), 'card', 'EUR')
    other = SalesStore(str(tmp_path / 'otra'))
    assert other.months() == []
    assert other.next_number() == 1


def test_store_survives_a_broken_month_file(shop):
    os.makedirs(shop.root / 'sales')
    (shop.root / 'sales' / '2026-10.json').write_text('{broken', encoding='utf-8')
    assert shop.store.month('2026-10') == []


def test_csv_has_one_row_per_line_and_guards_formulas(shop):
    sale = shop.checkout.charge(
        [SaleLine(kind='custom', name='=HYPERLINK("x")', unit_cents=500, quantity=2),
         find(shop.inventory.items(['yugioh']), 'Dark').model_copy(update={'quantity': 1})],
        Discount(kind='percent', value=10), 'card', 'EUR')
    text = sales_csv([sale]).decode('utf-8-sig')
    rows = text.strip().splitlines()
    assert rows[0].startswith('Número;Fecha;Estado;Método;Artículo')
    assert len(rows) == 3
    assert "'=HYPERLINK" in rows[1]
    assert '000001' in rows[1] and '10,00' in rows[1] and 'Dark Magician' in rows[2] and 'SDY-006' in rows[2]


# --- checkout: cash and card ---------------------------------------------------------------

def test_cash_sale_takes_stock_and_records_change(shop):
    line = find(shop.inventory.items(['yugioh']), 'Blue-Eyes', condition='Near Mint').model_copy(update={'quantity': 2})
    sale = shop.checkout.charge([line], Discount(kind='amount', value=5), 'cash', 'EUR', received_cents=5000)
    assert (sale.status, sale.method, sale.subtotal_cents, sale.discount_cents, sale.total_cents) == (
        'paid', 'cash', 5000, 500, 4500)
    assert (sale.received_cents, sale.change_cents, sale.number) == (5000, 500, 1)
    assert sale.paid_at
    assert qty(shop, 'Blue-Eyes', condition='Near Mint') == 1


@pytest.mark.parametrize('lines, method, received, message', [
    ([], 'cash', 100, 'vacío'),
    ([SaleLine(name='Sin precio', kind='custom', unit_cents=0)], 'card', None, 'precio'),
    ([SaleLine(name='Fundas', kind='custom', unit_cents=500)], 'cash', 400, 'no cubre'),
    ([SaleLine(name='Fundas', kind='custom', unit_cents=500)], 'cash', None, 'entregado'),
    ([SaleLine(name='Fundas', kind='custom', unit_cents=500)], 'bizum', None, 'cobro'),
])
def test_charge_rejects(shop, lines, method, received, message):
    with pytest.raises(SaleError, match=message):
        shop.checkout.charge(lines, Discount(), method, 'EUR', received_cents=received)
    assert shop.store.months() == []


def test_out_of_stock_leaves_no_sale_and_no_number(shop):
    line = find(shop.inventory.items(['yugioh']), 'Dark').model_copy(update={'quantity': 5})
    with pytest.raises(OutOfStock):
        shop.checkout.charge([line], Discount(), 'card', 'EUR')
    assert shop.store.months() == [] and shop.store.next_number() == 1


def test_refund_returns_stock_once(shop):
    line = find(shop.inventory.items(['magic']), 'Ragavan')
    sale = shop.checkout.charge([line], Discount(), 'card', 'EUR')
    assert qty(shop, 'Ragavan') == 0
    refunded = shop.checkout.refund(sale.id)
    assert refunded.status == 'refunded' and refunded.refunded_at
    assert qty(shop, 'Ragavan') == 2
    with pytest.raises(SaleError, match='ya'):
        shop.checkout.refund(sale.id)
    assert qty(shop, 'Ragavan') == 2


# --- checkout: Stripe ----------------------------------------------------------------------

class FakeGateway:
    def __init__(self):
        self.state = {}
        self.calls = []
        self.fail = None

    def create_checkout(self, sale, success_url):
        self.calls.append(('create', sale.total_cents, sale.currency, success_url))
        if self.fail:
            raise self.fail
        self.state['cs_1'] = 'open'
        return 'cs_1', 'https://checkout.stripe.com/c/pay/cs_1'

    def status(self, session):
        return self.state[session]

    def expire(self, session):
        self.calls.append(('expire', session))
        self.state[session] = 'expired'

    def refund(self, session):
        self.calls.append(('refund', session))


def stripe_sale(shop, gateway):
    line = find(shop.inventory.items(['yugioh']), 'Dark')
    return shop.checkout.start_stripe([line], Discount(), 'EUR', 'https://tienda.test/tpv/pagado', gateway)


def test_stripe_reserves_stock_and_waits(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    assert (sale.status, sale.method, sale.number, sale.stripe_session) == ('pending', 'stripe', None, 'cs_1')
    assert sale.stripe_url.startswith('https://checkout.stripe.com/')
    assert gateway.calls[0] == ('create', 1998, 'EUR', 'https://tienda.test/tpv/pagado')
    assert qty(shop, 'Dark') == 0
    assert shop.checkout.settle_stripe(sale.id, gateway).status == 'pending'


def test_stripe_paid_closes_the_sale_with_a_number(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    gateway.state['cs_1'] = 'paid'
    settled = shop.checkout.settle_stripe(sale.id, gateway)
    assert (settled.status, settled.number) == ('paid', 1) and settled.paid_at
    assert shop.checkout.settle_stripe(sale.id, gateway).number == 1
    assert qty(shop, 'Dark') == 0


def test_stripe_expired_gives_stock_back(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    gateway.state['cs_1'] = 'expired'
    assert shop.checkout.settle_stripe(sale.id, gateway).status == 'cancelled'
    assert qty(shop, 'Dark') == 2
    assert shop.store.next_number() == 1


def test_stripe_cancel_expires_and_gives_stock_back(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    cancelled = shop.checkout.cancel_stripe(sale.id, gateway)
    assert cancelled.status == 'cancelled' and ('expire', 'cs_1') in gateway.calls
    assert qty(shop, 'Dark') == 2
    assert shop.checkout.cancel_stripe(sale.id, gateway).status == 'cancelled'
    assert qty(shop, 'Dark') == 2


def test_stripe_cancel_after_the_customer_paid_keeps_the_sale(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    gateway.state['cs_1'] = 'paid'
    assert shop.checkout.cancel_stripe(sale.id, gateway).status == 'paid'
    assert qty(shop, 'Dark') == 0


def test_stripe_failure_creating_the_payment_gives_stock_back(shop):
    gateway = FakeGateway()
    gateway.fail = RuntimeError('boom')
    with pytest.raises(RuntimeError):
        stripe_sale(shop, gateway)
    assert qty(shop, 'Dark') == 2
    assert shop.store.months() == []


def test_stripe_needs_the_minimum_amount(shop):
    with pytest.raises(SaleError, match='0,50'):
        shop.checkout.start_stripe([SaleLine(kind='custom', name='Chicle', unit_cents=20)], Discount(), 'EUR',
                                   'https://x.test/ok', FakeGateway())


def test_stripe_refund_goes_through_stripe(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    gateway.state['cs_1'] = 'paid'
    shop.checkout.settle_stripe(sale.id, gateway)
    with pytest.raises(SaleError, match='Stripe'):
        shop.checkout.refund(sale.id)
    assert shop.checkout.refund(sale.id, gateway).status == 'refunded'
    assert ('refund', 'cs_1') in gateway.calls
    assert qty(shop, 'Dark') == 2


def test_reconcile_settles_every_pending_stripe_sale(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    gateway.state['cs_1'] = 'paid'
    assert [s.id for s in shop.checkout.reconcile(gateway)] == [sale.id]
    assert shop.store.get(sale.id).status == 'paid'
    assert shop.checkout.reconcile(gateway) == []


def test_sales_file_holds_no_secret(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    data = json.loads((shop.root / 'sales' / f'{sale.created_at[:7]}.json').read_text(encoding='utf-8'))
    assert data[0]['stripe_session'] == 'cs_1'
    assert 'key' not in json.dumps(data)


def test_close_pending_leaves_no_stock_reserved_before_disconnecting(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    assert qty(shop, 'Dark') < 2
    closed = shop.checkout.close_pending(gateway)
    assert [(one.id, one.status) for one in closed] == [(sale.id, 'cancelled')]
    assert qty(shop, 'Dark') == 2 and shop.store.pending_stripe() == []
    assert shop.checkout.close_pending(gateway) == []


def test_close_pending_stops_when_stripe_does_not_answer(shop):
    class Down(FakeGateway):
        def status(self, session):
            raise RuntimeError('sin red')

    stripe_sale(shop, FakeGateway())
    with pytest.raises(RuntimeError):
        shop.checkout.close_pending(Down())
    assert len(shop.store.pending_stripe()) == 1


# --- review fixes ----------------------------------------------------------------------------

def test_inventory_stays_with_the_account_it_was_built_for(tmp_path, monkeypatch):
    from src.core import persistence as module

    who = {'name': 'ana'}
    monkeypatch.setattr(module, 'current_account_name', lambda: who['name'])
    monkeypatch.setattr(module, 'uses_private_storage', lambda account: account is not None)
    monkeypatch.setattr(module, 'user_data_root', lambda account: str(tmp_path / 'users' / account))
    persistence = PersistenceManager(str(tmp_path / 'collections'), str(tmp_path / 'decks'))
    persistence.save_collection(Collection(name='Ana', cards=[
        CollectionCard(card_id=1, name='Carta de Ana', variants=[
            CollectionVariant(variant_id='a1', set_code='ANA-001', rarity='Common', entries=[
                CollectionEntry(quantity=2, list_price=1.0)])])]), 'ana.json')
    inventory = Inventory(persistence, GameCollectionStore(lambda: str(tmp_path)))

    who['name'] = None  # a worker thread, or another login in the same browser
    items = inventory.items(['yugioh'])
    assert [item.name for item in items] == ['Carta de Ana']
    inventory.take([items[0].model_copy(update={'quantity': 1})])
    who['name'] = 'ana'
    assert persistence.load_collection('ana.json').cards[0].variants[0].entries[0].quantity == 1
    assert not (tmp_path / 'collections' / 'ana.json').exists()


def test_release_pending_frees_stock_without_asking_stripe(shop):
    sale = stripe_sale(shop, FakeGateway())
    released = shop.checkout.release_pending()
    assert [(one.id, one.status) for one in released] == [(sale.id, 'cancelled')]
    assert qty(shop, 'Dark') == 2 and shop.store.pending_stripe() == []
    assert 'panel de Stripe' in shop.store.get(sale.id).note
    assert shop.checkout.release_pending() == []


def test_stripe_is_never_called_while_the_sales_lock_is_held(shop):
    import threading

    held = []

    class Watching(FakeGateway):
        def _probe(self, name):
            free = []

            def knock():
                got = shop.store.lock.acquire(timeout=0.5)
                if got:
                    shop.store.lock.release()
                free.append(got)

            thread = threading.Thread(target=knock)
            thread.start()
            thread.join()
            if not free[0]:
                held.append(name)

        def create_checkout(self, sale, success_url):
            self._probe('create')
            return super().create_checkout(sale, success_url)

        def status(self, session):
            self._probe('status')
            return super().status(session)

        def expire(self, session):
            self._probe('expire')
            super().expire(session)

        def refund(self, session):
            self._probe('refund')
            super().refund(session)

    gateway = Watching()
    sale = stripe_sale(shop, gateway)
    shop.checkout.settle_stripe(sale.id, gateway)
    shop.checkout.cancel_stripe(sale.id, gateway)
    paid = stripe_sale(shop, gateway)
    gateway.state['cs_1'] = 'paid'
    assert shop.checkout.settle_stripe(paid.id, gateway).status == 'paid'
    assert shop.checkout.refund(paid.id, gateway).status == 'refunded'
    assert held == []
    assert qty(shop, 'Dark') == 2


def test_a_payment_settled_twice_gets_one_number_and_one_stock_move(shop):
    gateway = FakeGateway()
    sale = stripe_sale(shop, gateway)
    gateway.state['cs_1'] = 'paid'
    first = shop.checkout.settle_stripe(sale.id, gateway)
    second = shop.checkout.settle_stripe(sale.id, gateway)
    assert first.number == second.number and second.status == 'paid'
    refunded = shop.checkout.refund(sale.id, gateway)
    assert refunded.status == 'refunded' and qty(shop, 'Dark') == 2
    with pytest.raises(SaleError):
        shop.checkout.refund(sale.id, gateway)
    assert qty(shop, 'Dark') == 2
