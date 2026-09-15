"""Imports exercise retained jobs, dry runs, exact numbers, and atomic target writes."""
import asyncio
import csv
from datetime import datetime
from decimal import Decimal
from io import BytesIO, StringIO
import json

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.session import Base, TenantSession, set_tenant_context, get_db
from app.models import (Attachment, Company, Driver, DocumentRequirement, DocumentVersion, ImportRowResult, Location,
                        Part, PartCategory, Permission, Role, RolePermission, User, UserRole,
                        Vehicle, VehicleAssignment, VehicleFuel, VehiclePaper, VehicleService, Vendor)
from app.schemas import ImportTransactionMode as Transaction, ImportUpdateMode as Mode
from app.services import imports
from app.services.import_entities import MODELS, SPECS
from app.services.import_progress import read_progress


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIRECTORY", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = TenantSession(engine)
    set_tenant_context(db, 1)
    db.add(Company(id=1, name="One", slug="one"))
    user = User(email="admin@one.test", full_name="Admin", role="admin", hashed_password="unused")
    vehicle = Vehicle(registration_country="XK", license_plate="01-123-AB", license_plate_normalized="01123AB",
                      brand="Toyota", model="Corolla", fuel_type="Petrol", vehicle_location="Prishtina", odometer_km=100000, status=0)
    driver = Driver(full_name="Driver", employee_number="EMP-001", license_number="LIC-001", license_category="B", license_expiry_date=datetime(2020,1,1), status="Suspended")
    db.add_all([user, vehicle, driver, PartCategory(name="Filters")])
    db.commit()
    yield db, user, vehicle, driver
    db.close()
    engine.dispose()
    get_settings.cache_clear()


def sample(kind, **changes):
    values = {key: example for key, _, _, _, example in SPECS[kind]}
    values.update(changes)
    return values


def upload(db, user, kind, records, mode=Mode.create_only):
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
    job = asyncio.run(imports.store_import(UploadFile(filename="source.csv", file=BytesIO(out.getvalue().encode())), kind, user, db))
    mapping = {key: key for key in records[0]}
    imports.validate_job(db, job, mapping, mode, user)
    return job


def rows(db, job):
    return imports.job_query(db, job).order_by(ImportRowResult.row_number).all()


@pytest.mark.parametrize("kind", list(SPECS))
@pytest.mark.parametrize("format", ["csv", "xlsx"])
@pytest.mark.parametrize("language", ["en", "sq"])
def test_all_templates_roundtrip(kind, format, language):
    data, name, _ = imports.template_bytes(kind, language, format)
    headers, records = imports.parse_import_bytes(data, "." + format)
    mapping = imports.suggested_mapping(kind, headers)
    assert len(mapping) == len(SPECS[kind])
    assert len(records) == 1
    assert name.endswith(f"-{language}.{format}")


@pytest.mark.parametrize("kind", list(SPECS))
def test_entity_dry_run_create_duplicate_skip_explicit_update(context, kind):
    db, user, vehicle, driver = context
    record = sample(kind)
    job = upload(db, user, kind, [record])
    assert job.valid_rows == 1, rows(db, job)[0].errors
    assert db.query(MODELS[kind]).count() == 0
    result = imports.confirm_job(db, job, user, Mode.create_only, Transaction.file)
    assert result.created_rows == 1, rows(db, job)[0].errors
    assert result.status == "Completed"
    assert db.query(MODELS[kind]).count() == 1
    assert vehicle.odometer_km == 100000 and vehicle.status == 0
    assert driver.assigned_vehicle_id is None
    duplicate = upload(db, user, kind, [record])
    assert duplicate.invalid_rows == 1
    skip = upload(db, user, kind, [record], Mode.create_or_skip)
    assert rows(db, skip)[0].action == "skip"
    result = imports.confirm_job(db, skip, user, Mode.create_or_skip, Transaction.row)
    assert result.skipped_rows == 1 and result.status == "Completed"
    update = upload(db, user, kind, [record], Mode.update_existing)
    result = imports.confirm_job(db, update, user, Mode.update_existing, Transaction.file)
    assert result.updated_rows == 1, rows(db, update)[0].errors
    assert db.query(MODELS[kind]).count() == 1
    if kind == "Documents Metadata":
        assert db.query(DocumentVersion).count() == 2
        assert db.query(DocumentVersion).filter_by(is_current=True).count() == 1


