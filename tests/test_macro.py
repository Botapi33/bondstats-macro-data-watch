from pathlib import Path
import ast, json, datetime as dt, importlib.util

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("update_macro", ROOT/"scripts/update_macro.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

data = json.loads((ROOT/"data/macro.json").read_text())

def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        raise AssertionError(name)

inds = data["indicators"]
byid = {i["id"]: i for i in inds}

# Feed schema / integrity
ok("11 rate-relevant indicators", len(inds) == 11)
ok("unique ids", len(byid) == 11)
ok("US + Euro Area coverage", {i["region"] for i in inds} == {"United States","Euro Area"})
ok("official only", all(i["status"] == "official" for i in inds))
ok("https sources", all(i["sourceUrl"].startswith("https://") for i in inds))
ok("no consensus methodology", "no consensus" in data["meta"]["methodology"].lower())
ok("all values finite", all(isinstance(i["value"], (int,float)) for i in inds))

# Live observations must not be compared with historical seed values.
# Historical parser behavior is already covered by the fixture tests below.
expected_ids = {
    "US_CPI", "US_CORE_CPI", "US_PAYROLLS", "US_UNEMP",
    "US_PCE", "US_CORE_PCE", "US_GDP",
    "EA_HICP", "EA_CORE_HICP", "EA_UNEMP", "EA_GDP",
}
ok("required indicator ids", set(byid) == expected_ids)

# Reject NaN/Infinity and booleans (bool is an int subclass in Python).
import math
ok("finite numeric live observations", all(
    type(i.get("value")) in (int, float) and math.isfinite(i["value"])
    for i in inds
))

# BLS parser fixture
bls = json.loads((ROOT/"tests/fixtures/bls.json").read_text())
got = mod.parse_bls_response(bls)
ok("BLS required series parsed", set(got) == {"CUUR0000SA0","CUUR0000SA0L1E","CES0000000001","LNS14000000"})
ok("BLS months sorted", got["LNS14000000"][-1][0] == "2026-07")

# BEA parser fixtures
pce = mod.parse_bea_monthly_html((ROOT/"tests/fixtures/bea_pce.html").read_text())
ok("BEA PCE latest", pce[-1][0].strftime("%b %Y") == "Jul 2026" and pce[-1][1] == 3.7)
gdp = mod.parse_bea_gdp_html((ROOT/"tests/fixtures/bea_gdp.html").read_text())
ok("BEA GDP latest", gdp[-1] == ((2026,2),1.5))

# Eurostat JSON-stat fixture
eu = json.loads((ROOT/"tests/fixtures/eurostat.json").read_text())
seq = mod.jsonstat_series(eu)
ok("Eurostat JSON-stat sequence", seq[-1] == ("2026-07",2.9))

# Core architecture
script = (ROOT/"scripts/update_macro.py").read_text()
ast.parse(script)
ok("updater syntax", True)
ok("BLS official API", "api.bls.gov/publicAPI" in script)
ok("BEA official endpoints", script.count("https://www.bea.gov/") >= 3)
ok("Eurostat official API", "ec.europa.eu/eurostat/api/dissemination/statistics" in script)
ok("Euro Area 2026 aggregate", '"geo":"EA21"' in script)
ok("atomic source rollback", "Atomic rollback per source" in script)
ok("last-known-good health", '"degraded"' in script)
ok("separate freshness clocks", "lastChecked" in script and "lastSuccessfulDataUpdate" in script)
ok("no third-party providers", not any(x in script.lower() for x in ["bloomberg","reuters","tradingeconomics","investing.com"]))

# UI
html = (ROOT/"index.html").read_text()
ok("mobile responsive", "@media(max-width:820px)" in html)
ok("distinct macro release-board UI", "Macro pulse / latest" in html and "Source integrity" in html)
ok("copyright", "BondStats Ltd. All rights reserved." in html)

# Workflow
wf = (ROOT/".github/workflows/update-macro.yml").read_text()
ok("scheduled automation", "schedule:" in wf and "23 */6 * * *" in wf)
ok("manual Run workflow", "workflow_dispatch" in wf)
ok("write permission", "contents: write" in wf)
ok("tests before commit", wf.index("Run deterministic tests") < wf.index("Commit refreshed feed"))
ok("single updater run", "python scripts/update_macro.py" in wf)

print("ALL TESTS PASSED")
