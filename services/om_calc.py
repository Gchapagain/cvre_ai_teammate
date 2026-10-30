"""Every number in the OM, calculated in code from the deal's saved data. The AI never writes numbers.

Each calculation returns a Calc: the value, how it is shown, the formula in words, the worked steps
("How is this calculated?"), and what is still needed when it cannot be calculated yet. Financial
projections use only APPROVED assumptions and the price the broker entered.

Formulas
- Total SF            = sum of every unit's SF in the rent roll
- Average unit size   = total SF / number of units
- Leased SF           = sum of SF of units with a tenant (a blank tenant or one named "Vacant" is vacant)
- % leased            = leased SF / total SF x 100
- In-place rent       = sum of the annual rent of the leased units
- Price per SF        = sale price / total SF
- In-place NOI        = the T-12 "Net Operating Income" total
- Cash flow, year 0 (in-place): rent roll rent, T-12 reimbursements, other income and expenses as stated.
- Cash flow, year n = 1..5, with approved assumptions (e escalation, g expense growth, v vacancy allowance,
  m management fee, M market rent per SF, occ_n occupancy in year n, S total SF, L leased SF, R in-place rent):
    rental income  = R x (1+e)^n  +  max(0, occ_n x S - L) x M x (1+e)^(n-1)
    reimbursements = T-12 reimbursements x (1+g)^n x occ_n / in-place occupancy
    other income   = T-12 other income x (1+g)^n
    vacancy        = v x (rental income + reimbursements + other income)
    EGI            = rental income + reimbursements + other income - vacancy
    each expense   = T-12 line x (1+g)^n; management fee = m x EGI
    NOI            = EGI - total expenses
- Cap rate, year n    = NOI in year n / sale price x 100
"""

from dataclasses import dataclass, field

ASSUMPTIONS = {
    # key: (label, kind, help)
    "market_rent_psf": ("Market rent per SF (annual)", "currency", "Rent a vacant unit would lease for, per SF per year."),
    "escalation_pct": ("Annual rent escalation", "percent", "How much rents rise each year."),
    "occupancy_by_year": ("Lease-up: occupancy in years 1 to 5", "percent_list", "Occupancy % for each of the five years."),
    "expense_growth_pct": ("Expense growth per year", "percent", "How much each expense and reimbursement rises each year."),
    "vacancy_pct": ("Vacancy allowance", "percent", "Share of income held back for vacancy and credit loss."),
    "management_fee_pct": ("Management fee", "percent", "Management fee as a % of effective gross income."),
}
YEARS = 5


@dataclass
class Calc:
    value: object = None
    display: str = ""
    formula: str = ""
    steps: list = field(default_factory=list)
    needs: list = field(default_factory=list)   # what is missing before it can be calculated

    @property
    def ready(self):
        return self.value is not None and not self.needs


def money(value, cents=False):
    return f"${value:,.2f}" if cents else f"${value:,.0f}"


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def is_vacant(unit):
    tenant = (unit.get("tenant_name") or "").strip().lower()
    return not tenant or "vacant" in tenant


def _units(facts):
    return [u for u in facts.get("units", []) if _number(u.get("square_feet")) and u["square_feet"] > 0]


def total_sf(facts):
    units = _units(facts)
    if not units:
        return Calc(formula="Sum of every unit's SF in the rent roll", needs=["a rent roll with unit sizes"])
    total = sum(u["square_feet"] for u in units)
    return Calc(total, f"{total:,.0f} SF", "Sum of every unit's SF in the rent roll",
                [f"{len(units)} units: " + " + ".join(f"{u['square_feet']:,.0f}" for u in units) + f" = {total:,.0f} SF"])


def unit_count(facts):
    units = facts.get("units", [])
    if not units:
        return Calc(formula="Number of rows in the rent roll", needs=["a rent roll"])
    return Calc(len(units), f"{len(units)}", "Number of rows in the rent roll", [f"{len(units)} unit rows in the rent roll"])