@pytest.mark.parametrize("kind", list(SPECS))
def test_each_entity_file_duplicates_and_invalid_required_fields(context, kind):
    db, user, *_ = context
    record = sample(kind)
    job = upload(db, user, kind, [record, record])
    assert job.invalid_rows == 2
    assert all(any(e["code"] == "duplicate_in_file" for e in r.errors) for r in rows(db, job))
    key = next(key for key, _, _, required, _ in SPECS[kind] if required)
    record[key] = ""
    invalid = upload(db, user, kind, [record])
    assert invalid.invalid_rows == 1


def test_historical_services_dates_precision_and_mileage(context):
    db, user, vehicle, _ = context
    job = upload(db, user, "Historical Services", [sample("Historical Services", service_date="15/01/2020", cost="50.005", labor_cost="20.005", parts_cost="30")])
    assert job.valid_rows == 1
    imports.confirm_job(db, job, user, Mode.create_only, Transaction.file)
    record = db.query(VehicleService).one()
    assert record.service_date == datetime(2020, 1, 15)
    assert record.cost == Decimal("50.01") and record.labor_cost == Decimal("20.01")
    assert record.next_service_odometer_km == 30000
    assert vehicle.odometer_km == 100000
    future = upload(db, user, "Historical Services", [sample("Historical Services", service_date="2999-01-01")])
    assert future.invalid_rows == 1


@pytest.mark.parametrize("country,plate,normalized", [("AL","aa-123-aa","AA123AA"),("XK","01 123 ab","01123AB")])
def test_country_plate_resolution(context, country, plate, normalized):
    db, user, vehicle, _ = context
    vehicle.registration_country, vehicle.license_plate_normalized = country, normalized
    db.commit()
    job = upload(db, user, "Historical Services", [sample("Historical Services", registration_country=country, license_plate=plate)])
    assert job.valid_rows == 1
    assert rows(db,job)[0].mapped_data["vehicle_id"] == vehicle.id


def test_fuel_snapshot_units_and_exact_rounding(context):
    db, user, vehicle, _ = context
    record = sample("Fuel and Charging Records", unit="kWh", fuel_type="Electric", quantity="10.125", unit_cost="0.1234", total_cost="1.25")
    job = upload(db, user, "Fuel and Charging Records", [record])
    assert job.valid_rows == 1
    imports.confirm_job(db, job, user, Mode.create_only, Transaction.file)
    fuel = db.query(VehicleFuel).one()
    assert fuel.unit == "KWH" and fuel.fuel_type == "Electric" and fuel.liters is None
    assert fuel.quantity == Decimal("10.125") and fuel.unit_cost == Decimal("0.1234") and fuel.total_cost == Decimal("1.25")
    record.pop("fuel_type")
    update = upload(db,user,"Fuel and Charging Records",[record],Mode.update_existing)
    assert update.valid_rows == 1  # keeps the historical Electric snapshot despite current Petrol
    imports.confirm_job(db, update, user, Mode.update_existing, Transaction.file)
    assert fuel.fuel_type == "Electric"
    for changes in ({"unit":"L", "fuel_type":"Electric"}, {"quantity":"0"}, {"quantity":"NaN"}, {"unit_cost":"Infinity"}, {"total_cost":"2.00"}):
        invalid = upload(db,user,"Fuel and Charging Records",[dict(record, **changes)])
        assert invalid.invalid_rows == 1


