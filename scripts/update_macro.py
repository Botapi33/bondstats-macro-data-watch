#!/usr/bin/env python3
"""
BondStats Macro Data Watch — production updater.

Official sources only:
- U.S. Bureau of Labor Statistics Public Data API
- U.S. Bureau of Economic Analysis official data pages
- Eurostat Statistics API

Design:
- no API key
- no consensus / third-party data
- latest + immediately previous comparable observation
- fail closed / last-known-good
- source-level health
- lastChecked separated from lastSuccessfulDataUpdate
"""

from pathlib import Path
from html import unescape
import datetime as dt
import json, math, re, urllib.parse, urllib.request

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/macro.json"
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
UA = {"User-Agent": "BondStats-MacroDataWatch/1.1 (+https://www.bondstats.org/)"}

SOURCE_IDS = {
    "BLS": {"US_CPI","US_CORE_CPI","US_PAYROLLS","US_UNEMP"},
    "BEA": {"US_PCE","US_CORE_PCE","US_GDP"},
    "EUROSTAT": {"EA_HICP","EA_CORE_HICP","EA_UNEMP","EA_GDP"},
}

def iso_now():
    return NOW.isoformat().replace("+00:00", "Z")

def fetch(url, data=None, headers=None):
    h = dict(UA)
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=35) as r:
        return r.read().decode("utf-8", "ignore"), r.geturl()

