import io
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from pypdf import PdfReader, PdfWriter

from .vorlagen import zeichne

CENT = Decimal("0.01")


def uid(ziffern: str) -> str:
    summe = 0
    for stelle, zeichen in enumerate(ziffern):
        ziffer = int(zeichen)
        summe += ziffer if stelle % 2 == 0 else ziffer // 5 + (ziffer * 2) % 10
    return f"ATU{ziffern}{(10 - (summe + 4) % 10) % 10}"


def iban(konto: int, land: str = "AT") -> str:
    rumpf = f"00000{konto:011d}"
    zahlen = "".join(str(int(zeichen, 36)) for zeichen in rumpf + land + "00")
    return f"{land}{98 - int(zahlen) % 97:02d}{rumpf}"


@dataclass
class Firma:
    name: str
    strasse: str
    plz: str
    ort: str
    uid: str | None = None
    iban: str | None = None


@dataclass
class Posten:
    nummer: str
    text: str
    menge: Decimal
    einheit: str
    preis: Decimal
    satz: int = 20

    @property
    def netto(self) -> Decimal:
        return (self.menge * self.preis).quantize(CENT, ROUND_HALF_UP)


@dataclass
class Vorlage:
    lieferant: Firma
    empfaenger: Firma
    nummer: str
    datum: date
    posten: list[Posten]
    titel: str = "RECHNUNG"
    ziel: int | None = 30
    skonto: tuple[int, int] | None = None
    bestellnummer: str | None = None
    leistung: tuple[date, date] | None = None
    waehrung: str = "EUR"
    mit_uid: bool = False
    falsch: Decimal = Decimal(0)
    zeilen: list[str] = field(default_factory=list)
    ohne_summen: bool = False

    @property
    def steuern(self) -> list[tuple[int, Decimal, Decimal]]:
        ergebnis = []
        for satz in sorted({p.satz for p in self.posten}, reverse=True):
            netto = sum((p.netto for p in self.posten if p.satz == satz), Decimal(0))
            ergebnis.append((satz, netto, (netto * satz / 100).quantize(CENT, ROUND_HALF_UP)))
        return ergebnis

    @property
    def netto(self) -> Decimal:
        return sum((netto for _, netto, _ in self.steuern), Decimal(0))

    @property
    def ust(self) -> Decimal:
        return sum((ust for _, _, ust in self.steuern), Decimal(0))

    @property
    def brutto(self) -> Decimal:
        return self.netto + self.ust + self.falsch

    @property
    def faellig(self) -> date | None:
        return self.datum + timedelta(days=self.ziel) if self.ziel is not None else None


def pdf(v: Vorlage) -> bytes:
    puffer = io.BytesIO()
    zeichne(puffer, v)
    return puffer.getvalue()


def ubl(v: Vorlage) -> bytes:
    def partei(art: str, f: Firma) -> str:
        return (
            f"<cac:{art}><cac:Party><cac:PostalAddress><cbc:StreetName>{escape(f.strasse)}</cbc:StreetName>"
            f"<cbc:CityName>{escape(f.ort)}</cbc:CityName><cbc:PostalZone>{f.plz}</cbc:PostalZone>"
            "<cac:Country><cbc:IdentificationCode>AT</cbc:IdentificationCode></cac:Country></cac:PostalAddress>"
            f"<cac:PartyTaxScheme><cbc:CompanyID>{f.uid or ''}</cbc:CompanyID>"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
            f"</cac:PartyTaxScheme><cac:PartyLegalEntity><cbc:RegistrationName>{escape(f.name)}</cbc:RegistrationName>"
            f"</cac:PartyLegalEntity></cac:Party></cac:{art}>"
        )

    steuern = "".join(
        f'<cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">{netto}</cbc:TaxableAmount>'
        f'<cbc:TaxAmount currencyID="EUR">{ust}</cbc:TaxAmount><cac:TaxCategory><cbc:ID>S</cbc:ID>'
        f"<cbc:Percent>{satz}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>"
        "</cac:TaxSubtotal>"
        for satz, netto, ust in v.steuern
    )
    zeilen = "".join(
        f'<cac:InvoiceLine><cbc:ID>{i}</cbc:ID><cbc:InvoicedQuantity unitCode="C62">{p.menge}</cbc:InvoicedQuantity>'
        f'<cbc:LineExtensionAmount currencyID="EUR">{p.netto}</cbc:LineExtensionAmount><cac:Item>'
        f"<cbc:Name>{escape(p.text)}</cbc:Name><cac:SellersItemIdentification><cbc:ID>{p.nummer}</cbc:ID>"
        f"</cac:SellersItemIdentification><cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{p.satz}</cbc:Percent>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>"
        f'<cac:Price><cbc:PriceAmount currencyID="EUR">{p.preis}</cbc:PriceAmount></cac:Price></cac:InvoiceLine>'
        for i, p in enumerate(v.posten, 1)
    )
    von, bis = v.leistung or (v.datum, v.datum)
    skonto = f"#SKONTO#TAGE={v.skonto[1]}#PROZENT={v.skonto[0]}.00#" if v.skonto else ""
    bestellung = f"<cac:OrderReference><cbc:ID>{v.bestellnummer}</cbc:ID></cac:OrderReference>" if v.bestellnummer else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
        'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        "<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>"
        f"<cbc:ID>{v.nummer}</cbc:ID><cbc:IssueDate>{v.datum}</cbc:IssueDate><cbc:DueDate>{v.faellig}</cbc:DueDate>"
        "<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>"
        f"<cac:InvoicePeriod><cbc:StartDate>{von}</cbc:StartDate><cbc:EndDate>{bis}</cbc:EndDate></cac:InvoicePeriod>{bestellung}"
        f"{partei('AccountingSupplierParty', v.lieferant)}{partei('AccountingCustomerParty', v.empfaenger)}"
        "<cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode><cac:PayeeFinancialAccount>"
        f"<cbc:ID>{v.lieferant.iban}</cbc:ID></cac:PayeeFinancialAccount></cac:PaymentMeans>"
        f"<cac:PaymentTerms><cbc:Note>{skonto}</cbc:Note></cac:PaymentTerms>"
        f'<cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{v.ust}</cbc:TaxAmount>{steuern}</cac:TaxTotal>'
        f'<cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">{v.netto}</cbc:LineExtensionAmount>'
        f'<cbc:TaxExclusiveAmount currencyID="EUR">{v.netto}</cbc:TaxExclusiveAmount>'
        f'<cbc:TaxInclusiveAmount currencyID="EUR">{v.brutto}</cbc:TaxInclusiveAmount>'
        f'<cbc:PayableAmount currencyID="EUR">{v.brutto}</cbc:PayableAmount></cac:LegalMonetaryTotal>{zeilen}</Invoice>'
    ).encode()


