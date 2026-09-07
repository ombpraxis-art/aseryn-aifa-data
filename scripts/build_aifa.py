#!/usr/bin/env python3
import csv
import io
import json
import re
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MEDS_URL = "https://drive.aifa.gov.it/farmaci/confezioni_fornitura.csv"
ACTIVE_URL = "https://drive.aifa.gov.it/farmaci/PA_confezioni.csv"

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
SHARDS = PUBLIC / "shards"

def download(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ASERYN-AIFA-Builder/2.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass

    raise RuntimeError(f"Impossibile decodificare {url}")

def norm(value):
    value = "" if value is None else str(value)
    value = unicodedata.normalize("NFD", value)
    value = "".join(
        c for c in value
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(
        r"[^a-zA-Z0-9]+",
        " ",
        value.lower(),
    ).strip()

def clean(value):
    if value is None:
        return None

    value = str(value).strip().strip('"')

    if not value or value.upper() in {"NULL", "N/A", "ND"}:
        return None

    return value

def detect_delimiter(text):
    try:
        return csv.Sniffer().sniff(
            text[:10000],
            delimiters=";,|\t",
        ).delimiter
    except Exception:
        return ";"

def rows(text):
    return csv.DictReader(
        io.StringIO(text),
        delimiter=detect_delimiter(text),
    )

def first(row, *names):
    upper = {
        str(key).strip().upper(): value
        for key, value in row.items()
    }

    for name in names:
        if name.upper() in upper:
            return clean(upper[name.upper()])

    return None

def encode_char(char):
    if "a" <= char <= "z":
        return char

    if char.isdigit():
        return "0"

    return "_"

def shard_key(name):
    compact = re.sub(
        r"\s+",
        "",
        norm(name),
    )

    first_char = compact[0] if len(compact) > 0 else "_"
    second_char = compact[1] if len(compact) > 1 else "_"

    return (
        encode_char(first_char) +
        encode_char(second_char)
    )

def main():
    PUBLIC.mkdir(exist_ok=True)
    SHARDS.mkdir(parents=True, exist_ok=True)

    meds_text = download(MEDS_URL)
    active_text = download(ACTIVE_URL)

    active_by_aic = defaultdict(list)

    for row in rows(active_text):
        aic = first(row, "CODICE_AIC", "AIC")

        if not aic:
            continue

        ingredient = first(
            row,
            "PRINCIPIO_ATTIVO",
            "PA",
        )

        qty = first(
            row,
            "QUANTITA",
        )

        unit = first(
            row,
            "UNITA_MISURA",
        )

        if ingredient:
            active_by_aic[aic].append({
                "ingredient": ingredient,
                "qty": qty,
                "unit": unit,
            })

    shards = defaultdict(list)
    count = 0
    now = datetime.now(timezone.utc).isoformat()

    for row in rows(meds_text):
        aic = first(row, "CODICE_AIC", "AIC")
        name = first(row, "DENOMINAZIONE", "NOME")

        if not aic or not name:
            continue

        active_rows = active_by_aic.get(aic, [])

        ingredients = []
        strengths = []

        for active in active_rows:
            ingredient = active["ingredient"]

            if ingredient and ingredient not in ingredients:
                ingredients.append(ingredient)

            if active["qty"]:
                strength = active["qty"]

                if active["unit"]:
                    strength += f" {active['unit']}"

                if strength not in strengths:
                    strengths.append(strength)

        item = {
            "aic_code": aic,
            "name": name,
            "active_ingredient":
                " + ".join(ingredients)
                or first(row, "PA_ASSOCIATI"),
            "strength":
                " + ".join(strengths)
                or None,
            "pharmaceutical_form":
                first(row, "FORMA"),
            "package_description":
                first(row, "DESCRIZIONE"),
            "package_quantity": None,
            "package_unit": None,
            "company":
                first(row, "RAGIONE_SOCIALE"),
            "administrative_status":
                first(row, "STATO_AMMINISTRATIVO"),
            "atc_code":
                first(row, "CODICE_ATC"),
            "dosage_units": None,
            "supply_type":
                first(row, "FORNITURA"),
            "source_updated_at": None,
            "imported_at": now,
        }

        item["search_text"] = norm(
            " ".join(
                str(value)
                for value in [
                    item["name"],
                    item["active_ingredient"],
                    item["strength"],
                    item["package_description"],
                    item["aic_code"],
                ]
                if value
            )
        )

        shards[shard_key(name)].append(item)
        count += 1

    for old in SHARDS.glob("*.json"):
        old.unlink()

    for key, items in shards.items():
        items.sort(
            key=lambda item: (
                norm(item["name"]),
                item["aic_code"],
            )
        )

        (SHARDS / f"{key}.json").write_text(
            json.dumps(
                items,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    index = {
        "version": now[:10],
        "updated_at": now,
        "row_count": count,
        "shard_strategy": "first_two_name_characters",
        "shard_count": len(shards),
    }

    (PUBLIC / "index.json").write_text(
        json.dumps(
            index,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(
        f"Creati {len(shards)} shard "
        f"per {count} confezioni."
    )

if __name__ == "__main__":
    main()
