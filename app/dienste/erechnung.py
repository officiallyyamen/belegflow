import io
import re
from datetime import timedelta

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring
from pypdf import PdfReader

from .werte import Position, Rechnung, Steuerzeile, als_datum, als_zahl

EINHEITEN = {
    "C62": "Stk",
    "H87": "Stk",
    "EA": "Stk",
    "HUR": "Std",
    "DAY": "Tage",
    "MON": "Monat",
    "KMT": "km",
    "KGM": "kg",
    "LTR": "l",
    "MTR": "m",
}
ANHAENGE = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "ebinterface.xml", "facturx.xml")


def name(knoten) -> str:
    return knoten.tag.rsplit("}", 1)[-1]


def alle(knoten, weg: str) -> list:
    stand = [knoten]
    for teil in weg.split("/"):
        stand = [kind for k in stand for kind in k if name(kind) == teil]
    return stand


def eins(knoten, *wege: str) -> str | None:
    if knoten is None:
        return None
    for weg in wege:
        for treffer in alle(knoten, weg):
            text = " ".join((treffer.text or "").split())
            if text:
                return text
    return None


def einheit(knoten) -> str | None:
    if knoten is None:
        return None
    code = next((w for n, w in knoten.attrib.items() if n.rsplit("}", 1)[-1] in ("unitCode", "Unit")), None)
    return EINHEITEN.get(code, code)


def erster(knoten, weg: str):
    treffer = alle(knoten, weg) if knoten is not None else []
    return treffer[0] if treffer else None


def verbinde(*teile) -> str | None:
    return ", ".join(t for t in teile if t) or None


def skonto(text: str | None, datum: str | None) -> dict:
    treffer = re.search(r"#SKONTO#TAGE=(\d{1,3})#PROZENT=(\d{1,2}(?:\.\d+)?)", text or "")
    tag = als_datum(datum)
    if not treffer or not tag:
        return {}
    return {"skonto_bis": (tag + timedelta(days=int(treffer[1]))).isoformat(), "skonto_prozent": treffer[2]}


def ubl(wurzel) -> tuple[Rechnung, str]:
    gutschrift = name(wurzel) == "CreditNote"
    zeile_name, menge_name = ("CreditNoteLine", "CreditedQuantity") if gutschrift else ("InvoiceLine", "InvoicedQuantity")

    def partei(weg):
        p = erster(wurzel, weg)
        ort = verbinde(
            eins(p, "PostalAddress/StreetName"),
            " ".join(t for t in (eins(p, "PostalAddress/PostalZone"), eins(p, "PostalAddress/CityName")) if t),
        )
        return eins(p, "PartyLegalEntity/RegistrationName", "PartyName/Name"), ort, eins(p, "PartyTaxScheme/CompanyID")

    lieferant, lieferant_adresse, lieferant_uid = partei("AccountingSupplierParty/Party")
    empfaenger, empfaenger_adresse, empfaenger_uid = partei("AccountingCustomerParty/Party")
    datum = eins(wurzel, "IssueDate")
    positionen = []
    for zeile in alle(wurzel, zeile_name):
        menge = erster(zeile, menge_name)
        positionen.append(
            Position(
                nummer=eins(zeile, "Item/SellersItemIdentification/ID"),
                text=eins(zeile, "Item/Name", "Item/Description"),
                menge=menge.text if menge is not None else None,
                einheit=einheit(menge),
                einzelpreis=eins(zeile, "Price/PriceAmount"),
                netto=eins(zeile, "LineExtensionAmount"),
                satz=eins(zeile, "Item/ClassifiedTaxCategory/Percent"),
            )
        )
    rechnung = Rechnung(
        art="gutschrift" if gutschrift or eins(wurzel, "InvoiceTypeCode") == "381" else "rechnung",
        lieferant=lieferant,
        lieferant_adresse=lieferant_adresse,
        lieferant_uid=lieferant_uid,
        empfaenger=empfaenger,
        empfaenger_adresse=empfaenger_adresse,
        empfaenger_uid=empfaenger_uid,
        nummer=eins(wurzel, "ID"),
        datum=datum,
        leistung_von=eins(wurzel, "InvoicePeriod/StartDate", "Delivery/ActualDeliveryDate"),
        leistung_bis=eins(wurzel, "InvoicePeriod/EndDate", "Delivery/ActualDeliveryDate"),
        faellig_am=eins(wurzel, "DueDate", "PaymentMeans/PaymentDueDate"),
        bestellnummer=eins(wurzel, "OrderReference/ID", "BuyerReference"),
        iban=eins(wurzel, "PaymentMeans/PayeeFinancialAccount/ID"),
        bic=eins(wurzel, "PaymentMeans/PayeeFinancialAccount/FinancialInstitutionBranch/ID"),
        waehrung=eins(wurzel, "DocumentCurrencyCode"),
        steuerzeilen=[
            Steuerzeile(
                satz=eins(z, "TaxCategory/Percent") or "0",
                netto=eins(z, "TaxableAmount") or "",
                ust=eins(z, "TaxAmount") or "",
            )
            for z in alle(wurzel, "TaxTotal/TaxSubtotal")
        ],
        netto=eins(wurzel, "LegalMonetaryTotal/TaxExclusiveAmount"),
        ust=eins(wurzel, "TaxTotal/TaxAmount"),
        brutto=eins(wurzel, "LegalMonetaryTotal/TaxInclusiveAmount", "LegalMonetaryTotal/PayableAmount"),
        positionen=positionen,
        **skonto(eins(wurzel, "PaymentTerms/Note"), datum),
    )
    return rechnung, "XRechnung" if "xrechnung" in (eins(wurzel, "CustomizationID") or "").lower() else "UBL"


