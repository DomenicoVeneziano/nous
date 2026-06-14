# backend/services/export_service.py
import csv
import io
import json
from models.asset import Asset


def export_json(assets: list[Asset]) -> str:
    records = []
    for a in assets:
        records.append({
            "asset": a.asset,
            "status_code": a.status_code,
            "title": a.title,
            "content_length": a.content_length,
            "technologies": a.technologies or [],
            "dns_records": a.dns_records or [],
            "last_scanned": a.date_scanned.isoformat() if a.date_scanned else None,
        })
    return json.dumps(records, indent=2)


def export_csv(assets: list[Asset]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "asset", "status_code", "title", "content_length",
        "technologies", "dns_records", "last_scanned",
    ])
    for a in assets:
        writer.writerow([
            a.asset,
            a.status_code or "",
            a.title or "",
            a.content_length or "",
            ",".join(a.technologies or []),
            str(a.dns_records or []),
            a.date_scanned.isoformat() if a.date_scanned else "",
        ])
    return output.getvalue()
