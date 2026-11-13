import pytest

from sync.transforms import MappingError, map_record

MAPPING = [
    {"to": "crm_id", "from": "id"},
    {"to": "full_name", "concat": ["first_name", "last_name"], "sep": " "},
    {"to": "status", "from": "status", "enum": {"A": "Active", "I": "Inactive"}},
    {"to": "signup_date", "from": "created", "date": {"in": "%Y-%m-%d", "out": "%d/%m/%Y"}},
    {"to": "phone", "from": "phone", "default": "n/a"},
    {"to": "email", "from": "email", "required": True},
]
REC = {"id": 7, "first_name": "Ana", "last_name": "Petrova", "status": "I", "created": "2026-01-05", "email": "a@x.io"}


def test_all_transforms():
    assert map_record(MAPPING, REC) == {"crm_id": 7, "full_name": "Ana Petrova", "status": "Inactive",
                                        "signup_date": "05/01/2026", "phone": "n/a", "email": "a@x.io"}


def test_concat_skips_missing_parts():
    assert map_record([MAPPING[1]], {"first_name": "Ana"}) == {"full_name": "Ana"}


@pytest.mark.parametrize("patch, msg", [({"status": "X"}, "enum"), ({"created": "05/01/2026"}, "bad date"),
                                        ({"email": ""}, "required")])
def test_bad_values_raise(patch, msg):
    with pytest.raises(MappingError, match=msg):
        map_record(MAPPING, {**REC, **patch})