def clean_html(html):
    s = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I|re.S)
    s = re.sub(r"<style\b[^>]*>.*?</style>", " ", s, flags=re.I|re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", unescape(s)).strip()

def period_month(period):
    y, m = period.split("-")
    return dt.date(int(y), int(m), 1).strftime("%b %Y")

def direction(latest, previous, eps=1e-9):
    if previous is None:
        return "flat"
    if latest > previous + eps:
        return "up"
    if latest < previous - eps:
        return "down"
    return "flat"

def set_obs(item, value, previous, period, source_url=None):
    value = float(value)
    previous = None if previous is None else float(previous)
    if not math.isfinite(value) or (previous is not None and not math.isfinite(previous)):
        raise ValueError("non-finite observation")
    if not period:
        raise ValueError("missing period")
    item["value"] = round(value, 3)
    item["previous"] = None if previous is None else round(previous, 3)
    item["period"] = period
    item["direction"] = direction(value, previous)
    item["status"] = "official"
    if source_url:
        item["sourceUrl"] = source_url

def validate_indicator(i):
    if i.get("status") != "official":
        raise ValueError(f'{i.get("id")}: non-official status')
    if not str(i.get("sourceUrl","")).startswith("https://"):
        raise ValueError(f'{i.get("id")}: invalid source URL')
    if not math.isfinite(float(i["value"])):
        raise ValueError(f'{i.get("id")}: invalid value')
    if i.get("previous") is not None and not math.isfinite(float(i["previous"])):
        raise ValueError(f'{i.get("id")}: invalid previous value')
    if not i.get("period"):
        raise ValueError(f'{i.get("id")}: missing period')

# ---------- BLS ----------
def parse_bls_response(obj):
    if obj.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS API request failed")
    got = {}
    for series in obj.get("Results",{}).get("series",[]):
        obs = []
        for x in series.get("data",[]):
            p = x.get("period","")
            if re.fullmatch(r"M(0[1-9]|1[0-2])", p):
                obs.append((f'{x["year"]}-{p[1:]}', float(x["value"])))
        got[series.get("seriesID")] = sorted(obs)
    required = {"CUUR0000SA0","CUUR0000SA0L1E","CES0000000001","LNS14000000"}
    if not required.issubset(got):
        raise ValueError("BLS response missing required series")
    return got

def bls_update(items):
    series = ["CUUR0000SA0","CUUR0000SA0L1E","CES0000000001","LNS14000000"]
    payload = json.dumps({
        "seriesid": series,
        "startyear": str(NOW.year - 2),
        "endyear": str(NOW.year)
    }).encode()
    raw, _ = fetch(
        "https://api.bls.gov/publicAPI/v2/timeseries/data/",
        payload,
        {"Content-Type":"application/json"}
    )
    got = parse_bls_response(json.loads(raw))

    # CPI / Core CPI: calculate 12-month change from official unadjusted indexes.
    for sid, iid in [("CUUR0000SA0","US_CPI"),("CUUR0000SA0L1E","US_CORE_CPI")]:
        obs = got[sid]
        if len(obs) < 13:
            raise ValueError(f"{sid}: insufficient history")
        values = dict(obs)
        latest = obs[-1]
        prior_month = obs[-2]
        year_ago = values.get(f"{int(latest[0][:4])-1}-{latest[0][5:]}")
        prior_year_ago = values.get(f"{int(prior_month[0][:4])-1}-{prior_month[0][5:]}")
        if year_ago is None or prior_year_ago is None:
            raise ValueError(f"{sid}: missing YoY base")
        latest_yoy = (latest[1] / year_ago - 1) * 100
        previous_yoy = (prior_month[1] / prior_year_ago - 1) * 100
        set_obs(items[iid], latest_yoy, previous_yoy, period_month(latest[0]),
                "https://www.bls.gov/news.release/cpi.htm")

    # CES total nonfarm payroll level is in thousands; difference is monthly payroll change in thousands.
    obs = got["CES0000000001"]
    if len(obs) < 3:
        raise ValueError("CES payroll series: insufficient history")
    latest, prior, prior2 = obs[-1], obs[-2], obs[-3]
    set_obs(items["US_PAYROLLS"], latest[1]-prior[1], prior[1]-prior2[1],
            period_month(latest[0]), "https://www.bls.gov/news.release/empsit.htm")

    obs = got["LNS14000000"]
    if len(obs) < 2:
        raise ValueError("unemployment series: insufficient history")
    latest, prior = obs[-1], obs[-2]
    set_obs(items["US_UNEMP"], latest[1], prior[1], period_month(latest[0]),
            "https://www.bls.gov/news.release/empsit.htm")

# ---------- BEA ----------
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"

def parse_bea_monthly_html(html):
    t = clean_html(html)
    vals = {}
    for m in re.finditer(rf"\b({MONTHS})\s+(20\d{{2}})\s+\+?(-?\d+(?:\.\d+)?)\s*%", t, re.I):
        d = dt.datetime.strptime(m.group(1)[:3] + " " + m.group(2), "%b %Y")
        vals[d] = float(m.group(3))
    seq = sorted(vals.items())
    if len(seq) < 2:
        raise ValueError("BEA monthly values not parsed")
    return seq

def parse_bea_gdp_html(html):
    t = clean_html(html)
    vals = {}
    for m in re.finditer(r"\bQ([1-4])\s*(20\d{2})(?:\s*\([^)]*\))?\s+\+?(-?\d+(?:\.\d+)?)\s*%", t, re.I):
        vals[(int(m.group(2)), int(m.group(1)))] = float(m.group(3))
    seq = sorted(vals.items())
    if len(seq) < 2:
        raise ValueError("BEA GDP values not parsed")
    return seq

def bea_update(items):
    endpoints = [
        ("US_PCE",
         "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
         parse_bea_monthly_html),
        ("US_CORE_PCE",
         "https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy",
         parse_bea_monthly_html),
    ]
    for iid, url, parser in endpoints:
        raw, final = fetch(url)
        seq = parser(raw)
        (d, v), (_, pv) = seq[-1], seq[-2]
        set_obs(items[iid], v, pv, d.strftime("%b %Y"), final)

    url = "https://www.bea.gov/data/gdp/gross-domestic-product"
    raw, final = fetch(url)
    seq = parse_bea_gdp_html(raw)
    ((y,q),v), ((py,pq),pv) = seq[-1], seq[-2]
    set_obs(items["US_GDP"], v, pv, f"Q{q} {y}", final)

# ---------- EUROSTAT ----------
def jsonstat_series(obj):
    ids = obj.get("id", [])
    sizes = obj.get("size", [])
    if "time" not in ids or len(ids) != len(sizes):
        raise ValueError("Eurostat malformed dimensions")
    time_index = obj["dimension"]["time"]["category"]["index"]
    if isinstance(time_index, list):
        time_pos = {k:i for i,k in enumerate(time_index)}
    else:
        time_pos = {k:int(v) for k,v in time_index.items()}
    t_axis = ids.index("time")

    # Query must resolve every non-time dimension to exactly one category.
    for i, size in enumerate(sizes):
        if i != t_axis and int(size) != 1:
            raise ValueError(f"Eurostat query not singleton on {ids[i]}")

    strides = []
    for i in range(len(sizes)):
        stride = 1
        for s in sizes[i+1:]:
            stride *= int(s)
        strides.append(stride)

    values = obj.get("value", {})
    out = []
    for period, pos in time_pos.items():
        flat = int(pos) * strides[t_axis]
        if isinstance(values, dict):
            val = values.get(str(flat))
        else:
            val = values[flat] if flat < len(values) else None
        if val is not None:
            out.append((period, float(val)))
    out.sort()
    if len(out) < 2:
        raise ValueError("Eurostat insufficient observations")
    return out

def eurostat_fetch(dataset, filters):
    qs = urllib.parse.urlencode({"lang":"EN", **filters}, doseq=True)
    url = f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}?{qs}"
    raw, final = fetch(url)
    return jsonstat_series(json.loads(raw)), final

