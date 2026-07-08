import csv
import random
import datetime

# Categories and Products
CATEGORIES = {
    "Electronics": ["Sensor Module X", "Lithium Battery Pack", "Microcontroller Board", "LCD Display Unit", "RFID Tracker"],
    "Medical Supplies": ["Medical-Grade Gloves", "N95 Respirators", "Surgical Masks", "Disinfectant Wipes", "IV Drip Tubes"],
    "Industrial Parts": ["Steel Wire Rope", "Bearings Set", "Conveyor Belt Rubber", "Hydraulic Pump", "PVC Pipes 50mm"],
    "Chemicals": ["Industrial Solvent Alpha", "Epoxy Resin", "Machine Lubricant", "Coolant Liquid", "Chemical Resistant Gloves"],
    "Packaging": ["Cardboard Boxes Large", "Bubble Wrap Roll", "Pallet Wrap Film", "Shipping Labels", "Packing Tape"]
}

WAREHOUSES = ["WH-North", "WH-South", "WH-East", "WH-West", "WH-Central"]
SUPPLIERS = [
    {"name": "EmergencyFirst Supply", "reliability": 0.99, "cost_multiplier": 1.5, "lead_time_days": 1},
    {"name": "SafeBreath Corp", "reliability": 0.85, "cost_multiplier": 1.0, "lead_time_days": 5},
    {"name": "TechComponents Inc", "reliability": 0.92, "cost_multiplier": 1.1, "lead_time_days": 4},
    {"name": "GlobalSteel Parts", "reliability": 0.70, "cost_multiplier": 0.8, "lead_time_days": 10},
    {"name": "ChemPro Industries", "reliability": 0.88, "cost_multiplier": 0.9, "lead_time_days": 6},
    {"name": "PackIt Logistics", "reliability": 0.95, "cost_multiplier": 1.0, "lead_time_days": 3}
]

CARRIERS = ["GlobalQuick Logistics", "HeavyHaul Co", "RegionalDel Ltd", "FastTrack Shipping", "AirFreight Elite"]

def generate_inventory(num_rows=150):
    products = []
    idx = 1
    for i in range(num_rows):
        category = random.choice(list(CATEGORIES.keys()))
        prod_name = random.choice(CATEGORIES[category]) + f" (Variant {random.randint(1, 5)})"
        
        # Inject some deliberate critical items
        is_critical = idx in [2, 15, 45, 88]
        
        quantity = random.randint(5, 50) if is_critical else random.randint(100, 1000)
        reorder_threshold = random.randint(50, 100) if is_critical else random.randint(50, 300)
        avg_daily = random.randint(10, 30) if is_critical else random.randint(5, 20)
        
        products.append({
            "product_id": f"SKU-{idx:03d}",
            "product_name": prod_name,
            "category": category,
            "quantity_in_stock": quantity,
            "reorder_threshold": reorder_threshold,
            "warehouse": random.choice(WAREHOUSES),
            "supplier_info": random.choice(SUPPLIERS)["name"],
            "unit_cost": round(random.uniform(10.0, 500.0), 2),
            "avg_daily_consumption": avg_daily,
            "lead_time_days": random.randint(1, 14)
        })
        idx += 1

    with open('data/inventory_master_complex.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=products[0].keys())
        writer.writeheader()
        writer.writerows(products)

def generate_shipments(num_rows=150):
    shipments = []
    base_date = datetime.date.today()
    
    for i in range(num_rows):
        # Inject some delayed shipments
        is_delayed = random.random() < 0.25 # 25% delayed
        carrier = random.choice(CARRIERS)
        
        # GlobalQuick has terrible stats on purpose
        if carrier == "GlobalQuick Logistics":
            is_delayed = random.random() < 0.8
            
        shipments.append({
            "shipment_id": f"SHP-{i+1:03d}",
            "product_id": f"SKU-{random.randint(1, 150):03d}",
            "quantity": random.randint(50, 500),
            "origin": random.choice(WAREHOUSES),
            "destination": random.choice(WAREHOUSES),
            "carrier": carrier,
            "expected_delivery": (base_date + datetime.timedelta(days=random.randint(-2, 10))).isoformat(),
            "status": "Delayed" if is_delayed else random.choice(["In Transit", "Delivered", "Pending"]),
            "is_on_time": str(not is_delayed).lower(),
            "weather_impact": random.choice(["None", "Heavy Rain", "Snowstorm", "Hurricane"]) if is_delayed else "None",
            "traffic_delay_hours": random.randint(12, 72) if is_delayed else 0,
            "carrier_avg_delay": round(random.uniform(2.0, 5.0), 1) if carrier == "GlobalQuick Logistics" else round(random.uniform(0.1, 1.5), 1)
        })

    with open('data/shipments_master_complex.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=shipments[0].keys())
        writer.writeheader()
        writer.writerows(shipments)

def generate_suppliers():
    supp_data = []
    for s in SUPPLIERS:
        supp_data.append({
            "supplier_id": f"SUP-{random.randint(100, 999)}",
            "supplier_name": s["name"],
            "contact_email": f"sales@{s['name'].lower().replace(' ', '')}.com",
            "on_time_delivery_rate": s["reliability"],
            "quality_rating": round(random.uniform(3.5, 5.0), 1) if s["reliability"] > 0.8 else round(random.uniform(2.0, 3.5), 1),
            "historical_issues": random.randint(0, 1) if s["reliability"] > 0.8 else random.randint(3, 8),
            "base_cost_per_unit": round(random.uniform(10.0, 50.0) * s["cost_multiplier"], 2),
            "base_lead_time_days": s["lead_time_days"],
            "certifications": "ISO9001" if s["reliability"] > 0.8 else "None"
        })

    with open('data/suppliers_master_complex.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=supp_data[0].keys())
        writer.writeheader()
        writer.writerows(supp_data)

if __name__ == "__main__":
    generate_inventory(150)
    generate_shipments(150)
    generate_suppliers()
    print("Complex datasets generated successfully in data/ directory.")
