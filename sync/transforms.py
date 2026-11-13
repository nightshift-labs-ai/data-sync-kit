"""Field mapping: each rule produces one target field from a source record.

Rule keys (combine as needed):
  to:       target field name (required)
  from:     source field name (rename / copy)
  concat:   list of source fields joined with `sep` (default " ")
  enum:     dict mapping source values to target values (unknown value -> error)
  date:     {in: strptime format, out: strftime format}
  default:  value used when the source value is missing or empty
  required: true -> error if the final value is empty
"""
from datetime import datetime


class MappingError(ValueError):
    pass


def _empty(v):
    return v is None or v == ""


def apply_rule(rule, rec):
    to = rule["to"]
    if "concat" in rule:
        parts = [str(rec.get(f)) for f in rule["concat"] if not _empty(rec.get(f))]
        val = rule.get("sep", " ").join(parts)
    elif "from" in rule:
        val = rec.get(rule["from"])
    else:
        val = None
    if _empty(val):
        val = rule.get("default", val)
    elif "enum" in rule:
        if val not in rule["enum"]:
            raise MappingError(f"{to}: value {val!r} not in enum map")
        val = rule["enum"][val]
    elif "date" in rule:
        try:
            val = datetime.strptime(str(val), rule["date"]["in"]).strftime(rule["date"]["out"])
        except ValueError:
            raise MappingError(f"{to}: bad date {val!r} (expected {rule['date']['in']})")
    if rule.get("required") and _empty(val):
        raise MappingError(f"{to}: required value is missing")
    return to, val


def map_record(mapping, rec):
    return dict(apply_rule(rule, rec) for rule in mapping)