def cii(v: Vorlage) -> bytes:
    def tag(d: date) -> str:
        return f'<udt:DateTimeString format="102">{d:%Y%m%d}</udt:DateTimeString>'

    def partei(art: str, f: Firma) -> str:
        return (
            f"<ram:{art}><ram:Name>{escape(f.name)}</ram:Name><ram:PostalTradeAddress>"
            f"<ram:PostcodeCode>{f.plz}</ram:PostcodeCode>"
            f"<ram:LineOne>{escape(f.strasse)}</ram:LineOne><ram:CityName>{escape(f.ort)}</ram:CityName>"
            "<ram:CountryID>AT</ram:CountryID></ram:PostalTradeAddress><ram:SpecifiedTaxRegistration>"
            f'<ram:ID schemeID="VA">{f.uid or ""}</ram:ID></ram:SpecifiedTaxRegistration></ram:{art}>'
        )

    zeilen = "".join(
        f"<ram:IncludedSupplyChainTradeLineItem><ram:AssociatedDocumentLineDocument><ram:LineID>{i}</ram:LineID>"
        "</ram:AssociatedDocumentLineDocument><ram:SpecifiedTradeProduct>"
        f"<ram:SellerAssignedID>{p.nummer}</ram:SellerAssignedID><ram:Name>{escape(p.text)}</ram:Name></ram:SpecifiedTradeProduct>"
        "<ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice>"
        f"<ram:ChargeAmount>{p.preis}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>"
        f'<ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">{p.menge}</ram:BilledQuantity>'
        "</ram:SpecifiedLineTradeDelivery><ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode>"
        f"<ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>{p.satz}</ram:RateApplicablePercent>"
        "</ram:ApplicableTradeTax><ram:SpecifiedTradeSettlementLineMonetarySummation>"
        f"<ram:LineTotalAmount>{p.netto}</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>"
        "</ram:SpecifiedLineTradeSettlement></ram:IncludedSupplyChainTradeLineItem>"
        for i, p in enumerate(v.posten, 1)
    )
    steuern = "".join(
        f"<ram:ApplicableTradeTax><ram:CalculatedAmount>{ust}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>"
        f"<ram:BasisAmount>{netto}</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode>"
        f"<ram:RateApplicablePercent>{satz}</ram:RateApplicablePercent></ram:ApplicableTradeTax>"
        for satz, netto, ust in v.steuern
    )
    von, bis = v.leistung or (v.datum, v.datum)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" '
        'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">'
        "<rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017</ram:ID>"
        "</ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext>"
        f"<rsm:ExchangedDocument><ram:ID>{v.nummer}</ram:ID><ram:TypeCode>380</ram:TypeCode>"
        f"<ram:IssueDateTime>{tag(v.datum)}</ram:IssueDateTime></rsm:ExchangedDocument>"
        f"<rsm:SupplyChainTradeTransaction>{zeilen}<ram:ApplicableHeaderTradeAgreement>"
        f"{partei('SellerTradeParty', v.lieferant)}{partei('BuyerTradeParty', v.empfaenger)}"
        "</ram:ApplicableHeaderTradeAgreement><ram:ApplicableHeaderTradeDelivery/><ram:ApplicableHeaderTradeSettlement>"
        "<ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode><ram:SpecifiedTradeSettlementPaymentMeans>"
        "<ram:TypeCode>58</ram:TypeCode><ram:PayeePartyCreditorFinancialAccount>"
        f"<ram:IBANID>{v.lieferant.iban}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>"
        f"</ram:SpecifiedTradeSettlementPaymentMeans>{steuern}<ram:BillingSpecifiedPeriod>"
        f"<ram:StartDateTime>{tag(von)}</ram:StartDateTime><ram:EndDateTime>{tag(bis)}</ram:EndDateTime>"
        f"</ram:BillingSpecifiedPeriod><ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime>{tag(v.faellig)}</ram:DueDateDateTime>"
        "</ram:SpecifiedTradePaymentTerms><ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        f"<ram:LineTotalAmount>{v.netto}</ram:LineTotalAmount><ram:TaxBasisTotalAmount>{v.netto}</ram:TaxBasisTotalAmount>"
        f'<ram:TaxTotalAmount currencyID="EUR">{v.ust}</ram:TaxTotalAmount>'
        f"<ram:GrandTotalAmount>{v.brutto}</ram:GrandTotalAmount>"
        f"<ram:DuePayableAmount>{v.brutto}</ram:DuePayableAmount></ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        "</ram:ApplicableHeaderTradeSettlement></rsm:SupplyChainTradeTransaction></rsm:CrossIndustryInvoice>"
    ).encode()


