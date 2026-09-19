from dataclasses import dataclass


@dataclass(frozen=True)
class AdvertisingPlan:
    slug: str
    name: str
    price_tl: int
    features: tuple[str, ...]


# Draft advertising prices are centralized here so future price changes do
# not require template or view edits.
STANDARD = AdvertisingPlan(
    slug="standard",
    name="STANDART",
    price_tl=2500,
    features=(
        "Temel reklam görünürlüğü",
        "DertDerman reklam alanlarında yayın",
        "Responsive masaüstü/mobil gösterim",
        "Paket süresince görünürlük",
    ),
)

PRO = AdvertisingPlan(
    slug="pro",
    name="PRO",
    price_tl=4200,
    features=(
        "Daha yüksek görünürlük",
        "Öncelikli reklam alanları",
        "Ana sayfa görünürlüğü",
        "Responsive masaüstü/mobil gösterim",
        "Paket süresince görünürlük",
    ),
)

ADVERTISING_PLANS = {
    STANDARD.slug: STANDARD,
    PRO.slug: PRO,
}
