"""Per-account category presentation; ledger category keys remain stable."""
import unicodedata
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.models import Category, Transaction
from bot.database.repositories import DEFAULT_CATEGORIES
from bot.services.i18n import CATEGORY_LABELS

ICON_KEYS = {'tools', 'plane', 'ticket', 'lock', 'piggy', 'card', 'brain', 'users', 'ruler', 'wifi', 'news', 'transfer', 'bed', 'cart', 'charity', 'wallet', 'trash', 'ship', 'pet', 'cloud', 'cook', 'food', 'sofa', 'art', 'apple', 'help', 'gas', 'game', 'other', 'washer', 'home', 'science', 'movie', 'ball', 'coffee', 'doctor', 'truck', 'glasses', 'monitor', 'water', 'party', 'pencil', 'key', 'beef', 'goal', 'hammer', 'cake', 'shield', 'hospital', 'hotel', 'store', 'money', 'umbrella', 'banknote', 'receipt', 'shirt', 'language', 'paw', 'tax', 'mobile', 'bank', 'building', 'laptop', 'car', 'sparkles', 'trend', 'scissors', 'brush', 'parking', 'trophy', 'power', 'chart', 'syringe', 'train', 'phone', 'medal', 'book', 'camera', 'pill', 'globe', 'coins', 'cat', 'lamp', 'fridge', 'pizza', 'bike', 'fuel', 'map', 'school', 'music', 'heart', 'fish', 'scale', 'tent', 'tv', 'printer', 'bus', 'wine', 'package', 'read', 'mountain', 'drive', 'trees', 'keyboard', 'sport', 'calc', 'flower', 'baby', 'eye', 'work', 'luggage', 'gift'}


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


async def category_catalog(session: AsyncSession, user_id: int) -> list[dict]:
    defaults = {name for _, name in DEFAULT_CATEGORIES}
    historical = set((await session.execute(select(Transaction.category).where(
        Transaction.user_id == user_id, Transaction.category.is_not(None)).distinct())).scalars())
    records = (await session.execute(select(Category).where(Category.user_id == user_id))).scalars().all()
    by_name = {item.name: item for item in records}
    result = []
    for name in sorted(defaults | historical | set(by_name)):
        record = by_name.get(name)
        result.append({"name": name, "display_name": record.display_name if record else None,
                       "name_uz":record.name_uz if record else None,"name_ru":record.name_ru if record else None,
                       "icon": record.icon if record and record.icon in ICON_KEYS else None,
                       "parent_name": record.parent_name if record else None,
                       "archived": record.is_archived if record else False,
                       "source": "default" if name in defaults else "custom" if record else "imported"})
    archived_parents = {item["name"] for item in result if item["archived"]}
    for item in result:
        item["archived"] = item["archived"] or item["parent_name"] in archived_parents
    return result


def validate_category(catalog: list[dict], name: str, parent: str | None, key: str | None = None) -> None:
    """Validate names across both languages and enforce a two-level, acyclic tree."""
    names = set()
    for item in catalog:
        if item["name"] == key:
            continue
        names.update(normalized(value) for value in (
            item["name"], item["display_name"] or item["name"], item.get("name_uz") or item["name"],item.get("name_ru") or item["name"],CATEGORY_LABELS.get(item["name"], item["name"])) )
    if normalized(name) in names:
        raise ValueError("Bunday kategoriya mavjud.")
    if parent:
        found = next((item for item in catalog if item["name"] == parent), None)
        if not found or found["parent_name"] or parent == key:
            raise ValueError("Asosiy kategoriyani tanlang.")
        if found.get('archived') and not any(item['name']==key and item['parent_name']==parent for item in catalog):
            raise ValueError("Avval asosiy kategoriyani tiklang.")
        if key and any(item["parent_name"] == key for item in catalog):
            raise ValueError("Subkategoriyali kategoriya asosiy bo‘lib qolishi kerak.")
