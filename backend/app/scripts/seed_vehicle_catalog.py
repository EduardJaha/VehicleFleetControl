import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.migrations import run_additive_migrations
from app.db.session import Base, SessionLocal, engine
from app.models import VehicleBrand, VehicleModel
from app.utils.vehicle_catalog import clean_catalog_name, normalize_catalog_name

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "vehicle_catalog.json"


def seed_vehicle_catalog(db: Session, catalog_path: Path = DEFAULT_CATALOG_PATH) -> dict[str, int]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    counts = {
        "brands_created": 0,
        "brands_skipped": 0,
        "models_created": 0,
        "models_skipped": 0,
    }

    for entry in catalog["brands"]:
        brand_name = clean_catalog_name(entry["name"])
        brand_key = normalize_catalog_name(brand_name)
        brand = db.query(VehicleBrand).filter(VehicleBrand.normalized_name == brand_key).first()
        if brand is None:
            brand = VehicleBrand(name=brand_name, normalized_name=brand_key, is_active=True)
            db.add(brand)
            db.flush()
            counts["brands_created"] += 1
        else:
            counts["brands_skipped"] += 1

        for raw_model_name in entry["models"]:
            model_name = clean_catalog_name(raw_model_name)
            model_key = normalize_catalog_name(model_name)
            exists = db.query(VehicleModel).filter(
                VehicleModel.brand_id == brand.id,
                VehicleModel.normalized_name == model_key,
            ).first()
            if exists:
                counts["models_skipped"] += 1
                continue
            db.add(VehicleModel(
                brand_id=brand.id,
                name=model_name,
                normalized_name=model_key,
                is_active=True,
            ))
            counts["models_created"] += 1

    db.commit()
    return counts


def main() -> None:
    Base.metadata.create_all(bind=engine)
    run_additive_migrations(engine)
    with SessionLocal() as db:
        counts = seed_vehicle_catalog(db)
    print(
        "Vehicle catalog seed complete: "
        f"{counts['brands_created']} brands created, "
        f"{counts['brands_skipped']} brands skipped, "
        f"{counts['models_created']} models created, "
        f"{counts['models_skipped']} models skipped."
    )


if __name__ == "__main__":
    main()