def eurostat_update(items):
    # EA21 is the euro-area aggregate from 2026 after Bulgaria joined the euro area.
    common = {"geo":"EA21"}

    seq, url = eurostat_fetch("prc_hicp_manr",
        {**common, "coicop":"CP00", "unit":"RCH_A"})
    set_obs(items["EA_HICP"], seq[-1][1], seq[-2][1],
            period_month(seq[-1][0]), url)

    seq, url = eurostat_fetch("prc_hicp_manr",
        {**common, "coicop":"TOT_X_NRG_FOOD", "unit":"RCH_A"})
    set_obs(items["EA_CORE_HICP"], seq[-1][1], seq[-2][1],
            period_month(seq[-1][0]), url)

    seq, url = eurostat_fetch("une_rt_m",
        {**common, "sex":"T", "age":"Y15-74", "unit":"PC_ACT", "s_adj":"SA"})
    set_obs(items["EA_UNEMP"], seq[-1][1], seq[-2][1],
            period_month(seq[-1][0]), url)

    seq, url = eurostat_fetch("namq_10_gdp",
        {**common, "na_item":"B1GQ", "unit":"CLV_PCH_PRE", "s_adj":"SCA"})
    p, v = seq[-1]
    pp, pv = seq[-2]
    label = p.replace("-", " ")
    set_obs(items["EA_GDP"], v, pv, label, url)

UPDATERS = {"BLS": bls_update, "BEA": bea_update, "EUROSTAT": eurostat_update}

def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    items = {i["id"]: i for i in data["indicators"]}
    changed = False
    results = {}

    for key, updater in UPDATERS.items():
        ids = sorted(SOURCE_IDS[key])
        backup = {iid: dict(items[iid]) for iid in ids}
        before = {iid:(items[iid]["value"], items[iid].get("previous"), items[iid]["period"]) for iid in ids}
        try:
            updater(items)
            for iid in ids:
                validate_indicator(items[iid])
            after = {iid:(items[iid]["value"], items[iid].get("previous"), items[iid]["period"]) for iid in ids}
            changed = changed or (after != before)
            data["sourceHealth"][key] = {"state":"ok","lastChecked":iso_now()}
            results[key] = {"state":"ok","indicators":ids}
        except Exception as exc:
            # Atomic rollback per source. Never publish a half-updated source group.
            for iid in ids:
                items[iid].clear()
                items[iid].update(backup[iid])
            data["sourceHealth"][key] = {
                "state":"degraded",
                "lastChecked":iso_now(),
                "error":str(exc)[:220]
            }
            results[key] = {"state":"degraded","error":str(exc)[:220]}

    data["meta"]["lastChecked"] = iso_now()
    if changed:
        data["meta"]["lastSuccessfulDataUpdate"] = iso_now()
    data["meta"]["lastUpdated"] = data["meta"]["lastSuccessfulDataUpdate"]
    data["meta"]["healthySources"] = sum(v["state"]=="ok" for v in data["sourceHealth"].values())
    data["meta"]["degradedSources"] = sum(v["state"]=="degraded" for v in data["sourceHealth"].values())
    data["meta"]["refreshResults"] = results
    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
