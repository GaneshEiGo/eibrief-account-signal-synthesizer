"""
========================================================================================================================
  ███████╗██╗   ██╗██████╗ ██████╗ ██╗███████╗██╗███████╗
  ██╔════╝██║   ██║██╔══██╗██╔══██╗██║██╔════╝██║██╔════╝
  █████╗  ██║   ██║██████╔╝██████╔╝██║█████╗  ██║█████╗
  ██╔══╝  ██║   ██║██╔══██╗██╔══██╗██║██╔══╝  ██║██╔══╝
  ███████╗╚██████╔╝██████╔╝██║  ██║██║██║     ██║███████╗
  ╚══════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝╚══════╝

  EiBrief-AI Universal :: Enterprise Signal Synthesis OS
  Version : 6.0.0 "Dynamic Graphite"
  Author  : Kaduri Ganesh
================================================================================
"""

from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components

try:
    import google.generativeai as genai
    _HAS_GENAI = True
except ImportError:
    _HAS_GENAI = False

# ----------------------------------------------------------------------------
# FIXED CREDENTIALS (backend-only, never exposed to frontend)
# ----------------------------------------------------------------------------
_GEMINI_API_KEY =  st.secrets["GEMINI_API_KEY"]
_GEMINI_MODEL = "gemini-1.5-pro"

APP_NAME = "EiBrief-AI Universal"
APP_TAGLINE = "Just tell me what changed."
APP_VERSION = "6.0.0 Graphite"
DB_FILE = "eibrief_archive.db"

SEVERITY_WEIGHT = {
    "critical": 1.00,
    "high":     0.75,
    "medium":   0.50,
    "low":      0.25,
}

def _recency_weight(days_ago: int) -> float:
    if days_ago <= 0:  return 1.0
    if days_ago <= 2:  return 0.7
    if days_ago <= 7:  return 0.4
    if days_ago <= 14: return 0.25
    return 0.15

def risk_score(severity: str, days_ago: int) -> float:
    sev = SEVERITY_WEIGHT.get(str(severity).lower(), 0.5)
    rec = _recency_weight(days_ago)
    return round(sev * 0.7 + rec * 0.3, 2)

# ----------------------------------------------------------------------------
# SIGNAL-PARSING RISK DETECTOR (makes risks react to what you type)
# ----------------------------------------------------------------------------
RISK_RULES = [
    (["crack", "deflection", "strain", "pier", "span", "corrosion", "structural"], "Structural Integrity Breach", "critical"),
    (["depleted", "stockout", "shortage", "inventory"], "Supply / Stockout Risk", "high"),
    (["failing", "failed", "failure", "crash", "outage", "down", "closure", "blocked"], "Operational Failure", "high"),
    (["threshold", "limit", "exceed", "expanded", "spike"], "Threshold Breach", "high"),
    (["wind", "gust", "frost", "rain", "storm", "weather"], "Environmental Hazard", "medium"),
    (["latency", "slow", "backup", "congestion", "traffic"], "Flow / Performance Degradation", "medium"),
    (["overdue", "delayed", "behind", "pending", "waiting"], "Schedule Slippage", "medium"),
    (["dropped", "drop", "decline", "degraded", "errors"], "Metric Deterioration", "medium"),
]

def detect_risks_from_signals(signals: str) -> List["Risk"]:
    detected: List[Risk] = []
    seen = set()
    for keywords, category, severity in RISK_RULES:
        for kw in keywords:
            hit_line = next(
                (ln.strip() for ln in signals.splitlines() if kw in ln.lower()),
                None,
            )
            if hit_line and category not in seen:
                clean = re.sub(r"^\[.*?\]\s*", "", hit_line)
                detected.append(
                    Risk(category=category, severity=severity, days_ago=0, why=clean[:90])
                )
                seen.add(category)
                break
    return detected

def build_risk_pool(role: str, signals: str = "") -> List["Risk"]:
    pool = [Risk(c, s, d, w) for (c, s, d, w) in ROLES[role]["risks"]]
    if signals and signals.strip():
        pool = detect_risks_from_signals(signals) + pool
    best: Dict[str, Risk] = {}
    for r in pool:
        if r.category not in best or r.score > best[r.category].score:
            best[r.category] = r
    return sorted(best.values(), key=lambda r: -r.score)

def _h(html: str) -> str:
    """Strip indentation and blank lines so Streamlit renders HTML, not code."""
    lines = [ln.strip() for ln in html.splitlines()]
    return "\n".join(ln for ln in lines if ln)

