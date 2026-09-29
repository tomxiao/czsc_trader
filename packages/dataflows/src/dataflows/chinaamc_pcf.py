"""Cross-check a 159326 basket against ChinaAMC's historical PCF XML."""

from __future__ import annotations

from datetime import date
import hashlib
import re
import xml.etree.ElementTree as ET

import pandas as pd
import requests

from .errors import DataContractError, IncompleteDataError, SourceNotReadyError


_BASE = "https://accountquery.chinaamc.com/front/front/out/etf"
_FILE_NAME = re.compile(r"pcf_159326_\d{8}\.xml\Z")
_MAX_XML_BYTES = 2_000_000


def _post(path: str, data: dict[str, str]) -> requests.Response:
    try:
        response = requests.post(f"{_BASE}/{path}", data=data, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SourceNotReadyError("ChinaAMC PCF source is unavailable") from exc
    return response


def _text(parent: ET.Element, tag: str) -> str:
    value = parent.findtext(f"{{*}}{tag}")
    if value is None or not value.strip():
        raise DataContractError("ChinaAMC PCF XML is missing a required field", field=tag)
    return value.strip()


def verify_chinaamc_pcf_components(
    symbol: str, trade_date: str, basket: pd.DataFrame,
) -> dict[str, str | int | bool]:
    """Verify codes and quantities; do not infer publication time or past revisions."""

    if symbol != "159326.SZ":
        raise DataContractError("official PCF content check supports only 159326.SZ")
    try:
        day = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise DataContractError("official PCF check requires an ISO trade date") from exc
    if day.isoformat() != trade_date:
        raise DataContractError("official PCF check requires an ISO trade date")
    required = {"Date", "ConstituentSymbol", "Quantity"}
    if not required <= set(basket) or basket.empty or not basket["Date"].eq(trade_date).all():
        raise DataContractError("official PCF check requires one complete trade-date basket")
    if basket["ConstituentSymbol"].duplicated().any():
        raise DataContractError("official PCF check received duplicate constituents")

    try:
        listing = _post("tradeList", {
            "fundCode": "159326", "queryDate": trade_date, "instType": "",
        }).json()
    except requests.exceptions.JSONDecodeError as exc:
        raise DataContractError("ChinaAMC PCF listing is not JSON") from exc
    if not isinstance(listing, dict) or listing.get("status") != 1 or not isinstance(listing.get("data"), dict):
        raise SourceNotReadyError("ChinaAMC has no PCF listing for the trade date")
    source = listing["data"]
    file_name = source.get("fileName")
    expected_name = f"pcf_159326_{day:%Y%m%d}.xml"
    if not isinstance(file_name, str) or not _FILE_NAME.fullmatch(file_name):
        raise DataContractError("ChinaAMC returned an invalid PCF file name")
    if file_name != expected_name:
        raise DataContractError("ChinaAMC PCF file date differs from request")
    response = _post("query/etfDownload", {
        "fileName": file_name, "year": str(source.get("year") or ""),
        "fundCode": "159326",
    })
    payload = response.content
    if not payload or len(payload) > _MAX_XML_BYTES:
        raise IncompleteDataError("ChinaAMC PCF XML is empty or oversized")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DataContractError("ChinaAMC PCF file is not valid XML") from exc
    if root.tag.rsplit("}", 1)[-1] != "PCFFile":
        raise DataContractError("ChinaAMC PCF XML has an unexpected root")
    if _text(root, "SecurityID") != "159326" or _text(root, "TradingDay") != f"{day:%Y%m%d}":
        raise DataContractError("ChinaAMC PCF XML identity differs from request")
    components = root.find("{*}Components")
    if components is None or not len(components):
        raise IncompleteDataError("ChinaAMC PCF XML has no components")
    official: dict[str, int] = {}
    for component in components:
        code = _text(component, "UnderlyingSecurityID")
        exchange = {"101": "SH", "102": "SZ"}.get(
            _text(component, "UnderlyingSecurityIDSource")
        )
        raw_quantity = _text(component, "ComponentShare")
        try:
            quantity = float(raw_quantity)
        except ValueError as exc:
            raise DataContractError("ChinaAMC PCF quantity is invalid") from exc
        if (
            not re.fullmatch(r"\d{6}", code) or exchange is None
            or quantity < 0 or not quantity.is_integer()
        ):
            raise DataContractError("ChinaAMC PCF component is invalid")
        symbol_code = f"{code}.{exchange}"
        if symbol_code in official:
            raise DataContractError("ChinaAMC PCF contains duplicate components")
        official[symbol_code] = int(quantity)
    try:
        total_records = int(_text(root, "TotalRecordNum"))
        market_records = int(_text(root, "RecordNum"))
    except ValueError as exc:
        raise DataContractError("ChinaAMC PCF record counts are invalid") from exc
    if total_records != len(official) or market_records != sum(
        symbol_code.endswith(".SZ") for symbol_code in official
    ):
        raise IncompleteDataError("ChinaAMC PCF record counts differ from components")
    expected: dict[str, int] = {}
    for row in basket.itertuples(index=False):
        code = str(row.ConstituentSymbol)
        quantity = int(row.Quantity)
        if not re.fullmatch(r"\d{6}\.(?:SH|SZ)", code) or quantity < 0 or quantity != row.Quantity:
            raise DataContractError("basket contains an invalid component")
        expected[code] = quantity
    if official != expected:
        raise DataContractError(
            "Tushare basket differs from ChinaAMC official PCF content",
            official_count=len(official), vendor_count=len(expected),
        )
    return {
        "official_pcf_code_quantity_verified": True,
        "official_pcf_source": "ChinaAMC historical PCF XML",
        "official_pcf_file_name": file_name,
        "official_pcf_sha256": hashlib.sha256(payload).hexdigest(),
        "official_pcf_component_count": len(official),
        "official_pcf_publication_timestamp_verified": False,
        "official_pcf_historical_revisions_verified": False,
    }