def avg_unit_size(facts):
    total = total_sf(facts)
    units = _units(facts)
    if not total.ready:
        return Calc(formula="Total SF / number of units", needs=total.needs)
    average = total.value / len(units)
    return Calc(average, f"{average:,.0f} SF", "Total SF / number of units",
                [f"{total.value:,.0f} SF / {len(units)} units = {average:,.0f} SF"])


def leased_sf(facts):
    units = _units(facts)
    return sum(u["square_feet"] for u in units if not is_vacant(u))


def leased_pct(facts):
    total = total_sf(facts)
    if not total.ready:
        return Calc(formula="Leased SF / total SF x 100", needs=total.needs)
    leased = leased_sf(facts)
    pct = leased / total.value * 100
    vacant = [u["unit_number"] for u in _units(facts) if is_vacant(u)]
    steps = [f"Leased SF = {leased:,.0f} (units with a tenant)",
             f"{leased:,.0f} / {total.value:,.0f} x 100 = {pct:.1f}%"]
    if vacant:
        steps.insert(1, f"Vacant units: {', '.join(str(v) for v in vacant)}")
    return Calc(pct, f"{pct:.1f}%", "Leased SF / total SF x 100", steps)


def in_place_rent(facts):
    rents = [u["annual_rent"] for u in _units(facts) if not is_vacant(u) and _number(u.get("annual_rent"))]
    if not rents:
        return Calc(formula="Sum of the annual rent of leased units", needs=["a rent roll with annual rents"])
    total = sum(rents)
    return Calc(total, money(total), "Sum of the annual rent of leased units", [f"{len(rents)} leased units = {money(total, True)}"])


def sale_price(facts):
    price = _number(facts.get("price"))
    return price if price and price > 0 else None


def price_per_sf(facts):
    total, price = total_sf(facts), sale_price(facts)
    needs = (total.needs or []) + ([] if price else ["the sale price (broker)"])
    if needs:
        return Calc(formula="Sale price / total SF", needs=needs)
    value = price / total.value
    return Calc(value, money(value, True), "Sale price / total SF",
                [f"{money(price)} / {total.value:,.0f} SF = {money(value, True)} per SF"])


# ---- T-12 ----

def _t12_totals(facts):
    """{(category, line item): annual total} using each line's 'Total' period (or the sum of its months)."""
    lines = {}
    for row in facts.get("t12", []):
        if not _number(row.get("amount")):
            continue
        key = (row.get("category") or "", row.get("line_item") or "")
        entry = lines.setdefault(key, {"total": None, "months": 0.0})
        if str(row.get("period") or "").strip().lower() == "total":
            entry["total"] = row["amount"]
        else:
            entry["months"] += row["amount"]
    return {key: (e["total"] if e["total"] is not None else e["months"]) for key, e in lines.items()}


def t12_parts(facts):
    """The T-12 split the way the cash flow needs it, or None when there is no T-12."""
    totals = _t12_totals(facts)
    if not totals:
        return None
    income = {item: amount for (category, item), amount in totals.items() if category.lower() == "income"}
    expenses = {item: amount for (category, item), amount in totals.items() if category.lower() == "expense"}
    noi = next((amount for (category, item), amount in totals.items() if "net operating income" in item.lower()), None)
    reimbursements = sum(a for item, a in income.items() if "reimburse" in item.lower() or "cam" in item.lower())
    base = sum(a for item, a in income.items() if "rent" in item.lower() and "reimburse" not in item.lower())
    other = sum(income.values()) - reimbursements - base
    return {"expenses": expenses, "noi": noi, "reimbursements": reimbursements, "other_income": other, "base_rent": base}


def in_place_noi(facts):
    parts = t12_parts(facts)
    if not parts or parts["noi"] is None:
        return Calc(formula="T-12 Net Operating Income total", needs=["a T-12 with a Net Operating Income line"])
    return Calc(parts["noi"], money(parts["noi"]), "T-12 Net Operating Income total", [f"From the T-12: {money(parts['noi'], True)}"])


