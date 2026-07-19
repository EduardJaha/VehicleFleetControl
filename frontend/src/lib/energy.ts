import type { EnergyUnit } from "@/lib/types";

export function energyUnitLabel(unit: EnergyUnit): string {
  return unit === "KWH" ? "kWh" : "L";
}

export function formatEnergyQuantity(
  quantity: string | number,
  unit: EnergyUnit
): string {
  const value = Number(quantity);
  const formatted = Number.isFinite(value) ? value.toFixed(2) : String(quantity);
  return `${formatted} ${energyUnitLabel(unit)}`;
}

export function formatEnergyUnitPrice(
  unitCost: string | number,
  unit: EnergyUnit
): string {
  const value = Number(unitCost);
  const formatted = Number.isFinite(value) ? value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "") : String(unitCost);
  return `${formatted}/${energyUnitLabel(unit)}`;
}

export function quantityLabel(unit: EnergyUnit): string {
  return unit === "KWH" ? "Energy delivered (kWh)" : "Fuel quantity (L)";
}

export function unitCostLabel(unit: EnergyUnit): string {
  return unit === "KWH" ? "Cost per kWh" : "Cost per liter";
}

export function stationLabel(unit: EnergyUnit): string {
  return unit === "KWH" ? "Charging station / provider" : "Fuel station";
}

export function calculationDescription(unit: EnergyUnit): string {
  return unit === "KWH"
    ? "Calculated from kWh × cost per kWh"
    : "Calculated from liters × cost per liter";
}
