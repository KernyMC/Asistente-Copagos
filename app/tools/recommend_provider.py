"""
Provider recommendation tool: ranks Quito providers by out-of-pocket cost for a given scenario.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data_loader import get_providers_for_specialty, get_plan, load_data
from tools.estimate_benefit import estimate_benefit


def recommend_provider(
    city: str,
    specialty: str,
    attention_type: str,
    insurer_id: str,
    plan_id: str,
    deductible_remaining_usd: float,
) -> dict:
    """
    Ranks compatible Quito providers by estimated patient cost.

    Returns dict with: ranked_providers, best_option, rejected_providers
    """
    if city.lower() != "quito":
        return {
            "error": "Esta demo solo cubre prestadores en Quito.",
            "ranked_providers": [],
        }

    plan = get_plan(insurer_id, plan_id)
    if plan is None:
        return {
            "error": f"Plan '{plan_id}' no encontrado.",
            "ranked_providers": [],
        }

    data = load_data()
    network_rules = data["network_rules"]
    out_of_net_penalty = network_rules["out_of_network_penalty_pct"]

    all_providers = [p for p in data["providers"] if p["city"].lower() == "quito"]

    # For emergencias filter only by service type — any ER can handle the case.
    # For other attention types, also require the specialty.
    if attention_type == "emergencia":
        compatible = [p for p in all_providers if attention_type in p["service_types"]]
    else:
        compatible = get_providers_for_specialty(specialty, attention_type)

    rejected = []
    for p in all_providers:
        if p not in compatible:
            reason = (f"No ofrece servicio de '{attention_type}'"
                      if attention_type == "emergencia"
                      else f"No ofrece '{specialty}' o '{attention_type}'")
            rejected.append({"provider_id": p["provider_id"], "display_name": p["display_name"], "reason": reason})

    ranked = []
    for provider in compatible:
        prices = provider["estimated_base_prices_usd"]
        base = prices.get(attention_type, 0)
        lab_price = prices.get("laboratorio", 0) if attention_type in ("urgencia", "emergencia") else 0
        img_price = prices.get("imagenes", 0) if attention_type == "emergencia" else 0

        est = estimate_benefit(
            insurer_id=insurer_id,
            plan_id=plan_id,
            attention_type=attention_type,
            specialty=specialty,
            deductible_remaining_usd=deductible_remaining_usd,
            provider_base_price_usd=base,
            provider_lab_price_usd=lab_price,
            provider_imaging_price_usd=img_price,
        )

        oop = est.get("total_out_of_pocket_usd", 999)
        tier = provider["network_tier"]
        base_price = provider["estimated_base_prices_usd"].get(attention_type, 999)

        # Primary sort: out-of-pocket cost.
        # Tiebreak for emergencia/urgencia: prefer preferente (0) over estandar (1).
        # Tiebreak for consulta: prefer lower base price.
        if attention_type in ("emergencia", "urgencia"):
            tier_rank = 0 if tier == "preferente" else 1
            sort_key = (round(oop, 2), tier_rank, base_price)
        else:
            sort_key = (round(oop, 2), base_price)

        ranked.append({
            "provider_id": provider["provider_id"],
            "display_name": provider["display_name"],
            "network_tier": tier,
            "estimated_out_of_pocket_usd": oop,
            "copay_usd": est.get("copay_estimate_usd"),
            "deductible_applied_usd": est.get("deductible_applied_usd", 0),
            "assumptions": est.get("assumptions", []),
            "caveats": est.get("caveats", []),
            "_sort_key": sort_key,
        })

    ranked.sort(key=lambda x: x["_sort_key"])  # (oop, base_price) tuple sort
    for r in ranked:
        r.pop("_sort_key")

    top3 = ranked[:3]
    best = top3[0] if top3 else None

    return {
        "ranked_providers": top3,
        "best_option": best,
        "rejected_providers": rejected,
    }
