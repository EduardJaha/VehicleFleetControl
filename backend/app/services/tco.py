"""Vehicle lifecycle, efficiency, anomaly, and TCO calculations.

All monetary arithmetic remains Decimal until the API serialization boundary.
The rules in this module are deterministic and intentionally described in the
report response; no recommendation is represented as AI-generated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from sqlalchemy.orm import Session, joinedload

from app.models import (
    Vehicle, VehicleAccident, VehicleFuel, VehicleOperatingCost, VehicleService, WorkOrder,
)


ZERO = Decimal("0")
MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
COST_CATEGORIES = (
    "fuel_cost", "charging_cost", "maintenance_cost", "parts_cost", "labor_cost",
    "accident_cost", "insurance_cost", "registration_cost", "lease_cost",
    "depreciation", "other_operating_cost",
)


def decimal_value(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def money(value) -> Decimal:
    return decimal_value(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def as_date(value: date | datetime | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def month_start(value: date) -> date:
    return value.replace(day=1)


def next_month(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def months_between(start: date, end: date) -> Decimal:
    """Calendar-month duration including a Decimal fraction for partial months."""
    if end <= start:
        return ZERO
    whole = (end.year - start.year) * 12 + end.month - start.month
    anchor_month = date(start.year + (start.month - 1 + whole) // 12, (start.month - 1 + whole) % 12 + 1, 1)
    anchor_day = min(start.day, (next_month(anchor_month) - timedelta(days=1)).day)
    anchor = anchor_month.replace(day=anchor_day)
    if anchor > end:
        whole -= 1
        anchor_month = date(start.year + (start.month - 1 + whole) // 12, (start.month - 1 + whole) % 12 + 1, 1)
        anchor_day = min(start.day, (next_month(anchor_month) - timedelta(days=1)).day)
        anchor = anchor_month.replace(day=anchor_day)
    days_in_anchor_month = (next_month(month_start(anchor)) - month_start(anchor)).days
    fraction = Decimal((end - anchor).days) / Decimal(days_in_anchor_month)
    return Decimal(max(whole, 0)) + max(fraction, ZERO)


def calculate_book_value(vehicle: Vehicle, as_of: date | None = None) -> Decimal | None:
    """Return deterministic current book value for an owned/financed vehicle."""
    purchase = decimal_value(vehicle.purchase_price)
    acquired = as_date(vehicle.acquisition_date)
    if purchase <= ZERO or acquired is None:
        return None
    if vehicle.ownership_type in {"Leased", "Rented"} or vehicle.depreciation_method == "None":
        return purchase.quantize(MONEY)
    effective = min(as_of or date.today(), as_date(vehicle.sale_date) or date.max)
    residual = min(decimal_value(vehicle.residual_value), purchase)
    life_months = Decimal(max(vehicle.expected_service_years or 5, 1) * 12)
    elapsed = min(months_between(acquired, effective), life_months)
    if vehicle.depreciation_method == "Declining Balance":
        # Transparent fixed 20% annual reducing-balance method, compounded monthly.
        full_months = int(elapsed)
        partial = elapsed - Decimal(full_months)
        monthly_factor = Decimal("0.98")  # close, stable Decimal approximation of 20% annual
        value = purchase * (monthly_factor ** full_months)
        value *= Decimal("1") - (Decimal("0.02") * partial)
    else:
        value = purchase - ((purchase - residual) * elapsed / life_months)
    return max(residual, value).quantize(MONEY, rounding=ROUND_HALF_UP)


def calculate_depreciation(vehicle: Vehicle, start: date | None, end: date) -> Decimal:
    if vehicle.ownership_type in {"Leased", "Rented"}:
        return ZERO
    acquired = as_date(vehicle.acquisition_date)
    if acquired is None or decimal_value(vehicle.purchase_price) <= ZERO:
        return ZERO
    period_start = max(start or acquired, acquired)
    if period_start >= end:
        return ZERO
    start_value = calculate_book_value(vehicle, period_start)
    end_value = calculate_book_value(vehicle, end)
    if start_value is None or end_value is None:
        return ZERO
    sold = as_date(vehicle.sale_date)
    if sold and period_start < sold <= end and vehicle.sale_price is not None:
        # On disposal, replace the scheduled ending book value with actual
        # proceeds so lifetime depreciation equals purchase price less sale price.
        return (start_value - decimal_value(vehicle.sale_price)).quantize(MONEY, rounding=ROUND_HALF_UP)
    return max(start_value - end_value, ZERO).quantize(MONEY)


def calculate_lease_cost(vehicle: Vehicle, start: date | None, end: date) -> Decimal:
    payment = decimal_value(vehicle.monthly_lease_payment)
    lease_start = as_date(vehicle.lease_start) or as_date(vehicle.acquisition_date)
    if vehicle.ownership_type not in {"Leased", "Rented"} or payment <= ZERO or lease_start is None:
        return ZERO
    period_start = max(start or lease_start, lease_start)
    period_end = min(end, as_date(vehicle.lease_end) or end, as_date(vehicle.sale_date) or end)
    if period_end <= period_start:
        return ZERO
    return (payment * months_between(period_start, period_end)).quantize(MONEY, rounding=ROUND_HALF_UP)


def monthly_lifecycle_costs(vehicle: Vehicle, start: date | None, end: date) -> dict[str, Decimal]:
    """Allocate lease and depreciation to their actual calendar months."""
    lifecycle_start = (
        as_date(vehicle.lease_start) or as_date(vehicle.acquisition_date)
        if vehicle.ownership_type in {"Leased", "Rented"}
        else as_date(vehicle.acquisition_date)
    )
    if lifecycle_start is None:
        return {}
    cursor = max(start or lifecycle_start, lifecycle_start)
    result: dict[str, Decimal] = defaultdict(lambda: ZERO)
    iterations = 0
    while cursor < end and iterations < 1200:
        boundary = min(next_month(month_start(cursor)), end)
        result[cursor.strftime("%Y-%m")] += (
            calculate_depreciation(vehicle, cursor, boundary)
            + calculate_lease_cost(vehicle, cursor, boundary)
        )
        cursor = boundary
        iterations += 1
    target = calculate_depreciation(vehicle, start, end) + calculate_lease_cost(vehicle, start, end)
    difference = target - sum(result.values(), ZERO)
    if difference and result:
        result[sorted(result)[-1]] += difference
    return result


def allocate_maintenance(total, labor, parts) -> dict[str, Decimal]:
    labor_value = money(labor)
    parts_value = money(parts)
    total_value = max(money(total), labor_value + parts_value)
    return {
        "labor_cost": labor_value,
        "parts_cost": parts_value,
        "maintenance_cost": max(total_value - labor_value - parts_value, ZERO),
    }


def _valid_deltas(records: list[VehicleFuel]) -> list[tuple[VehicleFuel, int]]:
    ordered = sorted(records, key=lambda row: (row.refuel_date, row.id or 0))
    result = []
    for previous, current in zip(ordered, ordered[1:]):
        distance = int(current.odometer_km or 0) - int(previous.odometer_km or 0)
        if distance > 0:
            result.append((current, distance))
    return result


def efficiency_metrics(records: list[VehicleFuel]) -> dict:
    deltas = _valid_deltas(records)
    if not deltas:
        return {
            "distance_km": None, "distance_between_refuels_km": None,
            "liters_per_100_km": None, "kwh_per_100_km": None, "energy_cost_per_km": None,
            "charging_cost_by_provider": {}, "insufficient_odometer_history": True,
        }
    distance = sum(item[1] for item in deltas)
    liquid = sum((decimal_value(row.quantity) for row, _ in deltas if row.unit == "L"), ZERO)
    electric = sum((decimal_value(row.quantity) for row, _ in deltas if row.unit == "KWH"), ZERO)
    energy_cost = sum((decimal_value(row.total_cost) for row, _ in deltas), ZERO)
    providers: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in records:
        if row.unit == "KWH":
            providers[row.station_name or "Unknown"] += decimal_value(row.total_cost)
    return {
        "distance_km": distance,
        "distance_between_refuels_km": (Decimal(distance) / Decimal(len(deltas))).quantize(Decimal("0.1")),
        "liters_per_100_km": (liquid * 100 / Decimal(distance)).quantize(Decimal("0.01")) if liquid else None,
        "kwh_per_100_km": (electric * 100 / Decimal(distance)).quantize(Decimal("0.01")) if electric else None,
        "energy_cost_per_km": (energy_cost / Decimal(distance)).quantize(RATE) if energy_cost else ZERO,
        "charging_cost_by_provider": {key: money(value) for key, value in sorted(providers.items())},
        "insufficient_odometer_history": False,
    }


def detect_energy_anomalies(vehicle: Vehicle, records: list[VehicleFuel]) -> list[dict]:
    anomalies: list[dict] = []
    ordered = sorted(records, key=lambda row: (row.refuel_date, row.id or 0))
    unit_prices: dict[str, list[Decimal]] = defaultdict(list)
    for record in ordered:
        prior_prices = unit_prices[record.unit]
        price = decimal_value(record.unit_cost)
        if len(prior_prices) >= 3:
            baseline = Decimal(str(median(prior_prices)))
            if baseline > ZERO and abs(price - baseline) / baseline > Decimal("0.50"):
                anomalies.append({"record_id": record.id, "type": "large_unit_price_deviation", "severity": "warning"})
        prior_prices.append(price)
    for previous, current in zip(ordered, ordered[1:]):
        if int(current.odometer_km or 0) < int(previous.odometer_km or 0):
            anomalies.append({"record_id": current.id, "type": "lower_odometer", "severity": "critical"})
        if current.refuel_date - previous.refuel_date <= timedelta(hours=2):
            anomalies.append({"record_id": current.id, "type": "repeated_fueling_short_interval", "severity": "warning"})
    for record in ordered:
        quantity = decimal_value(record.quantity)
        if record.unit == "L" and vehicle.fuel_tank_capacity_l and quantity > decimal_value(vehicle.fuel_tank_capacity_l):
            anomalies.append({"record_id": record.id, "type": "quantity_above_tank_capacity", "severity": "critical"})
        if record.unit == "KWH":
            limit = decimal_value(vehicle.battery_capacity_kwh) * Decimal("1.25") if vehicle.battery_capacity_kwh else Decimal("150")
            if quantity > limit:
                anomalies.append({"record_id": record.id, "type": "unusually_high_ev_charging_quantity", "severity": "warning"})
    for record, distance in _valid_deltas(ordered):
        consumption = decimal_value(record.quantity) * 100 / Decimal(distance)
        limit = Decimal("50") if record.unit == "KWH" else Decimal("25")
        if consumption > limit:
            anomalies.append({"record_id": record.id, "type": "unusually_high_consumption", "severity": "warning", "value": consumption.quantize(Decimal("0.01"))})
    return anomalies


def replacement_recommendation(
    vehicle: Vehicle, *, as_of: date, annual_cost: Decimal, downtime_days: Decimal, reliability_events: int,
) -> dict:
    score = 0
    reasons: list[str] = []
    acquired = as_date(vehicle.acquisition_date)
    age_years = Decimal((as_of - acquired).days) / Decimal("365.25") if acquired and acquired <= as_of else ZERO
    if vehicle.expected_service_years:
        ratio = age_years / Decimal(vehicle.expected_service_years)
        if ratio >= 1:
            score += 2; reasons.append("service_life_reached")
        elif ratio >= Decimal("0.8"):
            score += 1; reasons.append("approaching_service_life")
    if vehicle.expected_service_km and vehicle.odometer_km is not None:
        ratio = Decimal(vehicle.odometer_km) / Decimal(vehicle.expected_service_km)
        if ratio >= 1:
            score += 2; reasons.append("expected_mileage_reached")
        elif ratio >= Decimal("0.8"):
            score += 1; reasons.append("approaching_expected_mileage")
    purchase = decimal_value(vehicle.purchase_price)
    if purchase > ZERO:
        cost_ratio = annual_cost / purchase
        if cost_ratio >= Decimal("0.30"):
            score += 2; reasons.append("high_annual_cost")
        elif cost_ratio >= Decimal("0.20"):
            score += 1; reasons.append("elevated_annual_cost")
    if downtime_days >= 30:
        score += 2; reasons.append("high_downtime")
    elif downtime_days >= 14:
        score += 1; reasons.append("elevated_downtime")
    if reliability_events >= 4:
        score += 2; reasons.append("poor_reliability")
    elif reliability_events >= 2:
        score += 1; reasons.append("reliability_watch")
    if vehicle.sale_date or vehicle.status in {2, 3}:
        score = max(score, 5); reasons.append("disposed_or_out_of_use")
    status = "Replace" if score >= 5 else "Replace Soon" if score >= 3 else "Monitor" if score >= 1 else "Retain"
    return {"status": status, "score": score, "reasons": reasons}


def _serialize(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def tco_report(db: Session, vehicles: list[Vehicle], from_date: date | None = None, to_date: date | None = None) -> dict:
    end = to_date or date.today()
    vehicle_ids = {vehicle.id for vehicle in vehicles}
    fuels = db.query(VehicleFuel).filter(VehicleFuel.vehicle_id.in_(vehicle_ids), VehicleFuel.archived.is_(False)).all() if vehicle_ids else []
    services = db.query(VehicleService).filter(VehicleService.vehicle_id.in_(vehicle_ids), VehicleService.archived.is_(False)).all() if vehicle_ids else []
    work_orders = db.query(WorkOrder).options(joinedload(WorkOrder.linked_service)).filter(WorkOrder.vehicle_id.in_(vehicle_ids), WorkOrder.archived.is_(False)).all() if vehicle_ids else []
    accidents = db.query(VehicleAccident).options(joinedload(VehicleAccident.claim)).filter(VehicleAccident.vehicle_id.in_(vehicle_ids), VehicleAccident.archived.is_(False)).all() if vehicle_ids else []
    operating = db.query(VehicleOperatingCost).filter(VehicleOperatingCost.vehicle_id.in_(vehicle_ids), VehicleOperatingCost.archived.is_(False)).all() if vehicle_ids else []

    def included(value) -> bool:
        value = as_date(value)
        return value is not None and (from_date is None or value >= from_date) and value <= end

    rows = []
    fleet_categories = {category: ZERO for category in COST_CATEGORIES}
    fleet_months: dict[str, Decimal] = defaultdict(lambda: ZERO)
    all_anomalies = []
    for vehicle in vehicles:
        categories = {category: ZERO for category in COST_CATEGORIES}
        monthly: dict[str, Decimal] = defaultdict(lambda: ZERO)
        vehicle_fuels = [row for row in fuels if row.vehicle_id == vehicle.id and included(row.refuel_date)]
        for record in vehicle_fuels:
            category = "charging_cost" if record.unit == "KWH" else "fuel_cost"
            value = money(record.total_cost)
            categories[category] += value
            monthly[as_date(record.refuel_date).strftime("%Y-%m")] += value
        vehicle_services = [row for row in services if row.vehicle_id == vehicle.id and included(row.service_date) and row.status != "Cancelled"]
        for record in vehicle_services:
            allocation = allocate_maintenance(record.cost, record.labor_cost, record.parts_cost)
            for category, value in allocation.items(): categories[category] += value
            monthly[as_date(record.service_date).strftime("%Y-%m")] += sum(allocation.values(), ZERO)
        vehicle_orders = [row for row in work_orders if row.vehicle_id == vehicle.id]
        # A linked Service is authoritative: never add the Work Order monetary fields again.
        for record in vehicle_orders:
            record_date = record.actual_completion_date or record.created_at
            if record.linked_service is not None or record.status == "Cancelled" or not included(record_date):
                continue
            allocation = allocate_maintenance(record.total_cost, record.labor_cost, record.parts_cost)
            for category, value in allocation.items(): categories[category] += value
            monthly[as_date(record_date).strftime("%Y-%m")] += sum(allocation.values(), ZERO)
        for record in (row for row in accidents if row.vehicle_id == vehicle.id and included(row.accident_date)):
            damage = money(record.actual_damage_cost if record.actual_damage_cost is not None else record.estimated_damage_cost)
            settlement = money(record.claim.settlement_amount) if record.claim else ZERO
            deductible = money(record.claim.deductible) if record.claim else ZERO
            value = max(damage - settlement, deductible, ZERO)
            categories["accident_cost"] += value
            monthly[as_date(record.accident_date).strftime("%Y-%m")] += value
        for record in (row for row in operating if row.vehicle_id == vehicle.id and included(row.cost_date)):
            category = {"Insurance": "insurance_cost", "Registration": "registration_cost"}.get(record.category, "other_operating_cost")
            value = money(record.amount)
            categories[category] += value
            monthly[as_date(record.cost_date).strftime("%Y-%m")] += value
        categories["lease_cost"] = calculate_lease_cost(vehicle, from_date, end)
        categories["depreciation"] = calculate_depreciation(vehicle, from_date, end)
        for key, value in monthly_lifecycle_costs(vehicle, from_date, end).items():
            monthly[key] += value
        total = sum(categories.values(), ZERO).quantize(MONEY)
        efficiency = efficiency_metrics(vehicle_fuels)
        distance = efficiency["distance_km"]
        cost_per_km = (total / Decimal(distance)).quantize(RATE) if distance else None
        downtime = ZERO
        maintenance_events = len(vehicle_services)
        reliability_events = 0
        downtime_range_start = datetime.combine(from_date, datetime.min.time()) if from_date else None
        downtime_range_end = datetime.combine(end + timedelta(days=1), datetime.min.time())
        for order in vehicle_orders:
            finish = order.actual_completion_date or downtime_range_end
            if (
                order.status == "Cancelled" or order.created_at >= downtime_range_end
                or (downtime_range_start is not None and finish < downtime_range_start)
            ):
                continue
            effective_start = max(order.created_at, downtime_range_start) if downtime_range_start else order.created_at
            effective_finish = min(finish, downtime_range_end)
            downtime += Decimal(max((effective_finish - effective_start).total_seconds(), 0)) / Decimal(86400)
            if order.linked_service is None:
                maintenance_events += 1
            if order.source in {"Breakdown", "Accident", "Inspection"}:
                reliability_events += 1
        for accident in (row for row in accidents if row.vehicle_id == vehicle.id and included(row.accident_date)):
            if not accident.vehicle_available_after_accident and not accident.work_orders:
                finish_date = min(accident.resolved_at or accident.closed_at or downtime_range_end, downtime_range_end)
                start_date = max(accident.accident_date, downtime_range_start) if downtime_range_start else accident.accident_date
                downtime += Decimal(max((finish_date - start_date).total_seconds(), 0)) / Decimal(86400)
        period_start = from_date or as_date(vehicle.acquisition_date) or end - timedelta(days=365)
        period_years = max(Decimal((end - period_start).days) / Decimal("365.25"), Decimal("1"))
        annual_cost = total / period_years
        recommendation = replacement_recommendation(
            vehicle, as_of=end, annual_cost=annual_cost, downtime_days=downtime, reliability_events=reliability_events,
        )
        anomalies = detect_energy_anomalies(vehicle, vehicle_fuels)
        all_anomalies.extend({"vehicle_id": vehicle.id, **item} for item in anomalies)
        row = {
            "vehicle_id": vehicle.id, "license_plate": vehicle.license_plate,
            "vehicle": f"{vehicle.brand} {vehicle.model}", "ownership_type": vehicle.ownership_type,
            **categories, "total_cost": total, "cost_per_km": cost_per_km,
            "distance_km": distance, "downtime_days": downtime.quantize(Decimal("0.1")),
            "maintenance_frequency_per_year": (Decimal(maintenance_events) / period_years).quantize(Decimal("0.1")),
            "current_book_value": ZERO if (vehicle.status in {2, 3} or (vehicle.sale_date and as_date(vehicle.sale_date) <= end)) else calculate_book_value(vehicle, end),
            "recommendation_status": recommendation["status"],
            "recommendation_score": recommendation["score"],
            "recommendation_reasons": recommendation["reasons"],
            "efficiency": efficiency, "anomaly_count": len(anomalies),
        }
        rows.append(row)
        for category, value in categories.items(): fleet_categories[category] += value
        for key, value in monthly.items(): fleet_months[key] += value
    rows.sort(key=lambda item: item["total_cost"], reverse=True)
    total_cost = sum(fleet_categories.values(), ZERO).quantize(MONEY)
    measured_distance = sum((Decimal(row["distance_km"]) for row in rows if row["distance_km"]), ZERO)
    measured_cost = sum((row["total_cost"] for row in rows if row["distance_km"]), ZERO)
    response = {
        "kpis": {
            "total_cost": total_cost,
            "vehicle_count": len(rows),
            "average_cost_per_km": (measured_cost / measured_distance).quantize(RATE) if measured_distance else None,
            "total_downtime_days": sum((row["downtime_days"] for row in rows), ZERO),
            "replacement_candidates": sum(1 for row in rows if row["recommendation_status"] in {"Replace", "Replace Soon"}),
            "anomaly_count": len(all_anomalies),
        },
        "cost_by_category": fleet_categories,
        "monthly_trend": [{"month": key, "total_cost": value.quantize(MONEY)} for key, value in sorted(fleet_months.items())],
        "rows": rows,
        "anomalies": all_anomalies,
        "methodology": {
            "linked_cost_deduplication": "Linked Service cost is authoritative; its Work Order cost is excluded.",
            "cost_per_km": "Uses positive odometer distance between consecutive fuel/charging records; unavailable with fewer than two usable readings.",
            "recommendations": "Deterministic rules based on expected age and mileage, annual cost versus purchase price, downtime, and unplanned reliability events.",
            "recommendation_thresholds": {"Retain": "score 0", "Monitor": "score 1-2", "Replace Soon": "score 3-4", "Replace": "score 5+"},
            "recommendation_points": {
                "age_or_mileage": "1 point at 80% of expected life; 2 points at 100%",
                "annual_cost": "1 point at 20% of purchase price; 2 points at 30%",
                "downtime": "1 point at 14 days; 2 points at 30 days",
                "reliability": "1 point at 2 unplanned events; 2 points at 4 events",
            },
            "anomaly_thresholds": {
                "liquid_consumption": "above 25 L/100 km", "ev_consumption": "above 50 kWh/100 km",
                "unit_price": "more than 50% from median after three prior records",
                "repeat_interval": "two hours or less", "ev_quantity": "above 125% of recorded battery capacity, or 150 kWh when capacity is unknown",
            },
            "declining_balance": "20% annual reducing balance approximated with a 0.98 monthly factor; residual value is a floor.",
        },
    }
    return _serialize(response)
