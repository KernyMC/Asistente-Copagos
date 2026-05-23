import json
import os

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "datos_quemados_quito.json")

_cache = None

def load_data() -> dict:
    global _cache
    if _cache is None:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache

def get_plan(insurer_id: str, plan_id: str) -> dict | None:
    data = load_data()
    for insurer in data["insurers"]:
        if insurer["insurer_id"] == insurer_id:
            for plan in insurer["plans"]:
                if plan["plan_id"] == plan_id:
                    return plan
    return None

def get_providers_for_specialty(specialty: str, attention_type: str) -> list[dict]:
    data = load_data()
    result = []
    for p in data["providers"]:
        if specialty in p["specialties"] and attention_type in p["service_types"]:
            result.append(p)
    return result

def get_all_insurers_summary() -> list[dict]:
    data = load_data()
    summary = []
    for ins in data["insurers"]:
        plans = [{"plan_id": p["plan_id"], "display_name": p["display_name"]} for p in ins["plans"]]
        summary.append({"insurer_id": ins["insurer_id"], "display_name": ins["display_name"], "plans": plans})
    return summary