# ============================================================================
# INDUSTRY TELEMETRY DATABASE (30 roles)
# ============================================================================
ROLES: Dict[str, Dict[str, Any]] = {
    "Software Engineer": {
        "sources": ["GitHub", "CI/CD", "Datadog", "Sentry", "Slack"],
        "signals": (
            "[GITHUB]   PR #1402 merged (checkout fix). CI on main FAILING at integration-tests.\n"
            "[SENTRY]   847 unhandled exceptions in 2h from payment-worker. P99 latency 4500ms.\n"
            "[DATADOG]  Error rate spiked to 8.2% on /api/v2/checkout.\n"
            "[SLACK]    @oncall: Database connection pool exhaustion across 3 replicas.\n"
            "[JIRA]     Sprint velocity dropped 23%. 14 tickets carried over."
        ),
        "risks": [
            ("CI pipeline failing on main", "high", 0, "blocks every deploy including the checkout fix"),
            ("P99 latency > 4s on checkout", "high", 0, "direct revenue impact, correlates with Sentry errors"),
            ("DB connection pool exhaustion", "high", 0, "cascading failure across downstream services"),
            ("Sprint velocity down 23%", "medium", 1, "delivery timeline at risk")
        ],
    },
    "Product Manager": {
        "sources": ["Jira", "Linear", "Figma", "Amplitude", "Notion"],
        "signals": (
            "[JIRA]      Epic 'Q4 Launch' is 12 days behind schedule. 3 critical-path items blocked.\n"
            "[FIGMA]     Checkout flow handoff pending eng review for 5 days.\n"
            "[AMPLITUDE] Mobile v3 DAU -18% vs 7d avg. Retention curve inflecting.\n"
            "[NOTION]    PRD has 47 unresolved engineering comments.\n"
            "[SLACK]     Stakeholder demo moved to Thursday, MVP needed by EOD Wednesday."
        ),
        "risks": [
            ("Q4 Launch epic 12 days late", "high", 0, "3 critical-path items blocked, no ETA"),
            ("Mobile DAU -18% WoW", "high", 0, "correlates with unresolved PRD comments"),
            ("Design handoff stalled 5 days", "medium", 0, "engineering cannot start checkout work")
        ],
    },
    "Designer / UX": {
        "sources": ["Figma", "Maze", "Hotjar", "UserTesting"],
        "signals": (
            "[FIGMA]      42 new comments on 'Checkout V3' in the last hour.\n"
            "[MAZE]       Usability test: task-completion rate dropped 62% to 41%.\n"
            "[HOTJAR]     Rage clicks detected on payment button (847 sessions).\n"
            "[USERTST]    5/8 participants failed the new onboarding flow.\n"
            "[SLACK]      Engineering says spec is still moving, no freeze."
        ),
        "risks": [
            ("Task-completion 62% to 41%", "high", 0, "regression in latest prototype"),
            ("Rage clicks on payment button", "high", 0, "847 sessions affected, revenue risk"),
            ("Onboarding 5/8 failures", "high", 1, "new user activation at risk")
        ],
    },
    "DevOps / SRE": {
        "sources": ["Kubernetes", "PagerDuty", "Datadog", "Terraform"],
        "signals": (
            "[K8S]        Pod CrashLoopBackOff api-gateway, 12 restarts in 1h.\n"
            "[PAGERDUTY]  SEV-2 ongoing, 2 engineers engaged 3h.\n"
            "[DATADOG]    Error budget burn rate 4.2x (should be <1x).\n"
            "[TERRAFORM]  Drift detected in prod cluster config (14 resources).\n"
            "[GRAFANA]    p99 latency 3200ms, 5x baseline."
        ),
        "risks": [
            ("Error budget burning 4.2x", "critical", 0, "freeze deploys needed immediately"),
            ("api-gateway CrashLoop 12 restarts", "high", 0, "user-facing, SEV-2 ongoing"),
            ("p99 latency 3200ms", "high", 0, "5x baseline, SLA risk")
        ],
    },
    "Cybersecurity": {
        "sources": ["Firewall", "IDS/IPS", "SIEM", "CrowdStrike"],
        "signals": (
            "[FIREWALL]  847 IPs blocked in last hour, top source 103.47.29.1.\n"
            "[IDS]       CVE-2024-8472 attempts: 47, all blocked.\n"
            "[SIEM]      Privilege escalation on svc-account-12, quarantined.\n"
            "[ENDPOINT]  Trojan.GenericKD on WORKSTATION-847, quarantined.\n"
            "[CROWDSTRIKE] Suspicious lateral movement from 10.0.47.128."
        ),
        "risks": [
            ("Privilege escalation quarantined", "critical", 0, "investigate lateral movement"),
            ("Endpoint malware detected", "high", 0, "user j.doe, scope review required"),
            ("Lateral movement detected", "high", 0, "10.0.47.128 suspicious activity")
        ],
    },
    "Data Science / ML": {
        "sources": ["MLflow", "Feature Store", "Airflow", "W&B"],
        "signals": (
            "[MLFLOW]    Model v4.2 AUC 0.84 to 0.71 in production.\n"
            "[FEATURE]   Drift detected on feature 'user_age_days' p<0.001.\n"
            "[AIRFLOW]   DAG 'daily_etl' failed 3 consecutive days.\n"
            "[WANDB]     Training loss diverged at epoch 47.\n"
            "[DATA QUAL]  Null rate on 'email' column jumped 2% to 18%."
        ),
        "risks": [
            ("Production AUC dropped 0.84 to 0.71", "critical", 0, "model degradation, business impact"),
            ("Feature drift significant p<0.001", "high", 0, "input distribution shift"),
            ("ETL DAG failed 3 days running", "high", 0, "data freshness at risk")
        ],
    },
    "Civil Engineer": {
        "sources": ["Structural Sensors", "Weather Station", "Drone", "Site Log"],
        "signals": (
            "[STRUCTURAL] Bridge deck-7 vibration 4.2Hz, threshold 3.8Hz.\n"
            "[WEATHER]    Wind gusts 112 km/h, threshold 80 km/h.\n"
            "[DRONE]      Expansion joint 12 crack 2.3mm, threshold 1.5mm.\n"
            "[SITE LOG]   Pour scheduled tomorrow; concrete truck delayed 4h.\n"
            "[SENSOR]     Rebar strain on pier-3 exceeded 85% capacity."
        ),
        "risks": [
            ("Bridge vibration above threshold", "high", 0, "sustained load or resonance risk"),
            ("Rebar strain >85% capacity", "critical", 0, "pier-3 structural risk"),
            ("Concrete truck delayed 4h", "low", 0, "pour schedule at risk")
        ],
    },
    "Electrical Engineer": {
        "sources": ["SCADA", "Transformers", "Power Quality", "Grid"],
        "signals": (
            "[SCADA]       Substation north-47 at 94.1% capacity (847/900 MW).\n"
            "[TRANSFORMER] TX-2847 oil temp 87C, threshold 75C.\n"
            "[PQ]          Phase L2 voltage -5% vs nominal, THD 6.8%.\n"
            "[DISPATCH]    Regional deficit 127 MW.\n"
            "[PROTECTION]  Relay trip on feeder-12, auto-reclose failed."
        ),
        "risks": [
            ("Transformer TX-2847 overheating", "critical", 0, "87C vs 75C threshold, oil degraded"),
            ("Substation at 94% capacity", "high", 0, "no headroom for demand spike"),
            ("Feeder-12 relay trip, reclose failed", "high", 0, "downstream outage risk")
        ],
    },
    "Mechanical Engineer": {
        "sources": ["Vibration Monitor", "Thermal Imaging", "CMMS"],
        "signals": (
            "[VIBRATION]  Compressor-C3 bearing 14.2 mm/s, threshold 7.1 mm/s.\n"
            "[THERMAL]    Motor-M17 hotspot 142C, baseline 87C.\n"
            "[LUBE]       Oil analysis shows metal particles 3x baseline.\n"
            "[CMMS]       12 overdue work orders > 7 days.\n"
            "[PREDICT]    Pump-P8 predicted failure in 72 hours."
        ),
        "risks": [
            ("Compressor-C3 bearing 14.2 mm/s", "critical", 0, "2x threshold, imminent failure"),
            ("Motor-M17 hotspot 142C", "high", 0, "63% above baseline"),
            ("Pump-P8 failure in 72h", "high", 0, "predicted by ML model")
        ],
    },
    "Energy / Power Plant": {
        "sources": ["Turbine", "Emissions", "Cooling", "Fuel"],
        "signals": (
            "[TURBINE]   Gas turbine-3 efficiency 42.3%, nominal.\n"
            "[EMISSIONS] NOx 47ppm vs 40ppm limit.\n"
            "[COOLING]   Tower-2 water temp 42C, threshold 35C.\n"
            "[FUEL]      Natural gas inventory 4.2 days, min 7 days.\n"
            "[BOILER]    Tube leak detected on unit-4, output derated 15%."
        ),
        "risks": [
            ("Cooling tower above threshold", "critical", 0, "derating likely within 6h"),
            ("NOx emissions over limit", "high", 0, "regulatory exposure, fines possible"),
            ("Boiler tube leak unit-4", "high", 0, "15% output derated")
        ],
    },
    "Healthcare / Medical": {
        "sources": ["ICU", "Pharmacy", "Lab", "EMR"],
        "signals": (
            "[ICU]       Bed 12 tachycardia 142 bpm, SpO2 87%.\n"
            "[PHARMACY]  Vancomycin stock 12 units, daily use 8.\n"
            "[LAB]       Blood cultures 47 pending, SLA 24h, avg turnaround 36h.\n"
            "[BEDS]      General ward 94% occupancy, 2 admits held in ED.\n"
            "[EMR]       Medication reconciliation errors +340% this week."
        ),
        "risks": [
            ("ICU-12 patient critical", "critical", 0, "tachycardia + low SpO2, immediate attention"),
            ("Lab turnaround 36h vs 24h SLA", "high", 0, "diagnostic delays across 47 cultures"),
            ("Med reconciliation errors +340%", "high", 1, "patient safety risk")
        ],
    },
    "Finance / Banking": {
        "sources": ["Risk", "Fraud", "Compliance", "Trading"],
        "signals": (
            "[RISK]     Portfolio VaR-95 USD 47.2M vs 50M limit (94.4%).\n"
            "[FRAUD]    Alert FRD-84729 blocked, risk score 94.\n"
            "[COMPLY]   3 overdue SAR filings (10d SLA).\n"
            "[SETTLE]   Equities fail rate 0.14% (12/8472).\n"
            "[TRADING]   Algo-X triggered 47 circuit breakers today."
        ),
        "risks": [
            ("VaR-95 at 94.4% of limit", "high", 0, "breach risk on next move"),
            ("3 overdue SAR filings", "high", 1, "regulatory exposure, fines"),
            ("Algo-X 47 circuit breakers", "high", 0, "algo behavior anomaly")
        ],
    },
    "Legal / Compliance": {
        "sources": ["Contracts", "Regulations", "Cases", "eDiscovery"],
        "signals": (
            "[CONTRACT]  3 renewals due within 7 days, 1 unsigned.\n"
            "[REG]       New data-privacy rule published, impact assessment pending.\n"
            "[CASE]      Matter M-2847 deposition in 48h, exhibit list incomplete.\n"
            "[EDISCOVERY] 47,000 docs unreviewed, production due Friday.\n"
            "[POLICY]    Anti-bribery training 68% complete, target 95%."
        ),
        "risks": [
            ("Unsigned contract renewal due in 7d", "high", 0, "auto-renewal risk, unfavorable terms"),
            ("New privacy rule impact unassessed", "high", 1, "compliance gap"),
            ("47K docs unreviewed, due Friday", "high", 0, "production deadline at risk")
        ],
    },
    "Marketing": {
        "sources": ["Google Ads", "Meta Ads", "HubSpot", "GA4"],
        "signals": (
            "[GADS]     Campaign 'Spring' CPA +42% WoW, spend on pace.\n"
            "[META]     CTR dropped 1.8% to 0.9% on carousel creative.\n"
            "[HUBSPOT]  MQL to SQL conversion 14% to 9% this week.\n"
            "[GA4]      Landing page bounce rate 68% (was 54%).\n"
            "[SEO]      3 high-value keywords dropped off page 1."
        ),
        "risks": [
            ("CPA +42% WoW", "high", 0, "budget efficiency collapse"),
            ("MQL to SQL conversion halved", "high", 0, "pipeline at risk"),
            ("Landing bounce +14pp", "medium", 0, "creative/offer mismatch")
        ],
    },
    "Sales": {
        "sources": ["Salesforce", "Gong", "Outreach", "Stripe"],
        "signals": (
            "[SFDC]     Q4 pipeline -22% vs target. 3 late-stage deals stalled.\n"
            "[GONG]     Win rate on enterprise tier 31% to 19%.\n"
            "[STRIPE]   Churn on mid-market 4.1% this month (target 2.5%).\n"
            "[OUTREACH] Reply rate dropped 8% to 3% on SDR sequences.\n"
            "[HUBSPOT]  47 opportunities no activity in 14 days."
        ),
        "risks": [
            ("Q4 pipeline -22% vs target", "critical", 0, "3 stalled late-stage deals"),
            ("Enterprise win rate halved", "high", 0, "competitive pressure"),
            ("Mid-market churn above target", "high", 3, "retention leak")
        ],
    },
    "HR / People Ops": {
        "sources": ["Workday", "Culture Amp", "ATS", "Lattice"],
        "signals": (
            "[WORKDAY]    Eng attrition 18% annualized (target 12%).\n"
            "[CULTUREAMP] eNPS dropped +42 to +11 this quarter.\n"
            "[ATS]        47 open reqs, 29 with no qualified candidates.\n"
            "[PAYROLL]    3 payroll exceptions, manual corrections needed.\n"
            "[LATTICE]    68% of managers overdue performance reviews."
        ),
        "risks": [
            ("Eng attrition 18% vs 12% target", "high", 0, "50% above plan, flight risk"),
            ("eNPS collapsed +42 to +11", "high", 0, "morale signal, cultural concern"),
            ("68% managers overdue reviews", "medium", 7, "compliance + engagement risk")
        ],
    },
    "Operations": {
        "sources": ["Zendesk", "Asana", "ServiceNow", "Slack"],
        "signals": (
            "[ZENDESK]   CSAT 4.1 to 3.6 this week.\n"
            "[ASANA]     14 tasks > 7 days overdue.\n"
            "[SLACK]     Vendor X invoice 21 days unpaid.\n"
            "[SERVICENOW] 47 open incidents, 8 P1.\n"
            "[PROCUREMENT] 3 contracts expiring in 14 days, no renewals."
        ),
        "risks": [
            ("CSAT dropped 0.5 in one week", "high", 0, "customer experience degradation"),
            ("8 P1 incidents open", "high", 0, "service delivery at risk"),
            ("3 contracts expiring 14d", "medium", 2, "vendor continuity risk")
        ],
    },
    "Manufacturing": {
        "sources": ["MES", "Quality", "Equipment", "SCADA"],
        "signals": (
            "[MES]        Line assembly-3 at 94.1% efficiency (target 95%).\n"
            "[QUALITY]    Defect rate 4.7% vs 2.0% threshold.\n"
            "[EQUIPMENT]  CNC-mill-12 vibration 12.4mm/s, predicted bearing fail 48h.\n"
            "[INVENTORY]  Raw material SKU-847 at 2 days supply (min 7).\n"
            "[SCADA]      Press-P4 cycle time +18% vs baseline."
        ),
        "risks": [
            ("Defect rate 2x threshold", "critical", 0, "scrap and rework spike"),
            ("CNC bearing predicted fail 48h", "high", 0, "unplanned downtime imminent"),
            ("SKU-847 at 2 days supply", "high", 1, "production stoppage risk")
        ],
    },
    "Construction": {
        "sources": ["Procore", "Sensors", "Weather", "BIM"],
        "signals": (
            "[PROCORE]    Phase 2 schedule slipped 8 days.\n"
            "[SENSOR]     Concrete cure temp below 10C for 6h.\n"
            "[WEATHER]    Rain forecast 5 days running.\n"
            "[SUB]        Electrical sub 2 weeks behind.\n"
            "[BIM]        12 new clashes detected in MEP coordination."
        ),
        "risks": [
            ("Phase 2 slipped 8 days", "high", 0, "critical path impact"),
            ("Concrete cure below min temp", "high", 0, "strength compromised"),
            ("12 new MEP clashes", "medium", 1, "rework required")
        ],
    },
    "Architecture": {
        "sources": ["BIM", "Permits", "Client Portal", "Revit"],
        "signals": (
            "[BIM]       Clash detection: 47 new MEP conflicts.\n"
            "[PERMIT]    City review 14 days overdue.\n"
            "[CLIENT]    3 scope-change requests pending sign-off.\n"
            "[REVIT]     Model coordination issue in tower core.\n"
            "[SCHEDULE]  Design phase 2 weeks behind plan."
        ),
        "risks": [
            ("47 MEP clashes unresolved", "high", 0, "construction rework, cost impact"),
            ("Permit review 14 days overdue", "high", 2, "start date at risk"),
            ("Pending scope changes", "medium", 0, "fee exposure")
        ],
    },
    "Agriculture / Farming": {
        "sources": ["Soil", "Weather", "Equipment", "Irrigation"],
        "signals": (
            "[SOIL]       Field 7 moisture 18% (target 28%).\n"
            "[WEATHER]    Frost warning tonight.\n"
            "[EQUIP]      Tractor 3 in service, ETA 2 days.\n"
            "[DRONE]      NDVI shows stress in north quadrant.\n"
            "[IRRIGATION] Zone 4 pump failure, 12h offline."
        ),
        "risks": [
            ("Field 7 moisture below target", "high", 0, "yield impact"),
            ("Frost warning tonight", "high", 0, "crop damage imminent"),
            ("Zone 4 pump failure", "medium", 0, "12h irrigation gap")
        ],
    },
    "Education / Training": {
        "sources": ["LMS", "Portal", "Attendance", "Grading"],
        "signals": (
            "[LMS]        Course completion 68% vs 85% target.\n"
            "[ATTEND]     Cohort 7 attendance 71% (threshold 80%).\n"
            "[PORTAL]     29 open support tickets > 48h.\n"
            "[GRADING]    12% of assignments ungraded past deadline.\n"
            "[SURVEY]     Instructor NPS dropped 38 to 21."
        ),
        "risks": [
            ("Course completion 17pp below target", "high", 0, "learning outcomes at risk"),
            ("Attendance below threshold", "high", 0, "engagement signal, retention risk"),
            ("12% assignments ungraded", "medium", 1, "feedback loop broken")
        ],
    },
    "Government / Public Sector": {
        "sources": ["Case System", "Budget", "Portal", "Audit"],
        "signals": (
            "[CASE]       847 cases > 30d SLA.\n"
            "[BUDGET]     Q3 spend at 94% of cap, 6 weeks left.\n"
            "[PORTAL]     Citizen satisfaction 3.4/5 (target 4.0).\n"
            "[PROCUREMENT] 47 POs awaiting approval > 14 days.\n"
            "[AUDIT]      12 findings from last quarter still open."
        ),
        "risks": [
            ("847 cases breached 30d SLA", "high", 0, "service delivery failure, public trust"),
            ("Budget 94% spent, 6 weeks left", "high", 0, "overrun risk"),
            ("12 audit findings still open", "high", 30, "compliance risk")
        ],
    },
    "Media / Entertainment": {
        "sources": ["Analytics", "CMS", "Ad Server", "CDN"],
        "signals": (
            "[ANALYTICS] Daily uniques -28% WoW.\n"
            "[CMS]       7 scheduled stories unpublished.\n"
            "[ADSERVER]  Fill rate 61% (target 80%).\n"
            "[SOCIAL]    Sentiment shifted negative (-34 NPS).\n"
            "[CDN]       Video buffering rate 12% (baseline 3%)."
        ),
        "risks": [
            ("Daily uniques -28% WoW", "high", 0, "audience decline"),
            ("Ad fill rate 19pp below target", "high", 0, "revenue hit"),
            ("Video buffering 12% vs 3%", "high", 0, "user experience, churn risk")
        ],
    },
    "Telecommunications": {
        "sources": ["NOC", "Customer", "Network", "OSS"],
        "signals": (
            "[NOC]       Cell tower cluster 7 down 45 min.\n"
            "[CUSTOMER]  Complaints +240% in affected region.\n"
            "[NETWORK]   Packet loss 4.2% on backbone link.\n"
            "[BILLING]   847 disputed charges pending.\n"
            "[OSS]       Provisioning failures +340% today."
        ),
        "risks": [
            ("Tower cluster down 45 min", "critical", 0, "regulatory reporting required"),
            ("Complaints +240% in region", "high", 0, "churn wave incoming"),
            ("Provisioning failures +340%", "high", 0, "new customer activation blocked")
        ],
    },
    "Nonprofit / NGO": {
        "sources": ["Donor DB", "Programs", "Grants", "Volunteers"],
        "signals": (
            "[DONOR]     Monthly recurring -14% MoM.\n"
            "[PROGRAM]   Field team 3: 42% of KPIs on track.\n"
            "[GRANT]     Report X due in 9 days, 60% drafted.\n"
            "[VOLUNTEER] 23% no-show rate on last event.\n"
            "[FINANCE]   Program spend 87% of budget, 3 months left."
        ),
        "risks": [
            ("Recurring donations -14% MoM", "high", 0, "funding runway at risk"),
            ("Grant report 60% done, 9d left", "high", 0, "compliance risk, future funding"),
            ("Program spend 87%, 3 months left", "medium", 5, "budget pressure")
        ],
    },
    "Supply Chain / Logistics": {
        "sources": ["WMS", "TMS", "Customs", "Fleet"],
        "signals": (
            "[WMS]       Warehouse 3 backlog +47% vs capacity.\n"
            "[TMS]       On-time delivery 78% (target 95%).\n"
            "[CUSTOMS]   2 containers held 5 days.\n"
            "[INVENTORY] SKU-847 stockout in 3 days.\n"
            "[FLEET]     14% of trucks offline for maintenance."
        ),
        "risks": [
            ("On-time delivery -17pp vs target", "critical", 0, "customer SLA breach"),
            ("Warehouse backlog +47%", "high", 0, "throughput collapse"),
            ("SKU-847 stockout in 3 days", "high", 0, "revenue at risk")
        ],
    },
    "Aerospace / Defense": {
        "sources": ["Telemetry", "QA", "Supply", "DO-178C"],
        "signals": (
            "[TELEMETRY] Test article vibration anomaly on run 47.\n"
            "[QA]        Non-conformance NCR-2847 open 21 days.\n"
            "[SUPPLY]    Titanium alloy lead time extended to 26 weeks.\n"
            "[FLIGHT]    Test-12 scrubbed due to weather.\n"
            "[DO-178C]   14 MC/DC coverage gaps in flight-control software."
        ),
        "risks": [
            ("Test vibration anomaly", "critical", 0, "safety review required before next run"),
            ("NCR open 21 days", "high", 0, "certification path blocked"),
            ("MC/DC coverage gaps", "high", 3, "DO-178C compliance risk")
        ],
    },
    "Automotive": {
        "sources": ["MES", "Quality", "Supply", "Warranty"],
        "signals": (
            "[MES]       Line B throughput 42 to 31 units/hr.\n"
            "[QUALITY]   Weld defect rate 1.8% (target 0.5%).\n"
            "[SUPPLY]    Chip shortage: 2 SKUs out 3 weeks.\n"
            "[WARRANTY]  Claims +47% on powertrain this quarter.\n"
            "[BATTERY]   Cell yield 94% (target 98%)."
        ),
        "risks": [
            ("Throughput -26% on Line B", "high", 0, "production miss"),
            ("Weld defect rate 3.6x target", "high", 0, "safety and recall risk"),
            ("Warranty claims +47%", "high", 7, "quality pattern")
        ],
    },
    "Real Estate": {
        "sources": ["CRM", "Market", "Property Mgmt", "Leasing"],
        "signals": (
            "[CRM]       3 listings expired, 2 under contract fell through.\n"
            "[MARKET]    Days-on-market +18% vs last quarter.\n"
            "[PROP]      4 maintenance requests > 7 days old.\n"
            "[LEASING]   Vacancy rate 8.2% (target 5%).\n"
            "[APPRAISAL] 3 properties appraised 12% below asking."
        ),
        "risks": [
            ("2 contracts fell through", "high", 0, "revenue miss"),
            ("Vacancy rate 8.2% vs 5%", "high", 3, "income at risk"),
            ("3 appraisals 12% below asking", "medium", 2, "pricing misalignment")
        ],
    },
    "Customer Success": {
        "sources": ["Gainsight", "Zendesk", "Usage", "NPS"],
        "signals": (
            "[GAINSIGHT] 12 accounts in red health tier.\n"
            "[ZENDESK]   CSAT dropped 4.2 to 3.6 this week.\n"
            "[USAGE]     Enterprise tier logins -31% MoM.\n"
            "[NPS]       Score dropped 42 to 28.\n"
            "[CHURN]     4 accounts > 80% churn risk score."
        ),
        "risks": [
            ("12 accounts in red health", "critical", 0, "revenue at risk, CSM intervention needed"),
            ("Enterprise logins -31% MoM", "high", 0, "adoption collapse, expansion blocked"),
            ("4 accounts > 80% churn risk", "high", 0, "immediate retention action")
        ],
    },
}

# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class Risk:
    category: str
    severity: str
    days_ago: int
    why: str

    @property
    def score(self) -> float:
        return risk_score(self.severity, self.days_ago)

    def to_markdown_line(self, index: int) -> str:
        age = "today" if self.days_ago <= 0 else f"{self.days_ago}d ago"
        return f"{index}. **{self.category}** -- `{self.severity.upper()}` -- score `{self.score}` -- {self.why} ({age})"

    def to_html_row(self, rank: int) -> str:
        age = "today" if self.days_ago <= 0 else f"{self.days_ago}d ago"
        sev = self.severity.lower()
        bar_color = "var(--graphite-900)" if sev == "critical" else "var(--graphite-700)" if sev == "high" else "var(--graphite-500)" if sev == "medium" else "var(--graphite-300)"
        return f"""
        <div class="risk-row">
            <div class="risk-row-top">
                <div class="risk-row-left">
                    <span class="risk-rank">{rank}</span>
                    <strong class="risk-category">{self.category}</strong>
                    <span class="pixel-badge">{self.severity.upper()}</span>
                </div>
                <span class="risk-score">{self.score}</span>
            </div>
            <div class="risk-reason">{self.why} <span class="risk-age">-- {age}</span></div>
            <div class="bar-track">
                <div class="bar-fill" style="width: {self.score * 100}%; background: {bar_color};"></div>
            </div>
        </div>
        """