# ---- Assumptions and cash flow ----

def approved_assumptions(facts):
    return {key: a["value"] for key, a in facts.get("assumptions", {}).items() if a.get("status") == "approved"}


def missing_assumptions(facts):
    approved = approved_assumptions(facts)
    return [ASSUMPTIONS[key][0] for key in ASSUMPTIONS if key not in approved]


def assumptions_need(facts):
    """One line for whatever assumptions are still unapproved, or [] when all are approved."""
    missing = missing_assumptions(facts)
    if not missing:
        return []
    return [f"{len(missing)} approved assumption{'s' if len(missing) != 1 else ''} (" + ", ".join(m.lower() for m in missing) + ")"]


def cash_flow(facts):
    """In-place plus five years. Rows: (label, [year 0 .. year 5]). None values never appear."""
    parts, total, rent = t12_parts(facts), total_sf(facts), in_place_rent(facts)
    needs = list(total.needs) + ([] if rent.ready else rent.needs) + ([] if parts else ["a T-12 operating statement"])
    needs += assumptions_need(facts)
    formula = "In-place from the rent roll and T-12; years 1-5 from approved assumptions (see the formulas in om_calc)"
    if needs:
        return Calc(formula=formula, needs=needs)
    a = approved_assumptions(facts)
    e, g, v, m = a["escalation_pct"] / 100, a["expense_growth_pct"] / 100, a["vacancy_pct"] / 100, a["management_fee_pct"] / 100
    market, occupancy = a["market_rent_psf"], [p / 100 for p in a["occupancy_by_year"]][:YEARS]
    if len(occupancy) < YEARS:
        return Calc(formula=formula, needs=["an occupancy % for each of years 1 to 5"])
    S, L, R = total.value, leased_sf(facts), rent.value
    occ0 = L / S
    management_lines = [item for item in parts["expenses"] if "management" in item.lower()]
    other_lines = [item for item in parts["expenses"] if item not in management_lines]
    rows = {key: [] for key in ("occupancy", "rent", "reimb", "other", "vacancy", "egi", "expenses", "noi")}
    expense_rows = {item: [] for item in other_lines + (management_lines or ["Management Fee"])}
    for n in range(YEARS + 1):
        if n == 0:
            occ, rental, reimb, other, vacancy = occ0, R, parts["reimbursements"], parts["other_income"], 0.0
        else:
            occ = occupancy[n - 1]
            rental = R * (1 + e) ** n + max(0.0, occ * S - L) * market * (1 + e) ** (n - 1)
            reimb = parts["reimbursements"] * (1 + g) ** n * (occ / occ0 if occ0 else 0)
            other = parts["other_income"] * (1 + g) ** n
            vacancy = v * (rental + reimb + other)
        egi = rental + reimb + other - vacancy
        total_expenses = 0.0
        for item in other_lines:
            amount = parts["expenses"][item] * (1 + g) ** n
            expense_rows[item].append(amount)
            total_expenses += amount
        fee = sum(parts["expenses"][i] for i in management_lines) if n == 0 else m * egi
        expense_rows[(management_lines or ["Management Fee"])[0]].append(fee)
        for extra in management_lines[1:]:
            expense_rows[extra].append(0.0)
        total_expenses += fee
        for key, value in (("occupancy", occ * 100), ("rent", rental), ("reimb", reimb), ("other", other),
                           ("vacancy", -vacancy), ("egi", egi), ("expenses", total_expenses), ("noi", egi - total_expenses)):
            rows[key].append(value)
    table = [("Occupancy %", rows["occupancy"]), ("Rental income", rows["rent"]), ("Reimbursements", rows["reimb"])]
    if any(rows["other"]):
        table.append(("Other income", rows["other"]))
    table += [("Vacancy allowance", rows["vacancy"]), ("Effective gross income", rows["egi"])]
    table += [(item, values) for item, values in expense_rows.items()]
    table += [("Total expenses", rows["expenses"]), ("Net operating income", rows["noi"])]
    steps = [f"Year {n} NOI = EGI {money(rows['egi'][n])} - expenses {money(rows['expenses'][n])} = {money(rows['noi'][n])}"
             for n in range(YEARS + 1)]
    return Calc(table, f"Year 1 NOI {money(rows['noi'][1])}", formula, steps)