def cii(wurzel) -> tuple[Rechnung, str]:
    geschaeft = erster(wurzel, "SupplyChainTradeTransaction")
    abkommen = erster(geschaeft, "ApplicableHeaderTradeAgreement")
    lieferung = erster(geschaeft, "ApplicableHeaderTradeDelivery")
    abrechnung = erster(geschaeft, "ApplicableHeaderTradeSettlement")
    summe = "SpecifiedTradeSettlementHeaderMonetarySummation"

    def partei(weg):
        p = erster(abkommen, weg)
        uid = None
        for eintrag in alle(p, "SpecifiedTaxRegistration/ID") if p is not None else []:
            if eintrag.get("schemeID") == "VA":
                uid = eintrag.text
        ort = verbinde(
            eins(p, "PostalTradeAddress/LineOne"),
            " ".join(t for t in (eins(p, "PostalTradeAddress/PostcodeCode"), eins(p, "PostalTradeAddress/CityName")) if t),
        )
        return eins(p, "Name"), ort, uid

    lieferant, lieferant_adresse, lieferant_uid = partei("SellerTradeParty")
    empfaenger, empfaenger_adresse, empfaenger_uid = partei("BuyerTradeParty")
    datum = eins(wurzel, "ExchangedDocument/IssueDateTime/DateTimeString")
    positionen = []
    for zeile in alle(geschaeft, "IncludedSupplyChainTradeLineItem"):
        menge = erster(zeile, "SpecifiedLineTradeDelivery/BilledQuantity")
        positionen.append(
            Position(
                nummer=eins(zeile, "SpecifiedTradeProduct/SellerAssignedID"),
                text=eins(zeile, "SpecifiedTradeProduct/Name"),
                menge=menge.text if menge is not None else None,
                einheit=einheit(menge),
                einzelpreis=eins(zeile, "SpecifiedLineTradeAgreement/NetPriceProductTradePrice/ChargeAmount"),
                netto=eins(
                    zeile,
                    "SpecifiedLineTradeSettlement/SpecifiedTradeSettlementLineMonetarySummation/LineTotalAmount",
                ),
                satz=eins(zeile, "SpecifiedLineTradeSettlement/ApplicableTradeTax/RateApplicablePercent"),
            )
        )
    geliefert = eins(lieferung, "ActualDeliverySupplyChainEvent/OccurrenceDateTime/DateTimeString")
    rechnung = Rechnung(
        art="gutschrift" if eins(wurzel, "ExchangedDocument/TypeCode") == "381" else "rechnung",
        lieferant=lieferant,
        lieferant_adresse=lieferant_adresse,
        lieferant_uid=lieferant_uid,
        empfaenger=empfaenger,
        empfaenger_adresse=empfaenger_adresse,
        empfaenger_uid=empfaenger_uid,
        nummer=eins(wurzel, "ExchangedDocument/ID"),
        datum=datum,
        leistung_von=eins(abrechnung, "BillingSpecifiedPeriod/StartDateTime/DateTimeString") or geliefert,
        leistung_bis=eins(abrechnung, "BillingSpecifiedPeriod/EndDateTime/DateTimeString") or geliefert,
        faellig_am=eins(abrechnung, "SpecifiedTradePaymentTerms/DueDateDateTime/DateTimeString"),
        bestellnummer=eins(abkommen, "BuyerOrderReferencedDocument/IssuerAssignedID", "BuyerReference"),
        iban=eins(abrechnung, "SpecifiedTradeSettlementPaymentMeans/PayeePartyCreditorFinancialAccount/IBANID"),
        bic=eins(abrechnung, "SpecifiedTradeSettlementPaymentMeans/PayeeSpecifiedCreditorFinancialInstitution/BICID"),
        waehrung=eins(abrechnung, "InvoiceCurrencyCode"),
        steuerzeilen=[
            Steuerzeile(
                satz=eins(z, "RateApplicablePercent") or "0",
                netto=eins(z, "BasisAmount") or "",
                ust=eins(z, "CalculatedAmount") or "",
            )
            for z in alle(abrechnung, "ApplicableTradeTax")
        ],
        netto=eins(abrechnung, f"{summe}/TaxBasisTotalAmount"),
        ust=eins(abrechnung, f"{summe}/TaxTotalAmount"),
        brutto=eins(abrechnung, f"{summe}/GrandTotalAmount"),
        positionen=positionen,
        **skonto(eins(abrechnung, "SpecifiedTradePaymentTerms/Description"), datum),
    )
    leitfaden = eins(wurzel, "ExchangedDocumentContext/GuidelineSpecifiedDocumentContextParameter/ID") or ""
    return rechnung, "XRechnung" if "xrechnung" in leitfaden.lower() else "ZUGFeRD"