def test_assignment_overlap_warnings_preserve_old_corrections(context):
    db,user,vehicle,driver=context
    first=sample("Vehicle Assignments")
    second=sample("Vehicle Assignments",start_datetime="2024-01-15T09:00:00+01:00",end_datetime="2024-01-15T18:00:00",start_odometer_km=25050)
    # UTC normalization makes the start identical, therefore duplicate identity.
    duplicate=upload(db,user,"Vehicle Assignments",[first,second])
    assert duplicate.invalid_rows == 2
    second["start_datetime"]="2024-01-15T10:00:00+01:00"
    job=upload(db,user,"Vehicle Assignments",[first,second])
    assert job.valid_rows==2
    assert all(row.mapped_data["_warnings"] for row in rows(db,job))
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    assert job.created_rows==2
    assert db.query(VehicleAssignment).count()==2
    scheduled=upload(db,user,"Vehicle Assignments",[dict(second,status="Scheduled",start_datetime="2024-01-15T12:00:00")])
    assert scheduled.invalid_rows==1
    active=upload(db,user,"Vehicle Assignments",[dict(second,status="Active")])
    assert active.invalid_rows==1


def test_document_owner_dates_secure_files_and_version_history(context):
    db,user,vehicle,driver=context
    first=upload(db,user,"Documents Metadata",[sample("Documents Metadata")])
    imports.confirm_job(db,first,user,Mode.create_only,Transaction.file)
    doc=db.query(VehiclePaper).one()
    path=get_settings().uploads_path/'documents'/'safe.pdf'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'%PDF-1.4 secure existing upload')
    attachment=Attachment(original_filename="safe.pdf",stored_filename="safe.pdf",storage_path="documents/safe.pdf",mime_type="application/pdf",file_size=path.stat().st_size,uploaded_by=user.id,entity_type="VehiclePaper",entity_id=doc.id)
    db.add(attachment);db.commit()
    job=upload(db,user,"Documents Metadata",[sample("Documents Metadata",attachment_id=attachment.id,issuing_authority="Authority")],Mode.update_existing)
    assert job.valid_rows==1
    imports.confirm_job(db,job,user,Mode.update_existing,Transaction.file)
    versions=db.query(DocumentVersion).order_by(DocumentVersion.version_number).all()
    assert len(versions)==2 and versions[0].file_path=="" and not versions[0].is_current
    assert versions[1].attachment_id==attachment.id
    assert doc.file_path==f'/api/v1/files/{attachment.id}/download'
    invalid=upload(db,user,"Documents Metadata",[sample("Documents Metadata",license_plate="",registration_country="",employee_number="EMP-001",attachment_id=attachment.id)])
    assert invalid.invalid_rows==1
    for changes in ({"attachment_id":"../../secret"},{"employee_number":"EMP-001"},{"expiry_date":"2020-01-01"},{"status":"Verified"}):
        invalid=upload(db,user,"Documents Metadata",[sample("Documents Metadata",**changes)])
        assert invalid.invalid_rows==1


def test_parts_vendor_barcode_and_mapped_only_updates(context):
    db,user,*_=context
    vendor=upload(db,user,"Vendors",[sample("Vendors",name=" Workshop A ",phone="123")])
    imports.confirm_job(db,vendor,user,Mode.create_only,Transaction.file)
    changed=upload(db,user,"Vendors",[{"name":"workshop a","vendor_type":"Workshop","city":"Tirana"}],Mode.update_existing)
    imports.confirm_job(db,changed,user,Mode.update_existing,Transaction.file)
    assert db.query(Vendor).one().phone=="123"
    job=upload(db,user,"Parts",[sample("Parts",barcode="BAR1",supplier="WORKSHOP A",unit_cost="0.12345",minimum_stock="1.2345")])
    assert job.valid_rows==1
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    part=db.query(Part).one()
    assert part.unit_cost==Decimal('0.1235') and part.minimum_stock==Decimal('1.235')
    duplicate=upload(db,user,"Parts",[sample("Parts",part_number="OTHER",barcode="bar1")],Mode.update_existing)
    assert duplicate.invalid_rows==1
    duplicate=upload(db,user,"Parts",[sample("Parts",part_number="X",barcode="B"),sample("Parts",part_number="Y",barcode="b")])
    assert duplicate.invalid_rows==2


