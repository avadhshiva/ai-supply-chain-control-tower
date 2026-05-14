from faker import Faker
import pandas as pd
import random
from datetime import datetime, timedelta

fake = Faker()

# ---------------------------
# INVENTORY DATA
# ---------------------------

inventory_rows = []

for i in range(200):
    inventory_rows.append({
        "warehouse_id": f"WH-{random.randint(1,10):03}",
        "product_id": f"PRD-{random.randint(1,50):03}",
        "current_stock": random.randint(0, 10000),
        "reorder_point": random.randint(50, 500),
        "avg_daily_demand": random.randint(10, 200),
        "last_restock_date": fake.date_between(start_date='-1y', end_date='today'),
        "scenario_tag": random.choice([
            "normal",
            "low_stock",
            "critical",
            "overstocked"
        ])
    })

inventory_df = pd.DataFrame(inventory_rows)
inventory_df.to_csv("inventory.csv", index=False)

# ---------------------------
# SUPPLIERS DATA
# ---------------------------

supplier_rows = []

for i in range(200):
    supplier_rows.append({
        "supplier_id": f"SUP-{i+1:03}",
        "supplier_name": fake.company(),
        "reliability_score": round(random.uniform(0.5, 1.0), 2),
        "avg_lead_time_days": random.randint(1, 30),
        "on_time_delivery_rate": round(random.uniform(0.5, 1.0), 2),
        "scenario_tag": random.choice([
            "reliable",
            "delayed",
            "critical",
            "new"
        ])
    })

suppliers_df = pd.DataFrame(supplier_rows)
suppliers_df.to_csv("suppliers.csv", index=False)

# ---------------------------
# DELIVERY METRICS
# ---------------------------

delivery_rows = []

statuses = [
    "pending",
    "in_transit",
    "delayed",
    "delivered",
    "failed"
]

for i in range(200):
    sla_hours = random.randint(2, 48)
    actual_hours = random.randint(1, 72)

    delivery_rows.append({
        "delivery_id": f"DEL-{i+1:03}",
        "route_id": f"RT-{random.randint(1,20):03}",
        "status": random.choice(statuses),
        "sla_hours": sla_hours,
        "actual_hours": actual_hours,
        "scenario_tag": random.choice([
            "on_time",
            "delayed",
            "breach",
            "critical"
        ])
    })

delivery_df = pd.DataFrame(delivery_rows)
delivery_df.to_csv("delivery_metrics.csv", index=False)

print("Synthetic datasets generated successfully.")