@dataclass
class Brief:
    brief_id: str
    role: str
    project: str
    reader: str
    run_date: str
    changes: List[str]
    matters: str
    top_risks: List[Risk]
    action: str
    raw_signals: str
    confidence: float
    used_llm: bool

    def to_markdown(self) -> str:
        lines = [f"# {self.project} -- EiBrief", "", f"**Role:** {self.role}  ", f"**Reader:** {self.reader}  ", f"**Generated:** {self.run_date}  ", f"**Confidence:** {self.confidence:.0%}  ", f"**Mode:** {'AI Synthesis' if self.used_llm else 'Deterministic'}", "", "---", "", "## WHAT'S CHANGED (last 24h)"]
        for c in self.changes: lines.append(f"- {c}")
        lines += ["", "## WHAT MATTERS NOW", "", self.matters, "", "## TOP 3 RISKS (scored by deterministic rules)", ""]
        for i, r in enumerate(self.top_risks[:3], 1): lines.append(r.to_markdown_line(i))
        lines += ["", "## SUGGESTED NEXT ACTION", "", self.action, "", "---", "", f"*EiBrief-AI v{APP_VERSION} -- Kaduri Ganesh*"]
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["top_risks"] = [{"category": r.category, "severity": r.severity, "days_ago": r.days_ago, "why": r.why, "score": r.score} for r in self.top_risks]
        return d

    def to_html(self) -> str:
        changes_html = "\n".join(f'<li class="change-item">{c}</li>' for c in self.changes)
        risks_html = "\n".join(r.to_html_row(i) for i, r in enumerate(self.top_risks[:3], 1))
        mode_badge = "AI SYNTHESIS" if self.used_llm else "DETERMINISTIC"
        return f"""
        <div class="brief-rendered">
            <div class="brief-header">
                <div>
                    <h2 class="brief-title">{self.project}</h2>
                    <div class="brief-meta">{self.role} | {self.reader} | {self.run_date}</div>
                </div>
                <div class="brief-badges">
                    <span class="pixel-badge"><span class="status-dot"></span>VERIFIED</span>
                    <span class="pixel-badge">{self.confidence:.0%} CONFIDENCE</span>
                    <span class="pixel-badge">{mode_badge}</span>
                </div>
            </div>
            <div class="brief-section">
                <div class="section-label">WHAT'S CHANGED (LAST 24H)</div>
                <ul class="change-list">{changes_html}</ul>
            </div>
            <div class="brief-section">
                <div class="section-label">WHAT MATTERS NOW</div>
                <p class="matters-text">{self.matters}</p>
            </div>
            <div class="brief-section">
                <div class="section-label">TOP 3 RISKS (deterministic, not LLM)</div>
                <div class="risks-container">{risks_html}</div>
            </div>
            <div class="brief-section">
                <div class="section-label">SUGGESTED NEXT ACTION</div>
                <p class="action-text">{self.action}</p>
            </div>
        </div>
        """

# ============================================================================
# DATABASE LAYER (SQLite Archive with Auto-Migration)
# ============================================================================

