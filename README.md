# Estimador Agéntico de Copago y Cobertura

> Agente conversacional de orientación pre-atención médica para pacientes en Quito, Ecuador.
> Construido con **Google ADK + Gemini + FastAPI** para hackathon.

**Demo en vivo →** https://estimador-copago-quito-484146602083.us-central1.run.app

---

## ¿Qué hace?

El paciente escribe su síntoma en lenguaje natural. El agente:

1. **Clasifica el síntoma** → especialidad médica, tipo de atención (consulta / urgencia / emergencia) y nivel de urgencia
2. **Detecta señales de alarma** → si hay dolor de pecho, dificultad respiratoria o déficit neurológico, prioriza seguridad antes que costos
3. **Solicita el plan de seguro** → aseguradora, plan y deducible pendiente del año
4. **Calcula el gasto de bolsillo** → usando fórmulas determinísticas sobre datos locales
5. **Recomienda los 3 mejores prestadores de Quito** → rankeados por costo real esperado para ese plan

No diagnostica. No reemplaza al médico. No consulta sistemas reales de aseguradoras.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                        Usuario                               │
│              (browser — chat en lenguaje natural)           │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI  (server.py)                       │
│                                                             │
│   POST /chat      → corre el agente ADK                     │
│   POST /estimate  → llama recommend_provider directo        │
│   GET  /          → sirve index.html                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Google ADK Agent  (agent.py)                    │
│                                                             │
│   Modelo: Gemini 2.0 Flash                                  │
│   Rol: orquestador conversacional en español                │
│   Decide cuándo y con qué args llamar cada tool             │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐  │
│   │  FunctionTool: classify_symptom                     │  │
│   │  FunctionTool: estimate_benefit                     │  │
│   │  FunctionTool: recommend_provider                   │  │
│   └─────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │  llama tools
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Tools determinísticas (Python puro)            │
│                                                             │
│  classify_symptom   → keyword scoring + detección red flags │
│  estimate_benefit   → fórmulas copago/deducible por plan    │
│  recommend_provider → ranking por OOP real de cada prestador│
│                                                             │
│              Única fuente de datos                          │
│         data/datos_quemados_quito.json  (cargado en RAM)   │
└─────────────────────────────────────────────────────────────┘
```

### Principio de diseño clave

**El LLM no calcula nada.** El agente interpreta lenguaje natural, mantiene el hilo de conversación y decide qué tool llamar. La lógica financiera y el triage viven en funciones Python puras, determinísticas y testeables. Esto elimina alucinaciones en los números y hace el resultado auditable.

---

## Estructura del proyecto

```
medical-assistant/
│
├── app/
│   ├── agent.py                  # Definición del agente ADK + system prompt
│   ├── data_loader.py            # Carga y cacheo del JSON local
│   │
│   ├── tools/
│   │   ├── classify_symptom.py   # Triage: síntoma → especialidad + urgencia
│   │   ├── estimate_benefit.py   # Finanzas: copago + deducible + cobertura
│   │   └── recommend_provider.py # Ranking de prestadores por costo real
│   │
│   ├── tests/
│   │   └── test_tools.py         # 20 tests: unitarios, golden, negativos, seguridad
│   │
│   └── ui/
│       ├── server.py             # FastAPI: /chat /estimate /
│       └── static/index.html    # UI de chat con tutorial interactivo
│
├── data/
│   └── datos_quemados_quito.json # Única fuente de verdad de la demo
│
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Flujo conversacional

```
Paciente: "Me caí jugando fútbol y me duele la rodilla"
                │
                ▼
     [classify_symptom]
     specialty      = traumatologia
     attention_type = consulta
     urgency        = media
     red_flags      = []
                │
                ▼
     Agente pide: aseguradora, plan, deducible
                │
     Paciente selecciona: Vida Clara Plus / deducible $20
                │
                ▼
     [recommend_provider]  →  [estimate_benefit x proveedor]
     Clínica Pichincha     →  OOP: $10  (copago $10, ded. $0)
     Hospital Pasteur      →  OOP: $10
     Hospital Vozandes     →  OOP: $10
                │
                ▼
     Agente responde con top 3 + explicación del cálculo
```