def noi_by_year(facts):
    flow = cash_flow(facts)
    if not flow.ready:
        return None
    return dict(flow.value)["Net operating income"]


def cap_rate(facts, year):
    flow, price = cash_flow(facts), sale_price(facts)
    needs = list(flow.needs) + ([] if price else ["the sale price (broker)"])
    if needs:
        return Calc(formula=f"Year-{year} NOI / sale price x 100", needs=needs)
    noi = dict(flow.value)["Net operating income"][year]
    rate = noi / price * 100
    return Calc(rate, f"{rate:.2f}%", f"Year-{year} NOI / sale price x 100",
                [f"{money(noi)} / {money(price)} x 100 = {rate:.2f}%"])


def assumptions_note(facts):
    approved = approved_assumptions(facts)
    if missing_assumptions(facts):
        return Calc(formula="The approved assumptions, listed", needs=assumptions_need(facts))
    parts = [f"Market rent {money(approved['market_rent_psf'], True)}/SF",
             f"{approved['escalation_pct']:g}% annual escalations",
             "occupancy " + ", ".join(f"{p:g}%" for p in approved["occupancy_by_year"][:YEARS]) + " (years 1-5)",
             f"{approved['expense_growth_pct']:g}% expense growth",
             f"{approved['vacancy_pct']:g}% vacancy allowance",
             f"{approved['management_fee_pct']:g}% management fee"]
    text = "Market leasing assumptions: " + "; ".join(parts) + "."
    return Calc(text, text, "The approved assumptions, listed", [text])


def rent_roll_table(facts):
    units = facts.get("units", [])
    if not units:
        return Calc(formula="Every unit from the rent roll", needs=["a rent roll"])
    rows = [{"unit": u.get("unit_number"), "tenant": "Vacant" if is_vacant(u) else u.get("tenant_name"),
             "sf": u.get("square_feet"), "start": u.get("lease_start"), "end": u.get("lease_end"),
             "annual_rent": u.get("annual_rent"), "rent_psf": u.get("rent_per_sf"), "lease_type": u.get("lease_type")}
            for u in units]
    return Calc(rows, f"{len(rows)} units", "Every unit from the rent roll, as extracted",
                [f"{len(rows)} rows from the rent roll"])


def contacts(facts):
    profile = facts.get("profile") or {}
    needs = [f"your {field_name} (Settings)" for field_name in ("title", "phone") if not (profile.get(field_name) or "").strip()]
    if needs:
        return Calc(formula="From your profile", needs=needs)
    value = [{"name": profile["full_name"], "title": profile["title"], "phone": profile["phone"], "email": profile["email"]}]
    return Calc(value, f"{profile['full_name']}, {profile['title']}", "From your profile",
                [f"{profile['full_name']} · {profile['title']} · {profile['phone']} · {profile['email']}"])


def contents(facts, template):
    titles = [f"{s['number']}  {s['title']}" for s in template.sections]
    return Calc(titles, "; ".join(titles), "The template's sections", titles)


CALCS = {
    "total_sf": total_sf, "unit_count": unit_count, "avg_unit_size": avg_unit_size, "leased_pct": leased_pct,
    "in_place_rent": in_place_rent, "price_per_sf": price_per_sf, "in_place_noi": in_place_noi,
    "cap_rate_y4": lambda facts: cap_rate(facts, 4), "cash_flow": cash_flow, "assumptions_note": assumptions_note,
    "rent_roll_table": rent_roll_table, "contacts": contacts,
}