def _db() -> sqlite3.Connection:
    """Auto-migrates old schemas to prevent column errors."""
    conn = sqlite3.connect(DB_FILE)
    table_info = conn.execute("PRAGMA table_info(briefs)").fetchall()
    if table_info:
        cols = [row[1] for row in table_info]
        if "role" not in cols or "project" not in cols or "reader" not in cols:
            conn.execute("DROP TABLE briefs")
            
    conn.execute("""
        CREATE TABLE IF NOT EXISTS briefs (
            brief_id   TEXT PRIMARY KEY,
            role       TEXT NOT NULL,
            project    TEXT NOT NULL,
            run_date   TEXT NOT NULL,
            reader     TEXT,
            brief_md   TEXT,
            brief_json TEXT,
            created_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_role_project ON briefs(role, project, run_date)")
    conn.commit()
    return conn

def save_brief(brief: Brief) -> None:
    with _db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO briefs
               (brief_id, role, project, run_date, reader, brief_md, brief_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (brief.brief_id, brief.role, brief.project, brief.run_date, brief.reader, brief.to_markdown(), json.dumps(brief.to_dict(), indent=2), datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()

def load_archive(limit: int = 200) -> List[Tuple]:
    with _db() as conn:
        return conn.execute("SELECT project, run_date, role, reader, brief_md, brief_id FROM briefs ORDER BY run_date DESC LIMIT ?", (limit,)).fetchall()

def archive_stats() -> Dict[str, int]:
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0]
        roles = conn.execute("SELECT COUNT(DISTINCT role) FROM briefs").fetchone()[0]
        projects = conn.execute("SELECT COUNT(DISTINCT project) FROM briefs").fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM briefs WHERE DATE(run_date) = DATE('now')").fetchone()[0]
    return {"total": total, "roles": roles, "projects": projects, "today": today}

# ============================================================================
# LLM SYNTHESIS ENGINE (Bulletproof JSON Mode & Human-Friendly Tone)
# ============================================================================

def _configure_gemini() -> bool:
    if not _HAS_GENAI: return False
    try:
        genai.configure(api_key=_GEMINI_API_KEY)
        return True
    except Exception:
        return False

def _llm_synthesise(role: str, signals: str, top_risks: List[Risk]) -> Optional[Dict[str, Any]]:
    risks_summary = "\n".join(f"- {r.category} ({r.severity}, score {r.score}): {r.why}" for r in top_risks[:3])
    prompt = f"""You are Ei, a highly empathetic and sharp senior analyst. Your job is to read messy, lengthy raw operational signals for a {role} and distill them into a clear, human-friendly executive brief. 

Write in plain, accessible English. Avoid technical jargon where possible. Explain *why* it matters in a way a non-technical executive could understand instantly without feeling overwhelmed.

Return a JSON object with exactly these keys:
1. "changes": A list of 3 to 5 concise bullet points summarizing what materially changed in the last 24 hours. Strip out the noise.
2. "matters": 1 to 2 sentences connecting the dots. Explain the real-world impact of these changes in a calm, professional tone.
3. "action": One single, clear sentence stating the most useful next step.

Do not use emojis. Ground every sentence strictly in the provided signals.

RAW SIGNALS:
{signals}

PRE-SCORED TOP RISKS:
{risks_summary}"""
    
    try:
        model = genai.GenerativeModel(_GEMINI_MODEL)
        resp = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.4,
                max_output_tokens=1500,
                response_mime_type="application/json"
            )
        )
        data = json.loads(resp.text)
        changes = data.get("changes", [])
        matters = data.get("matters", "")
        action = data.get("action", "")
        
        if not changes or not matters or not action: return None
        return {"changes": changes, "matters": matters, "action": action}
    except Exception:
        # Silent failure, triggers fallback
        return None

def _fallback_synthesise(signals: str, top_risks: List[Risk]) -> Dict[str, Any]:
    changes = []
    for ln in signals.splitlines():
        clean = re.sub(r"^\[.*?\]\s*", "", ln).strip()
        if clean: changes.append(clean)
    changes = changes[:5]
    if not changes: changes = ["No material changes detected in the signal window."]
    if top_risks:
        top = top_risks[0]
        matters = f"The signals above share an underlying story: the most urgent signal is {top.category.lower()}, which correlates with the broader pattern."
        action = f"Address {top.category.lower()} before any other work today; {top.why.lower()}"
    else:
        matters = "No material risks detected. The signals are within normal operating ranges."
        action = "Continue monitoring; no immediate action required."
    return {"changes": changes, "matters": matters, "action": action}

# ============================================================================
# CSS DESIGN SYSTEM (Monochrome Graphite, Minimal Vercel/Apple style)
# ============================================================================

_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');
    :root {
        --bg-absolute: #FFFFFF; --bg-card: #FFFFFF; --bg-elevated: #FAFAFA; --bg-subtle: #F4F4F5;
        --graphite-900: #0A0A0A; --graphite-800: #18181B; --graphite-700: #27272A; --graphite-600: #3F3F46; --graphite-500: #71717A; --graphite-400: #A1A1AA; --graphite-300: #D4D4D8; --graphite-200: #E4E4E7; --graphite-100: #F4F4F5;
        --border-light: rgba(10, 10, 10, 0.05); --border-medium: rgba(10, 10, 10, 0.1);
        --shadow-xs: 0 1px 2px rgba(10, 10, 10, 0.02); --shadow-sm: 0 1px 3px rgba(10, 10, 10, 0.04), 0 1px 2px rgba(10, 10, 10, 0.02); --shadow-md: 0 4px 6px rgba(10, 10, 10, 0.04), 0 2px 4px rgba(10, 10, 10, 0.03); --shadow-lg: 0 10px 15px rgba(10, 10, 10, 0.06), 0 4px 6px rgba(10, 10, 10, 0.04); --shadow-xl: 0 20px 25px rgba(10, 10, 10, 0.08), 0 10px 10px rgba(10, 10, 10, 0.05);
        --radius-xl: 20px; --radius-lg: 14px; --radius-md: 10px; --radius-sm: 6px; --radius-pill: 9999px;
        --ease-smooth: cubic-bezier(0.16, 1, 0.3, 1);
    }
    .stApp { background-color: var(--bg-absolute); color: var(--graphite-900); font-family: 'Inter', -apple-system, sans-serif !important; -webkit-font-smoothing: antialiased; }
    #MainMenu, header, footer, .stDeployButton, .stAppViewBlockContainer { visibility: hidden !important; display: none !important; }
    .block-container { max-width: 1400px; padding: 2.5rem 3rem 6rem 3rem !important; }
    h1, h2, h3, h4, h5, h6 { font-family: 'Sora', sans-serif !important; color: var(--graphite-900) !important; letter-spacing: -0.02em !important; line-height: 1.2 !important; }
    h1 { font-size: 3.5rem !important; font-weight: 600 !important; margin: 0 !important; }
    h1 em { font-style: normal !important; font-weight: 400 !important; color: var(--graphite-500); }
    h2 { font-size: 2rem !important; font-weight: 600 !important; }
    h3 { font-size: 1.25rem !important; font-weight: 500 !important; }
    h4 { font-family: 'JetBrains Mono', monospace !important; font-size: 0.8rem !important; text-transform: uppercase; letter-spacing: 0.1em !important; color: var(--graphite-500) !important; font-weight: 500 !important; font-style: normal !important; }
    p, li, span, div { font-family: 'Inter', sans-serif; color: var(--graphite-700); line-height: 1.6; font-size: 0.95rem; }
    strong { color: var(--graphite-900); font-weight: 600; }
    code { font-family: 'JetBrains Mono', monospace !important; background: var(--graphite-100) !important; color: var(--graphite-900) !important; padding: 2px 6px; border-radius: 4px; font-size: 0.85em; font-weight: 500; }
    .ticker-container { overflow: hidden; border-top: 1px solid var(--border-light); border-bottom: 1px solid var(--border-light); padding: 12px 0; margin: 24px 0 32px 0; background: var(--bg-absolute); }
    .ticker-track { display: inline-block; white-space: nowrap; animation: ticker-scroll 80s linear infinite; font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.1em; color: var(--graphite-400); }
    .ticker-track strong { color: var(--graphite-900); font-weight: 700; }
    @keyframes ticker-scroll { 0%   { transform: translateX(0); } 100% { transform: translateX(-50%); } }
    .typing-line { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--graphite-500); overflow: hidden; white-space: nowrap; width: 50ch; border-right: 2px solid var(--graphite-900); animation: typing-anim 3.5s steps(50) 0.5s both, caret-blink 0.9s step-end infinite; margin-top: 10px; }
    @keyframes typing-anim { from { width: 0; } to   { width: 50ch; } }
    @keyframes caret-blink { 50% { border-color: transparent; } }
    .prism-card { background: var(--bg-card); border: 1px solid var(--border-light); border-radius: var(--radius-xl); padding: 32px; margin-bottom: 24px; box-shadow: var(--shadow-sm); position: relative; overflow: hidden; transition: all 0.4s var(--ease-smooth); }
    .prism-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); border-color: var(--border-medium); }
    .pixel-badge { font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; padding: 5px 12px; border-radius: var(--radius-pill); display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border-light); background: var(--bg-elevated); color: var(--graphite-700); }
    .status-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; background: var(--graphite-900); animation: pulse-anim 2s cubic-bezier(0.4, 0, 0.2, 1) infinite; }
    @keyframes pulse-anim { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.8); } }
    .stTextInput>div>div>input, .stTextArea textarea, .stSelectbox>div>div, .stRadio>div { background: var(--bg-absolute) !important; border: 1px solid var(--border-light) !important; color: var(--graphite-900) !important; border-radius: var(--radius-md) !important; font-family: 'Inter', sans-serif !important; padding: 12px !important; box-shadow: var(--shadow-xs); transition: all 0.2s var(--ease-smooth); }
    .stTextArea textarea { font-family: 'JetBrains Mono', monospace !important; font-size: 0.85rem !important; line-height: 1.6 !important; }
    .stTextInput>div>div>input:focus, .stTextArea textarea:focus { border-color: var(--graphite-900) !important; box-shadow: 0 0 0 3px var(--graphite-100) !important; background: var(--bg-card) !important; }
    .stButton>button { background: var(--graphite-900) !important; color: var(--bg-absolute) !important; font-family: 'Sora', sans-serif !important; font-weight: 500; font-size: 0.95rem; border: none !important; border-radius: var(--radius-pill) !important; padding: 12px 24px !important; width: 100%; box-shadow: var(--shadow-sm); transition: all 0.2s var(--ease-smooth); }
    .stButton>button:hover { background: var(--graphite-700) !important; box-shadow: var(--shadow-md); transform: translateY(-1px); }
    .stDownloadButton>button { background: var(--bg-card) !important; color: var(--graphite-900) !important; border: 1px solid var(--border-medium) !important; border-radius: var(--radius-pill) !important; font-family: 'Sora', sans-serif !important; font-weight: 500; padding: 10px 20px !important; transition: all 0.2s ease; width: 100%; }
    .stDownloadButton>button:hover { background: var(--graphite-100) !important; border-color: var(--graphite-900) !important; color: var(--graphite-900) !important; transform: translateY(-1px); }
    .stTabs [data-baseweb="tab-list"] { gap: 32px; border-bottom: 1px solid var(--border-light); margin-bottom: 32px; }
    .stTabs [data-baseweb="tab"] { font-family: 'Sora', sans-serif !important; font-weight: 500; font-size: 1.1rem; color: var(--graphite-400); padding: 10px 0 14px 0; transition: all 0.2s ease; }
    .stTabs [data-baseweb="tab"]:hover { color: var(--graphite-700); }
    .stTabs [aria-selected="true"] { color: var(--graphite-900) !important; border-bottom: 2px solid var(--graphite-900) !important; }
    
    /* FIX: Force Sidebar to always be visible and pinned */
    section[data-testid="stSidebar"] {
        background: var(--bg-card);
        border-right: 1px solid var(--border-light);
        padding: 2rem 1.5rem;
        min-width: 300px !important;
        max-width: 300px !important;
        display: block !important;
    }
    section[data-testid="stSidebar"] > div {
        position: sticky;
        top: 2rem;
    }
    section[data-testid="stSidebar"] h3 { font-size: 1rem !important; margin-top: 1.5rem !important; margin-bottom: 0.5rem !important; }
    section[data-testid="stSidebar"] label { font-family: 'JetBrains Mono', monospace !important; font-size: 0.7rem !important; text-transform: uppercase; letter-spacing: 0.1em; color: var(--graphite-500) !important; }
    
    .risk-row { padding: 14px 0; border-bottom: 1px solid var(--border-light); }
    .risk-row:last-child { border-bottom: none; }
    .risk-row-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
    .risk-row-left { display: flex; align-items: center; gap: 10px; }
    .risk-rank { font-family: 'Sora', sans-serif; font-size: 1.2rem; font-weight: 400; color: var(--graphite-400); min-width: 20px; }
    .risk-category { font-family: 'Inter', sans-serif; font-size: 0.95rem; color: var(--graphite-900); }
    .risk-score { font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: var(--graphite-900); font-weight: 700; }
    .risk-reason { font-size: 0.85rem; color: var(--graphite-600); line-height: 1.5; margin-bottom: 8px; }
    .risk-age { color: var(--graphite-400); font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; }
    .bar-track { width: 100%; height: 4px; background: var(--graphite-100); border-radius: 4px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 4px; transform-origin: left; animation: bar-fill-anim 1s cubic-bezier(0.16, 1, 0.3, 1) both; }
    @keyframes bar-fill-anim { from { transform: scaleX(0); } }
    .brief-rendered { padding: 8px 0; }
    .brief-header { display: flex; justify-content: space-between; align-items: flex-start; padding-bottom: 20px; margin-bottom: 24px; border-bottom: 1px solid var(--border-light); }
    .brief-title { margin: 0 0 4px 0 !important; }
    .brief-meta { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: var(--graphite-500); letter-spacing: 0.05em; }
    .brief-badges { display: flex; gap: 8px; flex-wrap: wrap; }
    .brief-section { margin-bottom: 28px; }
    .section-label { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--graphite-500); font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
    .section-label::before { content: ''; width: 4px; height: 4px; background: var(--graphite-900); border-radius: 50%; }
    .change-list { list-style: none; padding: 0; margin: 0; }
    .change-item { padding: 10px 0 10px 24px; position: relative; color: var(--graphite-700); font-size: 0.95rem; line-height: 1.6; border-bottom: 1px solid var(--graphite-100); }
    .change-item:last-child { border-bottom: none; }
    .change-item::before { content: '>'; position: absolute; left: 6px; color: var(--graphite-400); font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; font-weight: 700; }
    .matters-text { font-family: 'Sora', sans-serif !important; font-size: 1.15rem !important; line-height: 1.5 !important; color: var(--graphite-800); padding: 16px 20px; background: var(--bg-elevated); border-left: 3px solid var(--graphite-900); border-radius: var(--radius-md); }
    .action-text { font-size: 1rem; font-weight: 500; color: var(--graphite-900); padding: 16px 20px; background: var(--bg-elevated); border-left: 3px solid var(--graphite-900); border-radius: var(--radius-md); }
    .risks-container { background: var(--bg-elevated); padding: 8px 20px; border-radius: var(--radius-md); }
    .metric-card { text-align: center; padding: 16px; background: var(--bg-card); border-radius: var(--radius-md); border: 1px solid var(--border-light); }
    .metric-value { font-family: 'Sora', sans-serif; font-size: 2rem; font-weight: 600; color: var(--graphite-900); }
    .metric-label { font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.1em; color: var(--graphite-500); text-transform: uppercase; margin-top: 4px; }
    .streamlit-expanderHeader { font-family: 'Sora', sans-serif !important; font-weight: 500; font-size: 0.95rem; color: var(--graphite-900); padding: 12px 0; }
    .stProgress > div > div > div > div { background: var(--graphite-900) !important; }
    .stSpinner > div > div { border-top-color: var(--graphite-900) !important; }
</style>
"""

# ============================================================================
# INTERACTIVE PARTICLE CANVAS (Monochrome Minimalist Physics)
# ============================================================================

_PARTICLE_CANVAS = """
<div style="position: relative; height: 360px; border-radius: 20px; overflow: hidden; border: 1px solid rgba(10,10,10,0.05); background: #FFFFFF; box-shadow: 0 10px 20px rgba(10,10,10,0.03); margin-bottom: 32px;">
    <canvas id="graphiteCanvas" style="position: absolute; inset: 0; width: 100%; height: 100%;"></canvas>
    <div style="position: absolute; top: 32px; left: 40px; z-index: 10; pointer-events: none;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
            <div style="width: 6px; height: 6px; background: #0A0A0A; border-radius: 50%;"></div>
            <span style="font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 600; letter-spacing: 0.1em; color: #0A0A0A; text-transform: uppercase;">Graphite Engine</span>
        </div>
        <div style="font-family: 'Sora', sans-serif; font-size: 32px; font-weight: 600; color: #0A0A0A; letter-spacing: -0.02em;">Operational Synthesis</div>
        <div style="font-family: 'Inter', sans-serif; font-size: 13px; color: #71717A; margin-top: 2px;">across 30 industries</div>
    </div>
    <div style="position: absolute; bottom: 24px; right: 40px; z-index: 10; display: flex; gap: 16px; font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #A1A1AA; letter-spacing: 0.08em;">
        <span id="graphiteFPS">60 FPS</span><span>LIVE</span><span>PHYSICS</span>
    </div>
</div>
<script>
const canvas = document.getElementById('graphiteCanvas');
const ctx = canvas.getContext('2d');
const fpsDisplay = document.getElementById('graphiteFPS');
let width, height, particles = [], pulses = [];
const CONNECTION_DISTANCE = 120, SPACING = 34; let time = 0;
function initCanvas() {
    width = canvas.width = canvas.offsetWidth * window.devicePixelRatio;
    height = canvas.height = canvas.offsetHeight * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    width = canvas.offsetWidth; height = canvas.offsetHeight;
    particles = [];
    for (let x = -width * 0.6; x < width * 1.6; x += SPACING) {
        for (let y = -height * 0.6; y < height * 1.6; y += SPACING) {
            if (Math.random() > 0.35) continue;
            const shade = Math.random() > 0.95 ? '#0A0A0A' : (Math.random() > 0.8 ? '#71717A' : '#D4D4D8');
            particles.push({ ox: x, oy: y, cx: x, cy: y, vx: 0, vy: 0, size: Math.random() * 2 + 1, color: shade });
        }
    }
}
window.addEventListener('resize', initCanvas); initCanvas();
let mouse = { x: -1000, y: -1000, radius: 180 };
canvas.addEventListener('mousemove', (e) => { const rect = canvas.getBoundingClientRect(); mouse.x = e.clientX - rect.left; mouse.y = e.clientY - rect.top; });
canvas.addEventListener('mouseleave', () => { mouse.x = -1000; mouse.y = -1000; });
let lastFrame = performance.now(); let frameCount = 0;
function animate() {
    ctx.clearRect(0, 0, width, height); time += 0.01;
    const now = performance.now(); frameCount++;
    if (now - lastFrame >= 1000) { fpsDisplay.innerText = frameCount + ' FPS'; frameCount = 0; lastFrame = now; }
    for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        const z = Math.sin(p.ox * 0.007 + time) * Math.cos(p.oy * 0.007 + time) * 30;
        const targetX = (p.ox - p.oy) * 0.7 + width / 2;
        const targetY = (p.ox + p.oy) * 0.35 + z + height / 2;
        const dx = p.cx - mouse.x, dy = p.cy - mouse.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < mouse.radius) { const force = (mouse.radius - dist) / mouse.radius; p.vx += (dx / dist) * force * 2.5; p.vy += (dy / dist) * force * 2.5; }
        p.vx += (targetX - p.cx) * 0.04; p.vy += (targetY - p.cy) * 0.04; p.vx *= 0.88; p.vy *= 0.88; p.cx += p.vx; p.cy += p.vy;
        for (let j = i + 1; j < particles.length; j++) {
            const p2 = particles[j];
            const ddx = p.cx - p2.cx, ddy = p.cy - p2.cy;
            const ddist = Math.sqrt(ddx * ddx + ddy * ddy);
            if (ddist < CONNECTION_DISTANCE && ddist > 0) {
                const opacity = 1 - (ddist / CONNECTION_DISTANCE);
                ctx.beginPath(); ctx.moveTo(p.cx, p.cy); ctx.lineTo(p2.cx, p2.cy);
                let color = 'rgba(212, 212, 216, ' + (opacity * 0.3) + ')';
                if (p.color === '#0A0A0A' || p2.color === '#0A0A0A') { color = 'rgba(10, 10, 10, ' + (opacity * 0.4) + ')'; }
                ctx.strokeStyle = color; ctx.lineWidth = 0.6; ctx.stroke();
                if (Math.random() < 0.0005) { pulses.push({ sx: p.cx, sy: p.cy, tx: p2.cx, ty: p2.cy, progress: 0, speed: 0.015 + Math.random() * 0.015 }); }
            }
        }
        if (p.cx > -30 && p.cx < width + 30 && p.cy > -30 && p.cy < height + 30) { ctx.fillStyle = p.color; ctx.fillRect(p.cx - p.size / 2, p.cy - p.size / 2, p.size, p.size); }
    }
    for (let i = pulses.length - 1; i >= 0; i--) {
        const pulse = pulses[i]; pulse.progress += pulse.speed;
        if (pulse.progress >= 1) { pulses.splice(i, 1); continue; }
        const curX = pulse.sx + (pulse.tx - pulse.sx) * pulse.progress;
        const curY = pulse.sy + (pulse.ty - pulse.sy) * pulse.progress;
        ctx.beginPath(); ctx.arc(curX, curY, 2, 0, Math.PI * 2); ctx.fillStyle = '#0A0A0A'; ctx.fill();
    }
    requestAnimationFrame(animate);
}
animate();
</script>
"""

# ============================================================================
# MAIN STREAMLIT APPLICATION
# ============================================================================

def render_header():
    st.markdown(_h("""
    <div class="ticker-container">
        <div class="ticker-track">
            <strong>EIBRIEF-AI v6.0 GRAPHITE</strong> &nbsp;|&nbsp;
            ALL SYSTEMS NOMINAL &nbsp;|&nbsp;
            30 INDUSTRIES ACTIVE &nbsp;|&nbsp;
            NEURAL MESH ONLINE &nbsp;|&nbsp;
            HUMAN-FRIENDLY TONE &nbsp;|&nbsp;
            ZERO-RUPEE ARCHITECTURE &nbsp;|&nbsp;
            READ TIME &lt; 60s &nbsp;|&nbsp;
            NO EMOJI &nbsp;|&nbsp;
            <strong>EIBRIEF-AI v6.0 GRAPHITE</strong> &nbsp;|&nbsp;
            ALL SYSTEMS NOMINAL &nbsp;|&nbsp;
            30 INDUSTRIES ACTIVE &nbsp;|&nbsp;
            NEURAL MESH ONLINE &nbsp;|&nbsp;
            HUMAN-FRIENDLY TONE &nbsp;|&nbsp;
            ZERO-RUPEE ARCHITECTURE &nbsp;|&nbsp;
            READ TIME &lt; 60s &nbsp;|&nbsp;
            NO EMOJI &nbsp;|&nbsp;
        </div>
    </div>
    """), unsafe_allow_html=True)

    h_col1, h_col2, h_col3 = st.columns([3.2, 1.3, 1])

    with h_col1:
        st.markdown("<h1>Just tell me <em>what changed.</em></h1>", unsafe_allow_html=True)
        st.markdown("<div class='typing-line'>synthesis is automation, judgment is yours_</div>", unsafe_allow_html=True)

    with h_col2:
        st.markdown(_h("""
        <div style="display: flex; gap: 10px; justify-content: flex-end; padding-top: 18px; flex-wrap: wrap;">
            <span class="pixel-badge"><span class="status-dot"></span>ONLINE</span>
            <span class="pixel-badge">NEURAL</span>
        </div>
        """), unsafe_allow_html=True)

    with h_col3:
        current_time = datetime.now().strftime('%H:%M:%S')
        current_date = datetime.now().strftime('%d %b %Y').upper()
        st.markdown(f"""
        <div style="text-align: right; padding-top: 12px;">
            <div style="font-family: 'JetBrains Mono', monospace; font-size: 1.4rem; font-weight: 700; color: #0A0A0A;">{current_time}</div>
            <div style="font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.1em; color: #A1A1AA; margin-top: 2px;">{current_date} // DAILY RUN</div>
        </div>
        """, unsafe_allow_html=True)


def render_sidebar():
    with st.sidebar:
        st.markdown('<span class="pixel-badge">CONTROL</span>', unsafe_allow_html=True)
        st.markdown("#### Role")
        role = st.selectbox("Role", list(ROLES.keys()), index=0)
        st.markdown("#### Project")
        default_project = st.session_state.get("project", "Apollo Launch")
        project = st.text_input("Project name", value=default_project)
        st.session_state["project"] = project
        st.markdown("#### Reader")
        reader = st.radio("Who will read this brief?", ["Non-technical executive", "Technical lead", "Peer"], index=0)
        st.markdown("---")
        st.markdown("#### Principles")
        st.markdown(_h("""
        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.85rem; color: #3F3F46;">
            <div>Risks scored by <strong>rules</strong>, never the LLM</div>
            <div>One page, under 60s read time</div>
            <div>Synthesis automated; <strong>judgment is yours</strong></div>
            <div>Every brief archived, idempotent</div>
            <div>Zero emoji. Pure professional tone.</div>
        </div>
        """), unsafe_allow_html=True)
        st.markdown("#### Archive")
        stats = archive_stats()
        st.markdown(f"""
        <div style="font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: #71717A; line-height: 1.8;">
            TOTAL BRIEFS: <strong style="color: #0A0A0A;">{stats['total']}</strong><br>
            UNIQUE ROLES: <strong style="color: #0A0A0A;">{stats['roles']}</strong><br>
            PROJECTS: <strong style="color: #0A0A0A;">{stats['projects']}</strong><br>
            TODAY: <strong style="color: #0A0A0A;">{stats['today']}</strong>
        </div>
        """, unsafe_allow_html=True)
    return role, project, reader


def render_signals_tab(role: str, project: str, reader: str):
    role_cfg = ROLES[role]
    ca, cb = st.columns([1.4, 1], gap="large")

    with ca:
        st.markdown(_h(f"""
        <div class="prism-card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <div>
                    <h3 style="margin: 0;">Raw Signals -- {role}</h3>
                    <p style="margin: 6px 0 0; font-size: 0.85rem; color: #71717A;">{', '.join(role_cfg['sources'])}</p>
                </div>
                <span class="pixel-badge">UNSTRUCTURED</span>
            </div>
        </div>
        """), unsafe_allow_html=True)
        raw = st.text_area("signals", value=role_cfg["signals"], height=320, label_visibility="collapsed")
        st.caption(f"{len(raw):,} chars / ~{max(1, len(raw) // 4)} tokens. Edit freely -- this is your real input.")

    with cb:
        st.markdown(_h("""
        <div class="prism-card">
            <h3>Pipeline</h3>
            <p style="font-size: 0.85rem; color: #71717A; margin-bottom: 20px;">Normalize, detect deltas, score risks by rules, then ask the LLM for narrative only.</p>
            <div style="background: #F4F4F5; border: 1px solid #E4E4E7; border-radius: 10px; padding: 16px; margin-bottom: 20px;">
                <div style="display: flex; flex-direction: column; gap: 8px; font-size: 0.85rem; font-family: 'JetBrains Mono', monospace; color: #71717A;">
                    <div>schema normalize (per role)</div>
                    <div>delta T vs T-1</div>
                    <div style="color: #0A0A0A;">risk rules + severity x recency</div>
                    <div>LLM narrative (grounded only)</div>
                </div>
            </div>
            <div style="padding: 12px; background: #FAFAFA; border-radius: 8px; border: 1px solid #F4F4F5; font-size: 0.8rem; color: #3F3F46;">
                <strong>Risk Engine:</strong> severity x 0.7 + recency x 0.3. Same signals in = same ranking out. Auditable.
            </div>
        </div>
        """), unsafe_allow_html=True)
        if st.button("Generate today's brief", use_container_width=True):
            st.session_state.update(run_synthesis=True, raw_data=raw, role=role, project=project, reader=reader)
            st.rerun()


def render_brief_tab():
    if st.session_state.get("run_synthesis"):
        # MASTER TRY-EXCEPT: Guarantee no Python tracebacks ever hit the UI
        try:
            role_name = st.session_state["role"]
            project_name = st.session_state["project"]
            reader_name = st.session_state["reader"]
            raw_in = st.session_state["raw_data"]

            # DYNAMIC RISK DETECTION: Scans the text area for what you actually typed
            all_risks = build_risk_pool(role_name, raw_in)
            top3 = all_risks[:3]

            st.markdown('<div class="prism-card">', unsafe_allow_html=True)

            with st.spinner("synthesizing"):
                pb = st.progress(0.0)
                stx = st.empty()
                stages = [
                    (25, "`scoring risks (severity x recency)`"),
                    (55, "`asking neural mesh for narrative`"),
                    (85, "`assembling brief`"),
                    (98, "`persisting to archive`"),
                ]
                for i in range(100):
                    time.sleep(0.012)
                    pb.progress((i + 1) / 100.0)
                    for threshold, message in stages:
                        if i == threshold:
                            stx.markdown(message)
                pb.empty()
                stx.empty()

            llm_ready = _configure_gemini()
            synth = None
            if llm_ready:
                synth = _llm_synthesise(role_name, raw_in, top3)

            used_llm = synth is not None
            if synth is None:
                synth = _fallback_synthesise(raw_in, top3)

            brief = Brief(
                brief_id=hashlib.md5(f"{role_name}:{project_name}:{datetime.now().date()}:{uuid.uuid4()}".encode()).hexdigest()[:16],
                role=role_name,
                project=project_name,
                reader=reader_name,
                run_date=datetime.now().strftime("%d %b %Y %H:%M"),
                changes=synth["changes"],
                matters=synth["matters"],
                top_risks=top3,
                action=synth["action"],
                raw_signals=raw_in,
                confidence=0.94 if used_llm else 0.82,
                used_llm=used_llm,
            )

            save_brief(brief)
            st.session_state["last_brief"] = brief

            # FIX: HTML rendering stripped of indentation via _h()
            st.markdown(_h(brief.to_html()), unsafe_allow_html=True)
            st.markdown("---")
            
            fname_base = f"eibrief_{project_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}"
            c1, c2, c3 = st.columns(3)
            with c1:
                st.download_button("Download .md", brief.to_markdown(), file_name=f"{fname_base}.md", mime="text/markdown", use_container_width=True)
            with c2:
                st.download_button("Download .json", json.dumps(brief.to_dict(), indent=2), file_name=f"{fname_base}.json", mime="application/json", use_container_width=True)
            with c3:
                if st.button("Regenerate", use_container_width=True):
                    st.session_state["run_synthesis"] = False
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)
            
        except Exception:
            # Graceful fallback if something completely unexpected happens
            st.markdown(_h("""
            <div class="prism-card" style="text-align: center; padding: 60px 20px;">
                <h3 style="color: #71717A; font-weight: 500;">Synthesis Engine Temporarily Unavailable</h3>
                <p style="color: #A1A1AA; font-size: 1rem;">The system encountered an unexpected issue. Please try regenerating or check your network connection.</p>
            </div>
            """), unsafe_allow_html=True)

    else:
        st.markdown(_h("""
        <div class="prism-card" style="text-align: center; padding: 100px 20px;">
            <div style="font-family: 'Sora', sans-serif; font-size: 3rem; font-weight: 300; opacity: 0.1; margin-bottom: 12px;">.</div>
            <h3 style="color: #71717A; font-weight: 500;">No brief generated yet today.</h3>
            <p style="color: #A1A1AA; font-size: 1rem;">Go to <strong>Signals</strong>, pick a role, and hit generate.</p>
        </div>
        """), unsafe_allow_html=True)


