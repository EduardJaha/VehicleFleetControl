import type { EnergyUnit } from "@/lib/types";
import i18n from "@/i18n";
import { getActiveLanguage } from "@/i18n/language";

export function energyUnitLabel(unit: EnergyUnit): string {
  return unit === "KWH" ? "kWh" : "L";
}

export function formatEnergyQuantity(
  quantity: string | number,
  unit: EnergyUnit
): string {
  const value = Number(quantity);
  const formatted = Number.isFinite(value) ? new Intl.NumberFormat(getActiveLanguage() === "sq" ? "sq-AL" : "en-GB", { maximumFractionDigits: 2 }).format(value) : String(quantity);
  return `${formatted} ${energyUnitLabel(unit)}`;
}

export function formatEnergyUnitPrice(
  unitCost: string | number,
  unit: EnergyUnit
): string {
  const value = Number(unitCost);
  const formatted = Number.isFinite(value) ? new Intl.NumberFormat(getActiveLanguage() === "sq" ? "sq-AL" : "en-GB", { maximumFractionDigits: 4 }).format(value) : String(unitCost);
  return `${formatted}/${energyUnitLabel(unit)}`;
}

export function quantityLabel(unit: EnergyUnit): string {
  return i18n.t(unit === "KWH" ? "modules:fuel.energyDelivered" : "modules:fuel.fuelQuantity");
}

export function unitCostLabel(unit: EnergyUnit): string {
  return i18n.t(unit === "KWH" ? "modules:fuel.costKwh" : "modules:fuel.costLiter");
}

export function stationLabel(unit: EnergyUnit): string {
  return i18n.t(unit === "KWH" ? "modules:fuel.chargingStation" : "modules:fuel.fuelStation");
}

export function calculationDescription(unit: EnergyUnit): string {
  return unit === "KWH"
    ? i18n.t("modules:fuel.calculationElectric")
    : i18n.t("modules:fuel.calculationLiquid");
}
