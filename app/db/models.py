from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.models.recommendation import Priority


class Base(DeclarativeBase):
    pass


class Role(str, Enum):
    # Admins manage coordinator accounts; coordinators manage gadgets.
    ADMIN = "admin"
    COORDINATOR = "coordinator"


def _enum(enum_cls: type[Enum], name: str) -> SAEnum:
    # VARCHAR + CHECK rather than a native Postgres ENUM: adding a value
    # later is a one-line migration instead of an ALTER TYPE dance.
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
        length=20,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stored lower-cased by the code that writes it.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuthSession(Base):
    """A signed-in browser. Only a hash of the cookie token is stored, so a
    leaked database row cannot be replayed as a session."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")


class Place(Base):
    """A destination chosen through the picker. Coordinates come from the
    geocoder, so two coordinators picking "Kaptai Lake" share one row."""

    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint("name", "latitude", "longitude", name="uq_places_name_coords"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    country_code: Mapped[str | None] = mapped_column(String(2))
    country_name: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    # Bangladesh administrative area, set when a coordinator enters a place
    # the geocoders do not know. Null for geocoded and foreign places.
    district: Mapped[str | None] = mapped_column(String(60))
    division: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Gadget(Base):
    """A gadget entered once and reused across destinations."""

    __tablename__ = "gadgets"
    __table_args__ = (UniqueConstraint("slug", name="uq_gadgets_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # The search-friendly URL key for the gadget's public detail page,
    # /gadget/<slug>. Unique; derived from the name when a gadget is saved.
    slug: Mapped[str | None] = mapped_column(String(140))
    brand: Mapped[str | None] = mapped_column(String(80))
    model_name: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(60))
    color: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    image_key: Mapped[str | None] = mapped_column(String(100))
    # A retired gadget stays in the catalog -- its placements and history
    # are worth keeping -- but a future traveller-facing surface shows only
    # the active ones. The coordinator area shows both, marked.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # Who first put it in the catalog: a coordinator, or the language model
    # (a suggestion saved from a traveller's list, see
    # services/gadgets/suggestions.py). Model suggestions start inactive and
    # "pending" and only go live once a coordinator approves them, so the
    # Verified badge keeps meaning a person checked it.
    origin: Mapped[str] = mapped_column(String(20), default="coordinator", server_default="coordinator")
    # None for coordinator entries; pending / approved / rejected for model ones.
    review_status: Mapped[str | None] = mapped_column(String(20))
    # How many traveller lists the model suggested it in -- the review queue's
    # signal for what is worth approving first.
    suggestion_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    placements: Mapped[list["Placement"]] = relationship(
        back_populates="gadget",
        cascade="all, delete-orphan",
        order_by="Placement.id",
    )
    variants: Mapped[list["GadgetVariant"]] = relationship(
        back_populates="gadget",
        cascade="all, delete-orphan",
        order_by="GadgetVariant.price",
    )


# Case-insensitive uniqueness: "Power bank" and "power bank" collide.
# Declared outside the class so it can reference the real column -- a
# string inside func.lower() compiles to a constant, not the column.
Index("uq_gadgets_name_lower", func.lower(Gadget.name), unique=True)


class Placement(Base):
    """Where and when a gadget is recommended.

    trip_types must be non-empty. activities may be empty, meaning the
    gadget applies whatever the traveller plans to do there.
    """

    __tablename__ = "placements"
    __table_args__ = (
        CheckConstraint("cardinality(trip_types) > 0", name="ck_placements_trip_types"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gadget_id: Mapped[int] = mapped_column(
        ForeignKey("gadgets.id", ondelete="CASCADE"), index=True
    )
    place_id: Mapped[int] = mapped_column(
        ForeignKey("places.id", ondelete="RESTRICT"), index=True
    )
    trip_types: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    activities: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default="{}"
    )
    priority: Mapped[Priority] = mapped_column(_enum(Priority, "placement_priority"))
    why: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    gadget: Mapped[Gadget] = relationship(back_populates="placements")
    place: Mapped[Place] = relationship(lazy="joined")


class Division(Base):
    """An admin-managed region grouping for destinations, per country.

    Seeded from the static admin dataset so the picker keeps working, and
    editable from the admin panel. A place carries its division as a string,
    so renaming here does not rewrite places -- the label is the key."""

    __tablename__ = "divisions"
    __table_args__ = (
        UniqueConstraint("country_code", "name", name="uq_divisions_country_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2))
    name: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TripTypeOption(Base):
    """A trip type the forms offer, admin-managed.

    `value` is the key stored on placements and sent in requests (a slug
    like "beach"); `label` is what people see. Replaces the former hardcoded
    enum, seeded with the same values so existing data stays valid."""

    __tablename__ = "trip_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(30), unique=True)
    label: Mapped[str] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ActivityOption(Base):
    """An activity the forms offer, admin-managed. See TripTypeOption."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(30), unique=True)
    label: Mapped[str] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GadgetVariant(Base):
    """A buyable variant of a gadget: a specific brand/model offering with
    its own price, colour and quality tier, from our inventory or a vendor.

    Shown on the gadget's public detail page so a traveller can compare the
    options for the same item."""

    __tablename__ = "gadget_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gadget_id: Mapped[int] = mapped_column(
        ForeignKey("gadgets.id", ondelete="CASCADE"), index=True
    )
    brand: Mapped[str] = mapped_column(String(80))
    model_name: Mapped[str | None] = mapped_column(String(80))
    color: Mapped[str | None] = mapped_column(String(40))
    # One of budget / standard / premium -- the quality tier.
    quality: Mapped[str] = mapped_column(String(20))
    # Whole currency units (e.g. taka); fractional pricing is not needed here.
    price: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="BDT", server_default="BDT")
    vendor: Mapped[str | None] = mapped_column(String(80))
    url: Mapped[str | None] = mapped_column(String(300))
    # Units on hand, kept by coordinators. Required: a buying option is
    # never shown as available without a confirmed count.
    stock_quantity: Mapped[int] = mapped_column(Integer)
    # When the quantity was last set, so travellers can judge how fresh it is.
    stock_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    gadget: Mapped[Gadget] = relationship(back_populates="variants")