@pytest.mark.parametrize("kind",list(SPECS))
@pytest.mark.parametrize("transaction",[Transaction.row,Transaction.file])
def test_runtime_partial_failure_and_rollback_each_entity(context,monkeypatch,kind,transaction):
    db,user,*_=context
    first=sample(kind)
    unique_key={"Historical Services":"service_date","Fuel and Charging Records":"refuel_date","Vehicle Assignments":"start_datetime","Documents Metadata":"document_number","Vendors":"name","Parts":"part_number"}[kind]
    second=dict(first,**{unique_key:"2023-01-01" if "date" in unique_key else "SECOND"})
    job=upload(db,user,kind,[first,second])
    assert job.valid_rows==2, [r.errors for r in rows(db,job)]
    original=imports._apply_row
    def fail_second(session,job,row,user):
        if row.row_number==3:
            raise ValueError("forced runtime conflict")
        return original(session,job,row,user)
    monkeypatch.setattr(imports,"_apply_row",fail_second)
    imports.confirm_job(db,job,user,Mode.create_only,transaction)
    assert db.query(MODELS[kind]).count()==(1 if transaction==Transaction.row else 0)
    assert job.status==("Completed With Errors" if transaction==Transaction.row else "Failed")
    report=imports.error_report(job,rows(db,job),"sq").decode('utf-8-sig')
    assert ("import_failed" if transaction==Transaction.row else "import_rolled_back") in report


def test_revalidation_changed_mode_target_and_permission(context):
    db,user,*_=context
    job=upload(db,user,"Vendors",[sample("Vendors")])
    with pytest.raises(HTTPException):
        imports.confirm_job(db,job,user,Mode.update_existing,Transaction.file)
    db.add(Vendor(name="Workshop A",vendor_type="Workshop"));db.commit()
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.row)
    assert job.created_rows==0 and job.status=="Completed With Errors"
    update=upload(db,user,"Vendors",[sample("Vendors")],Mode.update_existing)
    db.query(Vendor).one().city="Changed after validation";db.commit()
    imports.confirm_job(db,update,user,Mode.update_existing,Transaction.row)
    assert update.updated_rows==0
    assert db.query(Vendor).one().city=="Changed after validation"
    other=upload(db,user,"Parts",[sample("Parts")])
    user.role="viewer";db.commit()
    with pytest.raises(HTTPException) as error:
        imports.confirm_job(db,other,user,Mode.create_only,Transaction.row)
    assert error.value.status_code==403


def test_file_mode_invalid_rows_writes_nothing_and_csv_injection(context):
    db,user,*_=context
    job=upload(db,user,"Vendors",[sample("Vendors"),sample("Vendors",name="=SUM(1)",vendor_type="invalid")])
    assert job.invalid_rows==1
    with pytest.raises(HTTPException):
        imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    assert db.query(Vendor).count()==0
    assert "'=SUM(1)" in imports.error_report(job,rows(db,job)).decode('utf-8-sig')


def test_chunked_progress_and_large_source_limits(context,monkeypatch):
    db,user,*_=context
    monkeypatch.setattr(imports,"CHUNK_SIZE",2)
    phases=[]
    original=imports.write_progress
    def capture(job,phase,processed,total):
        original(job,phase,processed,total)
        phases.append((phase,processed,read_progress(job)["progress_percent"]))
    monkeypatch.setattr(imports,"write_progress",capture)
    job=upload(db,user,"Vendors",[sample("Vendors",name=f"Vendor {i}") for i in range(8)])
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    assert job.created_rows==8
    assert ("Validating",6,75) in phases and ("Importing",6,75) in phases
    with pytest.raises(HTTPException):
        imports.parse_import_bytes(b'A\n'+b'x\n'*20001,'.csv')
    with pytest.raises(HTTPException):
        imports.parse_import_bytes(b'A\nx,y\n','.csv')
    book=Workbook();book.active.append(['A']);book.active.append(['=1+1']);buffer=BytesIO();book.save(buffer)
    with pytest.raises(HTTPException):
        imports.parse_import_bytes(buffer.getvalue(),'.xlsx')


