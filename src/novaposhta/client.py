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

    # ── Пошук та редагування ТТН ──────────────────────────────────────────

    async def find_document(self, ttn_number: str) -> Optional[NPDocument]:
        """Шукає ТТН за номером серед останніх документів кабінету.
        Повертає NPDocument з повним сирим payload в .raw, або None."""
        # шукаємо за 60 днів (зазвичай вистачає)
        now = datetime.now(KIEV_TZ)
        date_from = (now - timedelta(days=60)).strftime("%d.%m.%Y")
        date_to = now.strftime("%d.%m.%Y")
        data = await self._call("InternetDocument", "getDocumentList", {
            "DateTimeFrom": date_from,
            "DateTimeTo": date_to,
            "GetFullList": "1",
            "Page": "1",
        })
        for item in data.get("data", []):
            if str(item.get("IntDocNumber", "")).strip() == ttn_number.strip():
                doc = NPDocument(item)
                doc.raw = item
                return doc
        return None

    async def check_possibility_change(self, ttn_number: str) -> dict:
        """AdditionalService.CheckPossibilityChangeEW — повертає {success, data: {...}}.
        У data: PhoneRecipient, FullNameRecipient, CounterpartyType — допустимі зміни."""
        try:
            res = await self._call("AdditionalService", "CheckPossibilityChangeEW", {
                "IntDocNumber": ttn_number,
            })
            data = res.get("data", [])
            return data[0] if data else {}
        except Exception:
            return {}

    async def update_draft(
        self,
        doc_raw: dict,
        new_phone: Optional[str] = None,
        new_name: Optional[str] = None,
        remove_cod: bool = False,
    ) -> dict:
        """Редагує ТТН-чернетку через InternetDocument.update.
        Передаємо набір полів з поточної ТТН + замінюємо потрібні.
        NP вимагає Ref + усі ключові поля."""
        props = {
            "Ref": doc_raw["Ref"],
            "PayerType": doc_raw.get("PayerType", "Recipient"),
            "PaymentMethod": doc_raw.get("PaymentMethod", "Cash"),
            "DateTime": datetime.now(KIEV_TZ).strftime("%d.%m.%Y"),
            "CargoType": doc_raw.get("CargoType", "Cargo"),
            "Weight": str(doc_raw.get("Weight", "1")),
            "ServiceType": doc_raw.get("ServiceType", "WarehouseWarehouse"),
            "SeatsAmount": str(doc_raw.get("SeatsAmount", "1")),
            "Description": doc_raw.get("Description", "Косметика"),
            "Cost": str(doc_raw.get("Cost", "100")),
            "CitySender": doc_raw.get("CitySender", ""),
            "Sender": doc_raw.get("Sender", ""),
            "SenderAddress": doc_raw.get("SenderAddress", ""),
            "ContactSender": doc_raw.get("ContactSender", ""),
            "SendersPhone": doc_raw.get("SendersPhone", ""),
            "CityRecipient": doc_raw.get("CityRecipient", ""),
            "Recipient": doc_raw.get("Recipient", ""),
            "RecipientAddress": doc_raw.get("RecipientAddress", ""),
            "ContactRecipient": doc_raw.get("ContactRecipient", ""),
            "RecipientsPhone": new_phone or doc_raw.get("RecipientsPhone", ""),
        }

        # Накладений платіж
        cod_sum = doc_raw.get("BackwardDeliverySum") or doc_raw.get("AfterpaymentOnGoodsCost") or 0
        try:
            cod_val = float(str(cod_sum or 0))
        except (ValueError, TypeError):
            cod_val = 0
        if cod_val > 0 and not remove_cod:
            props["BackwardDeliveryData"] = [{
                "PayerType": "Recipient",
                "CargoType": "Money",
                "RedeliveryString": str(cod_val),
            }]
        # remove_cod=True → не додаємо BackwardDeliveryData, НП прибере НП

        # Якщо змінюємо ім'я отримувача — оновлюємо ContactPerson
        if new_name and doc_raw.get("ContactRecipient"):
            parts = new_name.strip().split(maxsplit=2)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""
            middle = parts[2] if len(parts) > 2 else ""
            try:
                await self._call("ContactPersonGeneral", "update", {
                    "Ref": doc_raw["ContactRecipient"],
                    "CounterpartyRef": doc_raw.get("Recipient", ""),
                    "FirstName": first,
                    "LastName": last,
                    "MiddleName": middle,
                    "Phone": (new_phone or doc_raw.get("RecipientsPhone", "")).lstrip("+").lstrip("38") or "",
                })
            except Exception:
                pass  # м'яко — ContactPerson не критично, дані все одно в ТТН

        result = await self._call("InternetDocument", "update", props)
        return result

    async def request_change_after_accept(
        self,
        ttn_number: str,
        new_phone: Optional[str] = None,
        new_name: Optional[str] = None,
        remove_cod: bool = False,
        current_phone: Optional[str] = None,
    ) -> dict:
        """Платна заявка на зміну даних ТТН, що вже на складі.
        Викликає AdditionalService.save з OrderType=orderChangeEW.

        Структура повторює запит NP UI (бізнес-кабінет):
        - Для ПІБ створюємо нову Counterparty (Recipient) + передаємо RecipientContactName рядком.
        - Зміна тільки телефону — без створення Counterparty.
        - Прибрати НП — поки не реалізовано.
        """
        if remove_cod and not (new_phone or new_name):
            raise NotImplementedError(
                "Прибрати накладений платіж через платну заявку поки не підтримується. "
                "Звернись в підтримку НП."
            )

        # Тягнемо поточний стан, бо payload вимагає Recipient/PayerType/PaymentMethod
        check = await self._call("AdditionalService", "CheckPossibilityChangeEW", {
            "IntDocNumber": ttn_number,
        })
        cur = (check.get("data") or [{}])[0]
        phone = new_phone or current_phone or cur.get("RecipientPhone", "")

        props: dict = {
            "IntDocNumber": ttn_number,
            "OrderType": "orderChangeEW",
            "PayerType": cur.get("PayerType", "Recipient"),
            "PaymentMethod": cur.get("PaymentMethod", "Cash"),
            "BackwardDeliveryData": [],
            "RecipientPhone": phone,
        }

        if new_name:
            # Створюємо нового Counterparty (приватна особа, отримувач)
            parts = new_name.strip().split(maxsplit=2)
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""
            middle = parts[2] if len(parts) > 2 else ""
            cp_res = await self._call("CounterpartyGeneral", "save", {
                "FirstName": first,
                "LastName": last,
                "MiddleName": middle,
                "Phone": phone,
                "CounterpartyType": "PrivatePerson",
                "CounterpartyProperty": "Recipient",
            })
            cp_ref = (cp_res.get("data") or [{}])[0].get("Ref", "")
            if not cp_ref:
                raise ValueError("Не вдалося створити нового отримувача в кабінеті НП")
            await asyncio.sleep(1)
            props["Recipient"] = cp_ref
            # ПІБ передається одним рядком як LastName FirstName MiddleName (NP UI робить так)
            props["RecipientContactName"] = " ".join(p for p in [last, first, middle] if p).strip()

        return await self._call("AdditionalService", "save", props)

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