def render_risk_radar_tab(role: str):
    cx, cy = st.columns([1.6, 1], gap="large")
    
    # DYNAMIC RISK DETECTION for the radar tab as well
    all_risks = build_risk_pool(role, st.session_state.get("raw_data", ""))

    with cx:
        st.markdown(_h(f"""
        <div class="prism-card">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px;">
                <div>
                    <h3 style="margin: 0;">All Risks -- {role}</h3>
                    <p style="margin: 6px 0 0; font-size: 0.85rem; color: #71717A;">{len(all_risks)} detected, sorted by score</p>
                </div>
                <span class="pixel-badge">{len(all_risks)} RISKS</span>
            </div>
            <p style="font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #71717A; margin-bottom: 16px;">score = severity x 0.7 + recency x 0.3</p>
        </div>
        """), unsafe_allow_html=True)
        
        # FIX: HTML rendering stripped of indentation via _h()
        for i, r in enumerate(all_risks, 1):
            st.markdown(_h(r.to_html_row(i)), unsafe_allow_html=True)
            
        st.markdown("</div>", unsafe_allow_html=True)

    with cy:
        st.markdown(_h("""
        <div class="prism-card">
            <h3 style="margin-top: 0;">Why rules, not the LLM?</h3>
            <p style="font-size: 0.9rem; line-height: 1.6;">Risk flagging must be <strong>auditable</strong>. The same signals in produce the same ranking out, every time. The LLM narrates; the engine judges. That is what makes this safe to trust in front of a board.</p>
            <div style="display: flex; flex-direction: column; gap: 8px; margin-top: 16px;">
                <span class="pixel-badge">CRITICAL = 1.00</span>
                <span class="pixel-badge">HIGH = 0.75</span>
                <span class="pixel-badge">MEDIUM = 0.50</span>
                <span class="pixel-badge">LOW = 0.25</span>
            </div>
            <p style="font-family: 'JetBrains Mono', monospace; font-size: 10px; color: #71717A; margin-top: 20px; line-height: 1.7;">
                RECENCY WEIGHTS:<br>today 1.0<br>1-2 days 0.7<br>3-7 days 0.4<br>8-14 days 0.25<br>> 14 days 0.15
            </p>
        </div>
        <div class="prism-card" style="margin-top: 16px;">
            <h3 style="margin-top: 0;">Split Responsibilities</h3>
            <div style="font-size: 0.88rem; line-height: 1.8;">
                <div style="padding: 10px 0; border-bottom: 1px solid #F4F4F5;">
                    <strong style="color: #0A0A0A;">LLM (Gemini)</strong><br>
                    <span style="color: #71717A;">Writes the narrative. Connects dots. Never judges risk.</span>
                </div>
                <div style="padding: 10px 0;">
                    <strong style="color: #0A0A0A;">Risk Engine</strong><br>
                    <span style="color: #71717A;">Scores and ranks risk. Deterministic. Auditable.</span>
                </div>
            </div>
        </div>
        """), unsafe_allow_html=True)