def zugferd(v: Vorlage) -> bytes:
    schreiber = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf(v))))
    schreiber.add_attachment("factur-x.xml", cii(v))
    puffer = io.BytesIO()
    schreiber.write(puffer)
    return puffer.getvalue()


def ebinterface(v: Vorlage) -> bytes:
    def anschrift(f: Firma) -> str:
        return (
            f"<VATIdentificationNumber>{f.uid or ''}</VATIdentificationNumber><Address><Name>{escape(f.name)}</Name>"
            f"<Street>{escape(f.strasse)}</Street><Town>{escape(f.ort)}</Town><ZIP>{f.plz}</ZIP>"
            '<Country CountryCode="AT">Österreich</Country></Address>'
        )

    zeilen = "".join(
        f"<ListLineItem><Description>{escape(p.text)}</Description><ArticleNumber>{p.nummer}</ArticleNumber>"
        f'<Quantity Unit="C62">{p.menge}</Quantity><UnitPrice>{p.preis}</UnitPrice><TaxItem>'
        f'<TaxableAmount>{p.netto}</TaxableAmount><TaxPercent TaxCategoryCode="S">{p.satz}</TaxPercent></TaxItem>'
        f"<LineItemAmount>{p.netto}</LineItemAmount></ListLineItem>"
        for p in v.posten
    )
    steuern = "".join(
        f'<TaxItem><TaxableAmount>{netto}</TaxableAmount><TaxPercent TaxCategoryCode="S">{satz}</TaxPercent>'
        f"<TaxAmount>{ust}</TaxAmount></TaxItem>"
        for satz, netto, ust in v.steuern
    )
    von, bis = v.leistung or (v.datum, v.datum)
    bestellung = f"<OrderReference><OrderID>{v.bestellnummer}</OrderID></OrderReference>" if v.bestellnummer else ""
    skonto = ""
    if v.skonto:
        bis_wann = v.datum + timedelta(days=v.skonto[1])
        skonto = f"<Discount><PaymentDate>{bis_wann}</PaymentDate><Percentage>{v.skonto[0]}</Percentage></Discount>"
    kunde = anschrift(v.empfaenger).replace("<Address>", f"{bestellung}<Address>", 1)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Invoice xmlns="http://www.ebinterface.at/schema/6p1/" GeneratingSystem="Belegflow Demo" DocumentType="Invoice" '
        'InvoiceCurrency="EUR" Language="ger">'
        f"<InvoiceNumber>{v.nummer}</InvoiceNumber><InvoiceDate>{v.datum}</InvoiceDate>"
        f"<Delivery><Period><FromDate>{von}</FromDate><ToDate>{bis}</ToDate></Period></Delivery>"
        f"<Biller>{anschrift(v.lieferant)}</Biller><InvoiceRecipient>{kunde}</InvoiceRecipient>"
        f"<Details><ItemList>{zeilen}</ItemList></Details><Tax>{steuern}</Tax>"
        f"<TotalGrossAmount>{v.brutto}</TotalGrossAmount><PayableAmount>{v.brutto}</PayableAmount>"
        "<PaymentMethod><UniversalBankTransaction><BeneficiaryAccount>"
        f"<IBAN>{v.lieferant.iban}</IBAN></BeneficiaryAccount></UniversalBankTransaction></PaymentMethod>"
        f"<PaymentConditions><DueDate>{v.faellig}</DueDate>{skonto}</PaymentConditions></Invoice>"
    ).encode()