**Caso de emergencia:**
```
Paciente: "Siento presión en el pecho y falta de aire"
                │
                ▼
     [classify_symptom]  detecta red_flags → emergencia inmediata
     Agente prioriza mensaje de SEGURIDAD antes que costos
     Luego calcula: copago emergencia + deducible completo pendiente
```

---

## Las tres tools en detalle

### `classify_symptom(symptom_text)`

Convierte texto libre en una ruta asistencial.

- Normaliza tildes y mayúsculas para tolerancia a errores de escritura
- Busca coincidencias en `symptom_router` del JSON (scoring por keywords)
- **Prioridad absoluta a señales de alarma**: cualquier red flag fuerza `attention_type = emergencia` y `urgency = alta`, independientemente del resto del síntoma
- Fallback a `medicina_general / consulta / baja` si no hay match

```python
classify_symptom("Me duele el pecho y no puedo respirar")
# → { specialty: "cardiologia", attention_type: "emergencia",
#     urgency: "alta", red_flags: ["dolor de pecho", "falta de aire"] }
```

### `estimate_benefit(insurer_id, plan_id, attention_type, ...)`

Calcula el gasto de bolsillo usando únicamente el JSON local.

| Tipo de atención | Fórmula |
|---|---|
| Consulta | `copago_fijo` del plan |
| Urgencia | `copago_urgencia` + share de laboratorio si aplica, menos deducible disponible |
| Emergencia | `copago_emergencia` + deducible pendiente completo |

Devuelve además las `assumptions` (explicación legible del cálculo) y `caveats` (advertencias del plan).

### `recommend_provider(city, specialty, attention_type, insurer_id, plan_id, deductible)`

Rankea los prestadores de Quito compatibles por costo real.

- Para **emergencias**: filtra solo por `service_types` (cualquier ER puede atender), no por especialidad
- Para **consultas/urgencias**: filtra por especialidad + tipo de servicio disponible
- Ranking primario: menor OOP
- Tiebreak en emergencia/urgencia: tier `preferente` gana sobre `estandar` (igual costo, mejor calidad)
- Tiebreak en consulta: menor precio base del prestador
- Devuelve top 3 + lista de rechazados con motivo

---

## Datos demo

Toda la lógica se alimenta de `data/datos_quemados_quito.json`. No hay llamadas a APIs externas.

### Planes disponibles

| Aseguradora | Plan | Deducible | Copago consulta | Copago urgencia | Copago emergencia |
|---|---|---|---|---|---|
| Vida Clara | Esencial | $120 | $15 | $35 | $60 |
| Vida Clara | Plus | $80 | $10 | $25 | $45 |
| Andes Salud | Familiar | $150 | $18 | $40 | $70 |
| Andes Salud | Preferente | $100 | $12 | $28 | $50 |
| Equa Benefits | Urbano | $180 | $20 | $45 | $75 |
| Equa Benefits | Ejecutivo | $90 | $12 | $30 | $48 |

> Los nombres de aseguradoras son ficticios, inspirados en el mercado ecuatoriano.

### Prestadores de Quito

| Prestador | Tier | Especialidades clave |
|---|---|---|
| Hospital Metropolitano | Preferente | Cardiología, Gastroenterología, Traumatología, Neurología |
| Hospital Vozandes Quito | Preferente | Medicina general, Pediatría, Ginecología, Traumatología |
| Hospital Axxis | Preferente | Medicina general, Traumatología, Neurología, Cardiología |
| Hospital Pasteur | Estándar | Medicina general, Traumatología, Ginecología |
| Clínica Pichincha | Estándar | Medicina general, Dermatología, Gastroenterología |
| Clínica Internacional Quito | Estándar | Medicina general, Ginecología, Pediatría, Cardiología |

---

## Tests

20 tests cubriendo tools unitarias, escenarios golden y casos negativos.

```bash
python3 -m pytest app/tests/test_tools.py -v
```