def render_archive_tab():
    st.markdown(_h("""
    <div class="prism-card">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px;">
            <div>
                <h3 style="margin: 0;">Brief Archive</h3>
                <p style="margin: 6px 0 0; font-size: 0.85rem; color: #71717A;">The project narrative over time</p>
            </div>
            <span class="pixel-badge">HISTORICAL</span>
        </div>
    </div>
    """), unsafe_allow_html=True)

    rows = load_archive()
    if not rows:
        st.markdown(_h("""
        <div class="prism-card" style="text-align: center; padding: 60px;">
            <p style="color: #71717A;">No briefs in archive yet. Generate one and it persists here (idempotent per role + project + date).</p>
        </div>
        """), unsafe_allow_html=True)
        return

    stats = archive_stats()
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"<div class='metric-card'><div class='metric-value'>{stats['total']}</div><div class='metric-label'>Total Briefs</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-card'><div class='metric-value'>{stats['roles']}</div><div class='metric-label'>Roles</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-card'><div class='metric-value'>{stats['projects']}</div><div class='metric-label'>Projects</div></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='metric-card'><div class='metric-value'>{stats['today']}</div><div class='metric-label'>Today</div></div>", unsafe_allow_html=True)

    st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
    for project, run_date, rl, rd, md, brief_id in rows:
        with st.expander(f"{run_date}  --  {project}  ({rl} / {rd or 'reader'})"):
            st.markdown(md)


