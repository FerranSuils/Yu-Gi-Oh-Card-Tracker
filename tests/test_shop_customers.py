import json
import os
import threading

import pytest

from src.core.shop_models import Customer
from src.services.shop.customers import CustomerError, CustomerStore


@pytest.fixture
def store(tmp_path):
    return CustomerStore(str(tmp_path))


def test_add_and_list_customers_by_name(store):
    store.add('  Zoe  ', email='z@example.com')
    ana = store.add('ana', phone='600')
    assert [c.name for c in store.all()] == ['ana', 'Zoe']
    assert store.get(ana.id).phone == '600'
    assert store.get('nope') is None


def test_a_customer_needs_a_name(store):
    with pytest.raises(CustomerError):
        store.add('   ')


def test_long_fields_are_cut(store):
    customer = store.add('x' * 200, note='n' * 2000)
    assert len(customer.name) == 80 and len(customer.note) == 500


def test_update_changes_the_card_only(store):
    ana = store.add('Ana')
    store.post(ana.id, 'credit', 500, 'Regalo')
    store.update(ana.id, name='Ana B', email='a@b.c', phone='', note='vip')
    assert store.get(ana.id).name == 'Ana B'
    assert store.balance(ana.id, 'credit') == 500


def test_balance_is_the_sum_of_entries_per_kind(store):
    ana = store.add('Ana')
    store.post(ana.id, 'credit', 1000, 'Compra 000001', ref='p1')
    store.post(ana.id, 'credit', -350, 'Venta 000004', ref='s4')
    store.post(ana.id, 'consignment', 720, 'Venta 000005', ref='s5')
    assert store.balance(ana.id, 'credit') == 650
    assert store.balance(ana.id, 'consignment') == 720
    assert store.balances() == {ana.id: {'credit': 650, 'consignment': 720, 'points': 0}}
    assert [e.cents for e in store.entries(ana.id)] == [720, -350, 1000]  # newest first
    assert [e.ref for e in store.entries(ana.id, kind='credit')] == ['s4', 'p1']


def test_credit_cannot_go_below_zero(store):
    ana = store.add('Ana')
    store.post(ana.id, 'credit', 300, 'Ajuste')
    with pytest.raises(CustomerError) as error:
        store.post(ana.id, 'credit', -301, 'Venta')
    assert '3,00' in str(error.value)
    assert store.balance(ana.id, 'credit') == 300


def test_consignment_may_go_negative(store):
    ana = store.add('Ana')
    store.post(ana.id, 'consignment', -200, 'Devolución 000002')
    assert store.balance(ana.id, 'consignment') == -200


def test_post_refuses_nonsense(store):
    ana = store.add('Ana')
    for args in ((ana.id, 'credit', 0, 'x'), ('nope', 'credit', 5, 'x'), (ana.id, 'gems', 5, 'x'),
                 (ana.id, 'credit', 5, '  '), (ana.id, 'credit', 1.5, 'x'), (ana.id, 'credit', 10**10, 'x')):
        with pytest.raises(CustomerError):
            store.post(*args)
    assert store.entries(ana.id) == []


def test_customer_with_balance_cannot_be_removed(store):
    ana = store.add('Ana')
    store.post(ana.id, 'credit', 100, 'Ajuste')
    with pytest.raises(CustomerError):
        store.remove(ana.id)
    store.post(ana.id, 'credit', -100, 'Ajuste')
    store.remove(ana.id)
    assert store.all() == []
    assert len(store.entries(ana.id)) == 2  # the book is never rewritten


def test_data_survives_a_new_store(store, tmp_path):
    ana = store.add('Ana')
    store.post(ana.id, 'credit', 100, 'Ajuste')
    again = CustomerStore(str(tmp_path))
    assert again.get(ana.id).name == 'Ana' and again.balance(ana.id, 'credit') == 100
    assert again.lock is store.lock  # one lock per account, shared with sales


def test_a_broken_ledger_is_never_overwritten(store, tmp_path):
    ana = store.add('Ana')
    path = os.path.join(str(tmp_path), 'shop', 'ledger.json')
    with open(path, 'w', encoding='utf-8') as file:
        file.write('[{"broken"')
    with pytest.raises(CustomerError):
        store.post(ana.id, 'credit', 100, 'Ajuste')
    with open(path, encoding='utf-8') as file:
        assert file.read() == '[{"broken"'


def test_two_spends_at_once_cannot_overdraw(store):
    ana = store.add('Ana')
    store.post(ana.id, 'credit', 1000, 'Ajuste')
    failures = []

    def spend():
        try:
            store.post(ana.id, 'credit', -700, 'Venta')
        except CustomerError:
            failures.append(1)

    threads = [threading.Thread(target=spend) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(failures) == 5 and store.balance(ana.id, 'credit') == 300


def test_files_are_plain_json(store, tmp_path):
    store.add('Ana')
    with open(os.path.join(str(tmp_path), 'shop', 'customers.json'), encoding='utf-8') as file:
        assert json.load(file)[0]['name'] == 'Ana'
    assert isinstance(store.all()[0], Customer)