```
PASSED  TestClassifySymptom::test_knee_pain_maps_to_traumatologia
PASSED  TestClassifySymptom::test_chest_pain_is_emergencia
PASSED  TestClassifySymptom::test_stomach_ache_maps_to_gastro
PASSED  TestClassifySymptom::test_fever_maps_to_medicina_general
PASSED  TestClassifySymptom::test_dizziness_maps_to_neurologia
PASSED  TestClassifySymptom::test_unknown_symptom_fallback
PASSED  TestClassifySymptom::test_red_flag_neurological
PASSED  TestEstimateBenefit::test_consulta_vc_plus
PASSED  TestEstimateBenefit::test_emergencia_as_preferente
PASSED  TestEstimateBenefit::test_invalid_plan_returns_error
PASSED  TestEstimateBenefit::test_zero_deductible_no_deductible_applied
PASSED  TestRecommendProvider::test_returns_three_providers
PASSED  TestRecommendProvider::test_best_option_is_cheapest
PASSED  TestRecommendProvider::test_wrong_city_returns_error
PASSED  TestRecommendProvider::test_specialty_filter_respected
PASSED  TestGoldenScenarios::test_scenario_rodilla_vc_plus
PASSED  TestGoldenScenarios::test_scenario_pecho_as_preferente
PASSED  TestGoldenScenarios::test_scenario_gastritis_eb_ejecutivo
PASSED  TestNegativeCases::test_empty_deductible_accepted
PASSED  TestNegativeCases::test_chest_pain_always_emergencia

20 passed in 0.04s
```

---

## Ejecutar localmente

### 1. Requisitos

- Python 3.12+
- Google Gemini API Key ([obtener aquí](https://aistudio.google.com/app/apikey))

### 2. Instalación

```bash
git clone <repo>
cd medical-assistant
pip install -r requirements.txt
```

### 3. Configurar API key

```bash
cp .env.example .env
# Editar .env y poner GOOGLE_API_KEY=tu_key
```

### 4. Correr

```bash
export $(grep -v '^#' .env | xargs)
uvicorn app.ui.server:app --reload --port 8080
```

Abrir: http://localhost:8080

---

## Deploy en Cloud Run

El proyecto incluye `Dockerfile` listo para Cloud Run.

```bash
gcloud run deploy estimador-copago-quito \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_API_KEY=tu_key" \
  --memory 512Mi \
  --port 8080
```

El servicio escala a cero cuando no hay tráfico (costo $0 en inactividad).

**Para producción**, usar Secret Manager en lugar de variable de entorno:

```bash
gcloud secrets create google-api-key --data-file=- <<< "tu_key"
gcloud run services update estimador-copago-quito \
  --update-secrets="GOOGLE_API_KEY=google-api-key:latest" \
  --region us-central1
```

---

## Limitaciones declaradas

Este proyecto es una demo para hackathon con alcance deliberadamente acotado:

- **Solo Quito.** No cubre otras ciudades.
- **Datos quemados.** No consulta pólizas reales ni sistemas de aseguradoras.
- **No diagnóstica.** Orienta sobre especialidad y costo, no sobre condición médica.
- **No emite autorizaciones.** El flujo de preautorización real no está modelado.
- **Mapeo de síntomas simplificado.** Cubre casos frecuentes de baja a media complejidad.

En producción, `estimate_benefit` consumiría la API real de la aseguradora y `recommend_provider` consultaría un directorio de red actualizado.

---

## Stack técnico

| Capa | Tecnología |
|---|---|
| Agente | [Google ADK](https://google.github.io/adk-docs/) 2.1 |
| Modelo | Gemini 2.0 Flash |
| Backend | FastAPI + Uvicorn |
| Datos | JSON local (sin base de datos) |
| Frontend | HTML/CSS/JS vanilla |
| Deploy | Google Cloud Run |
| Tests | pytest |

---

## Contexto

Desarrollado para el reto **"Estimador Agéntico de Copago y Cobertura para el Paciente"** en hackathon de IA en salud. El requisito: un agente que ayude al paciente a entender su beneficio antes de atenderse — especialidad sugerida, copago exacto y hospital más conveniente de la red.
