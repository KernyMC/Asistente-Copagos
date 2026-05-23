"""
Unit tests for classify_symptom, estimate_benefit, recommend_provider.
Golden tests use demo_scenarios from the JSON data.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from tools.classify_symptom import classify_symptom
from tools.estimate_benefit import estimate_benefit
from tools.recommend_provider import recommend_provider
from data_loader import load_data


# ─── classify_symptom ────────────────────────────────────────────────────────

class TestClassifySymptom:
    def test_knee_pain_maps_to_traumatologia(self):
        r = classify_symptom("Me duele mucho la rodilla desde ayer y me cai jugando futbol")
        assert r["specialty"] == "traumatologia"
        assert r["attention_type"] == "consulta"
        assert not r["red_flags"]

    def test_chest_pain_is_emergencia(self):
        r = classify_symptom("Tengo presión en el pecho y falta de aire")
        assert r["attention_type"] == "emergencia"
        assert r["urgency"] == "alta"
        assert len(r["red_flags"]) > 0

    def test_stomach_ache_maps_to_gastro(self):
        r = classify_symptom("Tengo dolor de estomago y reflujo hace dias")
        assert r["specialty"] == "gastroenterologia"
        assert r["attention_type"] == "consulta"

    def test_fever_maps_to_medicina_general(self):
        r = classify_symptom("Tengo fiebre y tos desde hace dos dias")
        assert r["specialty"] == "medicina_general"

    def test_dizziness_maps_to_neurologia(self):
        r = classify_symptom("Tengo mareo y dolor de cabeza fuerte")
        assert r["specialty"] == "neurologia"
        assert r["attention_type"] == "urgencia"

    def test_unknown_symptom_fallback(self):
        r = classify_symptom("xyzabc no reconocido")
        assert r["specialty"] == "medicina_general"
        assert r["follow_up_question"] is not None

    def test_red_flag_neurological(self):
        r = classify_symptom("Tengo debilidad en un lado y dificultad para hablar")
        assert r["attention_type"] == "emergencia"
        assert r["urgency"] == "alta"


# ─── estimate_benefit ────────────────────────────────────────────────────────

class TestEstimateBenefit:
    def test_consulta_vc_plus(self):
        r = estimate_benefit("vida_clara", "vc_plus", "consulta", "traumatologia", 20.0)
        assert r["copay_estimate_usd"] == 10
        assert r["total_out_of_pocket_usd"] == 10

    def test_emergencia_as_preferente(self):
        r = estimate_benefit("andes_salud", "as_preferente", "emergencia", "cardiologia", 100.0,
                             provider_base_price_usd=200, provider_lab_price_usd=28, provider_imaging_price_usd=95)
        assert r["copay_estimate_usd"] == 50
        assert r["total_out_of_pocket_usd"] >= 50

    def test_invalid_plan_returns_error(self):
        r = estimate_benefit("vida_clara", "plan_inexistente", "consulta", "medicina_general", 0)
        assert "error" in r

    def test_zero_deductible_no_deductible_applied(self):
        r = estimate_benefit("equa_benefits", "eb_ejecutivo", "consulta", "gastroenterologia", 0)
        assert r["deductible_applied_usd"] == 0
        assert r["copay_estimate_usd"] == 12


# ─── recommend_provider ──────────────────────────────────────────────────────

class TestRecommendProvider:
    def test_returns_three_providers(self):
        r = recommend_provider("Quito", "traumatologia", "consulta", "vida_clara", "vc_plus", 20)
        assert len(r["ranked_providers"]) <= 3
        assert len(r["ranked_providers"]) >= 1

    def test_best_option_is_cheapest(self):
        r = recommend_provider("Quito", "medicina_general", "consulta", "equa_benefits", "eb_ejecutivo", 0)
        if len(r["ranked_providers"]) > 1:
            costs = [p["estimated_out_of_pocket_usd"] for p in r["ranked_providers"]]
            assert costs[0] <= costs[1]

    def test_wrong_city_returns_error(self):
        r = recommend_provider("Guayaquil", "medicina_general", "consulta", "vida_clara", "vc_plus", 0)
        assert "error" in r

    def test_specialty_filter_respected(self):
        r = recommend_provider("Quito", "dermatologia", "consulta", "vida_clara", "vc_plus", 0)
        for p in r["ranked_providers"]:
            # Only Clinica Pichincha has dermatologia — verify no invalid provider slipped through
            assert p["provider_id"] in ["clinica_pichincha"]


# ─── Golden tests from demo_scenarios ────────────────────────────────────────

class TestGoldenScenarios:
    def _run_scenario(self, scenario):
        inp = scenario["input"]
        expected = scenario["expected_output_summary"]

        classify_result = classify_symptom(inp["symptom_text"])
        assert classify_result["specialty"] == expected["specialty"], (
            f"specialty mismatch for {scenario['scenario_id']}: "
            f"got {classify_result['specialty']}, expected {expected['specialty']}"
        )
        assert classify_result["attention_type"] == expected["attention_type"], (
            f"attention_type mismatch for {scenario['scenario_id']}"
        )

        rec = recommend_provider(
            city=inp["city"],
            specialty=classify_result["specialty"],
            attention_type=classify_result["attention_type"],
            insurer_id=inp["insurer_id"],
            plan_id=inp["plan_id"],
            deductible_remaining_usd=inp["deductible_remaining_usd"],
        )
        assert rec["best_option"] is not None, f"No provider found for {scenario['scenario_id']}"

    def test_scenario_rodilla_vc_plus(self):
        data = load_data()
        s = next(s for s in data["demo_scenarios"] if s["scenario_id"] == "rodilla_vc_plus")
        self._run_scenario(s)

    def test_scenario_pecho_as_preferente(self):
        data = load_data()
        s = next(s for s in data["demo_scenarios"] if s["scenario_id"] == "pecho_as_preferente")
        self._run_scenario(s)

    def test_scenario_gastritis_eb_ejecutivo(self):
        data = load_data()
        s = next(s for s in data["demo_scenarios"] if s["scenario_id"] == "gastritis_eb_ejecutivo")
        self._run_scenario(s)


# ─── Negative / edge cases ───────────────────────────────────────────────────

class TestNegativeCases:
    def test_empty_deductible_accepted(self):
        r = estimate_benefit("vida_clara", "vc_esencial", "consulta", "medicina_general", 0)
        assert r["copay_estimate_usd"] is not None

    def test_chest_pain_always_emergencia(self):
        for symptom in [
            "dolor de pecho",
            "presion en el pecho y sudor frio",
            "falta de aire y palpitaciones",
        ]:
            r = classify_symptom(symptom)
            assert r["attention_type"] == "emergencia", f"Failed for: {symptom}"