def test_tenant_lookup_and_job_identity_map_boundary(context):
    db,user,vehicle,_=context
    # Seed another company using an unscoped session, including identical natural identifiers.
    with Session(db.bind) as seed:
        seed.add(Company(id=2,name="Two",slug="two"));seed.flush()
        seed.add(Vehicle(company_id=2,registration_country="AL",license_plate="AA 123 AA",license_plate_normalized="AA123AA",brand="X",model="X",fuel_type="Electric",vehicle_location="Secret"))
        seed.add(Vendor(company_id=2,name="Workshop A",vendor_type="Workshop"));seed.commit()
    invalid=upload(db,user,"Historical Services",[sample("Historical Services",registration_country="AL",license_plate="AA123AA")])
    assert invalid.invalid_rows==1
    job=upload(db,user,"Vendors",[sample("Vendors")])
    assert job.valid_rows==1
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    assert job.created_rows==1
    from app.api.v1.endpoints.imports import authorize_job
    set_tenant_context(db,2)
    with pytest.raises(HTTPException) as error:
        authorize_job(job,user,db)
    assert error.value.status_code==404


def test_http_permissions_templates_validation_and_error_download(context):
    db,user,*_=context
    from app.main import app
    from app.core.security import get_current_user
    app.dependency_overrides[get_db]=lambda: db
    app.dependency_overrides[get_current_user]=lambda: user
    try:
        with TestClient(app) as client:
            assert client.get('/api/v1/imports/templates/Parts?format=xlsx&language=sq').status_code==200
            response=client.post('/api/v1/imports/upload',data={'entity_type':'Vendors'},files={'file':('vendors.csv',b'Name,Vendor Type\nExample,Invalid\n','text/csv')})
            assert response.status_code==201,response.text
            payload=response.json();identifier=payload['id']
            response=client.post(f'/api/v1/imports/{identifier}/validate',json={'column_mapping':payload['suggested_mapping'],'update_mode':'create_only'})
            assert response.status_code==200,response.text
            assert response.json()['invalid_rows']==1
            report=client.get(f'/api/v1/imports/{identifier}/errors?language=sq')
            assert report.status_code==200 and 'Kodet e Gabimeve' in report.text
            assert report.headers['cache-control']=='private, no-store'
            assert 'attachment;' in report.headers['content-disposition']
            user.role='viewer';db.commit()
            assert client.get(f'/api/v1/imports/{identifier}/errors').status_code==403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("kind,path", [
    ("Historical Services", "/services/history"), ("Fuel and Charging Records", "/fuel/all"),
    ("Vehicle Assignments", "/vehicle-assignments"), ("Documents Metadata", "/compliance/documents"),
    ("Vendors", "/vendors"), ("Parts", "/parts"),
])
def test_imported_records_read_back_through_existing_api(context, kind, path):
    db,user,*_=context
    if kind == "Documents Metadata":
        db.add(DocumentRequirement(document_type="Insurance", required=True, is_active=True, applies_to_driver=False))
        db.commit()
    job=upload(db,user,kind,[sample(kind)])
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    assert job.created_rows==1
    from app.main import app
    from app.core.security import get_current_user
    app.dependency_overrides[get_db]=lambda: db
    app.dependency_overrides[get_current_user]=lambda: user
    try:
        with TestClient(app) as client:
            response=client.get('/api/v1'+path)
            assert response.status_code==200,response.text
            result=response.json()
            records=result if isinstance(result,list) else result['items']
            assert len(records)==1
            if kind=='Historical Services':
                assert records[0]['source']=='Imported'
    finally:
        app.dependency_overrides.clear()


