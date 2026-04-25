from types import SimpleNamespace

from MealAgent.migrations.add_role_migration import iter_objects as iter_role_objects
from MealAgent.migrations.promote_all_to_admin import iter_objects as iter_admin_objects
from MealAgent.migrations.add_mealagent_hardening_fields import REQUIRED_PROPERTIES, plan_missing_properties


class _PagedQuery:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def fetch_objects(self, limit, offset=0):
        self.calls.append({"limit": limit, "offset": offset})
        return SimpleNamespace(objects=self.objects[offset : offset + limit])


def test_role_migration_iterates_past_first_page():
    query = _PagedQuery([SimpleNamespace(uuid=str(i), properties={}) for i in range(5)])
    collection = SimpleNamespace(query=query)

    objects = list(iter_role_objects(collection, page_size=2))

    assert len(objects) == 5
    assert query.calls == [
        {"limit": 2, "offset": 0},
        {"limit": 2, "offset": 2},
        {"limit": 2, "offset": 4},
    ]


def test_admin_migration_iterates_past_first_page():
    query = _PagedQuery([SimpleNamespace(uuid=str(i), properties={}) for i in range(4)])
    collection = SimpleNamespace(query=query)

    objects = list(iter_admin_objects(collection, page_size=3))

    assert len(objects) == 4
    assert query.calls == [
        {"limit": 3, "offset": 0},
        {"limit": 3, "offset": 3},
    ]


class _CollectionConfig:
    def __init__(self, property_names):
        self._property_names = property_names

    def get(self):
        return SimpleNamespace(properties=[SimpleNamespace(name=name) for name in self._property_names])


class _Collections:
    def __init__(self, properties_by_collection):
        self.properties_by_collection = properties_by_collection

    def exists(self, name):
        return name in self.properties_by_collection

    def get(self, name):
        return SimpleNamespace(config=_CollectionConfig(self.properties_by_collection[name]))


def test_hardening_migration_plans_new_schema_fields():
    client = SimpleNamespace(
        collections=_Collections(
            {
                "MealLogEntry": {"log_id"},
                "MealPlanItem": {"plan_id"},
                "PantryItem": {"user_id", "ingredient_name"},
                "ShoppingItem": {"list_id", "ingredient_name"},
            }
        )
    )

    missing = plan_missing_properties(client)

    assert {f"{spec.collection}.{spec.name}" for spec in missing} == {
        f"{spec.collection}.{spec.name}" for spec in REQUIRED_PROPERTIES
    }
