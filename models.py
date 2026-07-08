from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


# ─────────────────────────────────────────────
# TABLE 1: Every file uploaded by the user
# ─────────────────────────────────────────────
class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    file_id         = Column(String, primary_key=True)   # UUID
    original_filename = Column(String, nullable=False)
    file_type       = Column(String, nullable=False)     # "inventory" | "supplier" | "shipment"
    upload_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    row_count       = Column(Integer, default=0)
    status          = Column(String, default="pending")  # pending | confirmed | rejected
    column_mapping  = Column(JSON, nullable=True)        # AI-inferred column mapping stored for audit

    # Relationships
    inventory_items = relationship("Inventory", back_populates="source_file", cascade="all, delete-orphan")
    suppliers       = relationship("Supplier",  back_populates="source_file", cascade="all, delete-orphan")
    shipments       = relationship("Shipment",  back_populates="source_file", cascade="all, delete-orphan")
    conflicts_a     = relationship("Conflict", foreign_keys="Conflict.file_id_a", back_populates="file_a")
    conflicts_b     = relationship("Conflict", foreign_keys="Conflict.file_id_b", back_populates="file_b")


# ─────────────────────────────────────────────
# TABLE 2: Normalized inventory records
# ─────────────────────────────────────────────
class Inventory(Base):
    __tablename__ = "inventory"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    file_id              = Column(String, ForeignKey("uploaded_files.file_id"), nullable=False)
    product_id           = Column(String, nullable=False)
    product_name         = Column(String, nullable=False)
    quantity_in_stock    = Column(Integer, nullable=False)
    reorder_threshold    = Column(Integer, nullable=False)
    warehouse            = Column(String, default="Main Warehouse")
    supplier_info        = Column(String, nullable=True)

    # Fields that were previously hardcoded — now come from the data
    unit_cost            = Column(Float, nullable=True)   # Was hardcoded as 25.50
    avg_daily_consumption = Column(Float, nullable=True)  # Was hardcoded as 6.4
    lead_time_days       = Column(Integer, nullable=True) # Was hardcoded as 7

    is_active            = Column(Boolean, default=True)  # False if overridden by newer upload
    created_at           = Column(DateTime(timezone=True), server_default=func.now())

    source_file = relationship("UploadedFile", back_populates="inventory_items")


# ─────────────────────────────────────────────
# TABLE 3: Supplier records
# ─────────────────────────────────────────────
class Supplier(Base):
    __tablename__ = "suppliers"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    file_id               = Column(String, ForeignKey("uploaded_files.file_id"), nullable=False)
    supplier_name         = Column(String, nullable=False)
    base_cost_per_unit    = Column(Float, nullable=False)
    on_time_delivery_rate = Column(Float, nullable=False)  # 0.0 to 1.0
    lead_time_days        = Column(Integer, nullable=False)
    quality_rating        = Column(Float, nullable=False)  # 1.0 to 5.0
    historical_issues     = Column(Integer, default=0)
    contact_info          = Column(String, nullable=True)
    is_active             = Column(Boolean, default=True)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())

    source_file = relationship("UploadedFile", back_populates="suppliers")


# ─────────────────────────────────────────────
# TABLE 4: Shipment records
# ─────────────────────────────────────────────
class Shipment(Base):
    __tablename__ = "shipments"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    file_id           = Column(String, ForeignKey("uploaded_files.file_id"), nullable=False)
    shipment_id       = Column(String, nullable=False)
    product_id        = Column(String, nullable=True)
    quantity          = Column(Integer, nullable=True)
    supplier          = Column(String, nullable=True)
    carrier           = Column(String, nullable=True)
    expected_delivery = Column(String, nullable=True)  # ISO date string
    actual_delivery   = Column(String, nullable=True)
    is_on_time        = Column(Boolean, nullable=True)
    carrier_avg_delay = Column(Float, default=0.0)
    is_active         = Column(Boolean, default=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    source_file = relationship("UploadedFile", back_populates="shipments")


# ─────────────────────────────────────────────
# TABLE 5: Conflicts between files
# ─────────────────────────────────────────────
class Conflict(Base):
    __tablename__ = "conflicts"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    table_name   = Column(String, nullable=False)       # "inventory" | "suppliers" | "shipments"
    product_name = Column(String, nullable=False)
    file_id_a    = Column(String, ForeignKey("uploaded_files.file_id"), nullable=False)  # existing
    file_id_b    = Column(String, ForeignKey("uploaded_files.file_id"), nullable=False)  # incoming
    field_name   = Column(String, nullable=False)       # which field differs e.g. "quantity_in_stock"
    value_a      = Column(String, nullable=True)        # existing value
    value_b      = Column(String, nullable=True)        # incoming value
    resolution   = Column(String, nullable=True)        # "use_existing" | "use_incoming" | "keep_both"
    resolved_at  = Column(DateTime(timezone=True), nullable=True)

    file_a = relationship("UploadedFile", foreign_keys=[file_id_a], back_populates="conflicts_a")
    file_b = relationship("UploadedFile", foreign_keys=[file_id_b], back_populates="conflicts_b")