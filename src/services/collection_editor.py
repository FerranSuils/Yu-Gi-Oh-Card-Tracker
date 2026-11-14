from src.core.models import Collection, CollectionCard, CollectionVariant, CollectionEntry, ApiCard
from src.core.utils import generate_variant_id
import copy
from typing import List, Optional, Tuple

from src.core.pricing_models import apply_list_price
from src.core import stock_moves
from src.core.sales_models import SaleLine

# What a bulk action points at: (card_id, variant_id, language, condition, first_edition).
# None means "any", so a whole card is (card_id, None, None, None, None) and a collector row names all five.
BulkTarget = Tuple[int, Optional[str], Optional[str], Optional[str], Optional[bool]]


def _ygo_id(line: SaleLine):
    return int(line.card_id) if line.kind == 'stock' else None


class CollectionEditor:
    @staticmethod
    def set_list_price(entry: CollectionEntry, price: Optional[float], locked: Optional[bool] = None) -> bool:
        """Set an entry's sale price and lock. Returns True if it changed."""
        return apply_list_price(entry, price, locked)

    @staticmethod
    def take_stock(collection: Collection, line: SaleLine) -> None:
        """Sell the copies of a ticket line. Raises OutOfStock, changing nothing, if the pile is short."""
        stock_moves.take(collection, line, _ygo_id(line), lambda v: v.variant_id == line.variant_id)

    @staticmethod
    def return_stock(collection: Collection, line: SaleLine) -> None:
        """Put a sold line back, rebuilding the card, variant and pile if the sale emptied them."""
        stock_moves.give_back(
            collection, line, _ygo_id(line), lambda v: v.variant_id == line.variant_id,
            lambda: CollectionCard(card_id=_ygo_id(line), name=line.name),
            lambda: CollectionVariant(variant_id=line.variant_id, set_code=line.set_code, rarity=line.rarity,
                                      image_id=line.image_id))

    @staticmethod
    def get_quantity(
        collection: Collection,
        card_id: int,
        variant_id: Optional[str] = None,
        set_code: Optional[str] = None,
        rarity: Optional[str] = None,
        image_id: Optional[int] = None,
        language: str = 'EN',
        condition: str = 'Near Mint',
        first_edition: bool = False,
        storage_location: Optional[str] = None
    ) -> int:
        """
        Returns the quantity of a specific card entry (specific storage location).
        """
        target_card = next((c for c in collection.cards if c.card_id == card_id), None)
        if not target_card:
            return 0

        target_variant_id = variant_id
        if not target_variant_id and set_code and rarity:
             target_variant_id = generate_variant_id(card_id, set_code, rarity, image_id)

        if not target_variant_id:
            return 0

        target_variant = next((v for v in target_card.variants if v.variant_id == target_variant_id), None)
        if not target_variant:
            return 0

        target_entry = next((e for e in target_variant.entries
                             if e.language == language and
                                e.condition == condition and
                                e.first_edition == first_edition and
                                e.storage_location == storage_location), None)

        return target_entry.quantity if target_entry else 0

    @staticmethod
    def _find_entry(collection: Collection, card_id: int, variant_id: Optional[str], set_code: str,
                    rarity: str, image_id: Optional[int], language: str, condition: str,
                    first_edition: bool, storage_location: Optional[str]) -> Optional[CollectionEntry]:
        card = next((c for c in collection.cards if c.card_id == card_id), None)
        target_variant_id = variant_id or generate_variant_id(card_id, set_code, rarity, image_id)
        variant = next((v for v in card.variants if v.variant_id == target_variant_id), None) if card else None
        if variant is None:
            return None
        return next((e for e in variant.entries if e.language == language and e.condition == condition and
                     e.first_edition == first_edition and e.storage_location == storage_location), None)

    @staticmethod
    def get_total_quantity(
        collection: Collection,
        card_id: int,
        variant_id: Optional[str] = None,
        set_code: Optional[str] = None,
        rarity: Optional[str] = None,
        image_id: Optional[int] = None,
        language: str = 'EN',
        condition: str = 'Near Mint',
        first_edition: bool = False
    ) -> int:
        """
        Returns the total quantity of a card configuration across all storage locations.
        """
        target_card = next((c for c in collection.cards if c.card_id == card_id), None)
        if not target_card:
            return 0

        target_variant_id = variant_id
        if not target_variant_id and set_code and rarity:
             target_variant_id = generate_variant_id(card_id, set_code, rarity, image_id)

        if not target_variant_id:
            return 0

        target_variant = next((v for v in target_card.variants if v.variant_id == target_variant_id), None)
        if not target_variant:
            return 0

        total = 0
        for e in target_variant.entries:
            if (e.language == language and
                e.condition == condition and
                e.first_edition == first_edition):
                total += e.quantity
        return total

    @staticmethod
    def apply_change(
        collection: Collection,
        api_card: ApiCard,
        set_code: str,
        rarity: str,
        language: str,
        quantity: int,
        condition: str,
        first_edition: bool,
        image_id: Optional[int] = None,
        variant_id: Optional[str] = None,
        mode: str = 'SET',
        storage_location: Optional[str] = None
    ) -> bool:
        """
        Applies a change (add, set, remove) to a collection.
        Returns True if the collection was modified, False otherwise.
        """
        modified = False

        # 1. Find or Create CollectionCard
        target_card = None
        for c in collection.cards:
            if c.card_id == api_card.id:
                target_card = c
                break

        if not target_card:
            # If removing/setting 0 and it doesn't exist, do nothing
            if quantity <= 0 and mode == 'SET':
                return False
            # Only create if we are adding positive amount
            if (mode == 'ADD' and quantity <= 0) or (mode == 'SET' and quantity <= 0):
                return False

            target_card = CollectionCard(card_id=api_card.id, name=api_card.name)
            collection.cards.append(target_card)
            modified = True

        # 2. Determine Variant ID
        target_variant_id = variant_id
        if not target_variant_id:
             target_variant_id = generate_variant_id(api_card.id, set_code, rarity, image_id)

        # 3. Find or Create CollectionVariant
        target_variant = None
        for v in target_card.variants:
            if v.variant_id == target_variant_id:
                target_variant = v
                break

        if not target_variant:
             # Need to add if quantity > 0
             should_add = False
             if mode == 'SET' and quantity > 0: should_add = True
             elif mode == 'ADD' and quantity > 0: should_add = True

             if should_add:
                 target_variant = CollectionVariant(
                     variant_id=target_variant_id,
                     set_code=set_code,
                     rarity=rarity,
                     image_id=image_id
                 )
                 target_card.variants.append(target_variant)
                 modified = True

        if target_variant:
            # 4. Find or Create CollectionEntry
            target_entry = None
            for e in target_variant.entries:
                if (e.condition == condition and
                    e.language == language and
                    e.first_edition == first_edition and
                    e.storage_location == storage_location):
                    target_entry = e
                    break

            # 5. Calculate New Quantity
            final_quantity = 0
            current_quantity = target_entry.quantity if target_entry else 0

            if mode == 'SET':
                final_quantity = quantity
            elif mode == 'ADD':
                final_quantity = current_quantity + quantity

            # 6. Apply Quantity Change
            if final_quantity > 0:
                if target_entry:
                    if target_entry.quantity != final_quantity:
                        target_entry.quantity = final_quantity
                        modified = True
                else:
                    target_variant.entries.append(CollectionEntry(
                        condition=condition,
                        language=language,
                        first_edition=first_edition,
                        quantity=final_quantity,
                        storage_location=storage_location
                    ))
                    modified = True
            else:
                if target_entry:
                    target_variant.entries.remove(target_entry)
                    modified = True

            # 7. Cleanup Empty Variant
            if not target_variant.entries:
                target_card.variants.remove(target_variant)
                modified = True

        # 8. Cleanup Empty Card
        if not target_card.variants:
            if target_card in collection.cards:
                collection.cards.remove(target_card)
                modified = True

        return modified

    @staticmethod
    def move_card(
        collection: Collection,
        api_card: ApiCard,
        set_code: str,
        rarity: str,
        language: str,
        condition: str,
        first_edition: bool,
        from_storage: Optional[str],
        to_storage: Optional[str],
        quantity: int = 1,
        image_id: Optional[int] = None,
        variant_id: Optional[str] = None
    ) -> bool:
        """
        Moves a specific quantity of a card from one storage location to another.
        """
        if from_storage == to_storage:
            return False

        # Verify availability
        available = CollectionEditor.get_quantity(
            collection, api_card.id, variant_id, set_code, rarity, image_id,
            language, condition, first_edition, from_storage
        )

        if available < quantity:
            return False

        # Remember the sale price: the target may be a brand-new entry.
        source = CollectionEditor._find_entry(collection, api_card.id, variant_id, set_code, rarity, image_id,
                                              language, condition, first_edition, from_storage)
        source_price = (source.list_price, source.price_locked) if source else (None, False)
        target_existed = CollectionEditor._find_entry(collection, api_card.id, variant_id, set_code, rarity,
                                                      image_id, language, condition, first_edition,
                                                      to_storage) is not None

        # Remove from Source
        removed = CollectionEditor.apply_change(
            collection, api_card, set_code, rarity, language, -quantity,
            condition, first_edition, image_id, variant_id, mode='ADD',
            storage_location=from_storage
        )

        # Add to Target
        added = CollectionEditor.apply_change(
            collection, api_card, set_code, rarity, language, quantity,
            condition, first_edition, image_id, variant_id, mode='ADD',
            storage_location=to_storage
        )

        if added and not target_existed:
            target = CollectionEditor._find_entry(collection, api_card.id, variant_id, set_code, rarity,
                                                  image_id, language, condition, first_edition, to_storage)
            if target is not None:
                CollectionEditor.set_list_price(target, source_price[0], source_price[1])

        return removed or added

    @staticmethod
    def rename_storage_location(collection: Collection, old_name: str, new_name: str) -> bool:
        """
        Updates all references of a storage location in the collection to a new name.
        Returns True if any changes were made.
        """
        if old_name == new_name:
            return False

        modified = False
        for card in collection.cards:
            for variant in card.variants:
                for entry in variant.entries:
                    if entry.storage_location == old_name:
                        entry.storage_location = new_name
                        modified = True

        return modified

    @staticmethod
    def select_entries(collection: Collection, targets: List[BulkTarget]):
        """Every (card, variant, entry) that one of the targets points at, each only once."""
        found, seen = [], set()
        for card in collection.cards:
            for variant in card.variants:
                for entry in variant.entries:
                    for card_id, variant_id, language, condition, first in targets:
                        if (card.card_id == card_id
                                and variant_id in (None, variant.variant_id)
                                and language in (None, entry.language)
                                and condition in (None, entry.condition)
                                and first in (None, entry.first_edition)):
                            if id(entry) not in seen:
                                seen.add(id(entry))
                                found.append((card, variant, entry))
                            break
        return found

    @staticmethod
    def _drop_empty(collection: Collection) -> None:
        for card in collection.cards:
            for variant in card.variants:
                variant.entries = [e for e in variant.entries if e.quantity > 0]
            card.variants = [v for v in card.variants if v.entries]
        collection.cards = [c for c in collection.cards if c.variants]

    @staticmethod
    def bulk_remove(collection: Collection, targets: List[BulkTarget]) -> int:
        """Removes every selected copy. Returns how many cards left the collection."""
        picked = CollectionEditor.select_entries(collection, targets)
        removed = sum(entry.quantity for _, _, entry in picked)
        for _, _, entry in picked:
            entry.quantity = 0
        CollectionEditor._drop_empty(collection)
        return removed

    @staticmethod
    def _merge_entries(variant: CollectionVariant) -> None:
        """Entries are unique by condition, language, edition and place: equal ones add up, the one that has a sale price keeps it."""
        merged = {}
        for entry in variant.entries:
            key = (entry.condition, entry.language, entry.first_edition, entry.storage_location)
            if key in merged:
                merged[key].quantity += entry.quantity
                if merged[key].list_price is None and entry.list_price is not None:
                    merged[key].list_price, merged[key].price_locked = entry.list_price, entry.price_locked
            else:
                merged[key] = entry
        variant.entries = list(merged.values())

    @staticmethod
    def bulk_assign_storage(collection: Collection, targets: List[BulkTarget], storage: Optional[str]) -> int:
        """Puts every selected copy in this storage (None = no place). Returns how many cards were affected."""
        picked = CollectionEditor.select_entries(collection, targets)
        touched = {}
        count = 0
        for _, variant, entry in picked:
            if entry.storage_location != storage:
                entry.storage_location = storage
                count += entry.quantity
            touched[id(variant)] = variant
        for variant in touched.values():
            CollectionEditor._merge_entries(variant)
        return count

    @staticmethod
    def bulk_set_attributes(collection: Collection, targets: List[BulkTarget], condition: Optional[str] = None,
                            language: Optional[str] = None, first_edition: Optional[bool] = None) -> int:
        """Gives every selected stack this condition / language / edition (None = leave as is).

        Stacks that end up equal (same condition, language, edition and place) are merged.
        Returns how many cards were affected.
        """
        picked = CollectionEditor.select_entries(collection, targets)
        touched, count = {}, 0
        for _, variant, entry in picked:
            before = (entry.condition, entry.language, entry.first_edition)
            if condition is not None:
                entry.condition = condition
            if language is not None:
                entry.language = language
            if first_edition is not None:
                entry.first_edition = first_edition
            if before != (entry.condition, entry.language, entry.first_edition):
                count += entry.quantity
            touched[id(variant)] = variant
        for variant in touched.values():
            CollectionEditor._merge_entries(variant)
        return count

    @staticmethod
    def bulk_set_rarity(collection: Collection, targets: List[BulkTarget], rarity: str, lookup):
        """Moves the selected copies to the printing of this rarity within the same set code.

        ``lookup(card_id, set_code, rarity)`` returns ``(variant_id, image_id)`` of that printing, or None
        when the card has no such rarity in that set: those copies stay as they are.
        Returns (moved, skipped) copies.
        """
        moved = skipped = 0
        for card, variant, entry in CollectionEditor.select_entries(collection, targets):
            if variant.rarity == rarity:
                continue
            found = lookup(card.card_id, variant.set_code, rarity)
            if not found:
                skipped += entry.quantity
                continue
            variant_id, image_id = found
            dest = next((v for v in card.variants if v.variant_id == variant_id), None)
            if dest is None:
                dest = CollectionVariant(variant_id=variant_id, set_code=variant.set_code, rarity=rarity,
                                         image_id=image_id if image_id is not None else variant.image_id)
                card.variants.append(dest)
            dest.entries.append(copy.deepcopy(entry))
            CollectionEditor._merge_entries(dest)
            moved += entry.quantity
            entry.quantity = 0
        CollectionEditor._drop_empty(collection)
        return moved, skipped

    @staticmethod
    def set_entry_quantity(collection: Collection, card_id: int, variant_id: str, language: str, condition: str,
                           first_edition: bool, storage_location: Optional[str], quantity: int) -> bool:
        """Sets the number of one stack of cards; 0 removes it."""
        for card in collection.cards:
            if card.card_id != card_id:
                continue
            for variant in card.variants:
                if variant.variant_id != variant_id:
                    continue
                for entry in variant.entries:
                    if (entry.language == language and entry.condition == condition and
                            entry.first_edition == first_edition and entry.storage_location == storage_location):
                        if entry.quantity == quantity:
                            return False
                        entry.quantity = max(0, quantity)
                        CollectionEditor._drop_empty(collection)
                        return True
        return False

    @staticmethod
    def transfer(source: Collection, target: Collection, targets: List[BulkTarget]) -> int:
        """Moves the selected copies into another collection, adding to the stacks it already has."""
        if source is target:
            return 0
        picked = CollectionEditor.select_entries(source, targets)
        moved = 0
        for card, variant, entry in picked:
            dest_card = next((c for c in target.cards if c.card_id == card.card_id), None)
            if dest_card is None:
                dest_card = CollectionCard(card_id=card.card_id, name=card.name)
                target.cards.append(dest_card)
            dest_variant = next((v for v in dest_card.variants if v.variant_id == variant.variant_id), None)
            if dest_variant is None:
                dest_variant = CollectionVariant(variant_id=variant.variant_id, set_code=variant.set_code,
                                                 rarity=variant.rarity, image_id=variant.image_id)
                dest_card.variants.append(dest_variant)
            dest_variant.entries.append(copy.deepcopy(entry))
            CollectionEditor._merge_entries(dest_variant)
            moved += entry.quantity
        for _, _, entry in picked:
            entry.quantity = 0
        CollectionEditor._drop_empty(source)
        return moved