def render_footer():
    st.markdown(_h("""
    <div style="display: flex; justify-content: space-between; padding: 32px 0 12px; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 0.1em; color: #A1A1AA; border-top: 1px solid #F4F4F5; margin-top: 32px;">
        <span>EIBRIEF-AI v6.0 GRAPHITE</span>
        <span>SYNTHESIS IS AUTOMATION -- JUDGMENT IS YOURS</span>
        <span>KADURI GANESH</span>
    </div>
    """), unsafe_allow_html=True)


def main():
    st.set_page_config(page_title=f"{APP_NAME} :: {APP_TAGLINE}", page_icon="|", layout="wide", initial_sidebar_state="expanded", menu_items={"About": f"# {APP_NAME} v{APP_VERSION}\n{APP_TAGLINE}"})
    _db().close() # Ensure DB exists and migrates if needed
    st.markdown(_CSS, unsafe_allow_html=True)
    render_header()
    components.html(_PARTICLE_CANVAS, height=372)
    role, project, reader = render_sidebar()
    tab_signals, tab_brief, tab_risks, tab_archive = st.tabs(["Signals", "Daily Brief", "Risk Radar", "Archive"])
    with tab_signals: render_signals_tab(role, project, reader)
    with tab_brief: render_brief_tab()
    with tab_risks: render_risk_radar_tab(role)
    with tab_archive: render_archive_tab()
    render_footer()

if __name__ == "__main__":
    main()
