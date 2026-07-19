import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.v1.endpoints.vehicle_catalog import (
    create_brand,
    create_model,
    list_brands,
    list_models,
)
from app.api.v1.endpoints.vehicles import create_vehicle, update_vehicle
from app.core.security import require_roles
from app.db.migrations import run_vehicle_catalog_migration
from app.db.session import Base
from app.models import User, Vehicle, VehicleBrand, VehicleModel
from app.schemas import (
    UserRole,
    VehicleBrandCreate,
    VehicleCreate,
    VehicleModelCreate,
    VehicleUpdate,
)


def vehicle_create(
    brand_id: int,
    model_id: int,
    plate: str = "01-123-AB",
    country: str = "XK",
) -> VehicleCreate:
    return VehicleCreate(
        brand_id=brand_id,
        model_id=model_id,
        fuel_type="Hybrid",
        vehicle_location="Belgrade",
        registration_country=country,
        license_plate=plate,
        year=2024,
        vin_number=None,
        engine_cc=1800,
        odometer_km=10,
        status=0,
    )


class VehicleCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.admin = User(
            id=1,
            email="admin@example.com",
            full_name="Admin",
            hashed_password="unused",
            role=UserRole.admin.value,
            is_active=True,
        )
        self.viewer = User(
            id=2,
            email="viewer@example.com",
            full_name="Viewer",
            hashed_password="unused",
            role=UserRole.viewer.value,
            is_active=True,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def add_brand(self, name: str) -> VehicleBrand:
        result = create_brand(VehicleBrandCreate(name=name), self.db)
        return self.db.get(VehicleBrand, result.id)

    def add_model(self, brand_id: int, name: str) -> VehicleModel:
        result = create_model(VehicleModelCreate(brand_id=brand_id, name=name), self.db)
        return self.db.get(VehicleModel, result.id)

    def test_create_brand(self) -> None:
        brand = self.add_brand(" Toyota ")
        self.assertEqual(brand.name, "Toyota")
        self.assertEqual(brand.normalized_name, "toyota")

    def test_duplicate_brand_is_rejected_case_insensitively(self) -> None:
        self.add_brand("Toyota")
        with self.assertRaises(HTTPException) as raised:
            self.add_brand("TOYOTA")
        self.assertEqual(raised.exception.status_code, 409)

    def test_create_model_under_brand(self) -> None:
        brand = self.add_brand("Toyota")
        model = self.add_model(brand.id, "Land   Cruiser")
        self.assertEqual(model.name, "Land Cruiser")
        self.assertEqual(model.brand_id, brand.id)

    def test_duplicate_model_under_same_brand_is_rejected(self) -> None:
        brand = self.add_brand("Toyota")
        self.add_model(brand.id, "Corolla")
        with self.assertRaises(HTTPException) as raised:
            self.add_model(brand.id, "COROLLA")
        self.assertEqual(raised.exception.status_code, 409)

    def test_same_model_name_is_allowed_under_another_brand(self) -> None:
        first = self.add_brand("Brand A")
        second = self.add_brand("Brand B")
        self.add_model(first.id, "City")
        other = self.add_model(second.id, "City")
        self.assertEqual(other.brand_id, second.id)

    def test_list_returns_active_brands_only(self) -> None:
        active = self.add_brand("Active")
        inactive = self.add_brand("Inactive")
        inactive.is_active = False
        self.db.commit()
        result = list_brands(None, False, 200, self.db, self.viewer)
        self.assertEqual([brand.id for brand in result], [active.id])

    def test_list_models_by_brand(self) -> None:
        toyota = self.add_brand("Toyota")
        other = self.add_brand("Other")
        corolla = self.add_model(toyota.id, "Corolla")
        self.add_model(other.id, "Different")
        result = list_models(toyota.id, None, False, 300, self.db, self.viewer)
        self.assertEqual([model.id for model in result], [corolla.id])

    def test_search_brands(self) -> None:
        self.add_brand("Toyota")
        self.add_brand("Volkswagen")
        result = list_brands("yot", False, 200, self.db, self.viewer)
        self.assertEqual([brand.name for brand in result], ["Toyota"])

    def test_search_models(self) -> None:
        brand = self.add_brand("Toyota")
        self.add_model(brand.id, "Corolla")
        self.add_model(brand.id, "RAV4")
        result = list_models(brand.id, "roll", False, 300, self.db, self.viewer)
        self.assertEqual([model.name for model in result], ["Corolla"])

    def test_vehicle_creation_with_valid_brand_and_model(self) -> None:
        brand = self.add_brand("Toyota")
        model = self.add_model(brand.id, "Corolla")
        result = create_vehicle(vehicle_create(brand.id, model.id), self.db, self.admin)
        self.assertEqual((result.brand_id, result.model_id), (brand.id, model.id))
        self.assertEqual((result.brand, result.model), ("Toyota", "Corolla"))

    def test_vehicle_creation_with_nonexistent_brand(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            create_vehicle(vehicle_create(999, 999), self.db, self.admin)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("brand does not exist", raised.exception.detail)

    def test_vehicle_creation_with_nonexistent_model(self) -> None:
        brand = self.add_brand("Toyota")
        with self.assertRaises(HTTPException) as raised:
            create_vehicle(vehicle_create(brand.id, 999), self.db, self.admin)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("model does not exist", raised.exception.detail)

    def test_vehicle_creation_rejects_model_from_another_brand(self) -> None:
        toyota = self.add_brand("Toyota")
        volkswagen = self.add_brand("Volkswagen")
        golf = self.add_model(volkswagen.id, "Golf")
        with self.assertRaises(HTTPException) as raised:
            create_vehicle(vehicle_create(toyota.id, golf.id), self.db, self.admin)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("does not belong", raised.exception.detail)

    def test_vehicle_update_changes_brand_and_model(self) -> None:
        toyota = self.add_brand("Toyota")
        corolla = self.add_model(toyota.id, "Corolla")
        volkswagen = self.add_brand("Volkswagen")
        golf = self.add_model(volkswagen.id, "Golf")
        vehicle = create_vehicle(vehicle_create(toyota.id, corolla.id), self.db, self.admin)
        payload = VehicleUpdate(**vehicle_create(volkswagen.id, golf.id).model_dump())
        result = update_vehicle(vehicle.id, payload, self.db, self.admin)
        self.assertEqual((result.brand, result.model), ("Volkswagen", "Golf"))

    def test_inactive_options_cannot_be_selected_for_new_vehicle(self) -> None:
        brand = self.add_brand("Toyota")
        model = self.add_model(brand.id, "Corolla")
        model.is_active = False
        self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            create_vehicle(vehicle_create(brand.id, model.id), self.db, self.admin)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("Inactive", raised.exception.detail)

    def test_unauthorized_user_cannot_manage_catalog(self) -> None:
        admin_dependency = require_roles(UserRole.admin)
        with self.assertRaises(HTTPException) as raised:
            admin_dependency(self.viewer)
        self.assertEqual(raised.exception.status_code, 403)


class VehicleCatalogMigrationTests(unittest.TestCase):
    def test_legacy_vehicles_are_preserved_and_backfilled(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE "Vehicles" ('
                '"Id" INTEGER PRIMARY KEY, "Brand" VARCHAR NOT NULL, "Model" VARCHAR NOT NULL)'
            ))
            connection.execute(text(
                'INSERT INTO "Vehicles" ("Id", "Brand", "Model") VALUES '
                "(1, 'Toyota ', 'Corolla'), (2, 'TOYOTA', 'RAV4')"
            ))
        VehicleBrand.__table__.create(engine)
        VehicleModel.__table__.create(engine)

        run_vehicle_catalog_migration(engine)

        with engine.connect() as connection:
            brands = connection.execute(text(
                'SELECT "Name", "NormalizedName" FROM "VehicleBrands"'
            )).all()
            vehicles = connection.execute(text(
                'SELECT "Brand", "Model", "BrandId", "ModelId" FROM "Vehicles" ORDER BY "Id"'
            )).all()
        self.assertEqual(brands, [("Toyota", "toyota")])
        self.assertEqual([(row[0], row[1]) for row in vehicles], [
            ("Toyota ", "Corolla"),
            ("TOYOTA", "RAV4"),
        ])
        self.assertTrue(all(row[2] is not None and row[3] is not None for row in vehicles))
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
