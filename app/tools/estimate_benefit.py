"""
Financial estimation tool: calculates copay, deductible applied and coverage %.
Pure deterministic logic using local JSON data only.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data_loader import get_plan

ATTENTION_TYPE_MAP = {
    "consulta": "consult_copay_usd",
    "urgencia": "urgent_care_copay_usd",
    "emergencia": "emergency_copay_usd",
}

INCLUDES_LABS = ["urgencia"]
INCLUDES_IMAGING = []


def estimate_benefit(
    insurer_id: str,
    plan_id: str,
    attention_type: str,
    specialty: str,
    deductible_remaining_usd: float,
    provider_base_price_usd: float = 0.0,
    provider_lab_price_usd: float = 0.0,
    provider_imaging_price_usd: float = 0.0,
) -> dict:
    """
    Estimates out-of-pocket cost for a given plan, attention type and provider prices.

    Returns dict with: copay_estimate_usd, deductible_applied_usd, coverage_pct,
                       total_out_of_pocket_usd, assumptions, caveats
    """
    plan = get_plan(insurer_id, plan_id)
    if plan is None:
        return {
            "error": f"Plan '{plan_id}' de aseguradora '{insurer_id}' no encontrado en datos demo.",
            "copay_estimate_usd": None,
        }

    assumptions = []
    caveats = []
    deductible_applied = 0.0

    # Base copay
    copay_key = ATTENTION_TYPE_MAP.get(attention_type, "consult_copay_usd")
    copay = plan[copay_key]
    assumptions.append(f"Copago fijo del plan para '{attention_type}': ${copay}")

    # Coverage percentage for reference
    hosp_cov = plan["hospitalization_coverage_in_network_pct"]
    lab_cov = plan["lab_coverage_in_network_pct"]
    img_cov = plan["imaging_coverage_in_network_pct"]

    extra_costs = 0.0

    # Emergencia: full remaining deductible applies directly on top of copay
    if attention_type == "emergencia" and deductible_remaining_usd > 0:
        deductible_applied += deductible_remaining_usd
        extra_costs += deductible_remaining_usd
        assumptions.append(f"Deducible pendiente aplicado a emergencia: ${deductible_remaining_usd:.2f}")

    # Labs (urgency and emergency typically include labs)
    if attention_type in INCLUDES_LABS and provider_lab_price_usd > 0:
        lab_patient_share = round(provider_lab_price_usd * (1 - lab_cov), 2)
        if deductible_remaining_usd > 0:
            ded_used = min(deductible_remaining_usd, lab_patient_share)
            deductible_applied += ded_used
            lab_patient_share = max(0, lab_patient_share - ded_used)
            assumptions.append(f"Deducible aplicado a laboratorio: ${ded_used:.2f}")
        extra_costs += lab_patient_share
        assumptions.append(f"Laboratorio estimado (paciente paga): ${lab_patient_share:.2f} ({int(lab_cov*100)}% cobertura)")

    # Imaging (emergency typically includes imaging)
    if attention_type in INCLUDES_IMAGING and provider_imaging_price_usd > 0:
        img_patient_share = round(provider_imaging_price_usd * (1 - img_cov), 2)
        remaining_ded = max(0, deductible_remaining_usd - deductible_applied)
        if remaining_ded > 0:
            ded_used = min(remaining_ded, img_patient_share)
            deductible_applied += ded_used
            img_patient_share = max(0, img_patient_share - ded_used)
            assumptions.append(f"Deducible aplicado a imágenes: ${ded_used:.2f}")
        extra_costs += img_patient_share
        assumptions.append(f"Imágenes estimadas (paciente paga): ${img_patient_share:.2f} ({int(img_cov*100)}% cobertura)")

    total_oop = round(copay + extra_costs, 2)

    caveats.append("Estimación demo: no reemplaza validación real con la aseguradora.")
    if plan.get("requires_preauthorization_for_hospitalization") and attention_type in ("urgencia", "emergencia"):
        caveats.append("Este plan puede requerir preautorización para hospitalización.")

    return {
        "copay_estimate_usd": copay,
        "deductible_applied_usd": round(deductible_applied, 2),
        "coverage_pct": int(hosp_cov * 100),
        "total_out_of_pocket_usd": total_oop,
        "assumptions": assumptions,
        "caveats": caveats,
    }
