"""
Клієнт Nova Poshta API v2.
Документація: https://developers.novaposhta.ua/documentation
"""
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz

NP_API_URL = "https://api.novaposhta.ua/v2.0/json/"
NP_PRINT_URL = "https://my.novaposhta.ua/scanSheet/printScanSheet/refs[]/{ref}/type/pdf/apiKey/{key}"
KIEV_TZ = pytz.timezone("Europe/Kiev")


class NPDocument:
    """ТТН з полями, потрібними для реєстру."""
    def __init__(self, data: dict):
        self.ref = data.get("Ref", "")
        self.number = data.get("IntDocNumber", "")
        self.recipient_name = (
            data.get("RecipientContactPerson")
            or data.get("RecipientFullName")
            or data.get("RecipientDescription", "")
        )
        self.recipient_city = data.get("CityRecipientDescription", "")
        self.weight = data.get("Weight", "")
        self.cost = data.get("Cost", "")
        self.cod = data.get("BackwardDeliverySum") or data.get("AfterpaymentOnGoodsCost") or 0
        self.date_created = data.get("DateTime", "")
        self.scan_sheet = data.get("ScanSheetNumber", "")
        self.state_id = str(data.get("StateId", ""))

    @property
    def is_draft(self) -> bool:
        """Чернетка = ТТН не включена в жоден реєстр і ще не передана на склад НП."""
        return not self.scan_sheet and self.state_id == "1"

    def __str__(self):
        try:
            cod_val = float(str(self.cod or 0))
        except (ValueError, TypeError):
            cod_val = 0
        cod_str = f" | НП: {cod_val:.0f} грн" if cod_val > 0 else ""
        name = self.recipient_name or "—"
        city = self.recipient_city or "—"
        return f"#{self.number} — {name} ({city}){cod_str}"


class NPRegistry:
    """Результат створеного реєстру."""
    def __init__(self, data: dict):
        self.ref = data.get("Ref", "")
        self.number = data.get("Number", "")
        self.date = data.get("DateTime", "")
        self.count = data.get("DocumentCount", "")


class NovaPooshtaClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _call(self, model: str, method: str, props: dict) -> dict:
        payload = {
            "apiKey": self.api_key,
            "modelName": model,
            "calledMethod": method,
            "methodProperties": props,
        }
        for attempt in range(4):
            try:
                resp = await self.client.post(NP_API_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not data.get("success"):
                    errors = data.get("errors", [])
                    raise ValueError(f"NP API error: {', '.join(errors)}")
                return data
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 3:
                    raise
                await asyncio.sleep(2 ** attempt)
        return {}

    async def get_drafts(self, days_back: int = 7) -> List[NPDocument]:
        """Повертає всі ТТН без реєстру за останні N днів."""
        now = datetime.now(KIEV_TZ)
        date_from = (now - timedelta(days=days_back)).strftime("%d.%m.%Y")
        date_to = now.strftime("%d.%m.%Y")

        data = await self._call("InternetDocument", "getDocumentList", {
            "DateTimeFrom": date_from,
            "DateTimeTo": date_to,
            "GetFullList": "1",
            "Page": "1",
        })

        docs = []
        for item in data.get("data", []):
            doc = NPDocument(item)
            if doc.is_draft and doc.ref:
                docs.append(doc)
        return docs

    async def create_registry(self, doc_refs: List[str]) -> NPRegistry:
        """Створює новий реєстр одразу з ТТН (без Ref = новий реєстр).
        Повертає інформацію про створений реєстр."""
        result = await self._call("ScanSheet", "insertDocuments", {
            "DocumentRefs": doc_refs,
            "Date": datetime.now(KIEV_TZ).strftime("%d.%m.%Y"),
        })

        # Перевіряємо чи були помилки на рівні окремих документів
        for item in result.get("data", []):
            errors = item.get("Errors") or []
            if errors:
                msgs = [e.get("Error") if isinstance(e, dict) else str(e) for e in errors]
                raise ValueError(f"NP ScanSheet error: {', '.join(msgs)}")

        # API повертає масив, де є Ref/Number реєстру
        data = result.get("data", [])
        sheet_ref = ""
        sheet_number = ""
        for item in data:
            sheet_ref = item.get("Ref") or item.get("ScanSheetRef") or sheet_ref
            sheet_number = item.get("Number") or item.get("ScanSheetNumber") or sheet_number

        # Якщо номер ще не повернувся — дотягуємо через getScanSheet
        if sheet_ref and not sheet_number:
            try:
                info = await self._call("ScanSheet", "getScanSheet", {"Ref": sheet_ref})
                d = info.get("data", [])
                if d:
                    sheet_number = d[0].get("Number", "")
            except Exception:
                pass

        return NPRegistry({"Ref": sheet_ref, "Number": sheet_number})

    async def download_registry_pdf(self, scan_sheet_ref: str) -> bytes:
        """Завантажує офіційний PDF-бланк реєстру (зі штрихкодом)."""
        url = NP_PRINT_URL.format(ref=scan_sheet_ref, key=self.api_key)
        resp = await self.client.get(url, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF"):
            raise ValueError("NP повернув не PDF (можливо невірний ref або ключ)")
        return resp.content

    async def close(self):
        await self.client.aclose()