def ebinterface(wurzel) -> tuple[Rechnung, str]:
    def partei(knoten):
        adresse = erster(knoten, "Address")
        ort = verbinde(eins(adresse, "Street"), " ".join(t for t in (eins(adresse, "ZIP"), eins(adresse, "Town")) if t))
        return eins(adresse, "Name"), ort, eins(knoten, "VATIdentificationNumber")

    lieferant, lieferant_adresse, lieferant_uid = partei(erster(wurzel, "Biller"))
    kunde = erster(wurzel, "InvoiceRecipient")
    empfaenger, empfaenger_adresse, empfaenger_uid = partei(kunde)
    positionen = []
    for zeile in alle(wurzel, "Details/ItemList/ListLineItem"):
        menge = erster(zeile, "Quantity")
        positionen.append(
            Position(
                nummer=eins(zeile, "ArticleNumber"),
                text=eins(zeile, "Description"),
                menge=menge.text if menge is not None else None,
                einheit=einheit(menge),
                einzelpreis=eins(zeile, "UnitPrice"),
                netto=eins(zeile, "LineItemAmount"),
                satz=eins(zeile, "TaxItem/TaxPercent", "VATRate"),
            )
        )
    steuern = [
        Steuerzeile(satz=eins(z, "TaxPercent") or "0", netto=eins(z, "TaxableAmount") or "", ust=eins(z, "TaxAmount") or "")
        for z in alle(wurzel, "Tax/TaxItem")
    ] or [
        Steuerzeile(satz=eins(z, "VATRate") or "0", netto=eins(z, "TaxedAmount") or "", ust=eins(z, "Amount") or "")
        for z in alle(wurzel, "Tax/VAT/VATItem")
    ]
    summen = [(als_zahl(z.netto) or 0, als_zahl(z.ust) or 0) for z in steuern]
    version = re.search(r"schema/(\d)p(\d)", wurzel.tag)
    skonto_zeile = erster(wurzel, "PaymentConditions/Discount")
    rechnung = Rechnung(
        art="gutschrift" if "CreditMemo" in "".join(wurzel.attrib.values()) else "rechnung",
        lieferant=lieferant,
        lieferant_adresse=lieferant_adresse,
        lieferant_uid=lieferant_uid,
        empfaenger=empfaenger,
        empfaenger_adresse=empfaenger_adresse,
        empfaenger_uid=empfaenger_uid,
        nummer=eins(wurzel, "InvoiceNumber"),
        datum=eins(wurzel, "InvoiceDate"),
        leistung_von=eins(wurzel, "Delivery/Period/FromDate", "Delivery/Date"),
        leistung_bis=eins(wurzel, "Delivery/Period/ToDate", "Delivery/Date"),
        faellig_am=eins(wurzel, "PaymentConditions/DueDate"),
        skonto_bis=eins(skonto_zeile, "PaymentDate"),
        skonto_prozent=eins(skonto_zeile, "Percentage"),
        bestellnummer=eins(kunde, "OrderReference/OrderID"),
        iban=eins(
            wurzel,
            "PaymentMethod/UniversalBankTransaction/BeneficiaryAccount/IBAN",
            "PaymentMethod/SEPADirectDebit/IBAN",
        ),
        bic=eins(wurzel, "PaymentMethod/UniversalBankTransaction/BeneficiaryAccount/BIC"),
        waehrung=next((w for n, w in wurzel.attrib.items() if n.rsplit("}", 1)[-1] == "InvoiceCurrency"), None),
        steuerzeilen=steuern,
        netto=str(sum(n for n, _ in summen)) if summen else None,
        ust=str(sum(u for _, u in summen)) if summen else None,
        brutto=eins(wurzel, "TotalGrossAmount", "PayableAmount"),
        positionen=positionen,
    )
    return rechnung, f"ebInterface {version[1]}.{version[2]}" if version else "ebInterface"


def lies(xml: bytes) -> tuple[Rechnung, str] | None:
    try:
        wurzel = fromstring(xml, forbid_dtd=True)
    except (ParseError, DefusedXmlException, ValueError):
        return None
    art = name(wurzel)
    if "ebinterface" in wurzel.tag:
        return ebinterface(wurzel)
    if art in ("Invoice", "CreditNote") and "ubl" in wurzel.tag:
        return ubl(wurzel)
    if art == "CrossIndustryInvoice" and erster(wurzel, "SupplyChainTradeTransaction") is not None:
        return cii(wurzel)
    return None


def aus_pdf(inhalt: bytes) -> bytes | None:
    try:
        anhaenge = PdfReader(io.BytesIO(inhalt)).attachments
        for dateiname, daten in anhaenge.items():
            if dateiname.lower() in ANHAENGE or dateiname.lower().endswith(".xml"):
                return bytes(daten[0])
    except Exception:
        return None
    return None