def test_scoped_or_missing_domain_permissions_cannot_import(context):
    db,user,*_=context
    from app.core.authorization import seed_authorization_defaults
    seed_authorization_defaults(db)
    restricted=User(email='restricted@one.test',full_name='Restricted',hashed_password='unused',role='viewer')
    role=Role(code='import_only',name='Import Only')
    permission=db.query(Permission).filter_by(code='imports.manage').one()
    role.role_permissions.append(RolePermission(permission_id=permission.id))
    db.add_all([restricted,role]);db.flush()
    db.add(UserRole(user_id=restricted.id,role_id=role.id));db.commit()
    with pytest.raises(HTTPException) as denied:
        imports.authorize_import(db,restricted,'Vendors')
    assert denied.value.status_code==403
    vendor_permission=db.query(Permission).filter_by(code='vendors.manage').one()
    role.role_permissions.append(RolePermission(permission_id=vendor_permission.id))
    location=Location(code='LOC',name='Location');db.add(location);db.flush()
    db.query(UserRole).filter_by(user_id=restricted.id).one().location_id=location.id;db.commit()
    with pytest.raises(HTTPException):
        imports.authorize_import(db,restricted,'Vendors')


def test_localized_permission_error_and_fractional_odometer(context):
    db,user,vehicle,_=context
    from app.core.i18n import translate
    assert 'leje' in translate('import_permission_required','sq')
    invalid=upload(db,user,'Fuel and Charging Records',[sample('Fuel and Charging Records',odometer_km='1.0001')])
    assert invalid.invalid_rows==1


def test_same_job_cannot_be_claimed_or_confirmed_twice(context):
    db,user,*_=context
    job=upload(db,user,'Vendors',[sample('Vendors')])
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    with pytest.raises(HTTPException) as conflict:
        imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    assert conflict.value.status_code==409
    assert db.query(Vendor).count()==1


@pytest.mark.parametrize('transaction',[Transaction.row,Transaction.file])
def test_real_database_constraint_failure_is_transactional(context,monkeypatch,transaction):
    db,user,*_=context
    job=upload(db,user,'Parts',[sample('Parts'),sample('Parts',part_number='SECOND')])
    original=imports._apply_row
    def violate_constraint(session,job,row,user):
        action,target=original(session,job,row,user)
        if row.row_number==3:
            part=session.get(Part,target)
            part.unit_cost=Decimal('-1')
            session.flush()
        return action,target
    monkeypatch.setattr(imports,'_apply_row',violate_constraint)
    imports.confirm_job(db,job,user,Mode.create_only,transaction)
    assert db.query(Part).count()==(1 if transaction==Transaction.row else 0)
    assert job.status==('Completed With Errors' if transaction==Transaction.row else 'Failed')


def test_related_vehicle_snapshot_change_requires_revalidation(context):
    db,user,vehicle,_=context
    record=sample('Fuel and Charging Records')
    record.pop('fuel_type')
    job=upload(db,user,'Fuel and Charging Records',[record])
    vehicle.fuel_type='Diesel';db.commit()
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.row)
    assert job.created_rows==0
    assert db.query(VehicleFuel).count()==0


def test_document_attachment_archived_after_validation_is_rejected(context):
    db,user,*_=context
    job=upload(db,user,'Documents Metadata',[sample('Documents Metadata')])
    imports.confirm_job(db,job,user,Mode.create_only,Transaction.file)
    doc=db.query(VehiclePaper).one()
    path=get_settings().uploads_path/'existing.pdf';path.write_bytes(b'%PDF-1.4')
    attachment=Attachment(original_filename='existing.pdf',stored_filename='existing.pdf',storage_path='existing.pdf',mime_type='application/pdf',file_size=8,uploaded_by=user.id,entity_type='VehiclePaper',entity_id=doc.id)
    db.add(attachment);db.commit()
    update=upload(db,user,'Documents Metadata',[sample('Documents Metadata',attachment_id=attachment.id)],Mode.update_existing)
    assert update.valid_rows==1
    attachment.archived=True;db.commit()
    imports.confirm_job(db,update,user,Mode.update_existing,Transaction.row)
    assert update.updated_rows==0 and db.query(DocumentVersion).count()==1