class HeroImage(Base):
    """A photo for the home page hero, uploaded by an admin.

    Keyed by the destination's URL slug -- the same slug the home page uses
    in ?to=<slug> -- rather than a place row, because the curated spots in
    destinations.json have no row. An empty slug is the country's default
    hero, shown when the chosen destination has no photo of its own."""

    __tablename__ = "hero_images"
    __table_args__ = (
        UniqueConstraint("country_code", "place_slug", name="uq_hero_images_place"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2))
    # "" for the default hero; otherwise url_slug(place_name).
    place_slug: Mapped[str] = mapped_column(String(140))
    place_name: Mapped[str | None] = mapped_column(String(200))
    alt: Mapped[str] = mapped_column(String(200))
    image_key: Mapped[str] = mapped_column(String(100))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ---------- visitor analytics ----------
#
# Aggregates only: no raw requests, no IP addresses, no cookies. See
# app/services/analytics.py for how visits are counted.


class AnalyticsCount(Base):
    """A daily counter: page views per page, packing lists per destination,
    referrers, devices. One row per (day, event, label)."""

    __tablename__ = "analytics_counts"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    event: Mapped[str] = mapped_column(String(20), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class AnalyticsVisitor(Base):
    """One row per anonymous visitor per day, for counting unique visitors.

    The hash is of that day's random salt plus IP and browser. The salt is
    deleted once the day is over, after which a hash can no longer be tied
    back to anyone -- it only says "a distinct visitor on this day"."""

    __tablename__ = "analytics_visitors"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    visitor_hash: Mapped[str] = mapped_column(String(32), primary_key=True)


class AnalyticsSalt(Base):
    """The random salt for one day's visitor hashes; kept only for today and
    yesterday (late flushes), then deleted."""

    __tablename__ = "analytics_salts"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    salt: Mapped[str] = mapped_column(String(64))


class DistinctGadgetPair(Base):
    """Two gadgets a coordinator has confirmed are different items, though
    their names look alike -- so the possible-duplicates list stops showing
    them. Stored with the lower id first."""

    __tablename__ = "distinct_gadget_pairs"
    __table_args__ = (CheckConstraint("low_id < high_id", name="ck_distinct_pairs_order"),)

    low_id: Mapped[int] = mapped_column(ForeignKey("gadgets.id", ondelete="CASCADE"), primary_key=True)
    high_id: Mapped[int] = mapped_column(ForeignKey("gadgets.id", ondelete="CASCADE"), primary_key=True)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelListCache(Base):
    """The model's fresh suggestions for one kind of trip, kept so the next
    traveller planning the same trip gets them without waiting on the model.

    `key` is a hash of what shapes the answer (places, month, trip types,
    activities, party, prompt version) -- see services/gadgets/list_cache.py.
    `hit_count` doubles as a signal for which trips coordinators should
    curate first."""

    __tablename__ = "model_list_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    items: Mapped[list] = mapped_column(JSONB)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Order(Base):
    """A traveller's order, placed from the checkout page.

    Guest checkout: the customer's details live on the order, no account.
    Cash on delivery for now. Stock is taken from the buying options when
    the order is placed and given back if it is cancelled, so what the
    public pages show as available stays true.

    status: pending (new; a coordinator calls to confirm) -> confirmed ->
    shipped -> delivered; pending or confirmed can be cancelled."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')",
            name="ck_orders_status",
        ),
        CheckConstraint("payment_method IN ('cod')", name="ck_orders_payment_method"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # What the customer and coordinator quote on the phone: "TXP-7K3Q9M".
    code: Mapped[str] = mapped_column(String(12), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending", index=True)
    customer_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(300))
    area: Mapped[str] = mapped_column(String(80))
    # A key from the country's delivery.json ("inside_dhaka" / "outside_dhaka").
    delivery_zone: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(300))
    payment_method: Mapped[str] = mapped_column(String(10), default="cod", server_default="cod")
    # Whole currency units, worked out on the server -- never the browser's.
    subtotal: Mapped[int] = mapped_column(Integer)
    delivery_fee: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="BDT", server_default="BDT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )


class OrderItem(Base):
    """One line of an order. The gadget and option are copied as they were
    when bought, so the order still reads correctly after a rename, a price
    change or the option being deleted (variant_id then becomes NULL)."""

    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_items_quantity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("gadget_variants.id", ondelete="SET NULL"))
    gadget_name: Mapped[str] = mapped_column(String(120))
    option: Mapped[str] = mapped_column(String(200))  # "Petzl Tikkina · Black · standard"
    vendor: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")


class SavedBag(Base):
    """A traveller's bag saved as a short link (/bag/<code>), to keep for
    later or share. No account: whoever has the link can open it.

    Items are references, not copies: a gadget's slug and the chosen buying
    option's id, so the saved bag always shows today's names, prices and
    stock. Gadgets without a catalog page (model suggestions) keep just
    their name."""

    __tablename__ = "saved_bags"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    # [{"name": ..., "slug": ... | null, "variant_id": ... | null, "priority": ... | null}]
    items: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
