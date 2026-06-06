from __future__ import annotations

import asyncio
import csv
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def fmt_price(raw: str) -> str:
    """Return a dollar-formatted string from a numeric string, or pass through."""
    try:
        return f"${int(raw.replace(',', '').replace('$', '')):,}"
    except (ValueError, AttributeError):
        return raw

logger = logging.getLogger("katmarket")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

STAFF_ROLE_NAME: str        = os.getenv("STAFF_ROLE_NAME", "Staff")
SENIOR_STAFF_ROLE_NAME: str = os.getenv("SENIOR_STAFF_ROLE_NAME", "Senior Staff")
ADMIN_ROLE_NAME: str        = os.getenv("ADMIN_ROLE_NAME", "Administrator")

PAYMENT_REVIEW_CHANNEL_ID: int = int(os.getenv("PAYMENT_REVIEW_CHANNEL_ID", "0"))
UPI_ID: str                    = os.getenv("UPI_ID", "")
UPI_QR_URL: str                = os.getenv("UPI_QR_URL", "")
REPORT_CHANNEL_ID: int         = int(os.getenv("REPORT_CHANNEL_ID", "0"))
LISTINGS_CHANNEL_ID: int       = int(os.getenv("LISTINGS_CHANNEL_ID", "0"))
BOUNTY_CHANNEL_ID: int         = int(os.getenv("BOUNTY_CHANNEL_ID", "0"))
GIVEAWAY_CHANNEL_ID: int       = int(os.getenv("GIVEAWAY_CHANNEL_ID", "0"))
AD_CHANNEL_ID: int             = int(os.getenv("AD_CHANNEL_ID", "0"))
STAFF_LOG_CHANNEL_ID: int      = int(os.getenv("STAFF_LOG_CHANNEL_ID", "0"))
CONTRACT_CHANNEL_ID: int       = int(os.getenv("CONTRACT_CHANNEL_ID", "0"))
BIRTHDAY_CHANNEL_ID: int       = int(os.getenv("BIRTHDAY_CHANNEL_ID", "0"))
BIRTHDAY_ROLE_NAME: str        = os.getenv("BIRTHDAY_ROLE_NAME", "🎂 Birthday")

COIN_PACKAGES: list[dict] = [
    {"label": "10 Coins — ₹5",   "coins": 10,  "price": "₹5"},
    {"label": "25 Coins — ₹10",  "coins": 25,  "price": "₹10"},
    {"label": "55 Coins — ₹20",  "coins": 55,  "price": "₹20"},
    {"label": "150 Coins — ₹50", "coins": 150, "price": "₹50"},
    {"label": "Custom Package",  "coins": 0,   "price": "Custom"},
]

CRATE_REWARDS: list[dict] = [
    {"label": "🪙 50 KAT Coins",      "weight": 20, "type": "coins",   "value": 50},
    {"label": "🪙 100 KAT Coins",     "weight": 15, "type": "coins",   "value": 100},
    {"label": "💵 $100,000 Cash",     "weight": 25, "type": "cash",    "value": 100_000},
    {"label": "💵 $500,000 Cash",     "weight": 15, "type": "cash",    "value": 500_000},
    {"label": "💵 $1,000,000 Cash",   "weight": 10, "type": "cash",    "value": 1_000_000},
    {"label": "🎨 Rare Skin Voucher", "weight": 8,  "type": "voucher", "value": 1},
    {"label": "📦 Rare Item Crate",   "weight": 5,  "type": "item",    "value": 1},
    {"label": "⭐ Premium Reward",    "weight": 2,  "type": "premium", "value": 1},
]

DAILY_REWARDS: dict  = {"coins": 5,  "cash": 50_000}
WEEKLY_REWARDS: dict = {"coins": 25, "cash": 500_000, "crates": 2}

VERIFIED_TRADER_REQUIREMENTS: dict = {
    "min_trades": 10, "min_reputation": 4.0, "max_reports": 0,
}

BOUNTY_FREE_DAYS: int     = 2
BOUNTY_COST_PER_DAY: int  = 3

MARKETPLACE_TAX_RATES: dict[str, float] = {
    "vehicle": 0.02, "property": 0.03, "business": 0.05,
    "skin": 0.02, "item": 0.02,
}

LISTING_EXPIRY_OPTIONS: list[dict] = [
    {"label": "7 Days",  "value": "7",  "emoji": "📅"},
    {"label": "14 Days", "value": "14", "emoji": "📅"},
    {"label": "30 Days", "value": "30", "emoji": "📅"},
]

COIN_SINK_COSTS: dict[str, int] = {
    "feature_listing": 5, "urgent_listing": 2,
    "rename_listing": 1,  "custom_color": 3, "extended_bounty": 3,
}

SELLER_BADGE_THRESHOLDS: dict[str, dict] = {
    "🥇 Top Seller":      {"trade_count": 50,  "total_sales": 100_000_000},
    "💎 Elite Trader":    {"trade_count": 100, "total_sales": 500_000_000},
    "🏢 Business Tycoon": {"trade_count": 20,  "category": "business"},
    "⭐ Verified Trader": {"is_verified": True},
    "🎂 Early Supporter": {"trade_count": 1},
}

DATABASE_PATH:   str = os.path.join(os.path.dirname(__file__), "data", "katmarket.db")
HOUSES_CSV:      str = os.path.join(os.path.dirname(__file__), "data", "houses.csv")
APARTMENTS_CSV:  str = os.path.join(os.path.dirname(__file__), "data", "apartments.csv")
BUSINESSES_CSV:  str = os.path.join(os.path.dirname(__file__), "data", "businesses.csv")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT NOT NULL,
    kat_coins   INTEGER NOT NULL DEFAULT 0,
    game_cash   INTEGER NOT NULL DEFAULT 0,
    reputation  REAL    NOT NULL DEFAULT 5.0,
    trade_count INTEGER NOT NULL DEFAULT 0,
    total_sales INTEGER NOT NULL DEFAULT 0,
    is_verified INTEGER NOT NULL DEFAULT 0,
    is_banned   INTEGER NOT NULL DEFAULT 0,
    daily_last  TEXT,
    weekly_last TEXT,
    joined_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS listings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id    INTEGER NOT NULL,
    category     TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    description  TEXT,
    asking_price INTEGER NOT NULL DEFAULT 0,
    listing_type TEXT    NOT NULL DEFAULT 'Standard',
    status       TEXT    NOT NULL DEFAULT 'active',
    message_id   INTEGER,
    channel_id   INTEGER,
    image_url    TEXT,
    extra_data   TEXT,
    expires_at   TEXT,
    featured     INTEGER NOT NULL DEFAULT 0,
    urgent       INTEGER NOT NULL DEFAULT 0,
    listing_color TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (seller_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS offers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id   INTEGER NOT NULL,
    buyer_id     INTEGER NOT NULL,
    offer_type   TEXT NOT NULL DEFAULT 'cash',
    offer_amount INTEGER NOT NULL DEFAULT 0,
    offer_asset  TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (listing_id) REFERENCES listings(id),
    FOREIGN KEY (buyer_id)   REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    listing_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, listing_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    keyword    TEXT NOT NULL,
    category   TEXT,
    alert_type TEXT NOT NULL DEFAULT 'new_listing',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, keyword, category)
);

CREATE TABLE IF NOT EXISTS vouches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    listing_id INTEGER,
    rating     INTEGER NOT NULL DEFAULT 5,
    message    TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trade_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id    INTEGER NOT NULL,
    buyer_id     INTEGER NOT NULL,
    listing_id   INTEGER NOT NULL,
    sale_price   INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coin_purchases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    package_name   TEXT NOT NULL,
    coins          INTEGER NOT NULL,
    price          TEXT NOT NULL,
    screenshot_url TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    reviewed_by    INTEGER,
    review_note    TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at    TEXT
);

CREATE TABLE IF NOT EXISTS bounties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL,
    target_name TEXT NOT NULL,
    reward      TEXT NOT NULL,
    reason      TEXT NOT NULL,
    duration    INTEGER NOT NULL DEFAULT 1,
    coins_paid  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    accepted_by INTEGER,
    message_id  INTEGER,
    channel_id  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT
);

CREATE TABLE IF NOT EXISTS bounty_interested (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    bounty_id INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    UNIQUE(bounty_id, user_id)
);

CREATE TABLE IF NOT EXISTS contracts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL,
    title       TEXT NOT NULL,
    description TEXT,
    reward      TEXT,
    duration    TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    message_id  INTEGER,
    channel_id  INTEGER,
    accepted_by INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id  INTEGER NOT NULL,
    target_type  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    reason       TEXT NOT NULL,
    evidence_url TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    reviewed_by  INTEGER,
    resolution   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at  TEXT
);

CREATE TABLE IF NOT EXISTS disputes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    opener_id    INTEGER NOT NULL,
    trade_id     INTEGER,
    description  TEXT NOT NULL,
    evidence_url TEXT,
    status       TEXT NOT NULL DEFAULT 'open',
    reviewed_by  INTEGER,
    resolution   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deal_verifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL,
    buyer_name   TEXT,
    seller_name  TEXT,
    asset        TEXT NOT NULL,
    price        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    reviewed_by  INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS giveaways (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id    INTEGER NOT NULL,
    prize         TEXT NOT NULL,
    description   TEXT,
    winners_count INTEGER NOT NULL DEFAULT 1,
    message_id    INTEGER,
    channel_id    INTEGER,
    status        TEXT NOT NULL DEFAULT 'active',
    ends_at       TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    UNIQUE(giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    reward      TEXT,
    ends_at     TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_by  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS crates (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS achievements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    achievement TEXT NOT NULL,
    earned_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, achievement)
);

CREATE TABLE IF NOT EXISTS advertisements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    ad_type       TEXT NOT NULL,
    content       TEXT NOT NULL,
    duration_days INTEGER NOT NULL DEFAULT 1,
    message_id    INTEGER,
    channel_id    INTEGER,
    status        TEXT NOT NULL DEFAULT 'active',
    expires_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ad_interested (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_id   INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    UNIQUE(ad_id, user_id)
);

CREATE TABLE IF NOT EXISTS staff_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id    INTEGER NOT NULL,
    action      TEXT NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS db_submissions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    submitter_id INTEGER NOT NULL,
    asset_type   TEXT NOT NULL,
    data         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    reviewed_by  INTEGER,
    review_note  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS houses (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    number  INTEGER UNIQUE NOT NULL,
    city    TEXT NOT NULL,
    type    TEXT,
    address TEXT
);

CREATE TABLE IF NOT EXISTS apartments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    number  INTEGER UNIQUE NOT NULL,
    city    TEXT NOT NULL,
    type    TEXT,
    address TEXT
);

CREATE TABLE IF NOT EXISTS businesses (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    number   INTEGER,
    name     TEXT NOT NULL,
    location TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_config (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS birthdays (
    birthday_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL UNIQUE,
    username      TEXT NOT NULL,
    day           INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    year          INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    approved_by   INTEGER,
    approval_date TEXT,
    last_rewarded TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS escrows (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    buyer_id   INTEGER NOT NULL,
    seller_id  INTEGER NOT NULL,
    amount     INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'awaiting_deposit',
    staff_id   INTEGER,
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    type       TEXT NOT NULL,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    is_read    INTEGER NOT NULL DEFAULT 0,
    ref_id     INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    category    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    staff_id    INTEGER,
    resolution  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wanted_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    category    TEXT NOT NULL,
    description TEXT NOT NULL,
    location    TEXT,
    max_budget  INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS brokers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'pending',
    commission_rate REAL NOT NULL DEFAULT 2.0,
    deals_closed    INTEGER NOT NULL DEFAULT 0,
    applied_at      TEXT NOT NULL DEFAULT (datetime('now')),
    approved_by     INTEGER,
    approved_at     TEXT
);

CREATE TABLE IF NOT EXISTS ownership_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type  TEXT NOT NULL,
    asset_ref   TEXT NOT NULL,
    asset_name  TEXT NOT NULL,
    owner_id    INTEGER NOT NULL,
    owner_name  TEXT NOT NULL,
    acquired_at TEXT NOT NULL DEFAULT (datetime('now')),
    released_at TEXT,
    price       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS listing_features (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    feature    TEXT NOT NULL,
    coins_paid INTEGER NOT NULL DEFAULT 0,
    value      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS asset_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    note       TEXT NOT NULL,
    added_by   INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS asset_aliases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    alias      TEXT NOT NULL COLLATE NOCASE,
    added_by   INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(asset_type, asset_ref, alias)
);

CREATE TABLE IF NOT EXISTS asset_locations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    location   TEXT,
    coord_x    INTEGER,
    coord_y    INTEGER,
    map_link   TEXT,
    updated_by INTEGER,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(asset_type, asset_ref)
);

CREATE TABLE IF NOT EXISTS asset_images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    image_url  TEXT NOT NULL,
    label      TEXT,
    added_by   INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS asset_value_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    value      INTEGER NOT NULL,
    year       INTEGER NOT NULL,
    note       TEXT,
    added_by   INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(asset_type, asset_ref, year)
);

CREATE TABLE IF NOT EXISTS asset_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type        TEXT NOT NULL,
    asset_ref         TEXT NOT NULL,
    is_verified       INTEGER NOT NULL DEFAULT 0,
    is_blacklisted    INTEGER NOT NULL DEFAULT 0,
    blacklist_reason  TEXT,
    verified_by       INTEGER,
    blacklisted_by    INTEGER,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(asset_type, asset_ref)
);

CREATE TABLE IF NOT EXISTS asset_flags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    flag_type  TEXT NOT NULL,
    reason     TEXT,
    flagged_by INTEGER NOT NULL,
    resolved   INTEGER NOT NULL DEFAULT 0,
    resolved_by INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS asset_archive (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type  TEXT NOT NULL,
    asset_ref   TEXT NOT NULL,
    asset_name  TEXT,
    reason      TEXT,
    archived_by INTEGER NOT NULL,
    data_json   TEXT,
    archived_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS asset_change_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type  TEXT NOT NULL,
    asset_ref   TEXT NOT NULL,
    action      TEXT NOT NULL,
    changed_by  INTEGER NOT NULL,
    old_value   TEXT,
    new_value   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS asset_tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    tag        TEXT NOT NULL COLLATE NOCASE,
    added_by   INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(asset_type, asset_ref, tag)
);

CREATE TABLE IF NOT EXISTS asset_favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    asset_type TEXT NOT NULL,
    asset_ref  TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, asset_type, asset_ref)
);

CREATE TABLE IF NOT EXISTS watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    listing_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, listing_id)
);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.executescript(SCHEMA)
            await db.commit()
        logger.info("Database initialised at %s", self.db_path)

    async def execute(self, sql: str, params: tuple = ()) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    async def lastrowid(self, sql: str, params: tuple = ()) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(sql, params)
            await db.commit()
            return cur.lastrowid or 0

    async def load_csv(self, csv_path: str, table: str, columns: list[str], skip_header: bool = True) -> int:
        if not os.path.exists(csv_path):
            logger.warning("CSV not found: %s", csv_path)
            return 0
        count = 0
        async with aiosqlite.connect(self.db_path) as db:
            with open(csv_path, encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                if skip_header:
                    next(reader, None)
                for row in reader:
                    if len(row) < len(columns):
                        continue
                    row_data = [r.strip() for r in row[:len(columns)]]
                    placeholders = ",".join("?" * len(columns))
                    col_str = ",".join(columns)
                    await db.execute(
                        f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})",
                        row_data,
                    )
                    count += 1
            await db.commit()
        logger.info("Loaded %d rows into %s from %s", count, table, csv_path)
        return count


# ---------------------------------------------------------------------------
# Shared listing buttons (Interested / Reduce Price / Sold / Make Offer)
# ---------------------------------------------------------------------------

# Expiry select — generic step inserted between listing-type select and any modal
EXPIRY_OPTIONS = [
    discord.SelectOption(label="7 Days",  value="7",  emoji="📅"),
    discord.SelectOption(label="14 Days", value="14", emoji="📅"),
    discord.SelectOption(label="30 Days", value="30", emoji="📅"),
]


class ExpiryDropdown(discord.ui.Select):
    def __init__(self, modal_factory, modal_args: tuple) -> None:
        super().__init__(placeholder="Select listing expiry…", options=EXPIRY_OPTIONS)
        self._factory = modal_factory
        self._args    = modal_args

    async def callback(self, interaction: discord.Interaction) -> None:
        modal = self._factory(*self._args, int(self.values[0]))
        await interaction.response.send_modal(modal)


class ExpiryView(discord.ui.View):
    def __init__(self, modal_factory, *args) -> None:
        super().__init__(timeout=60)
        self.add_item(ExpiryDropdown(modal_factory, args))


def listing_type_badge(listing_type: str) -> str:
    badges = {
        "Featured": "⭐ Featured Listing",
        "Urgent":   "🔴 Urgent Listing",
    }
    return badges.get(listing_type, "📌 Standard Listing")


class InterestedButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(
            label="Interested",
            emoji="👀",
            style=discord.ButtonStyle.primary,
            custom_id=f"listing_interested:{listing_id}",
        )
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        listing = await bot.db.fetchone("SELECT * FROM listings WHERE id=?", (self.listing_id,))
        if not listing or listing["status"] != "active":
            await interaction.response.send_message("This listing is no longer active.", ephemeral=True)
            return
        if interaction.user.id == listing["seller_id"]:
            await interaction.response.send_message("You cannot show interest in your own listing.", ephemeral=True)
            return
        seller = interaction.guild.get_member(listing["seller_id"]) if interaction.guild else None
        if seller:
            try:
                await seller.send(
                    f"👀 **{interaction.user}** is interested in your listing **{listing['title']}** (#{self.listing_id})!"
                )
            except discord.Forbidden:
                pass
        await bot.db.execute(
            "INSERT INTO notifications (user_id, type, title, content, ref_id) VALUES (?,?,?,?,?)",
            (listing["seller_id"], "interested", "New Interested User",
             f"{interaction.user} is interested in **{listing['title']}**", self.listing_id),
        )
        await interaction.response.send_message("✅ The seller has been notified!", ephemeral=True)


class ReducePriceModal(discord.ui.Modal, title="Reduce Asking Price"):
    new_price = discord.ui.TextInput(
        label="New Asking Price",
        placeholder="e.g. 25000000",
        max_length=20,
    )

    def __init__(self, listing_id: int) -> None:
        super().__init__()
        self.listing_id = listing_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        try:
            price = int(self.new_price.value.replace(",", "").replace("$", ""))
        except ValueError:
            await interaction.response.send_message("❌ Invalid price.", ephemeral=True)
            return
        await bot.db.execute(
            "UPDATE listings SET asking_price=?, updated_at=datetime('now') WHERE id=?",
            (price, self.listing_id),
        )
        listing = await bot.db.fetchone("SELECT * FROM listings WHERE id=?", (self.listing_id,))
        if listing and listing["message_id"] and listing["channel_id"]:
            ch = bot.get_channel(listing["channel_id"])
            if ch:
                try:
                    msg = await ch.fetch_message(listing["message_id"])
                    embed = msg.embeds[0] if msg.embeds else None
                    if embed:
                        new_fields = []
                        for f in embed.fields:
                            if "Asking Price" in f.name:
                                new_fields.append(discord.EmbedField(
                                    name=f.name, value=f"${price:,}", inline=f.inline
                                ))
                            else:
                                new_fields.append(f)
                        new_embed = embed.copy()
                        new_embed.clear_fields()
                        for f in new_fields:
                            new_embed.add_field(name=f.name, value=f.value, inline=f.inline)
                        await msg.edit(embed=new_embed)
                except Exception as e:
                    logger.warning("Could not update listing message: %s", e)
        await interaction.response.send_message(f"✅ Price reduced to **${price:,}**!", ephemeral=True)


class ReducePriceButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(
            label="Reduce Price",
            emoji="💸",
            style=discord.ButtonStyle.secondary,
            custom_id=f"listing_reduce:{listing_id}",
        )
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        listing = await bot.db.fetchone("SELECT seller_id FROM listings WHERE id=?", (self.listing_id,))
        if not listing or interaction.user.id != listing["seller_id"]:
            await interaction.response.send_message("Only the seller can reduce the price.", ephemeral=True)
            return
        await interaction.response.send_modal(ReducePriceModal(self.listing_id))


class SoldButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(
            label="Sold",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"listing_sold:{listing_id}",
        )
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        listing = await bot.db.fetchone("SELECT * FROM listings WHERE id=?", (self.listing_id,))
        if not listing:
            await interaction.response.send_message("Listing not found.", ephemeral=True)
            return
        if interaction.user.id != listing["seller_id"]:
            await interaction.response.send_message("Only the seller can mark this as sold.", ephemeral=True)
            return

        # Marketplace tax
        tax_rate   = MARKETPLACE_TAX_RATES.get(listing["category"], 0.0)
        tax_amount = int(listing["asking_price"] * tax_rate)

        await bot.db.execute(
            "UPDATE listings SET status='sold', updated_at=datetime('now') WHERE id=?",
            (self.listing_id,),
        )
        if tax_amount > 0:
            await bot.db.execute(
                "UPDATE users SET game_cash=MAX(0, game_cash-?) WHERE user_id=?",
                (tax_amount, listing["seller_id"]),
            )

        # Ownership history
        await bot.db.execute(
            "INSERT INTO ownership_history (asset_type, asset_ref, asset_name, owner_id, owner_name, price) "
            "VALUES (?,?,?,?,?,?)",
            (listing["category"], str(self.listing_id), listing["title"],
             listing["seller_id"], f"User#{listing['seller_id']}", listing["asking_price"]),
        )

        if listing["message_id"] and listing["channel_id"]:
            ch = bot.get_channel(listing["channel_id"])
            if ch:
                try:
                    msg = await ch.fetch_message(listing["message_id"])
                    embed = msg.embeds[0] if msg.embeds else None
                    if embed:
                        sold_embed = embed.copy()
                        sold_embed.colour = discord.Colour.red()
                        tax_note = f" | Tax: ${tax_amount:,}" if tax_amount else ""
                        sold_embed.set_footer(text=f"✅ SOLD — Listing #{self.listing_id}{tax_note}")
                        await msg.edit(embed=sold_embed, view=None)
                except Exception as e:
                    logger.warning("Could not update sold message: %s", e)

        tax_msg = f"\n💸 Marketplace tax deducted: **${tax_amount:,}** ({int(tax_rate*100)}%)" if tax_amount else ""
        await interaction.response.send_message(f"✅ Listing marked as **SOLD**!{tax_msg}", ephemeral=True)


# ---------------------------------------------------------------------------
# Make Offer flow
# ---------------------------------------------------------------------------

class OfferAcceptButton(discord.ui.Button):
    def __init__(self, offer_id: int) -> None:
        super().__init__(label="Accept", emoji="✅", style=discord.ButtonStyle.success,
                         custom_id=f"offer_accept:{offer_id}")
        self.offer_id = offer_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        offer = await bot.db.fetchone("SELECT * FROM offers WHERE id=?", (self.offer_id,))
        if not offer or offer["status"] != "pending":
            await interaction.response.send_message("This offer is no longer valid.", ephemeral=True)
            return
        if interaction.user.id != offer.get("seller_id", 0):
            listing = await bot.db.fetchone("SELECT seller_id FROM listings WHERE id=?", (offer["listing_id"],))
            if not listing or interaction.user.id != listing["seller_id"]:
                await interaction.response.send_message("Only the seller can accept this offer.", ephemeral=True)
                return
        await bot.db.execute("UPDATE offers SET status='accepted' WHERE id=?", (self.offer_id,))
        await bot.db.execute(
            "INSERT INTO notifications (user_id, type, title, content, ref_id) VALUES (?,?,?,?,?)",
            (offer["buyer_id"], "offer_accepted", "Offer Accepted",
             f"Your offer of ${offer['offer_amount']:,} was accepted!", self.offer_id),
        )
        buyer = None
        for guild in bot.guilds:
            buyer = guild.get_member(offer["buyer_id"])
            if buyer:
                break
        if buyer:
            try:
                await buyer.send(f"✅ Your offer of **${offer['offer_amount']:,}** was **accepted**! Contact the seller to complete the trade.")
            except discord.Forbidden:
                pass
        await interaction.response.edit_message(content="✅ Offer accepted! The buyer has been notified.", view=None, embed=None)


class OfferDeclineButton(discord.ui.Button):
    def __init__(self, offer_id: int) -> None:
        super().__init__(label="Decline", emoji="❌", style=discord.ButtonStyle.danger,
                         custom_id=f"offer_decline:{offer_id}")
        self.offer_id = offer_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.db.execute("UPDATE offers SET status='declined' WHERE id=?", (self.offer_id,))
        offer = await bot.db.fetchone("SELECT buyer_id, offer_amount FROM offers WHERE id=?", (self.offer_id,))
        if offer:
            await bot.db.execute(
                "INSERT INTO notifications (user_id, type, title, content, ref_id) VALUES (?,?,?,?,?)",
                (offer["buyer_id"], "offer_declined", "Offer Declined",
                 f"Your offer of ${offer['offer_amount']:,} was declined.", self.offer_id),
            )
        await interaction.response.edit_message(content="❌ Offer declined.", view=None, embed=None)


class CounterOfferModal(discord.ui.Modal, title="Counter Offer"):
    counter_amount = discord.ui.TextInput(label="Counter Amount ($)", placeholder="e.g. 28000000", max_length=20)

    def __init__(self, offer_id: int, buyer_id: int) -> None:
        super().__init__()
        self.offer_id = offer_id
        self.buyer_id = buyer_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        try:
            amount = int(self.counter_amount.value.replace(",", "").replace("$", ""))
        except ValueError:
            await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
            return
        await bot.db.execute("UPDATE offers SET status='countered' WHERE id=?", (self.offer_id,))
        await bot.db.execute(
            "INSERT INTO notifications (user_id, type, title, content, ref_id) VALUES (?,?,?,?,?)",
            (self.buyer_id, "counter_offer", "Counter Offer Received",
             f"Seller countered with ${amount:,}", self.offer_id),
        )
        buyer = None
        for guild in bot.guilds:
            buyer = guild.get_member(self.buyer_id)
            if buyer:
                break
        if buyer:
            embed = discord.Embed(title="🔄 Counter Offer Received", colour=discord.Colour.orange())
            embed.add_field(name="💰 Counter Amount",  value=f"${amount:,}",             inline=False)
            embed.add_field(name="👤 From Seller",     value=interaction.user.mention,   inline=False)
            try:
                await buyer.send(embed=embed)
            except discord.Forbidden:
                pass
        await interaction.response.edit_message(
            content=f"✅ Counter offer of **${amount:,}** sent to the buyer!", view=None, embed=None
        )


class OfferCounterButton(discord.ui.Button):
    def __init__(self, offer_id: int, buyer_id: int) -> None:
        super().__init__(label="Counter Offer", emoji="🔄", style=discord.ButtonStyle.secondary,
                         custom_id=f"offer_counter:{offer_id}")
        self.offer_id = offer_id
        self.buyer_id = buyer_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CounterOfferModal(self.offer_id, self.buyer_id))


class OfferResponseView(discord.ui.View):
    def __init__(self, offer_id: int, buyer_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(OfferAcceptButton(offer_id))
        self.add_item(OfferDeclineButton(offer_id))
        self.add_item(OfferCounterButton(offer_id, buyer_id))


class MakeOfferModal(discord.ui.Modal, title="Make an Offer"):
    offer_amount = discord.ui.TextInput(label="Offer Amount ($)", placeholder="e.g. 25000000", max_length=20)
    message      = discord.ui.TextInput(label="Message (optional)", required=False, max_length=200)

    def __init__(self, listing_id: int) -> None:
        super().__init__()
        self.listing_id = listing_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        listing = await bot.db.fetchone("SELECT * FROM listings WHERE id=?", (self.listing_id,))
        if not listing or listing["status"] != "active":
            await interaction.response.send_message("This listing is no longer active.", ephemeral=True)
            return
        if interaction.user.id == listing["seller_id"]:
            await interaction.response.send_message("You cannot offer on your own listing.", ephemeral=True)
            return
        try:
            amount = int(self.offer_amount.value.replace(",", "").replace("$", ""))
        except ValueError:
            await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
            return

        offer_id = await bot.db.lastrowid(
            "INSERT INTO offers (listing_id, buyer_id, offer_type, offer_amount, offer_asset) VALUES (?,?,?,?,?)",
            (self.listing_id, interaction.user.id, "cash", amount, self.message.value or None),
        )
        await bot.db.execute(
            "INSERT INTO notifications (user_id, type, title, content, ref_id) VALUES (?,?,?,?,?)",
            (listing["seller_id"], "offer", "New Offer Received",
             f"${amount:,} offer on **{listing['title']}** from {interaction.user}", offer_id),
        )

        seller = interaction.guild.get_member(listing["seller_id"]) if interaction.guild else None
        if not seller:
            for guild in bot.guilds:
                seller = guild.get_member(listing["seller_id"])
                if seller:
                    break
        if seller:
            embed = discord.Embed(title="💰 New Offer Received!", colour=discord.Colour.gold())
            embed.add_field(name="📦 Listing", value=listing["title"],            inline=False)
            embed.add_field(name="💰 Offer",   value=f"${amount:,}",             inline=False)
            embed.add_field(name="👤 From",    value=interaction.user.mention,   inline=False)
            if self.message.value:
                embed.add_field(name="💬 Message", value=self.message.value, inline=False)
            try:
                await seller.send(embed=embed, view=OfferResponseView(offer_id, interaction.user.id))
            except discord.Forbidden:
                pass

        await interaction.response.send_message(f"✅ Offer of **${amount:,}** sent to the seller!", ephemeral=True)


class MakeOfferButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(label="Make Offer", emoji="💰", style=discord.ButtonStyle.secondary,
                         custom_id=f"listing_offer:{listing_id}")
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        listing = await bot.db.fetchone("SELECT seller_id, status FROM listings WHERE id=?", (self.listing_id,))
        if not listing or listing["status"] != "active":
            await interaction.response.send_message("This listing is no longer active.", ephemeral=True)
            return
        if interaction.user.id == listing["seller_id"]:
            await interaction.response.send_message("You cannot offer on your own listing.", ephemeral=True)
            return
        await interaction.response.send_modal(MakeOfferModal(self.listing_id))


# ---------------------------------------------------------------------------
# Listing view
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Relist System
# ---------------------------------------------------------------------------

async def _do_relist(
    bot: "KATBot",
    old_listing: aiosqlite.Row,
    new_price: int,
    expiry_days: int,
    interaction: discord.Interaction,
) -> None:
    """Copy an old listing into a fresh active listing and post it to the channel."""
    expires_at = (utcnow() + timedelta(days=expiry_days)).isoformat()
    new_id = await bot.db.lastrowid(
        "INSERT INTO listings (seller_id, category, title, asking_price, listing_type, expires_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            old_listing["seller_id"],
            old_listing["category"],
            old_listing["title"],
            new_price,
            old_listing["listing_type"] or "Standard",
            expires_at,
        ),
    )
    await bot.db.execute(
        "UPDATE listings SET status='relisted' WHERE id=?", (old_listing["id"],)
    )
    await _log_change(
        bot, old_listing["category"], str(old_listing["id"]),
        "relisted", interaction.user.id,
        old_value=str(old_listing["asking_price"]),
        new_value=str(new_price),
    )

    category_emoji = {
        "vehicle": "🚗", "property": "🏠", "skin": "🎨",
        "item": "📦", "business": "🏢",
    }.get(old_listing["category"], "📋")

    embed = discord.Embed(
        title=f"{category_emoji} {old_listing['title']}",
        colour=discord.Colour.green(),
    )
    embed.add_field(name="🏷 Asking Price", value=f"${new_price:,}",           inline=False)
    embed.add_field(name="🔄 Relisted",     value="Re-posted listing",          inline=True)
    embed.add_field(name="👤 Seller",       value=interaction.user.mention,     inline=True)
    embed.add_field(name="📅 Listed",       value="Today",                      inline=False)
    badge = listing_type_badge(old_listing["listing_type"] or "Standard")
    embed.add_field(name="​",              value=badge,                         inline=False)
    embed.add_field(
        name="⏳ Expires",
        value=f"<t:{int((utcnow() + timedelta(days=expiry_days)).timestamp())}:R>",
        inline=False,
    )
    embed.set_footer(text=f"New Listing #{new_id} • Original #{old_listing['id']} ━━━━━━━━━━━━━━━━━━")
    embed.timestamp = utcnow()

    view = ListingView(new_id)
    ch = bot.get_channel(LISTINGS_CHANNEL_ID) or interaction.channel
    msg = await ch.send(embed=embed, view=view)
    await bot.db.execute(
        "UPDATE listings SET message_id=?, channel_id=? WHERE id=?",
        (msg.id, ch.id, new_id),
    )
    await interaction.followup.send(
        f"✅ Relisted as **#{new_id}** — expires in **{expiry_days} days**!",
        ephemeral=True,
    )


class RelistEditPriceModal(discord.ui.Modal, title="Edit Price & Relist"):
    new_price = discord.ui.TextInput(
        label="New Asking Price ($)",
        placeholder="e.g. 20000000",
        max_length=20,
    )

    def __init__(self, old_listing: aiosqlite.Row) -> None:
        super().__init__()
        self._old = old_listing
        self.new_price.default = str(old_listing["asking_price"])

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = int(self.new_price.value.replace(",", "").replace("$", ""))
        except ValueError:
            await interaction.response.send_message("❌ Invalid price.", ephemeral=True)
            return
        view = RelistExpiryView(self._old, price)
        await interaction.response.edit_message(
            content="**Select new listing expiry:**", view=view, embed=None
        )


class RelistExpiryDropdown(discord.ui.Select):
    def __init__(self, old_listing: aiosqlite.Row, new_price: int) -> None:
        super().__init__(placeholder="Select expiry duration…", options=EXPIRY_OPTIONS)
        self._old       = old_listing
        self._new_price = new_price

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        bot: KATBot = interaction.client  # type: ignore
        await _do_relist(bot, self._old, self._new_price, int(self.values[0]), interaction)


class RelistExpiryView(discord.ui.View):
    def __init__(self, old_listing: aiosqlite.Row, new_price: int) -> None:
        super().__init__(timeout=60)
        self.add_item(RelistExpiryDropdown(old_listing, new_price))


class RelistActionView(discord.ui.View):
    def __init__(self, old_listing: aiosqlite.Row) -> None:
        super().__init__(timeout=120)
        self._old = old_listing

    @discord.ui.button(label="Relist", emoji="🔄", style=discord.ButtonStyle.success)
    async def do_relist(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = RelistExpiryView(self._old, self._old["asking_price"])
        await interaction.response.edit_message(
            content="**Select new listing expiry:**", view=view, embed=None
        )

    @discord.ui.button(label="Edit Price", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit_price(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RelistEditPriceModal(self._old))

    @discord.ui.button(label="Delete Listing", emoji="🗑", style=discord.ButtonStyle.danger)
    async def delete_listing(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.db.execute(
            "UPDATE listings SET status='deleted' WHERE id=?", (self._old["id"],)
        )
        await _log_change(
            bot, self._old["category"], str(self._old["id"]),
            "deleted", interaction.user.id,
        )
        await interaction.response.edit_message(
            content=f"🗑 Listing **#{self._old['id']} — {self._old['title']}** has been deleted.",
            view=None, embed=None,
        )


class RelistSelectDropdown(discord.ui.Select):
    def __init__(self, listings: list) -> None:
        options = []
        for r in listings[:25]:
            status_icon = {"expired": "⌛", "relisted": "🔄", "archived": "📦", "unsold": "📋"}.get(
                r["status"], "📋"
            )
            days_ago = ""
            try:
                from datetime import datetime as _dt
                created = _dt.fromisoformat(r["created_at"])
                delta = (utcnow().replace(tzinfo=None) - created.replace(tzinfo=None)).days
                days_ago = f" · {delta}d ago"
            except Exception:
                pass
            options.append(
                discord.SelectOption(
                    label=f"#{r['id']} {r['title'][:60]}",
                    description=f"{status_icon} {r['status'].capitalize()}{days_ago} · ${r['asking_price']:,}",
                    value=str(r["id"]),
                    emoji=status_icon,
                )
            )
        super().__init__(placeholder="Select a listing to relist…", options=options)
        self._listings = {str(r["id"]): r for r in listings[:25]}

    async def callback(self, interaction: discord.Interaction) -> None:
        listing = self._listings.get(self.values[0])
        if not listing:
            await interaction.response.send_message("❌ Listing not found.", ephemeral=True)
            return
        status_icon = {"expired": "⌛", "relisted": "🔄", "archived": "📦"}.get(listing["status"], "📋")
        days_ago = ""
        try:
            from datetime import datetime as _dt
            created = _dt.fromisoformat(listing["created_at"])
            delta = (utcnow().replace(tzinfo=None) - created.replace(tzinfo=None)).days
            days_ago = f"{delta} days ago"
        except Exception:
            days_ago = "Unknown"

        embed = discord.Embed(
            title=f"{status_icon} Listing #{listing['id']} — {listing['title']}",
            colour=discord.Colour.orange(),
        )
        embed.add_field(name="💰 Current Price", value=f"${listing['asking_price']:,}", inline=True)
        embed.add_field(name="📊 Status",        value=listing["status"].capitalize(),  inline=True)
        embed.add_field(name="🏷 Category",      value=listing["category"].capitalize(), inline=True)
        embed.add_field(name="📅 Created",       value=days_ago,                         inline=True)
        embed.add_field(name="⏳ Expired",
                        value=listing["expires_at"][:10] if listing["expires_at"] else "N/A",
                        inline=True)
        embed.set_footer(text="Choose an action below ━━━━━━━━━━━━━━━━━━")
        view = RelistActionView(listing)
        await interaction.response.edit_message(embed=embed, view=view, content=None)


class RelistSelectView(discord.ui.View):
    def __init__(self, listings: list) -> None:
        super().__init__(timeout=60)
        self.add_item(RelistSelectDropdown(listings))


class RelistButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(
            label="Relist",
            emoji="🔄",
            style=discord.ButtonStyle.secondary,
            custom_id=f"listing_relist:{listing_id}",
        )
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        listing = await bot.db.fetchone("SELECT * FROM listings WHERE id=?", (self.listing_id,))
        if not listing:
            await interaction.response.send_message("❌ Listing not found.", ephemeral=True)
            return
        if interaction.user.id != listing["seller_id"]:
            await interaction.response.send_message("❌ Only the seller can relist.", ephemeral=True)
            return
        if listing["status"] == "active":
            is_expired = (
                listing["expires_at"]
                and listing["expires_at"] < utcnow().isoformat()
            )
            if not is_expired:
                await interaction.response.send_message(
                    "⚠️ This listing is still active. Use `/relist` to manage it.", ephemeral=True
                )
                return
        days_ago = ""
        try:
            from datetime import datetime as _dt
            created = _dt.fromisoformat(listing["created_at"])
            delta = (utcnow().replace(tzinfo=None) - created.replace(tzinfo=None)).days
            days_ago = f"{delta} days ago"
        except Exception:
            days_ago = "Unknown"
        embed = discord.Embed(
            title=f"🔄 Relist — {listing['title']}",
            colour=discord.Colour.orange(),
        )
        embed.add_field(name="💰 Price",    value=f"${listing['asking_price']:,}",     inline=True)
        embed.add_field(name="📊 Status",   value=listing["status"].capitalize(),      inline=True)
        embed.add_field(name="📅 Created",  value=days_ago,                             inline=True)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        view = RelistActionView(listing)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ListingView(discord.ui.View):
    def __init__(self, listing_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(InterestedButton(listing_id))
        self.add_item(MakeOfferButton(listing_id))
        self.add_item(ReducePriceButton(listing_id))
        self.add_item(SoldButton(listing_id))
        self.add_item(RelistButton(listing_id))


# ---------------------------------------------------------------------------
# Marketplace Cog — vehicle, property, skin, item, business
# ---------------------------------------------------------------------------

LISTING_TYPE_OPTIONS = [
    discord.SelectOption(label="Standard",  value="Standard",  emoji="📌", description="Free listing"),
    discord.SelectOption(label="Featured",  value="Featured",  emoji="⭐", description=f"Costs {COIN_SINK_COSTS['feature_listing']} KAT Coins"),
    discord.SelectOption(label="Urgent",    value="Urgent",    emoji="🔴", description=f"Costs {COIN_SINK_COSTS['urgent_listing']} KAT Coins"),
]


# ── Vehicle ──────────────────────────────────────────────────────────────────

class VehicleModal(discord.ui.Modal, title="Vehicle Listing"):
    veh_name    = discord.ui.TextInput(label="Vehicle Name",    placeholder="e.g. Lamborghini Urus",  max_length=100)
    owners      = discord.ui.TextInput(label="Number of Owners", placeholder="e.g. 2",               max_length=10)
    state_price = discord.ui.TextInput(label="State Price ($)",  placeholder="e.g. 25000000",         max_length=20)
    asking_price = discord.ui.TextInput(label="Asking Price ($)", placeholder="e.g. 30000000",        max_length=20)
    image_url   = discord.ui.TextInput(label="Image URL (optional)", required=False,                  max_length=300)

    def __init__(self, listing_type: str, expiry_days: int = 7) -> None:
        super().__init__()
        self.listing_type = listing_type
        self.expiry_days  = expiry_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)
        sp  = fmt_price(self.state_price.value)
        ap  = fmt_price(self.asking_price.value)
        badge = listing_type_badge(self.listing_type)

        embed = discord.Embed(title=f"🚗 {self.veh_name.value}", colour=discord.Colour.blue())
        embed.add_field(name="👤 Owners",       value=self.owners.value,        inline=False)
        embed.add_field(name="💰 State Price",  value=sp,                       inline=False)
        embed.add_field(name="🏷 Asking Price", value=ap,                       inline=False)
        embed.add_field(name="​",               value=badge,                    inline=False)
        embed.add_field(name="👤 Seller",       value=interaction.user.mention, inline=False)
        embed.add_field(name="📅 Listed",       value="Today",                  inline=False)
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)
            embed.add_field(name="🖼 Images", value="1 Attached", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        try:
            price_int = int(self.asking_price.value.replace(",", "").replace("$", ""))
        except ValueError:
            price_int = 0

        expires_at = (utcnow() + timedelta(days=self.expiry_days)).isoformat()
        listing_id = await bot.db.lastrowid(
            "INSERT INTO listings (seller_id, category, title, asking_price, listing_type, expires_at) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, "vehicle", self.veh_name.value, price_int, self.listing_type, expires_at),
        )
        view = ListingView(listing_id)
        ch = bot.get_channel(LISTINGS_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE listings SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, listing_id),
        )
        await interaction.response.send_message(f"✅ Vehicle listing posted! (#{listing_id})", ephemeral=True)


class VehicleListingTypeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Select listing type…", options=LISTING_TYPE_OPTIONS)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = ExpiryView(VehicleModal, self.values[0])
        await interaction.response.edit_message(content="**Select listing expiry:**", view=view)


class VehicleListingTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.add_item(VehicleListingTypeSelect())


# ── Property ─────────────────────────────────────────────────────────────────

class PropertyModal(discord.ui.Modal, title="Property Listing"):
    prop_ref     = discord.ui.TextInput(label="Property (e.g. House #20)",  placeholder="House #20 / Apartment #5", max_length=60)
    prop_class   = discord.ui.TextInput(label="Class (e.g. Luxury)",         placeholder="Standard / Luxury / Elite", max_length=60)
    location     = discord.ui.TextInput(label="Location",                    placeholder="e.g. Elite Village",       max_length=100)
    address      = discord.ui.TextInput(label="Address",                     placeholder="e.g. Elite Village Street 5", max_length=150)
    asking_price = discord.ui.TextInput(label="Asking Price ($)",             placeholder="e.g. 500000000",            max_length=20)

    def __init__(self, listing_type: str, prop_type: str, expiry_days: int = 7) -> None:
        super().__init__()
        self.listing_type = listing_type
        self.prop_type    = prop_type
        self.expiry_days  = expiry_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)
        ap    = fmt_price(self.asking_price.value)
        badge = listing_type_badge(self.listing_type)
        emoji = "🏠" if self.prop_type == "house" else "🏢"

        embed = discord.Embed(title=f"{emoji} {self.prop_ref.value}", colour=discord.Colour.green())
        embed.add_field(name="🏷 Type",          value=self.prop_type.capitalize(), inline=False)
        embed.add_field(name="⭐ Class",         value=self.prop_class.value,       inline=False)
        embed.add_field(name="📍 Location",      value=self.location.value,         inline=False)
        embed.add_field(name=f"{emoji} Address", value=self.address.value,          inline=False)
        embed.add_field(name="💰 Asking Price",  value=ap,                          inline=False)
        embed.add_field(name="​",                value=badge,                       inline=False)
        embed.add_field(name="👤 Seller",        value=interaction.user.mention,    inline=False)
        embed.add_field(name="📅 Listed",        value="Today",                     inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        try:
            price_int = int(self.asking_price.value.replace(",", "").replace("$", ""))
        except ValueError:
            price_int = 0

        expires_at = (utcnow() + timedelta(days=self.expiry_days)).isoformat()
        listing_id = await bot.db.lastrowid(
            "INSERT INTO listings (seller_id, category, title, asking_price, listing_type, expires_at) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, "property", self.prop_ref.value, price_int, self.listing_type, expires_at),
        )
        view = ListingView(listing_id)
        ch = bot.get_channel(LISTINGS_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE listings SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, listing_id),
        )
        await interaction.response.send_message(f"✅ Property listing posted! (#{listing_id})", ephemeral=True)


class PropertyTypeSelect(discord.ui.Select):
    def __init__(self, listing_type: str) -> None:
        self.listing_type = listing_type
        super().__init__(
            placeholder="Select property type…",
            options=[
                discord.SelectOption(label="House",     value="house",     emoji="🏠"),
                discord.SelectOption(label="Apartment", value="apartment", emoji="🏢"),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = ExpiryView(PropertyModal, self.listing_type, self.values[0])
        await interaction.response.edit_message(content="**Select listing expiry:**", view=view)


class PropertyTypeView(discord.ui.View):
    def __init__(self, listing_type: str) -> None:
        super().__init__(timeout=60)
        self.add_item(PropertyTypeSelect(listing_type))


class PropertyListingTypeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Select listing type…", options=LISTING_TYPE_OPTIONS)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = PropertyTypeView(self.values[0])
        await interaction.response.edit_message(content="**Select property type:**", view=view)


class PropertyListingTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.add_item(PropertyListingTypeSelect())


# ── Skin ─────────────────────────────────────────────────────────────────────

class SkinModal(discord.ui.Modal, title="Skin Listing"):
    skin_name    = discord.ui.TextInput(label="Skin Name",        placeholder="e.g. Dragon Skin",   max_length=100)
    skin_id      = discord.ui.TextInput(label="Skin ID",          placeholder="e.g. 1542",          max_length=20)
    asking_price = discord.ui.TextInput(label="Asking Price ($)", placeholder="e.g. 15000000",      max_length=20)
    image_url    = discord.ui.TextInput(label="Image URL (optional)", required=False,               max_length=300)

    def __init__(self, listing_type: str, expiry_days: int = 7) -> None:
        super().__init__()
        self.listing_type = listing_type
        self.expiry_days  = expiry_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)
        ap    = fmt_price(self.asking_price.value)
        badge = listing_type_badge(self.listing_type)

        embed = discord.Embed(title=f"🎨 {self.skin_name.value}", colour=discord.Colour.purple())
        embed.add_field(name="🆔 Skin ID",      value=self.skin_id.value,          inline=False)
        embed.add_field(name="💰 Asking Price", value=ap,                          inline=False)
        embed.add_field(name="​",               value=badge,                       inline=False)
        embed.add_field(name="👤 Seller",       value=interaction.user.mention,    inline=False)
        embed.add_field(name="📅 Listed",       value="Today",                     inline=False)
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)
            embed.add_field(name="🖼 Images", value="1 Attached", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        try:
            price_int = int(self.asking_price.value.replace(",", "").replace("$", ""))
        except ValueError:
            price_int = 0

        expires_at = (utcnow() + timedelta(days=self.expiry_days)).isoformat()
        listing_id = await bot.db.lastrowid(
            "INSERT INTO listings (seller_id, category, title, asking_price, listing_type, expires_at) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, "skin", self.skin_name.value, price_int, self.listing_type, expires_at),
        )
        view = ListingView(listing_id)
        ch = bot.get_channel(LISTINGS_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE listings SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, listing_id),
        )
        await interaction.response.send_message(f"✅ Skin listing posted! (#{listing_id})", ephemeral=True)


class SkinListingTypeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Select listing type…", options=LISTING_TYPE_OPTIONS)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = ExpiryView(SkinModal, self.values[0])
        await interaction.response.edit_message(content="**Select listing expiry:**", view=view)


class SkinListingTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.add_item(SkinListingTypeSelect())


# ── Item ─────────────────────────────────────────────────────────────────────

class ItemModal(discord.ui.Modal, title="Item Listing"):
    item_name    = discord.ui.TextInput(label="Item Name",        placeholder="e.g. Gold Crate",    max_length=100)
    quantity     = discord.ui.TextInput(label="Quantity",         placeholder="e.g. 10",            max_length=10)
    asking_price = discord.ui.TextInput(label="Asking Price ($)", placeholder="e.g. 25000000",      max_length=20)
    image_url    = discord.ui.TextInput(label="Image URL (optional)", required=False,               max_length=300)

    def __init__(self, listing_type: str, expiry_days: int = 7) -> None:
        super().__init__()
        self.listing_type = listing_type
        self.expiry_days  = expiry_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)
        ap    = fmt_price(self.asking_price.value)
        badge = listing_type_badge(self.listing_type)

        embed = discord.Embed(title=f"📦 {self.item_name.value}", colour=discord.Colour.orange())
        embed.add_field(name="📊 Quantity",     value=self.quantity.value,         inline=False)
        embed.add_field(name="💰 Asking Price", value=ap,                          inline=False)
        embed.add_field(name="​",               value=badge,                       inline=False)
        embed.add_field(name="👤 Seller",       value=interaction.user.mention,    inline=False)
        embed.add_field(name="📅 Listed",       value="Today",                     inline=False)
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)
            embed.add_field(name="🖼 Images", value="1 Attached", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        try:
            price_int = int(self.asking_price.value.replace(",", "").replace("$", ""))
        except ValueError:
            price_int = 0

        expires_at = (utcnow() + timedelta(days=self.expiry_days)).isoformat()
        listing_id = await bot.db.lastrowid(
            "INSERT INTO listings (seller_id, category, title, asking_price, listing_type, expires_at) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, "item", self.item_name.value, price_int, self.listing_type, expires_at),
        )
        view = ListingView(listing_id)
        ch = bot.get_channel(LISTINGS_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE listings SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, listing_id),
        )
        await interaction.response.send_message(f"✅ Item listing posted! (#{listing_id})", ephemeral=True)


class ItemListingTypeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Select listing type…", options=LISTING_TYPE_OPTIONS)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = ExpiryView(ItemModal, self.values[0])
        await interaction.response.edit_message(content="**Select listing expiry:**", view=view)


class ItemListingTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.add_item(ItemListingTypeSelect())


# ── Business ─────────────────────────────────────────────────────────────────

class BusinessModal(discord.ui.Modal, title="Business Listing"):
    biz_name     = discord.ui.TextInput(label="Business Name",        placeholder="e.g. Shop 24/7 Arzamas Center", max_length=120)
    biz_type     = discord.ui.TextInput(label="Business Type",        placeholder="e.g. 24/7 Store",               max_length=80)
    location     = discord.ui.TextInput(label="Location",             placeholder="e.g. Arzamas",                  max_length=100)
    daily_profit = discord.ui.TextInput(label="Avg Daily Profit ($)", placeholder="e.g. 8500000",                  max_length=20)
    asking_price = discord.ui.TextInput(label="Asking Price ($)",     placeholder="e.g. 500000000",                max_length=20)

    def __init__(self, listing_type: str, expiry_days: int = 7) -> None:
        super().__init__()
        self.listing_type = listing_type
        self.expiry_days  = expiry_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)
        dp    = fmt_price(self.daily_profit.value)
        ap    = fmt_price(self.asking_price.value)
        badge = listing_type_badge(self.listing_type)

        embed = discord.Embed(title=f"🏢 {self.biz_name.value}", colour=discord.Colour.gold())
        embed.add_field(name="🏷 Type",                 value=self.biz_type.value,         inline=False)
        embed.add_field(name="📍 Location",             value=self.location.value,         inline=False)
        embed.add_field(name="📈 Average Daily Profit", value=dp,                          inline=False)
        embed.add_field(name="📊 10 Day Profit",        value="Screenshot Attached",       inline=False)
        embed.add_field(name="💰 Asking Price",         value=ap,                          inline=False)
        embed.add_field(name="​",                       value=badge,                       inline=False)
        embed.add_field(name="👤 Seller",               value=interaction.user.mention,    inline=False)
        embed.add_field(name="📅 Listed",               value="Today",                     inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        try:
            price_int = int(self.asking_price.value.replace(",", "").replace("$", ""))
        except ValueError:
            price_int = 0

        expires_at = (utcnow() + timedelta(days=self.expiry_days)).isoformat()
        listing_id = await bot.db.lastrowid(
            "INSERT INTO listings (seller_id, category, title, asking_price, listing_type, expires_at) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, "business", self.biz_name.value, price_int, self.listing_type, expires_at),
        )
        view = ListingView(listing_id)
        ch = bot.get_channel(LISTINGS_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE listings SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, listing_id),
        )
        await interaction.response.send_message(f"✅ Business listing posted! (#{listing_id})", ephemeral=True)


class BusinessListingTypeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Select listing type…", options=LISTING_TYPE_OPTIONS)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = ExpiryView(BusinessModal, self.values[0])
        await interaction.response.edit_message(content="**Select listing expiry:**", view=view)


class BusinessListingTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.add_item(BusinessListingTypeSelect())


class MarketplaceCog(commands.Cog, name="Marketplace"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="sell_vehicle", description="Post a vehicle listing")
    async def sell_vehicle(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select listing type:**", view=VehicleListingTypeView(), ephemeral=True)

    @app_commands.command(name="sell_property", description="Post a property listing")
    async def sell_property(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select listing type:**", view=PropertyListingTypeView(), ephemeral=True)

    @app_commands.command(name="sell_skin", description="Post a skin listing")
    async def sell_skin(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select listing type:**", view=SkinListingTypeView(), ephemeral=True)

    @app_commands.command(name="sell_item", description="Post an item listing")
    async def sell_item(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select listing type:**", view=ItemListingTypeView(), ephemeral=True)

    @app_commands.command(name="sell_business", description="Post a business listing")
    async def sell_business(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select listing type:**", view=BusinessListingTypeView(), ephemeral=True)


# ---------------------------------------------------------------------------
# Bounty Cog
# ---------------------------------------------------------------------------

class BountyInterestedButton(discord.ui.Button):
    def __init__(self, bounty_id: int) -> None:
        super().__init__(
            label="Interested",
            emoji="👀",
            style=discord.ButtonStyle.primary,
            custom_id=f"bounty_interested:{bounty_id}",
        )
        self.bounty_id = bounty_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        bounty = await bot.db.fetchone("SELECT * FROM bounties WHERE id=?", (self.bounty_id,))
        if not bounty or bounty["status"] != "active":
            await interaction.response.send_message("This bounty is no longer active.", ephemeral=True)
            return
        await bot.db.execute(
            "INSERT OR IGNORE INTO bounty_interested (bounty_id, user_id) VALUES (?,?)",
            (self.bounty_id, interaction.user.id),
        )
        creator = interaction.guild.get_member(bounty["creator_id"]) if interaction.guild else None
        if creator:
            try:
                await creator.send(f"👀 **{interaction.user}** is interested in your bounty #{self.bounty_id}!")
            except discord.Forbidden:
                pass
        await interaction.response.send_message("✅ The bounty creator has been notified!", ephemeral=True)


class BountyAcceptButton(discord.ui.Button):
    def __init__(self, bounty_id: int) -> None:
        super().__init__(
            label="Accept Contract",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"bounty_accept:{bounty_id}",
        )
        self.bounty_id = bounty_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        bounty = await bot.db.fetchone("SELECT * FROM bounties WHERE id=?", (self.bounty_id,))
        if not bounty or bounty["status"] != "active":
            await interaction.response.send_message("This bounty is no longer available.", ephemeral=True)
            return
        if interaction.user.id == bounty["creator_id"]:
            await interaction.response.send_message("You cannot accept your own bounty.", ephemeral=True)
            return
        await bot.db.execute(
            "UPDATE bounties SET status='accepted', accepted_by=? WHERE id=?",
            (interaction.user.id, self.bounty_id),
        )
        creator = interaction.guild.get_member(bounty["creator_id"]) if interaction.guild else None
        if creator:
            try:
                await creator.send(
                    f"✅ **{interaction.user}** has accepted your bounty #{self.bounty_id} on **{bounty['target_name']}**!"
                )
            except discord.Forbidden:
                pass
        await interaction.response.send_message("✅ Bounty accepted! The creator has been notified.", ephemeral=True)


class BountyView(discord.ui.View):
    def __init__(self, bounty_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(BountyInterestedButton(bounty_id))
        self.add_item(BountyAcceptButton(bounty_id))


class BountyModal(discord.ui.Modal, title="Post a Bounty"):
    target_name = discord.ui.TextInput(label="Target Name",    placeholder="e.g. COOL_HABIBI2", max_length=80)
    reward      = discord.ui.TextInput(label="Reward",         placeholder="e.g. $10,000,000",  max_length=80)
    duration    = discord.ui.TextInput(label="Duration (days)",placeholder="e.g. 7",            max_length=5)
    reason      = discord.ui.TextInput(label="Reason",         placeholder="e.g. Business Dispute",
                                       style=discord.TextStyle.paragraph, max_length=500)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)

        try:
            duration_days = int(self.duration.value)
        except ValueError:
            duration_days = 1

        extra_days = max(0, duration_days - BOUNTY_FREE_DAYS)
        coins_cost = extra_days * BOUNTY_COST_PER_DAY

        if coins_cost > 0:
            user = await bot.db.fetchone("SELECT kat_coins FROM users WHERE user_id=?", (interaction.user.id,))
            if not user or user["kat_coins"] < coins_cost:
                await interaction.response.send_message(
                    f"❌ You need **{coins_cost} KAT Coins** for a {duration_days}-day bounty.", ephemeral=True
                )
                return
            await bot.db.execute(
                "UPDATE users SET kat_coins=kat_coins-? WHERE user_id=?",
                (coins_cost, interaction.user.id),
            )

        expires_at = (utcnow() + timedelta(days=duration_days)).isoformat()
        bounty_id = await bot.db.lastrowid(
            "INSERT INTO bounties (creator_id, target_name, reward, reason, duration, coins_paid, expires_at) VALUES (?,?,?,?,?,?,?)",
            (interaction.user.id, self.target_name.value, self.reward.value,
             self.reason.value, duration_days, coins_cost, expires_at),
        )

        embed = discord.Embed(title=f"🎯 Bounty #{bounty_id}", colour=discord.Colour.red())
        embed.add_field(name="🎯 Target",    value=self.target_name.value,      inline=False)
        embed.add_field(name="💰 Reward",    value=self.reward.value,            inline=False)
        embed.add_field(name="📅 Duration",  value=f"{duration_days} Days",     inline=False)
        embed.add_field(name="🪙 Cost",      value=f"{coins_cost} Coins",       inline=False)
        embed.add_field(name="📝 Reason",    value=self.reason.value,            inline=False)
        embed.add_field(name="📅 Created",   value="Today",                     inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        view = BountyView(bounty_id)
        ch = bot.get_channel(BOUNTY_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE bounties SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, bounty_id),
        )
        await interaction.response.send_message(f"✅ Bounty posted! (#{bounty_id})", ephemeral=True)


class BountyCog(commands.Cog, name="Bounty"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="post_bounty", description="Post a bounty on a player")
    async def post_bounty(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(BountyModal())


# ---------------------------------------------------------------------------
# Contract Cog
# ---------------------------------------------------------------------------

class ContractInterestedButton(discord.ui.Button):
    def __init__(self, contract_id: int) -> None:
        super().__init__(
            label="Interested",
            emoji="👀",
            style=discord.ButtonStyle.primary,
            custom_id=f"contract_interested:{contract_id}",
        )
        self.contract_id = contract_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        contract = await bot.db.fetchone("SELECT * FROM contracts WHERE id=?", (self.contract_id,))
        if not contract or contract["status"] != "active":
            await interaction.response.send_message("This contract is no longer active.", ephemeral=True)
            return
        creator = interaction.guild.get_member(contract["creator_id"]) if interaction.guild else None
        if creator:
            try:
                await creator.send(f"👀 **{interaction.user}** is interested in your contract **{contract['title']}** (#{self.contract_id})!")
            except discord.Forbidden:
                pass
        await interaction.response.send_message("✅ The contract creator has been notified!", ephemeral=True)


class ContractAcceptButton(discord.ui.Button):
    def __init__(self, contract_id: int) -> None:
        super().__init__(
            label="Accept Contract",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"contract_accept:{contract_id}",
        )
        self.contract_id = contract_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        contract = await bot.db.fetchone("SELECT * FROM contracts WHERE id=?", (self.contract_id,))
        if not contract or contract["status"] != "active":
            await interaction.response.send_message("This contract is no longer available.", ephemeral=True)
            return
        if interaction.user.id == contract["creator_id"]:
            await interaction.response.send_message("You cannot accept your own contract.", ephemeral=True)
            return
        await bot.db.execute(
            "UPDATE contracts SET status='accepted', accepted_by=? WHERE id=?",
            (interaction.user.id, self.contract_id),
        )
        creator = interaction.guild.get_member(contract["creator_id"]) if interaction.guild else None
        if creator:
            try:
                await creator.send(
                    f"✅ **{interaction.user}** has accepted your contract **{contract['title']}** (#{self.contract_id})!"
                )
            except discord.Forbidden:
                pass
        await interaction.response.send_message("✅ Contract accepted! The creator has been notified.", ephemeral=True)


class ContractView(discord.ui.View):
    def __init__(self, contract_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(ContractInterestedButton(contract_id))
        self.add_item(ContractAcceptButton(contract_id))


class ContractModal(discord.ui.Modal, title="Post a Contract"):
    title_input = discord.ui.TextInput(label="Contract Title",  placeholder="e.g. Security Contract",      max_length=100)
    reward      = discord.ui.TextInput(label="Reward",          placeholder="e.g. $5,000,000",             max_length=80)
    duration    = discord.ui.TextInput(label="Duration",        placeholder="e.g. 3 Days",                 max_length=40)
    description = discord.ui.TextInput(label="Description",     placeholder="Describe the contract terms…",
                                       style=discord.TextStyle.paragraph, max_length=800)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)

        contract_id = await bot.db.lastrowid(
            "INSERT INTO contracts (creator_id, title, reward, duration, description) VALUES (?,?,?,?,?)",
            (interaction.user.id, self.title_input.value, self.reward.value,
             self.duration.value, self.description.value),
        )

        embed = discord.Embed(title=f"📜 {self.title_input.value}", colour=discord.Colour.blurple())
        embed.add_field(name="💰 Reward",      value=self.reward.value,            inline=False)
        embed.add_field(name="📅 Duration",    value=self.duration.value,          inline=False)
        embed.add_field(name="📝 Description", value=self.description.value,       inline=False)
        embed.add_field(name="👤 Created By",  value=interaction.user.mention,     inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        view = ContractView(contract_id)
        ch = bot.get_channel(CONTRACT_CHANNEL_ID) or bot.get_channel(LISTINGS_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE contracts SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, contract_id),
        )
        await interaction.response.send_message(f"✅ Contract posted! (#{contract_id})", ephemeral=True)


class ContractCog(commands.Cog, name="Contracts"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="post_contract", description="Post a contract/job offer")
    async def post_contract(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ContractModal())


# ---------------------------------------------------------------------------
# Advertising Cog — rent, business ad, family promo
# ---------------------------------------------------------------------------

AD_DURATIONS = [
    discord.SelectOption(label="1 Day",   value="1",  emoji="📅"),
    discord.SelectOption(label="3 Days",  value="3",  emoji="📅"),
    discord.SelectOption(label="7 Days",  value="7",  emoji="📅"),
    discord.SelectOption(label="30 Days", value="30", emoji="📅"),
]

AD_TYPES = [
    discord.SelectOption(label="Housing — Looking for Roommate",     value="roommate",  emoji="🏠"),
    discord.SelectOption(label="Housing — Apartment/House for Rent", value="rental",    emoji="🏠"),
    discord.SelectOption(label="Personal — Looking for Partner",     value="partner",   emoji="👥"),
    discord.SelectOption(label="Personal — Looking for Property",    value="looking",   emoji="🔍"),
    discord.SelectOption(label="Business — Promote My Business",     value="business",  emoji="🏢"),
    discord.SelectOption(label="Family — Family Recruitment",        value="family",    emoji="👪"),
]

AD_EMOJI = {o.value: str(o.emoji) for o in AD_TYPES}


class AdInterestedButton(discord.ui.Button):
    def __init__(self, ad_id: int) -> None:
        super().__init__(
            label="Interested",
            emoji="👀",
            style=discord.ButtonStyle.primary,
            custom_id=f"ad_interested:{ad_id}",
        )
        self.ad_id = ad_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        ad = await bot.db.fetchone("SELECT * FROM advertisements WHERE id=?", (self.ad_id,))
        if not ad:
            await interaction.response.send_message("Ad not found.", ephemeral=True)
            return
        if interaction.user.id == ad["user_id"]:
            await interaction.response.send_message("You cannot show interest in your own ad.", ephemeral=True)
            return
        await bot.db.execute(
            "INSERT OR IGNORE INTO ad_interested (ad_id, user_id) VALUES (?,?)",
            (self.ad_id, interaction.user.id),
        )
        poster = interaction.guild.get_member(ad["user_id"]) if interaction.guild else None
        if poster:
            try:
                await poster.send(f"👀 **{interaction.user}** is interested in your advertisement (#{self.ad_id})!")
            except discord.Forbidden:
                pass
        await interaction.response.send_message("✅ The advertiser has been notified!", ephemeral=True)


class AdView(discord.ui.View):
    def __init__(self, ad_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(AdInterestedButton(ad_id))


class RentModal(discord.ui.Modal, title="Rent / Roommate Ad"):
    ad_title    = discord.ui.TextInput(label="Ad Title",          placeholder="e.g. Looking For Roommate",     max_length=100)
    location    = discord.ui.TextInput(label="Location",          placeholder="e.g. Apartment #50, Arzamas",   max_length=150)
    rent        = discord.ui.TextInput(label="Rent / Price",      placeholder="e.g. $150,000 Per Week",        max_length=100)
    extra_info  = discord.ui.TextInput(label="Extra Info (optional)", required=False,
                                       placeholder="e.g. Private Room Available",                              max_length=200)

    def __init__(self, ad_type: str, duration_days: int) -> None:
        super().__init__()
        self.ad_type       = ad_type
        self.duration_days = duration_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)

        emoji = AD_EMOJI.get(self.ad_type, "🏠")
        expires_at = (utcnow() + timedelta(days=self.duration_days)).isoformat()
        content = f"{self.ad_title.value}|{self.location.value}|{self.rent.value}|{self.extra_info.value}"
        ad_id = await bot.db.lastrowid(
            "INSERT INTO advertisements (user_id, ad_type, content, duration_days, expires_at) VALUES (?,?,?,?,?)",
            (interaction.user.id, self.ad_type, content, self.duration_days, expires_at),
        )

        embed = discord.Embed(title=f"{emoji} {self.ad_title.value}", colour=discord.Colour.teal())
        embed.add_field(name="📍 Location",   value=self.location.value,          inline=False)
        embed.add_field(name="💰 Rent",       value=self.rent.value,              inline=False)
        if self.extra_info.value:
            embed.add_field(name="🛏 Info",   value=self.extra_info.value,        inline=False)
        embed.add_field(name="📩 Contact",    value=interaction.user.mention,     inline=False)
        embed.add_field(name="📅 Expires",    value=f"{self.duration_days} Days", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        view = AdView(ad_id)
        ch = bot.get_channel(AD_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE advertisements SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, ad_id),
        )
        await interaction.response.send_message(f"✅ Ad posted! (#{ad_id})", ephemeral=True)


class BusinessAdModal(discord.ui.Modal, title="Business Advertisement"):
    biz_name    = discord.ui.TextInput(label="Business Name",    placeholder="e.g. Premium Motors",           max_length=100)
    location    = discord.ui.TextInput(label="Location",         placeholder="e.g. Arzamas",                  max_length=100)
    ad_text     = discord.ui.TextInput(label="Advertisement",    style=discord.TextStyle.paragraph,
                                       placeholder="Describe your business, offers, contact…",                max_length=800)

    def __init__(self, duration_days: int) -> None:
        super().__init__()
        self.duration_days = duration_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)

        expires_at = (utcnow() + timedelta(days=self.duration_days)).isoformat()
        content = f"{self.biz_name.value}|{self.location.value}|{self.ad_text.value}"
        ad_id = await bot.db.lastrowid(
            "INSERT INTO advertisements (user_id, ad_type, content, duration_days, expires_at) VALUES (?,?,?,?,?)",
            (interaction.user.id, "business", content, self.duration_days, expires_at),
        )

        embed = discord.Embed(title=f"🏢 {self.biz_name.value}", colour=discord.Colour.gold())
        embed.add_field(name="📍 Location",        value=self.location.value,          inline=False)
        embed.add_field(name="📢 Advertisement",   value=self.ad_text.value,           inline=False)
        embed.add_field(name="👤 Posted By",       value=interaction.user.mention,     inline=False)
        embed.add_field(name="📅 Expires",         value=f"{self.duration_days} Days", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        view = AdView(ad_id)
        ch = bot.get_channel(AD_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE advertisements SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, ad_id),
        )
        await interaction.response.send_message(f"✅ Business ad posted! (#{ad_id})", ephemeral=True)


class FamilyAdModal(discord.ui.Modal, title="Family Recruitment Ad"):
    family_name  = discord.ui.TextInput(label="Family Name",      placeholder="e.g. Shadow Family",     max_length=80)
    requirements = discord.ui.TextInput(label="Requirements",     style=discord.TextStyle.paragraph,
                                        placeholder="• Active Daily\n• Good RP\n• Loyal",               max_length=500)

    def __init__(self, duration_days: int) -> None:
        super().__init__()
        self.duration_days = duration_days

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)

        expires_at = (utcnow() + timedelta(days=self.duration_days)).isoformat()
        content = f"{self.family_name.value}|{self.requirements.value}"
        ad_id = await bot.db.lastrowid(
            "INSERT INTO advertisements (user_id, ad_type, content, duration_days, expires_at) VALUES (?,?,?,?,?)",
            (interaction.user.id, "family", content, self.duration_days, expires_at),
        )

        embed = discord.Embed(title=f"👨‍👩‍👧 {self.family_name.value}", colour=discord.Colour.from_rgb(255, 200, 100))
        embed.add_field(name="📢 Recruiting Active Members", value="\u200b", inline=False)
        embed.add_field(name="Requirements",                 value=self.requirements.value, inline=False)
        embed.add_field(name="📩 Contact",                   value=interaction.user.mention,     inline=False)
        embed.add_field(name="📅 Expires",                   value=f"{self.duration_days} Days", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()

        view = AdView(ad_id)
        ch = bot.get_channel(AD_CHANNEL_ID) or interaction.channel
        msg = await ch.send(embed=embed, view=view)
        await bot.db.execute(
            "UPDATE advertisements SET message_id=?, channel_id=? WHERE id=?",
            (msg.id, ch.id, ad_id),
        )
        await interaction.response.send_message(f"✅ Family ad posted! (#{ad_id})", ephemeral=True)


class AdTypeDropdown(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Select Ad Type…", options=AD_TYPES)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = AdDurationView(self.values[0])
        await interaction.response.edit_message(content="**Select duration:**", view=view)


class AdDurationDropdown(discord.ui.Select):
    def __init__(self, ad_type: str) -> None:
        super().__init__(placeholder="Select duration…", options=AD_DURATIONS)
        self.ad_type = ad_type

    async def callback(self, interaction: discord.Interaction) -> None:
        days = int(self.values[0])
        if self.ad_type == "business":
            await interaction.response.send_modal(BusinessAdModal(days))
        elif self.ad_type == "family":
            await interaction.response.send_modal(FamilyAdModal(days))
        else:
            await interaction.response.send_modal(RentModal(self.ad_type, days))


class AdDurationView(discord.ui.View):
    def __init__(self, ad_type: str) -> None:
        super().__init__(timeout=60)
        self.add_item(AdDurationDropdown(ad_type))


class RentChannelTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.add_item(AdTypeDropdown())


class AdvertisingCog(commands.Cog, name="Advertising"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="rent_channel", description="Post a housing, rental, or personal advertisement")
    async def rent_channel(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select your ad type:**", view=RentChannelTypeView(), ephemeral=True)

    @app_commands.command(name="promote_business", description="Promote your business")
    async def promote_business(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select promotion duration:**", view=AdDurationView("business"), ephemeral=True)

    @app_commands.command(name="promote_family", description="Post a family recruitment advertisement")
    async def promote_family(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("**Select promotion duration:**", view=AdDurationView("family"), ephemeral=True)

    @app_commands.command(name="ad_ledger", description="View your active advertisements")
    async def ad_ledger(self, interaction: discord.Interaction) -> None:
        ads = await self.bot.db.fetchall(
            "SELECT * FROM advertisements WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="📋 My Advertisements", colour=discord.Colour.teal())
        if not ads:
            embed.description = "You have no advertisements."
        for ad in ads:
            status_emoji = "🟢" if ad["status"] == "active" else "🔴"
            embed.add_field(
                name=f"{status_emoji} #{ad['id']} — {ad['ad_type'].capitalize()}",
                value=f"{ad['content'][:80]}… • {ad['duration_days']} day(s)",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Birthday Cog
# ---------------------------------------------------------------------------

BIRTHDAY_REWARDS = {
    "coins":  5,
    "cash":   500_000,
    "crates": 1,
}


class BirthdayCog(commands.Cog, name="Birthday"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot
        self._birthday_loop.start()

    def cog_unload(self) -> None:
        self._birthday_loop.cancel()

    # ── Background task ──────────────────────────────────────────────────────

    @tasks.loop(hours=24)
    async def _birthday_loop(self) -> None:
        now = utcnow()
        rows = await self.bot.db.fetchall(
            """SELECT * FROM birthdays
               WHERE status='approved'
               AND day=? AND month=?
               AND (last_rewarded IS NULL OR last_rewarded NOT LIKE ?)""",
            (now.day, now.month, f"{now.year}%"),
        )
        for row in rows:
            await self._celebrate(row, now)

    @_birthday_loop.before_loop
    async def _before_birthday_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ── Core reward logic ────────────────────────────────────────────────────

    async def _celebrate(self, row: dict, now: datetime) -> None:
        user_id = row["user_id"]
        await self.bot.ensure_user_by_id(user_id)

        await self.bot.db.execute(
            "UPDATE users SET kat_coins=kat_coins+?, game_cash=game_cash+? WHERE user_id=?",
            (BIRTHDAY_REWARDS["coins"], BIRTHDAY_REWARDS["cash"], user_id),
        )

        existing = await self.bot.db.fetchone(
            "SELECT id, count FROM crates WHERE user_id=?", (user_id,)
        )
        if existing:
            await self.bot.db.execute(
                "UPDATE crates SET count=count+? WHERE user_id=?",
                (BIRTHDAY_REWARDS["crates"], user_id),
            )
        else:
            await self.bot.db.execute(
                "INSERT INTO crates (user_id, count) VALUES (?,?)",
                (user_id, BIRTHDAY_REWARDS["crates"]),
            )

        await self.bot.db.execute(
            "UPDATE birthdays SET last_rewarded=? WHERE user_id=?",
            (now.isoformat(), user_id),
        )

        channel_id = BIRTHDAY_CHANNEL_ID or await self.bot.get_channel_id("birthday")
        ch = self.bot.get_channel(channel_id)
        if not ch:
            return

        member = None
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member:
                break

        if member:
            await self._assign_birthday_role(member)

        mention = member.mention if member else f"<@{user_id}>"
        embed = self._announcement_embed(mention)
        await ch.send(embed=embed)

        if member:
            try:
                await member.send(embed=self._rewards_embed())
            except discord.Forbidden:
                pass

        if member:
            self.bot.loop.call_later(
                86400,
                lambda: asyncio.ensure_future(self._remove_birthday_role(member)),
            )

    async def _assign_birthday_role(self, member: discord.Member) -> None:
        role = discord.utils.get(member.guild.roles, name=BIRTHDAY_ROLE_NAME)
        if role:
            try:
                await member.add_roles(role, reason="Birthday reward")
            except discord.Forbidden:
                pass

    async def _remove_birthday_role(self, member: discord.Member) -> None:
        role = discord.utils.get(member.guild.roles, name=BIRTHDAY_ROLE_NAME)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Birthday role expired (24h)")
            except discord.Forbidden:
                pass

    # ── Embeds ───────────────────────────────────────────────────────────────

    @staticmethod
    def _rewards_embed() -> discord.Embed:
        embed = discord.Embed(
            title="🎂 Birthday Rewards",
            colour=discord.Colour.from_rgb(255, 105, 180),
        )
        embed.add_field(
            name="Rewards",
            value=(
                f"🪙 {BIRTHDAY_REWARDS['coins']} KAT Coins\n"
                f"💵 ${BIRTHDAY_REWARDS['cash']:,} Game Cash\n"
                f"🎁 Birthday Crate\n"
                f"🎂 Birthday Role (24 Hours)"
            ),
            inline=False,
        )
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        return embed

    @staticmethod
    def _announcement_embed(mention: str) -> discord.Embed:
        embed = discord.Embed(
            title="🎉 Happy Birthday!",
            colour=discord.Colour.from_rgb(255, 215, 0),
        )
        embed.add_field(name="🎂",                  value=mention,              inline=False)
        embed.add_field(
            name="\u200b",
            value="The KAT Market Team wishes you a wonderful birthday!",
            inline=False,
        )
        embed.add_field(
            name="Rewards Received",
            value=(
                f"🪙 {BIRTHDAY_REWARDS['coins']} KAT Coins\n"
                f"💵 ${BIRTHDAY_REWARDS['cash']:,} Cash\n"
                f"🎁 Birthday Crate\n"
                f"🎂 Birthday Role (24 Hours)"
            ),
            inline=False,
        )
        embed.add_field(name="\u200b", value="Enjoy your special day! 🎉", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()
        return embed

    # ── Slash commands ───────────────────────────────────────────────────────

    @app_commands.command(name="birthday_register", description="Register your birthday")
    async def birthday_register(
        self,
        interaction: discord.Interaction,
        day: app_commands.Range[int, 1, 31],
        month: app_commands.Range[int, 1, 12],
        year: app_commands.Range[int, 1900, 2099],
    ) -> None:
        existing = await self.bot.db.fetchone(
            "SELECT * FROM birthdays WHERE user_id=?", (interaction.user.id,)
        )
        if existing:
            await interaction.response.send_message(
                f"🎂 Your birthday is already registered as **{existing['day']:02d}/{existing['month']:02d}/{existing['year']}** "
                f"(Status: `{existing['status']}`).",
                ephemeral=True,
            )
            return

        await self.bot.db.execute(
            "INSERT OR IGNORE INTO birthdays (user_id, username, day, month, year) VALUES (?,?,?,?,?)",
            (interaction.user.id, str(interaction.user), day, month, year),
        )
        await interaction.response.send_message(
            f"✅ Birthday registered as **{day:02d}/{month:02d}/{year}**!\n"
            "It will be reviewed by staff before rewards are activated.",
            ephemeral=True,
        )

    @app_commands.command(name="birthday_rewards", description="See what birthday rewards you'll receive")
    async def birthday_rewards_info(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=self._rewards_embed(), ephemeral=True)

    @app_commands.command(name="birthday_today", description="Check who has a birthday today")
    async def birthday_today(self, interaction: discord.Interaction) -> None:
        now = utcnow()
        rows = await self.bot.db.fetchall(
            "SELECT * FROM birthdays WHERE status='approved' AND day=? AND month=?",
            (now.day, now.month),
        )
        embed = discord.Embed(title="🎂 Birthdays Today", colour=discord.Colour.from_rgb(255, 215, 0))
        if not rows:
            embed.description = "No birthdays today."
        else:
            embed.description = "\n".join(f"🎉 <@{r['user_id']}> — {r['username']}" for r in rows)
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Notification Cog
# ---------------------------------------------------------------------------

class NotificationCog(commands.Cog, name="Notifications"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="notifications", description="View your marketplace notifications")
    async def notifications(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
            (interaction.user.id,),
        )
        unread = [r for r in rows if not r["is_read"]]
        embed = discord.Embed(
            title=f"🔔 Notifications ({len(unread)} unread)",
            colour=discord.Colour.blurple(),
        )
        if not rows:
            embed.description = "You have no notifications."
        else:
            type_emojis = {
                "interested":     "👀",
                "offer":          "💰",
                "offer_accepted": "✅",
                "offer_declined": "❌",
                "counter_offer":  "🔄",
                "price_drop":     "📉",
                "birthday":       "🎂",
                "staff_message":  "📢",
                "expired":        "⏰",
            }
            for r in rows[:15]:
                emoji  = type_emojis.get(r["type"], "🔔")
                status = "" if r["is_read"] else " 🆕"
                embed.add_field(
                    name=f"{emoji} {r['title']}{status}",
                    value=f"{r['content']}\n*{r['created_at'][:16]}*",
                    inline=False,
                )
        embed.set_footer(text="Use /clear_notifications to mark all as read")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        if unread:
            ids = tuple(r["id"] for r in unread)
            placeholders = ",".join("?" * len(ids))
            await self.bot.db.execute(
                f"UPDATE notifications SET is_read=1 WHERE id IN ({placeholders})", ids
            )

    @app_commands.command(name="clear_notifications", description="Mark all notifications as read")
    async def clear_notifications(self, interaction: discord.Interaction) -> None:
        await self.bot.db.execute(
            "UPDATE notifications SET is_read=1 WHERE user_id=?", (interaction.user.id,)
        )
        await interaction.response.send_message("✅ All notifications marked as read.", ephemeral=True)


# ---------------------------------------------------------------------------
# Broker Cog
# ---------------------------------------------------------------------------

class BrokerCog(commands.Cog, name="Brokers"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="apply_broker", description="Apply to become a KAT Market certified broker")
    async def apply_broker(self, interaction: discord.Interaction) -> None:
        existing = await self.bot.db.fetchone(
            "SELECT * FROM brokers WHERE user_id=?", (interaction.user.id,)
        )
        if existing:
            status_map = {"pending": "⏳ Pending review", "approved": "✅ Approved", "rejected": "❌ Rejected"}
            label = status_map.get(existing["status"], existing["status"])
            await interaction.response.send_message(
                f"📋 Your broker application status: **{label}**", ephemeral=True
            )
            return
        await self.bot.db.execute(
            "INSERT INTO brokers (user_id) VALUES (?)", (interaction.user.id,)
        )
        embed = discord.Embed(title="📋 Broker Application Submitted", colour=discord.Colour.teal())
        embed.add_field(name="👤 Applicant",     value=interaction.user.mention, inline=False)
        embed.add_field(name="📅 Applied",       value=utcnow().strftime("%d/%m/%Y"), inline=False)
        embed.add_field(
            name="ℹ️ What happens next?",
            value="Staff will review your application. Approved brokers can earn commissions on facilitated deals.",
            inline=False,
        )
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        ch = self.bot.get_channel(STAFF_LOG_CHANNEL_ID)
        if ch:
            notify = discord.Embed(title="📋 New Broker Application", colour=discord.Colour.teal())
            notify.add_field(name="👤 User", value=f"{interaction.user} ({interaction.user.id})", inline=False)
            await ch.send(embed=notify)

    @app_commands.command(name="broker_list", description="View all approved brokers")
    async def broker_list(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM brokers WHERE status='approved' ORDER BY deals_closed DESC LIMIT 20"
        )
        embed = discord.Embed(title="🤝 Certified KAT Market Brokers", colour=discord.Colour.teal())
        if not rows:
            embed.description = "No brokers approved yet."
        else:
            for r in rows:
                embed.add_field(
                    name=f"<@{r['user_id']}>",
                    value=f"💼 Deals Closed: **{r['deals_closed']}** | 💰 Commission: **{r['commission_rate']}%**",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Escrow Cog
# ---------------------------------------------------------------------------

class EscrowCog(commands.Cog, name="Escrow"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="create_escrow", description="Open an escrow for a marketplace deal")
    @app_commands.describe(
        listing_id="The listing ID for the deal",
        buyer="The buyer",
        amount="The agreed deal amount",
    )
    async def create_escrow(
        self,
        interaction: discord.Interaction,
        listing_id: int,
        buyer: discord.Member,
        amount: int,
    ) -> None:
        listing = await self.bot.db.fetchone("SELECT * FROM listings WHERE id=?", (listing_id,))
        if not listing or listing["seller_id"] != interaction.user.id:
            await interaction.response.send_message(
                "❌ Listing not found or you are not the seller.", ephemeral=True
            )
            return
        if buyer.id == interaction.user.id:
            await interaction.response.send_message("❌ Buyer cannot be yourself.", ephemeral=True)
            return
        escrow_id = await self.bot.db.lastrowid(
            "INSERT INTO escrows (listing_id, buyer_id, seller_id, amount) VALUES (?,?,?,?)",
            (listing_id, buyer.id, interaction.user.id, amount),
        )
        embed = discord.Embed(title="🔒 Escrow Created", colour=discord.Colour.teal())
        embed.add_field(name="🆔 Escrow ID",      value=str(escrow_id),          inline=True)
        embed.add_field(name="📦 Listing",        value=listing["title"],        inline=False)
        embed.add_field(name="💰 Amount",         value=f"${amount:,}",          inline=True)
        embed.add_field(name="🛒 Buyer",          value=buyer.mention,           inline=True)
        embed.add_field(name="🏪 Seller",         value=interaction.user.mention, inline=True)
        embed.add_field(
            name="ℹ️ Next Steps",
            value="Both parties must complete the trade. Staff will then use `/confirm_escrow` to release funds.",
            inline=False,
        )
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)
        ch = self.bot.get_channel(STAFF_LOG_CHANNEL_ID)
        if ch:
            await ch.send(
                f"🔒 **New Escrow #{escrow_id}** — Listing #{listing_id} | "
                f"${amount:,} | Seller: {interaction.user} | Buyer: {buyer}"
            )

    @app_commands.command(name="escrow_status", description="Check the status of an escrow")
    @app_commands.describe(escrow_id="The escrow ID to check")
    async def escrow_status(self, interaction: discord.Interaction, escrow_id: int) -> None:
        escrow = await self.bot.db.fetchone("SELECT * FROM escrows WHERE id=?", (escrow_id,))
        if not escrow:
            await interaction.response.send_message("❌ Escrow not found.", ephemeral=True)
            return
        if interaction.user.id not in (escrow["buyer_id"], escrow["seller_id"]):
            await interaction.response.send_message("❌ You are not part of this escrow.", ephemeral=True)
            return
        status_map = {
            "awaiting_deposit": "⏳ Awaiting Deposit",
            "in_progress":      "🔄 In Progress",
            "completed":        "✅ Completed",
            "disputed":         "⚠️ Disputed",
            "cancelled":        "❌ Cancelled",
        }
        embed = discord.Embed(title=f"🔒 Escrow #{escrow_id}", colour=discord.Colour.teal())
        embed.add_field(name="📊 Status",  value=status_map.get(escrow["status"], escrow["status"]), inline=False)
        embed.add_field(name="💰 Amount",  value=f"${escrow['amount']:,}",   inline=True)
        embed.add_field(name="🛒 Buyer",   value=f"<@{escrow['buyer_id']}>",  inline=True)
        embed.add_field(name="🏪 Seller",  value=f"<@{escrow['seller_id']}>", inline=True)
        if escrow["notes"]:
            embed.add_field(name="📝 Notes", value=escrow["notes"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="confirm_escrow", description="[Staff] Confirm escrow completion and release funds")
    @app_commands.describe(escrow_id="The escrow ID to confirm", notes="Optional notes")
    async def confirm_escrow(
        self, interaction: discord.Interaction, escrow_id: int, notes: Optional[str] = None
    ) -> None:
        escrow = await self.bot.db.fetchone("SELECT * FROM escrows WHERE id=?", (escrow_id,))
        if not escrow:
            await interaction.response.send_message("❌ Escrow not found.", ephemeral=True)
            return
        if escrow["status"] == "completed":
            await interaction.response.send_message("This escrow is already completed.", ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE escrows SET status='completed', staff_id=?, notes=?, updated_at=datetime('now') WHERE id=?",
            (interaction.user.id, notes, escrow_id),
        )
        await self.bot.db.execute(
            "INSERT INTO notifications (user_id, type, title, content, ref_id) VALUES (?,?,?,?,?)",
            (escrow["seller_id"], "escrow", "Escrow Completed",
             f"Escrow #{escrow_id} has been confirmed by staff.", escrow_id),
        )
        await interaction.response.send_message(
            f"✅ Escrow **#{escrow_id}** confirmed as completed.", ephemeral=True
        )
        await self.bot.log_staff(
            interaction.user.id, "confirm_escrow", "escrow", str(escrow_id), notes
        )


# ---------------------------------------------------------------------------
# Ownership Cog
# ---------------------------------------------------------------------------

class OwnershipCog(commands.Cog, name="Ownership"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    async def _show_history(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str, title: str
    ) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM ownership_history WHERE asset_type=? AND asset_ref=? ORDER BY acquired_at DESC LIMIT 15",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"📜 Ownership History — {title}",
            colour=discord.Colour.gold(),
        )
        if not rows:
            embed.description = "No ownership records found."
        else:
            for i, r in enumerate(rows, 1):
                released = r["released_at"][:10] if r["released_at"] else "Current"
                embed.add_field(
                    name=f"#{i} — <@{r['owner_id']}>",
                    value=(
                        f"💰 Paid: ${r['price']:,}\n"
                        f"📅 From: {r['acquired_at'][:10]} → {released}"
                    ),
                    inline=False,
                )
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="vehicle_history", description="View ownership history for a vehicle listing")
    @app_commands.describe(listing_id="The vehicle listing ID")
    async def vehicle_history(self, interaction: discord.Interaction, listing_id: int) -> None:
        listing = await self.bot.db.fetchone("SELECT title FROM listings WHERE id=? AND category='vehicle'", (listing_id,))
        title = listing["title"] if listing else f"Listing #{listing_id}"
        await self._show_history(interaction, "vehicle", str(listing_id), title)

    @app_commands.command(name="property_history", description="View ownership history for a property")
    @app_commands.describe(listing_id="The property listing ID")
    async def property_history(self, interaction: discord.Interaction, listing_id: int) -> None:
        listing = await self.bot.db.fetchone("SELECT title FROM listings WHERE id=? AND category='property'", (listing_id,))
        title = listing["title"] if listing else f"Property #{listing_id}"
        await self._show_history(interaction, "property", str(listing_id), title)

    @app_commands.command(name="business_history", description="View ownership history for a business listing")
    @app_commands.describe(listing_id="The business listing ID")
    async def business_history(self, interaction: discord.Interaction, listing_id: int) -> None:
        listing = await self.bot.db.fetchone("SELECT title FROM listings WHERE id=? AND category='business'", (listing_id,))
        title = listing["title"] if listing else f"Business #{listing_id}"
        await self._show_history(interaction, "business", str(listing_id), title)


# ---------------------------------------------------------------------------
# KAT Market App Cog  (/market hub)
# ---------------------------------------------------------------------------

class MarketHubView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)

    @discord.ui.button(label="Marketplace", emoji="🏪", style=discord.ButtonStyle.primary)
    async def marketplace(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(title="🏪 Marketplace", colour=discord.Colour.blue())
        embed.add_field(
            name="Listing Commands",
            value=(
                "`/sell_vehicle` — Post a vehicle\n"
                "`/sell_property` — Post a property\n"
                "`/sell_skin` — Post a skin\n"
                "`/sell_item` — Post an item\n"
                "`/sell_business` — Post a business\n"
                "`/my_listings` — View your active listings"
            ),
            inline=False,
        )
        embed.set_footer(text="Listings expire in 7 / 14 / 30 days depending on your choice.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Notifications", emoji="🔔", style=discord.ButtonStyle.secondary)
    async def notifications_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: KATBot = interaction.client  # type: ignore
        unread = await bot.db.fetchone(
            "SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND is_read=0", (interaction.user.id,)
        )
        count = unread["c"] if unread else 0
        embed = discord.Embed(title=f"🔔 Notifications — {count} Unread", colour=discord.Colour.blurple())
        embed.description = "Use `/notifications` to view all your notifications."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="My Listings", emoji="📋", style=discord.ButtonStyle.secondary)
    async def my_listings_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot: KATBot = interaction.client  # type: ignore
        rows = await bot.db.fetchall(
            "SELECT * FROM listings WHERE seller_id=? AND status='active' ORDER BY created_at DESC LIMIT 10",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="📋 My Active Listings", colour=discord.Colour.teal())
        if not rows:
            embed.description = "You have no active listings."
        else:
            for r in rows:
                expires = r["expires_at"][:10] if r.get("expires_at") else "N/A"
                embed.add_field(
                    name=f"#{r['id']} — {r['title']}",
                    value=f"💰 ${r['asking_price']:,} | 🏷 {r['listing_type']} | ⏰ Expires: {expires}",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Brokers", emoji="🤝", style=discord.ButtonStyle.secondary)
    async def brokers_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(title="🤝 Broker Services", colour=discord.Colour.teal())
        embed.add_field(
            name="What is a Broker?",
            value=(
                "Certified brokers help connect buyers and sellers, "
                "negotiate deals, and provide escrow services.\n\n"
                "Use `/apply_broker` to apply.\n"
                "Use `/broker_list` to view active brokers."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Support", emoji="🎫", style=discord.ButtonStyle.danger)
    async def support_btn(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        embed = discord.Embed(title="🎫 Support", colour=discord.Colour.red())
        embed.description = "Use `/support` to open a support ticket."
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MarketAppCog(commands.Cog, name="MarketApp"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="market", description="Open the KAT Market hub")
    async def market(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🏪 KAT Market",
            description=(
                "Welcome to **KAT Market** — your all-in-one roleplay marketplace.\n\n"
                "Use the buttons below to navigate."
            ),
            colour=discord.Colour.gold(),
        )
        embed.add_field(name="🏪 Marketplace", value="Browse & post listings",       inline=True)
        embed.add_field(name="🔔 Notifications", value="Offers, interests & alerts", inline=True)
        embed.add_field(name="📋 My Listings",  value="Manage your active posts",    inline=True)
        embed.add_field(name="🤝 Brokers",      value="Find certified brokers",      inline=True)
        embed.add_field(name="🎫 Support",      value="Open a support ticket",       inline=True)
        embed.set_footer(text="KAT Market | Roleplay Marketplace")
        embed.timestamp = utcnow()
        await interaction.response.send_message(embed=embed, view=MarketHubView(), ephemeral=True)

    @app_commands.command(name="my_listings", description="View your active marketplace listings")
    async def my_listings(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM listings WHERE seller_id=? AND status='active' ORDER BY created_at DESC LIMIT 10",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="📋 My Active Listings", colour=discord.Colour.teal())
        if not rows:
            embed.description = "You have no active listings."
        else:
            for r in rows:
                expires = r["expires_at"][:10] if r.get("expires_at") else "N/A"
                embed.add_field(
                    name=f"#{r['id']} — {r['title']}",
                    value=f"💰 ${r['asking_price']:,} | 🏷 {r['listing_type']} | ⏰ Expires: {expires}",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Support Ticket Cog
# ---------------------------------------------------------------------------

TICKET_CATEGORIES = [
    discord.SelectOption(label="Payment Issue",      value="payment",    emoji="💳"),
    discord.SelectOption(label="Marketplace Issue",  value="marketplace",emoji="🏪"),
    discord.SelectOption(label="Bug Report",         value="bug",        emoji="🐛"),
    discord.SelectOption(label="General Appeal",     value="appeal",     emoji="📢"),
    discord.SelectOption(label="Other",              value="other",      emoji="❓"),
]


class TicketModal(discord.ui.Modal, title="Open a Support Ticket"):
    subject     = discord.ui.TextInput(label="Subject",     placeholder="Brief description of your issue", max_length=120)
    description = discord.ui.TextInput(label="Description", placeholder="Describe your issue in detail",   max_length=1000, style=discord.TextStyle.paragraph)

    def __init__(self, category: str) -> None:
        super().__init__()
        self.category = category

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.ensure_user(interaction.user)
        ticket_id = await bot.db.lastrowid(
            "INSERT INTO tickets (user_id, category, subject, description) VALUES (?,?,?,?)",
            (interaction.user.id, self.category, self.subject.value, self.description.value),
        )
        embed = discord.Embed(title=f"🎫 Ticket #{ticket_id} — {self.subject.value}", colour=discord.Colour.orange())
        embed.add_field(name="📂 Category",    value=self.category.capitalize(),  inline=True)
        embed.add_field(name="👤 User",        value=interaction.user.mention,    inline=True)
        embed.add_field(name="📝 Description", value=self.description.value,      inline=False)
        embed.add_field(name="📊 Status",      value="🟠 Open",                   inline=True)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()
        await interaction.response.send_message(
            f"✅ Ticket **#{ticket_id}** submitted! Staff will respond shortly.", ephemeral=True
        )
        ch = bot.get_channel(STAFF_LOG_CHANNEL_ID)
        if ch:
            await ch.send(embed=embed)


class TicketCategorySelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(placeholder="Select ticket category…", options=TICKET_CATEGORIES)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TicketModal(self.values[0]))


class TicketCategoryView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.add_item(TicketCategorySelect())


class TicketCog(commands.Cog, name="Tickets"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    @app_commands.command(name="support", description="Open a support ticket")
    async def support(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "**Select your ticket category:**", view=TicketCategoryView(), ephemeral=True
        )

    @app_commands.command(name="my_tickets", description="View your open support tickets")
    async def my_tickets(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM tickets WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="🎫 My Support Tickets", colour=discord.Colour.orange())
        if not rows:
            embed.description = "You have no support tickets."
        else:
            status_map = {"open": "🟠", "in_progress": "🔵", "resolved": "✅", "closed": "⚫"}
            for r in rows:
                s = status_map.get(r["status"], "❓")
                embed.add_field(
                    name=f"{s} #{r['id']} — {r['subject']}",
                    value=f"📂 {r['category'].capitalize()} | 📅 {r['created_at'][:10]}",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Badge Cog
# ---------------------------------------------------------------------------

SEASONAL_BADGES: dict[str, dict] = {
    "first_listing":  {"name": "🏪 First Listing",      "desc": "Posted your first listing"},
    "deal_maker":     {"name": "🤝 Deal Maker",          "desc": "Completed 5 deals"},
    "top_seller":     {"name": "🥇 Top Seller",          "desc": "Completed 25 deals"},
    "offer_king":     {"name": "💰 Offer King",          "desc": "Made 10 offers"},
    "broker_elite":   {"name": "🎖 Broker Elite",        "desc": "Closed 10 brokered deals"},
    "birthday_star":  {"name": "🎂 Birthday Star",       "desc": "Had a birthday rewarded"},
    "community_hero": {"name": "🌟 Community Hero",      "desc": "Referred 5 new members"},
    "early_adopter":  {"name": "⚡ Early Adopter",       "desc": "Joined in the first month"},
}


class BadgeCog(commands.Cog, name="Badges"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    async def _get_user_badges(self, user_id: int) -> list[str]:
        earned: list[str] = []
        listings = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM listings WHERE seller_id=?", (user_id,)
        )
        sold = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM listings WHERE seller_id=? AND status='sold'", (user_id,)
        )
        offers = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM offers WHERE buyer_id=?", (user_id,)
        )
        birthday = await self.bot.db.fetchone(
            "SELECT last_rewarded FROM birthdays WHERE user_id=? AND status='approved'", (user_id,)
        )
        broker = await self.bot.db.fetchone(
            "SELECT deals_closed FROM brokers WHERE user_id=? AND status='approved'", (user_id,)
        )

        lc = listings["c"] if listings else 0
        sc = sold["c"] if sold else 0
        oc = offers["c"] if offers else 0

        if lc >= 1:  earned.append("first_listing")
        if sc >= 5:  earned.append("deal_maker")
        if sc >= 25: earned.append("top_seller")
        if oc >= 10: earned.append("offer_king")
        if birthday and birthday["last_rewarded"]: earned.append("birthday_star")
        if broker and broker["deals_closed"] >= 10: earned.append("broker_elite")
        return earned

    @app_commands.command(name="my_badges", description="View your KAT Market badges")
    async def my_badges(self, interaction: discord.Interaction) -> None:
        badge_keys = await self._get_user_badges(interaction.user.id)
        embed = discord.Embed(
            title=f"🏅 {interaction.user.display_name}'s Badges",
            colour=discord.Colour.gold(),
        )
        if not badge_keys:
            embed.description = "You haven't earned any badges yet. Keep listing & trading!"
        else:
            for key in badge_keys:
                info = SEASONAL_BADGES.get(key)
                if info:
                    embed.add_field(name=info["name"], value=info["desc"], inline=False)
        embed.set_footer(text=f"{len(badge_keys)}/{len(SEASONAL_BADGES)} badges earned")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="check_badges", description="View another player's badges")
    @app_commands.describe(member="The player to check")
    async def check_badges(self, interaction: discord.Interaction, member: discord.Member) -> None:
        badge_keys = await self._get_user_badges(member.id)
        embed = discord.Embed(
            title=f"🏅 {member.display_name}'s Badges",
            colour=discord.Colour.gold(),
        )
        if not badge_keys:
            embed.description = "This player hasn't earned any badges yet."
        else:
            for key in badge_keys:
                info = SEASONAL_BADGES.get(key)
                if info:
                    embed.add_field(name=info["name"], value=info["desc"], inline=False)
        embed.set_footer(text=f"{len(badge_keys)}/{len(SEASONAL_BADGES)} badges earned")
        await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# Listing Management Cog  (expiry background task)
# ---------------------------------------------------------------------------

class ListingRenewButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(label="Renew 7 Days", emoji="🔄", style=discord.ButtonStyle.success,
                         custom_id=f"listing_renew:{listing_id}")
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        new_expiry = (utcnow() + timedelta(days=7)).isoformat()
        await bot.db.execute(
            "UPDATE listings SET status='active', expires_at=?, updated_at=datetime('now') WHERE id=?",
            (new_expiry, self.listing_id),
        )
        await interaction.response.edit_message(
            content=f"✅ Listing **#{self.listing_id}** renewed for 7 days!", view=None
        )


class ListingArchiveButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(label="Archive", emoji="📦", style=discord.ButtonStyle.secondary,
                         custom_id=f"listing_archive:{listing_id}")
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.db.execute(
            "UPDATE listings SET status='archived', updated_at=datetime('now') WHERE id=?",
            (self.listing_id,),
        )
        await interaction.response.edit_message(
            content=f"📦 Listing **#{self.listing_id}** archived.", view=None
        )


class ListingDeleteButton(discord.ui.Button):
    def __init__(self, listing_id: int) -> None:
        super().__init__(label="Delete", emoji="🗑️", style=discord.ButtonStyle.danger,
                         custom_id=f"listing_delete:{listing_id}")
        self.listing_id = listing_id

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: KATBot = interaction.client  # type: ignore
        await bot.db.execute(
            "UPDATE listings SET status='deleted', updated_at=datetime('now') WHERE id=?",
            (self.listing_id,),
        )
        await interaction.response.edit_message(
            content=f"🗑️ Listing **#{self.listing_id}** deleted.", view=None
        )


class ExpiryActionView(discord.ui.View):
    def __init__(self, listing_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(ListingRenewButton(listing_id))
        self.add_item(ListingArchiveButton(listing_id))
        self.add_item(ListingDeleteButton(listing_id))


class ListingManagementCog(commands.Cog, name="ListingManagement"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot
        self._expiry_loop.start()

    def cog_unload(self) -> None:
        self._expiry_loop.cancel()

    @tasks.loop(hours=1)
    async def _expiry_loop(self) -> None:
        now_iso = utcnow().isoformat()
        expired = await self.bot.db.fetchall(
            "SELECT * FROM listings WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= ?",
            (now_iso,),
        )
        for listing in expired:
            await self.bot.db.execute(
                "UPDATE listings SET status='expired', updated_at=datetime('now') WHERE id=?",
                (listing["id"],),
            )
            if listing["message_id"] and listing["channel_id"]:
                ch = self.bot.get_channel(listing["channel_id"])
                if ch:
                    try:
                        msg = await ch.fetch_message(listing["message_id"])
                        if msg.embeds:
                            exp_embed = msg.embeds[0].copy()
                            exp_embed.colour = discord.Colour.dark_grey()
                            exp_embed.set_footer(text=f"⏰ EXPIRED — Listing #{listing['id']}")
                            await msg.edit(embed=exp_embed, view=None)
                    except Exception as e:
                        logger.warning("Could not update expired listing #%s: %s", listing["id"], e)
            await self.bot.db.execute(
                "INSERT INTO notifications (user_id, type, title, content, ref_id) VALUES (?,?,?,?,?)",
                (listing["seller_id"], "expired", "Listing Expired",
                 f"Your listing **{listing['title']}** has expired. Renew, archive, or delete it.",
                 listing["id"]),
            )
            seller = None
            for guild in self.bot.guilds:
                seller = guild.get_member(listing["seller_id"])
                if seller:
                    break
            if seller:
                embed = discord.Embed(title="⏰ Listing Expired", colour=discord.Colour.dark_grey())
                embed.add_field(name="📦 Listing", value=listing["title"], inline=False)
                embed.add_field(name="🆔 ID",      value=str(listing["id"]), inline=True)
                embed.add_field(
                    name="ℹ️ What would you like to do?",
                    value="Choose below to **Renew** (7 more days), **Archive**, or **Delete** this listing.",
                    inline=False,
                )
                try:
                    await seller.send(embed=embed, view=ExpiryActionView(listing["id"]))
                except discord.Forbidden:
                    pass
            logger.info("Listing #%s expired (seller %s)", listing["id"], listing["seller_id"])

    @_expiry_loop.before_loop
    async def _before_expiry_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ── Relist command ────────────────────────────────────────────────────────

    @app_commands.command(name="relist", description="Repost an expired, unsold, or archived listing")
    async def relist(self, interaction: discord.Interaction) -> None:
        now_iso = utcnow().isoformat()
        rows = await self.bot.db.fetchall(
            """SELECT * FROM listings
               WHERE seller_id=?
               AND (
                   status IN ('expired', 'relisted', 'archived', 'unsold')
                   OR (status='active' AND expires_at IS NOT NULL AND expires_at <= ?)
               )
               ORDER BY created_at DESC LIMIT 25""",
            (interaction.user.id, now_iso),
        )
        if not rows:
            await interaction.response.send_message(
                "✅ You have no expired or unsold listings to relist.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="🔄 Your Eligible Listings",
            description=f"**{len(rows)}** listing(s) available to relist — select one below.",
            colour=discord.Colour.orange(),
        )
        for r in rows[:5]:
            status_icon = {"expired": "⌛", "relisted": "🔄", "archived": "📦"}.get(r["status"], "📋")
            embed.add_field(
                name=f"#{r['id']} {r['title'][:50]}",
                value=f"{status_icon} {r['status'].capitalize()} · 💰 ${r['asking_price']:,}",
                inline=False,
            )
        if len(rows) > 5:
            embed.set_footer(text=f"…and {len(rows) - 5} more in the dropdown ━━━━━━━━━━━━━━━━━━")
        else:
            embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        view = RelistSelectView(rows)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ---------------------------------------------------------------------------
# Database Improvements Cog
# (Notes, Aliases, GPS/Location, Image Archive, Value History,
#  Verified Records, Blacklist, Database Statistics)
# ---------------------------------------------------------------------------

ASSET_TYPES = ["house", "apartment", "business", "vehicle", "skin", "item"]
ASSET_TYPE_CHOICES = [app_commands.Choice(name=t.capitalize(), value=t) for t in ASSET_TYPES]


def _asset_header(asset_type: str, asset_ref: str) -> str:
    icons = {"house": "🏠", "apartment": "🏢", "business": "🏪",
             "vehicle": "🚗", "skin": "🎨", "item": "📦"}
    return f"{icons.get(asset_type, '📁')} {asset_type.capitalize()} — {asset_ref}"


class DatabaseCog(commands.Cog, name="Database"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot

    # ── Notes ────────────────────────────────────────────────────────────────

    @app_commands.command(name="add_note", description="Attach a note to any asset")
    @app_commands.describe(
        asset_type="Type of asset",
        asset_ref="Reference (e.g. House #20, Listing ID, business name)",
        note="The note to attach",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def add_note(
        self,
        interaction: discord.Interaction,
        asset_type: str,
        asset_ref: str,
        note: str,
    ) -> None:
        await self.bot.db.execute(
            "INSERT INTO asset_notes (asset_type, asset_ref, note, added_by) VALUES (?,?,?,?)",
            (asset_type, asset_ref, note, interaction.user.id),
        )
        embed = discord.Embed(title="📝 Note Added", colour=discord.Colour.teal())
        embed.add_field(name="📁 Asset",  value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="📝 Note",   value=note,                                 inline=False)
        embed.add_field(name="👤 Added",  value=interaction.user.mention,             inline=True)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="view_notes", description="View all notes for an asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def view_notes(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM asset_notes WHERE asset_type=? AND asset_ref=? ORDER BY created_at DESC",
            (asset_type, asset_ref),
        )
        record = await self.bot.db.fetchone(
            "SELECT is_verified, is_blacklisted, blacklist_reason FROM asset_records WHERE asset_type=? AND asset_ref=?",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"📝 Notes — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.teal(),
        )
        if record:
            flags = []
            if record["is_verified"]:    flags.append("✅ Verified")
            if record["is_blacklisted"]: flags.append(f"🚫 Blacklisted: {record['blacklist_reason'] or 'No reason'}")
            if flags:
                embed.add_field(name="🏷 Flags", value=" | ".join(flags), inline=False)
        if not rows:
            embed.description = "No notes found for this asset."
        else:
            for r in rows:
                embed.add_field(
                    name=f"• <@{r['added_by']}> — {r['created_at'][:10]}",
                    value=r["note"],
                    inline=False,
                )
        embed.set_footer(text=f"{len(rows)} note(s) ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="delete_note", description="Delete a note by its ID")
    @app_commands.describe(note_id="The note ID to delete")
    async def delete_note(self, interaction: discord.Interaction, note_id: int) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM asset_notes WHERE id=?", (note_id,))
        if not row:
            await interaction.response.send_message("❌ Note not found.", ephemeral=True)
            return
        if row["added_by"] != interaction.user.id:
            perms = interaction.user.guild_permissions if interaction.guild else None
            if not (perms and perms.manage_guild):
                await interaction.response.send_message(
                    "❌ You can only delete your own notes (or be staff).", ephemeral=True
                )
                return
        await self.bot.db.execute("DELETE FROM asset_notes WHERE id=?", (note_id,))
        await interaction.response.send_message(f"✅ Note **#{note_id}** deleted.", ephemeral=True)

    # ── Alias System ─────────────────────────────────────────────────────────

    @app_commands.command(name="add_alias", description="Add an alternative name for an asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier", alias="Alternative name")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def add_alias(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str, alias: str
    ) -> None:
        try:
            await self.bot.db.execute(
                "INSERT INTO asset_aliases (asset_type, asset_ref, alias, added_by) VALUES (?,?,?,?)",
                (asset_type, asset_ref, alias, interaction.user.id),
            )
        except Exception:
            await interaction.response.send_message(
                f"❌ The alias **{alias}** already exists for this asset.", ephemeral=True
            )
            return
        embed = discord.Embed(title="🏷 Alias Added", colour=discord.Colour.teal())
        embed.add_field(name="📁 Asset", value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="🏷 Alias", value=alias,                                inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="search_alias", description="Search for assets by alias or name")
    @app_commands.describe(query="Name or alias to search for")
    async def search_alias(self, interaction: discord.Interaction, query: str) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT DISTINCT asset_type, asset_ref, alias FROM asset_aliases "
            "WHERE alias LIKE ? OR asset_ref LIKE ? LIMIT 15",
            (f"%{query}%", f"%{query}%"),
        )
        embed = discord.Embed(
            title=f'🔍 Alias Search — "{query}"',
            colour=discord.Colour.blue(),
        )
        if not rows:
            embed.description = "No results found."
        else:
            seen: set = set()
            for r in rows:
                key = (r["asset_type"], r["asset_ref"])
                if key in seen:
                    continue
                seen.add(key)
                aliases_for = await self.bot.db.fetchall(
                    "SELECT alias FROM asset_aliases WHERE asset_type=? AND asset_ref=?",
                    (r["asset_type"], r["asset_ref"]),
                )
                alias_list = ", ".join(a["alias"] for a in aliases_for)
                embed.add_field(
                    name=_asset_header(r["asset_type"], r["asset_ref"]),
                    value=f"Aliases: {alias_list}",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed)

    # ── GPS / Location ────────────────────────────────────────────────────────

    @app_commands.command(name="set_location", description="Set GPS coordinates and location for an asset")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        location="Location name (e.g. Elite Village)",
        coord_x="X coordinate", coord_y="Y coordinate",
        map_link="Optional map/image link",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def set_location(
        self,
        interaction: discord.Interaction,
        asset_type: str,
        asset_ref: str,
        location: str,
        coord_x: int,
        coord_y: int,
        map_link: Optional[str] = None,
    ) -> None:
        await self.bot.db.execute(
            """INSERT INTO asset_locations (asset_type, asset_ref, location, coord_x, coord_y, map_link, updated_by)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(asset_type, asset_ref) DO UPDATE SET
                   location=excluded.location, coord_x=excluded.coord_x,
                   coord_y=excluded.coord_y, map_link=excluded.map_link,
                   updated_by=excluded.updated_by, updated_at=datetime('now')""",
            (asset_type, asset_ref, location, coord_x, coord_y, map_link, interaction.user.id),
        )
        embed = discord.Embed(title="📍 Location Set", colour=discord.Colour.green())
        embed.add_field(name="📁 Asset",    value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="📍 Location", value=location,  inline=True)
        embed.add_field(name="🗺 X",        value=str(coord_x), inline=True)
        embed.add_field(name="🗺 Y",        value=str(coord_y), inline=True)
        if map_link:
            embed.add_field(name="🔗 Map Link", value=map_link, inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="location_info", description="View GPS coordinates and location of an asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def location_info(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        row = await self.bot.db.fetchone(
            "SELECT * FROM asset_locations WHERE asset_type=? AND asset_ref=?",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"📍 Location — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.green(),
        )
        if not row:
            embed.description = "No location data found for this asset."
        else:
            embed.add_field(name="📍 Location", value=row["location"] or "N/A", inline=False)
            embed.add_field(name="🗺 X",         value=str(row["coord_x"]) if row["coord_x"] is not None else "N/A", inline=True)
            embed.add_field(name="🗺 Y",         value=str(row["coord_y"]) if row["coord_y"] is not None else "N/A", inline=True)
            if row["map_link"]:
                embed.add_field(name="🔗 Map Link", value=row["map_link"], inline=False)
            embed.add_field(name="🕒 Updated", value=row["updated_at"][:10], inline=True)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)

    # ── Image Archive ─────────────────────────────────────────────────────────

    @app_commands.command(name="add_image", description="Add an official image to the asset archive")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        image_url="Direct image URL", label="Optional label (e.g. 'Interior', 'Exterior')",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def add_image(
        self,
        interaction: discord.Interaction,
        asset_type: str,
        asset_ref: str,
        image_url: str,
        label: Optional[str] = None,
    ) -> None:
        await self.bot.db.execute(
            "INSERT INTO asset_images (asset_type, asset_ref, image_url, label, added_by) VALUES (?,?,?,?,?)",
            (asset_type, asset_ref, image_url, label, interaction.user.id),
        )
        embed = discord.Embed(
            title=f"📸 Image Archived — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.teal(),
        )
        if label:
            embed.add_field(name="🏷 Label", value=label, inline=True)
        embed.set_image(url=image_url)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="view_images", description="View archived images for an asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def view_images(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM asset_images WHERE asset_type=? AND asset_ref=? ORDER BY created_at DESC LIMIT 10",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"📸 Image Archive — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.teal(),
        )
        if not rows:
            embed.description = "No archived images for this asset."
        else:
            for r in rows:
                label = r["label"] or "Image"
                embed.add_field(
                    name=f"📷 {label}",
                    value=f"[View Image]({r['image_url']}) — Added by <@{r['added_by']}> on {r['created_at'][:10]}",
                    inline=False,
                )
            embed.set_image(url=rows[0]["image_url"])
        embed.set_footer(text=f"{len(rows)} image(s) archived ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)

    # ── Value History ─────────────────────────────────────────────────────────

    @app_commands.command(name="add_value", description="Record an asset's market value for a given year")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        value="Market value in $", year="Year (e.g. 2025)", note="Optional note",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def add_value(
        self,
        interaction: discord.Interaction,
        asset_type: str,
        asset_ref: str,
        value: int,
        year: app_commands.Range[int, 2020, 2099],
        note: Optional[str] = None,
    ) -> None:
        try:
            await self.bot.db.execute(
                """INSERT INTO asset_value_history (asset_type, asset_ref, value, year, note, added_by)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(asset_type, asset_ref, year) DO UPDATE SET
                       value=excluded.value, note=excluded.note""",
                (asset_type, asset_ref, value, year, note, interaction.user.id),
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
            return
        embed = discord.Embed(title="📊 Value Recorded", colour=discord.Colour.gold())
        embed.add_field(name="📁 Asset",    value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="📅 Year",     value=str(year),         inline=True)
        embed.add_field(name="💰 Value",    value=f"${value:,}",     inline=True)
        if note:
            embed.add_field(name="📝 Note", value=note,              inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="value_history", description="View the value history of an asset over time")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def value_history(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM asset_value_history WHERE asset_type=? AND asset_ref=? ORDER BY year ASC",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"📊 Value History — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.gold(),
        )
        if not rows:
            embed.description = "No value records found for this asset."
        else:
            lines = []
            for i, r in enumerate(rows):
                arrow = "↕" if i < len(rows) - 1 else "📍"
                change = ""
                if i > 0:
                    diff = r["value"] - rows[i - 1]["value"]
                    sign = "+" if diff >= 0 else ""
                    change = f" ({sign}${diff:,})"
                lines.append(f"**{r['year']}**: ${r['value']:,}{change}")
                if r["note"]:
                    lines.append(f"  ↳ _{r['note']}_")
            embed.description = "\n".join(lines)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)

    # ── Verified Records ──────────────────────────────────────────────────────

    @app_commands.command(name="verify_record", description="Mark an asset as verified by staff")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def verify_record(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        await self.bot.db.execute(
            """INSERT INTO asset_records (asset_type, asset_ref, is_verified, verified_by, updated_at)
               VALUES (?,?,1,?,datetime('now'))
               ON CONFLICT(asset_type, asset_ref) DO UPDATE SET
                   is_verified=1, verified_by=excluded.verified_by, updated_at=datetime('now')""",
            (asset_type, asset_ref, interaction.user.id),
        )
        embed = discord.Embed(title="✅ Record Verified", colour=discord.Colour.green())
        embed.add_field(name="📁 Asset",     value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="✅ Verified",  value="Yes",                                inline=True)
        embed.add_field(name="👤 By",        value=interaction.user.mention,             inline=True)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)
        await self.bot.log_staff(interaction.user.id, "verify_record", asset_type, asset_ref)

    # ── Blacklist ─────────────────────────────────────────────────────────────

    @app_commands.command(name="blacklist_record", description="Flag an asset as blacklisted")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        reason="Reason for blacklisting",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def blacklist_record(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str, reason: str
    ) -> None:
        await self.bot.db.execute(
            """INSERT INTO asset_records (asset_type, asset_ref, is_blacklisted, blacklist_reason, blacklisted_by, updated_at)
               VALUES (?,?,1,?,?,datetime('now'))
               ON CONFLICT(asset_type, asset_ref) DO UPDATE SET
                   is_blacklisted=1, blacklist_reason=excluded.blacklist_reason,
                   blacklisted_by=excluded.blacklisted_by, updated_at=datetime('now')""",
            (asset_type, asset_ref, reason, interaction.user.id),
        )
        embed = discord.Embed(title="🚫 Record Blacklisted", colour=discord.Colour.red())
        embed.add_field(name="📁 Asset",    value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="🚫 Status",   value="Blacklisted",                        inline=True)
        embed.add_field(name="👤 By",       value=interaction.user.mention,             inline=True)
        embed.add_field(name="📝 Reason",   value=reason,                               inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)
        await self.bot.log_staff(interaction.user.id, "blacklist_record", asset_type, asset_ref, reason)
        ch = self.bot.get_channel(STAFF_LOG_CHANNEL_ID)
        if ch:
            await ch.send(embed=embed)

    @app_commands.command(name="unblacklist_record", description="Remove the blacklist flag from an asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def unblacklist_record(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        await self.bot.db.execute(
            """INSERT INTO asset_records (asset_type, asset_ref, is_blacklisted, updated_at)
               VALUES (?,?,0,datetime('now'))
               ON CONFLICT(asset_type, asset_ref) DO UPDATE SET
                   is_blacklisted=0, blacklist_reason=NULL,
                   blacklisted_by=NULL, updated_at=datetime('now')""",
            (asset_type, asset_ref),
        )
        await interaction.response.send_message(
            f"✅ Blacklist removed from **{_asset_header(asset_type, asset_ref)}**.", ephemeral=True
        )
        await self.bot.log_staff(interaction.user.id, "unblacklist_record", asset_type, asset_ref)

    # ── Ownership History (unified) ───────────────────────────────────────────

    @app_commands.command(name="ownership_history", description="View the full ownership chain for any asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Listing ID or reference")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def ownership_history(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM ownership_history WHERE asset_type=? AND asset_ref=? ORDER BY acquired_at ASC",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"📜 Ownership Chain — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.gold(),
        )
        if not rows:
            embed.description = "No ownership records found."
        else:
            chain = []
            for i, r in enumerate(rows):
                released = r["released_at"][:10] if r["released_at"] else "Present"
                arrow = "\n↓" if i < len(rows) - 1 else ""
                chain.append(
                    f"**<@{r['owner_id']}>**\n"
                    f"💰 ${r['price']:,} | 📅 {r['acquired_at'][:10]} → {released}{arrow}"
                )
            embed.description = "\n".join(chain)
        embed.set_footer(text=f"{len(rows)} owner(s) ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)

    # ── Database Statistics ───────────────────────────────────────────────────

    @app_commands.command(name="database_stats", description="View KAT Market database statistics")
    async def database_stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        stats: dict[str, int] = {}
        for table in ("houses", "apartments", "businesses"):
            row = await self.bot.db.fetchone(f"SELECT COUNT(*) as c FROM {table}")
            stats[table] = row["c"] if row else 0

        listing_counts = await self.bot.db.fetchall(
            "SELECT category, COUNT(*) as c FROM listings GROUP BY category"
        )
        lc = {r["category"]: r["c"] for r in listing_counts}

        active_listings = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM listings WHERE status='active'"
        )
        sold_listings = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM listings WHERE status='sold'"
        )
        total_users = await self.bot.db.fetchone("SELECT COUNT(*) as c FROM users")
        total_offers = await self.bot.db.fetchone("SELECT COUNT(*) as c FROM offers")
        total_escrows = await self.bot.db.fetchone("SELECT COUNT(*) as c FROM escrows")
        total_verified = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM asset_records WHERE is_verified=1"
        )
        total_blacklisted = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM asset_records WHERE is_blacklisted=1"
        )

        embed = discord.Embed(
            title="📊 KAT Market — Database Statistics",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="🏗 Static Assets",
            value=(
                f"🏠 Houses: **{stats['houses']:,}**\n"
                f"🏢 Apartments: **{stats['apartments']:,}**\n"
                f"🏪 Businesses: **{stats['businesses']:,}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="📦 Active Listings by Category",
            value=(
                f"🚗 Vehicles: **{lc.get('vehicle', 0):,}**\n"
                f"🏠 Properties: **{lc.get('property', 0):,}**\n"
                f"🏢 Businesses: **{lc.get('business', 0):,}**\n"
                f"🎨 Skins: **{lc.get('skin', 0):,}**\n"
                f"📦 Items: **{lc.get('item', 0):,}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="📈 Marketplace Activity",
            value=(
                f"✅ Active Listings: **{active_listings['c']:,}**\n"
                f"🏷 Total Sold: **{sold_listings['c']:,}**\n"
                f"💰 Total Offers: **{total_offers['c']:,}**\n"
                f"🔒 Escrows: **{total_escrows['c']:,}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="👥 Community",
            value=(
                f"👤 Registered Users: **{total_users['c']:,}**\n"
                f"✅ Verified Assets: **{total_verified['c']:,}**\n"
                f"🚫 Blacklisted Assets: **{total_blacklisted['c']:,}**"
            ),
            inline=True,
        )
        embed.set_footer(text=f"KAT Market Database ━━━━━━━━━━━━━━━━━━")
        embed.timestamp = utcnow()
        await interaction.followup.send(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Advanced Database Features Cog
# (Flags, Archive, Change Log, Global Search, Tags, Favorites,
#  Last Seen, Demand Score, Database Alerts, Merge Records)
# ---------------------------------------------------------------------------

FLAG_TYPES = ["duplicate", "suspicious", "needs_update", "inactive"]
FLAG_CHOICES = [app_commands.Choice(name=f.replace("_", " ").title(), value=f) for f in FLAG_TYPES]
FLAG_EMOJIS = {
    "duplicate":   "⚠️ Duplicate",
    "suspicious":  "⚠️ Suspicious",
    "needs_update":"⚠️ Needs Update",
    "inactive":    "⚠️ Inactive",
}

PRESET_TAGS = ["Luxury", "Rare", "Verified", "High Profit", "Starter Property",
               "Prime Location", "Investment", "Staff Pick", "Popular", "Discounted"]


def _log_change(bot: "KATBot", asset_type: str, asset_ref: str,
                action: str, changed_by: int, old_value: Optional[str] = None,
                new_value: Optional[str] = None):
    """Fire-and-forget change log helper (returns coroutine — must be awaited)."""
    return bot.db.execute(
        "INSERT INTO asset_change_log (asset_type, asset_ref, action, changed_by, old_value, new_value) "
        "VALUES (?,?,?,?,?,?)",
        (asset_type, asset_ref, action, changed_by, old_value, new_value),
    )


class AdvancedDatabaseCog(commands.Cog, name="AdvancedDatabase"):
    def __init__(self, bot: "KATBot") -> None:
        self.bot = bot
        self._alert_loop.start()

    def cog_unload(self) -> None:
        self._alert_loop.cancel()

    # ── Flag Record ──────────────────────────────────────────────────────────

    @app_commands.command(name="flag_record", description="Flag an asset record for staff review")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        flag_type="Type of flag", reason="Optional reason",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES, flag_type=FLAG_CHOICES)
    async def flag_record(
        self, interaction: discord.Interaction,
        asset_type: str, asset_ref: str, flag_type: str,
        reason: Optional[str] = None,
    ) -> None:
        await self.bot.db.execute(
            "INSERT INTO asset_flags (asset_type, asset_ref, flag_type, reason, flagged_by) VALUES (?,?,?,?,?)",
            (asset_type, asset_ref, flag_type, reason, interaction.user.id),
        )
        await _log_change(self.bot, asset_type, asset_ref, f"flag:{flag_type}",
                          interaction.user.id, new_value=reason)
        embed = discord.Embed(title="🚩 Record Flagged", colour=discord.Colour.yellow())
        embed.add_field(name="📁 Asset",   value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="🚩 Flag",    value=FLAG_EMOJIS.get(flag_type, flag_type), inline=True)
        embed.add_field(name="👤 By",      value=interaction.user.mention,              inline=True)
        if reason:
            embed.add_field(name="📝 Reason", value=reason, inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        ch = self.bot.get_channel(STAFF_LOG_CHANNEL_ID)
        if ch:
            await ch.send(embed=embed)

    @app_commands.command(name="view_flags", description="View all flags on an asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def view_flags(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM asset_flags WHERE asset_type=? AND asset_ref=? ORDER BY created_at DESC",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"🚩 Flags — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.yellow(),
        )
        open_flags   = [r for r in rows if not r["resolved"]]
        closed_flags = [r for r in rows if r["resolved"]]
        if not rows:
            embed.description = "No flags found."
        else:
            for r in open_flags:
                embed.add_field(
                    name=f"🔴 {FLAG_EMOJIS.get(r['flag_type'], r['flag_type'])}",
                    value=f"By <@{r['flagged_by']}> | {r['created_at'][:10]}"
                          + (f"\n📝 {r['reason']}" if r["reason"] else ""),
                    inline=False,
                )
            if closed_flags:
                embed.add_field(
                    name=f"✅ {len(closed_flags)} resolved flag(s)",
                    value="\n".join(
                        f"{FLAG_EMOJIS.get(r['flag_type'], r['flag_type'])} — {r['created_at'][:10]}"
                        for r in closed_flags
                    ),
                    inline=False,
                )
        embed.set_footer(text=f"{len(open_flags)} open | {len(closed_flags)} resolved ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="resolve_flag", description="Mark a flag as resolved")
    @app_commands.describe(flag_id="The flag ID to resolve")
    async def resolve_flag(self, interaction: discord.Interaction, flag_id: int) -> None:
        row = await self.bot.db.fetchone("SELECT * FROM asset_flags WHERE id=?", (flag_id,))
        if not row:
            await interaction.response.send_message("❌ Flag not found.", ephemeral=True)
            return
        await self.bot.db.execute(
            "UPDATE asset_flags SET resolved=1, resolved_by=? WHERE id=?",
            (interaction.user.id, flag_id),
        )
        await _log_change(self.bot, row["asset_type"], row["asset_ref"],
                          "flag_resolved", interaction.user.id)
        await interaction.response.send_message(f"✅ Flag **#{flag_id}** resolved.", ephemeral=True)

    # ── Archive Record ────────────────────────────────────────────────────────

    @app_commands.command(name="archive_record", description="Move an asset record to the archive")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        asset_name="Display name of the asset", reason="Reason for archiving",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def archive_record(
        self, interaction: discord.Interaction,
        asset_type: str, asset_ref: str, asset_name: str, reason: str,
    ) -> None:
        import json as _json
        notes = await self.bot.db.fetchall(
            "SELECT note FROM asset_notes WHERE asset_type=? AND asset_ref=?",
            (asset_type, asset_ref),
        )
        snapshot = _json.dumps({"notes": [n["note"] for n in notes]})
        await self.bot.db.execute(
            "INSERT INTO asset_archive (asset_type, asset_ref, asset_name, reason, archived_by, data_json) "
            "VALUES (?,?,?,?,?,?)",
            (asset_type, asset_ref, asset_name, reason, interaction.user.id, snapshot),
        )
        await _log_change(self.bot, asset_type, asset_ref, "archived",
                          interaction.user.id, new_value=reason)
        embed = discord.Embed(title="📦 Record Archived", colour=discord.Colour.dark_grey())
        embed.add_field(name="📁 Asset",    value=_asset_header(asset_type, asset_ref), inline=False)
        embed.add_field(name="📛 Name",     value=asset_name,             inline=True)
        embed.add_field(name="👤 Archived", value=interaction.user.mention, inline=True)
        embed.add_field(name="📝 Reason",   value=reason,                 inline=False)
        embed.set_footer(text="Record preserved — not deleted ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)
        await self.bot.log_staff(interaction.user.id, "archive_record", asset_type, asset_ref, reason)

    @app_commands.command(name="view_archived", description="Browse archived asset records")
    @app_commands.describe(asset_type="Filter by type (leave blank for all)")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def view_archived(
        self, interaction: discord.Interaction, asset_type: Optional[str] = None
    ) -> None:
        if asset_type:
            rows = await self.bot.db.fetchall(
                "SELECT * FROM asset_archive WHERE asset_type=? ORDER BY archived_at DESC LIMIT 15",
                (asset_type,),
            )
        else:
            rows = await self.bot.db.fetchall(
                "SELECT * FROM asset_archive ORDER BY archived_at DESC LIMIT 15"
            )
        embed = discord.Embed(title="📦 Archived Records", colour=discord.Colour.dark_grey())
        if not rows:
            embed.description = "No archived records found."
        else:
            for r in rows:
                embed.add_field(
                    name=f"{_asset_header(r['asset_type'], r['asset_ref'])} — {r['asset_name'] or 'N/A'}",
                    value=f"📝 {r['reason'] or 'No reason'} | 📅 {r['archived_at'][:10]} | By <@{r['archived_by']}>",
                    inline=False,
                )
        embed.set_footer(text=f"{len(rows)} record(s) ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Change Log ────────────────────────────────────────────────────────────

    @app_commands.command(name="change_log", description="View the full modification history of an asset")
    @app_commands.describe(asset_type="Type of asset", asset_ref="Reference identifier")
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def change_log(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str
    ) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM asset_change_log WHERE asset_type=? AND asset_ref=? ORDER BY created_at DESC LIMIT 20",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(
            title=f"📋 Change Log — {_asset_header(asset_type, asset_ref)}",
            colour=discord.Colour.blue(),
        )
        if not rows:
            embed.description = "No change history found."
        else:
            for r in rows:
                detail = ""
                if r["old_value"] and r["new_value"]:
                    detail = f"\n`{r['old_value']}` → `{r['new_value']}`"
                elif r["new_value"]:
                    detail = f"\n`{r['new_value']}`"
                embed.add_field(
                    name=f"📌 {r['action'].replace('_', ' ').title()}",
                    value=f"By <@{r['changed_by']}> | {r['created_at'][:10]}{detail}",
                    inline=False,
                )
        embed.set_footer(text=f"{len(rows)} change(s) ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Global Search ─────────────────────────────────────────────────────────

    @app_commands.command(name="db_search", description="Search everything in the KAT Market database")
    @app_commands.describe(query="Name, alias, tag, or reference to search for")
    async def db_search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer(ephemeral=True)
        q = f"%{query}%"
        results: list[tuple[str, str, str]] = []

        for table, ref_col, name_col, atype in [
            ("houses",     "number", "address", "house"),
            ("apartments", "number", "address", "apartment"),
            ("businesses", "name",   "location", "business"),
        ]:
            rows = await self.bot.db.fetchall(
                f"SELECT {ref_col}, {name_col} FROM {table} WHERE CAST({ref_col} AS TEXT) LIKE ? OR {name_col} LIKE ? LIMIT 5",
                (q, q),
            )
            for r in rows:
                results.append((atype, str(r[ref_col]), str(r[name_col] or "")))

        listings = await self.bot.db.fetchall(
            "SELECT id, category, title FROM listings WHERE title LIKE ? AND status='active' LIMIT 8",
            (q,),
        )
        for r in listings:
            results.append((r["category"], str(r["id"]), r["title"]))

        alias_rows = await self.bot.db.fetchall(
            "SELECT asset_type, asset_ref, alias FROM asset_aliases WHERE alias LIKE ? LIMIT 5",
            (q,),
        )
        for r in alias_rows:
            results.append((r["asset_type"], r["asset_ref"], f"via alias: {r['alias']}"))

        tag_rows = await self.bot.db.fetchall(
            "SELECT DISTINCT asset_type, asset_ref FROM asset_tags WHERE tag LIKE ? LIMIT 5",
            (q,),
        )
        for r in tag_rows:
            results.append((r["asset_type"], r["asset_ref"], f"via tag: {query}"))

        seen: set = set()
        unique: list[tuple[str, str, str]] = []
        for item in results:
            key = (item[0], item[1])
            if key not in seen:
                seen.add(key)
                unique.append(item)

        embed = discord.Embed(
            title=f'🔍 Global Search — "{query}"',
            colour=discord.Colour.blurple(),
            description=f"**{len(unique)}** result(s) found",
        )
        if not unique:
            embed.description = "No results found. Try a different query."
        else:
            for atype, ref, detail in unique[:15]:
                rec = await self.bot.db.fetchone(
                    "SELECT is_verified, is_blacklisted FROM asset_records WHERE asset_type=? AND asset_ref=?",
                    (atype, ref),
                )
                badges = ""
                if rec:
                    if rec["is_verified"]:    badges += " ✅"
                    if rec["is_blacklisted"]: badges += " 🚫"
                embed.add_field(
                    name=f"{_asset_header(atype, ref)}{badges}",
                    value=detail or "—",
                    inline=False,
                )
        embed.set_footer(text="✅ Verified  🚫 Blacklisted ━━━━━━━━━━━━━━━━━━")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Tag System ────────────────────────────────────────────────────────────

    @app_commands.command(name="add_tag", description="Add a searchable tag to an asset")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        tag="Tag to add (e.g. Luxury, Rare, High Profit)",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def add_tag(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str, tag: str
    ) -> None:
        try:
            await self.bot.db.execute(
                "INSERT INTO asset_tags (asset_type, asset_ref, tag, added_by) VALUES (?,?,?,?)",
                (asset_type, asset_ref, tag.strip(), interaction.user.id),
            )
        except Exception:
            await interaction.response.send_message(
                f"❌ Tag **{tag}** already exists on this asset.", ephemeral=True
            )
            return
        await _log_change(self.bot, asset_type, asset_ref, "tag_added",
                          interaction.user.id, new_value=tag)
        await interaction.response.send_message(
            f"✅ Tag **{tag}** added to {_asset_header(asset_type, asset_ref)}.", ephemeral=True
        )

    @app_commands.command(name="remove_tag", description="Remove a tag from an asset")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier", tag="Tag to remove",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def remove_tag(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str, tag: str
    ) -> None:
        await self.bot.db.execute(
            "DELETE FROM asset_tags WHERE asset_type=? AND asset_ref=? AND tag=?",
            (asset_type, asset_ref, tag),
        )
        await _log_change(self.bot, asset_type, asset_ref, "tag_removed",
                          interaction.user.id, old_value=tag)
        await interaction.response.send_message(
            f"✅ Tag **{tag}** removed.", ephemeral=True
        )

    @app_commands.command(name="search_tag", description="Find all assets with a specific tag")
    @app_commands.describe(tag="Tag to search for")
    async def search_tag(self, interaction: discord.Interaction, tag: str) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT DISTINCT asset_type, asset_ref FROM asset_tags WHERE tag LIKE ? LIMIT 20",
            (f"%{tag}%",),
        )
        embed = discord.Embed(
            title=f'🏷 Tag Search — "{tag}"',
            colour=discord.Colour.teal(),
            description=f"**{len(rows)}** result(s)",
        )
        if not rows:
            embed.description = "No assets found with that tag."
        else:
            for r in rows:
                all_tags = await self.bot.db.fetchall(
                    "SELECT tag FROM asset_tags WHERE asset_type=? AND asset_ref=?",
                    (r["asset_type"], r["asset_ref"]),
                )
                tag_list = " • ".join(t["tag"] for t in all_tags)
                embed.add_field(
                    name=_asset_header(r["asset_type"], r["asset_ref"]),
                    value=tag_list or tag,
                    inline=False,
                )
        await interaction.response.send_message(embed=embed)

    # ── Favorites ─────────────────────────────────────────────────────────────

    @app_commands.command(name="favorite", description="Pin an important asset to your favorites")
    @app_commands.describe(
        asset_type="Type of asset", asset_ref="Reference identifier",
        note="Optional personal note",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def favorite(
        self, interaction: discord.Interaction, asset_type: str, asset_ref: str,
        note: Optional[str] = None,
    ) -> None:
        try:
            await self.bot.db.execute(
                "INSERT INTO asset_favorites (user_id, asset_type, asset_ref, note) VALUES (?,?,?,?)",
                (interaction.user.id, asset_type, asset_ref, note),
            )
        except Exception:
            await self.bot.db.execute(
                "DELETE FROM asset_favorites WHERE user_id=? AND asset_type=? AND asset_ref=?",
                (interaction.user.id, asset_type, asset_ref),
            )
            await interaction.response.send_message(
                f"⭐ Removed **{asset_ref}** from your favorites.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"⭐ Added **{_asset_header(asset_type, asset_ref)}** to your favorites!", ephemeral=True
        )

    @app_commands.command(name="my_favorites", description="View your pinned favorite records")
    async def my_favorites(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM asset_favorites WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="⭐ My Favorites", colour=discord.Colour.gold())
        if not rows:
            embed.description = "You haven't pinned any records yet."
        else:
            for r in rows:
                embed.add_field(
                    name=_asset_header(r["asset_type"], r["asset_ref"]),
                    value=(r["note"] or "No note") + f" | 📅 {r['created_at'][:10]}",
                    inline=False,
                )
        embed.set_footer(text=f"{len(rows)} favorite(s) • use /favorite again to remove ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="staff_picks", description="View staff-favourited records")
    async def staff_picks(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            "SELECT DISTINCT asset_type, asset_ref FROM asset_tags WHERE tag='Staff Pick' LIMIT 15"
        )
        embed = discord.Embed(title="⭐ Staff Picks", colour=discord.Colour.gold())
        if not rows:
            embed.description = "No staff picks yet."
        else:
            for r in rows:
                rec = await self.bot.db.fetchone(
                    "SELECT is_verified FROM asset_records WHERE asset_type=? AND asset_ref=?",
                    (r["asset_type"], r["asset_ref"]),
                )
                verified = " ✅" if rec and rec["is_verified"] else ""
                embed.add_field(
                    name=f"{_asset_header(r['asset_type'], r['asset_ref'])}{verified}",
                    value="🏷 Staff Pick",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed)

    # ── Last Seen ─────────────────────────────────────────────────────────────

    @app_commands.command(name="last_seen", description="Check when an asset was last listed or sold")
    @app_commands.describe(query="Asset name or title to look up")
    async def last_seen(self, interaction: discord.Interaction, query: str) -> None:
        q = f"%{query}%"
        last_listed = await self.bot.db.fetchone(
            "SELECT title, created_at, category FROM listings WHERE title LIKE ? ORDER BY created_at DESC LIMIT 1",
            (q,),
        )
        last_sold = await self.bot.db.fetchone(
            "SELECT title, updated_at, category FROM listings "
            "WHERE title LIKE ? AND status='sold' ORDER BY updated_at DESC LIMIT 1",
            (q,),
        )
        embed = discord.Embed(title=f'📅 Last Seen — "{query}"', colour=discord.Colour.blurple())
        if last_listed:
            from datetime import datetime as _dt
            try:
                listed_dt = _dt.fromisoformat(last_listed["created_at"])
                delta = utcnow() - listed_dt.replace(tzinfo=None).replace(tzinfo=utcnow().tzinfo)
                days_ago = delta.days
            except Exception:
                days_ago = None
            embed.add_field(
                name="📋 Last Listed",
                value=f"**{last_listed['title']}**\n"
                      f"📅 {last_listed['created_at'][:10]}"
                      + (f" ({days_ago} days ago)" if days_ago is not None else ""),
                inline=False,
            )
        else:
            embed.add_field(name="📋 Last Listed", value="Never listed", inline=False)

        if last_sold:
            embed.add_field(
                name="🏷 Last Sold",
                value=f"**{last_sold['title']}**\n📅 {last_sold['updated_at'][:10]}",
                inline=False,
            )
        else:
            embed.add_field(name="🏷 Last Sold", value="Never sold", inline=False)
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)

    # ── Demand Score ──────────────────────────────────────────────────────────

    @app_commands.command(name="demand_score", description="View the demand score and popularity of a listing")
    @app_commands.describe(listing_id="The marketplace listing ID")
    async def demand_score(self, interaction: discord.Interaction, listing_id: int) -> None:
        listing = await self.bot.db.fetchone(
            "SELECT * FROM listings WHERE id=?", (listing_id,)
        )
        if not listing:
            await interaction.response.send_message("❌ Listing not found.", ephemeral=True)
            return

        interested = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM notifications WHERE ref_id=? AND type='interested'",
            (listing_id,),
        )
        offers = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM offers WHERE listing_id=?", (listing_id,)
        )
        watchlisted = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM watchlist WHERE listing_id=?", (listing_id,)
        )

        i_count = interested["c"] if interested else 0
        o_count = offers["c"]    if offers     else 0
        w_count = watchlisted["c"] if watchlisted else 0

        raw_score = (i_count * 2) + (o_count * 5) + (w_count * 3)
        score = min(100, raw_score)

        if score >= 80:   demand_label, colour = "🔥 Very High",  discord.Colour.red()
        elif score >= 55: demand_label, colour = "📈 High",       discord.Colour.orange()
        elif score >= 30: demand_label, colour = "📊 Moderate",   discord.Colour.gold()
        elif score >= 10: demand_label, colour = "📉 Low",        discord.Colour.blue()
        else:             demand_label, colour = "❄️ Very Low",    discord.Colour.light_grey()

        bar_filled = round(score / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        embed = discord.Embed(
            title=f"📊 Demand Score — {listing['title']}",
            colour=colour,
        )
        embed.add_field(name="📊 Score",              value=f"`{bar}` **{score}/100**", inline=False)
        embed.add_field(name="📈 Demand",              value=demand_label,               inline=True)
        embed.add_field(name="👀 Interested Buyers",   value=str(i_count),               inline=True)
        embed.add_field(name="💰 Offers Made",         value=str(o_count),               inline=True)
        embed.add_field(name="🔖 Watchlisted",         value=str(w_count),               inline=True)
        embed.add_field(name="💰 Asking Price",        value=f"${listing['asking_price']:,}", inline=True)
        embed.add_field(name="🏷 Category",            value=listing["category"].capitalize(), inline=True)
        embed.set_footer(text="Score = (Interested×2) + (Offers×5) + (Watchlisted×3) ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)

    # ── Merge Records ─────────────────────────────────────────────────────────

    @app_commands.command(name="merge_records", description="Merge a duplicate asset reference into a canonical one")
    @app_commands.describe(
        asset_type="Type of asset",
        source_ref="The duplicate reference to merge FROM (e.g. 'House #020')",
        target_ref="The canonical reference to merge INTO (e.g. 'House #20')",
    )
    @app_commands.choices(asset_type=ASSET_TYPE_CHOICES)
    async def merge_records(
        self, interaction: discord.Interaction,
        asset_type: str, source_ref: str, target_ref: str,
    ) -> None:
        for table in ("asset_notes", "asset_aliases", "asset_images",
                      "asset_value_history", "asset_tags", "asset_change_log"):
            await self.bot.db.execute(
                f"UPDATE {table} SET asset_ref=? WHERE asset_type=? AND asset_ref=?",
                (target_ref, asset_type, source_ref),
            )
        for table in ("asset_locations", "asset_records"):
            existing_target = await self.bot.db.fetchone(
                f"SELECT id FROM {table} WHERE asset_type=? AND asset_ref=?",
                (asset_type, target_ref),
            )
            if not existing_target:
                await self.bot.db.execute(
                    f"UPDATE {table} SET asset_ref=? WHERE asset_type=? AND asset_ref=?",
                    (target_ref, asset_type, source_ref),
                )
            else:
                await self.bot.db.execute(
                    f"DELETE FROM {table} WHERE asset_type=? AND asset_ref=?",
                    (asset_type, source_ref),
                )
        await _log_change(
            self.bot, asset_type, target_ref, "merge",
            interaction.user.id, old_value=source_ref, new_value=target_ref,
        )
        embed = discord.Embed(title="🔄 Records Merged", colour=discord.Colour.green())
        embed.add_field(name="📁 Type",   value=asset_type.capitalize(), inline=True)
        embed.add_field(name="🗑 From",   value=source_ref,              inline=True)
        embed.add_field(name="✅ Into",   value=target_ref,              inline=True)
        embed.add_field(
            name="ℹ️ What was moved",
            value="Notes, aliases, images, tags, value history, change log → merged into canonical reference.",
            inline=False,
        )
        embed.set_footer(text="━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed)
        await self.bot.log_staff(
            interaction.user.id, "merge_records", asset_type, f"{source_ref}→{target_ref}"
        )

    # ── Database Alerts (background task) ────────────────────────────────────

    @tasks.loop(hours=12)
    async def _alert_loop(self) -> None:
        ch = self.bot.get_channel(STAFF_LOG_CHANNEL_ID)
        if not ch:
            return

        alerts: list[str] = []

        # Active listings with no image archived
        no_image = await self.bot.db.fetchall(
            """SELECT l.id, l.title, l.category FROM listings l
               WHERE l.status='active'
               AND NOT EXISTS (
                   SELECT 1 FROM asset_images ai
                   WHERE ai.asset_type=l.category AND ai.asset_ref=CAST(l.id AS TEXT)
               )
               LIMIT 10"""
        )
        if no_image:
            alerts.append(
                f"📸 **{len(no_image)} active listing(s) have no archived images:**\n"
                + "\n".join(f"  • #{r['id']} {r['title']} ({r['category']})" for r in no_image)
            )

        # Active listings with no location set
        no_location = await self.bot.db.fetchall(
            """SELECT l.id, l.title FROM listings l
               WHERE l.status='active'
               AND l.category IN ('house','apartment','business','property')
               AND NOT EXISTS (
                   SELECT 1 FROM asset_locations al
                   WHERE al.asset_type=l.category AND al.asset_ref=CAST(l.id AS TEXT)
               )
               LIMIT 10"""
        )
        if no_location:
            alerts.append(
                f"📍 **{len(no_location)} listing(s) have no location data:**\n"
                + "\n".join(f"  • #{r['id']} {r['title']}" for r in no_location)
            )

        # Open unresolved flags
        open_flags = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM asset_flags WHERE resolved=0"
        )
        if open_flags and open_flags["c"] > 0:
            alerts.append(f"🚩 **{open_flags['c']} unresolved flag(s)** pending staff review.")

        # Listings expiring in next 24 hours
        soon = (utcnow() + timedelta(hours=24)).isoformat()
        expiring_soon = await self.bot.db.fetchone(
            "SELECT COUNT(*) as c FROM listings WHERE status='active' AND expires_at IS NOT NULL AND expires_at <= ?",
            (soon,),
        )
        if expiring_soon and expiring_soon["c"] > 0:
            alerts.append(f"⏰ **{expiring_soon['c']} listing(s)** expire within 24 hours.")

        if alerts:
            embed = discord.Embed(
                title="🔔 Database Alerts",
                description="\n\n".join(alerts),
                colour=discord.Colour.orange(),
            )
            embed.set_footer(text=f"Auto-scan • {utcnow().strftime('%d/%m/%Y %H:%M')} UTC ━━━━━━━━━━━━━━━━━━")
            embed.timestamp = utcnow()
            await ch.send(embed=embed)

    @_alert_loop.before_loop
    async def _before_alert_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ── Watchlist ─────────────────────────────────────────────────────────────

    @app_commands.command(name="watchlist_add", description="Add a listing to your watchlist for price-drop alerts")
    @app_commands.describe(listing_id="The listing ID to watch")
    async def watchlist_add(self, interaction: discord.Interaction, listing_id: int) -> None:
        listing = await self.bot.db.fetchone(
            "SELECT * FROM listings WHERE id=? AND status='active'", (listing_id,)
        )
        if not listing:
            await interaction.response.send_message("❌ Listing not found or no longer active.", ephemeral=True)
            return
        if listing["seller_id"] == interaction.user.id:
            await interaction.response.send_message("❌ You cannot watch your own listing.", ephemeral=True)
            return
        try:
            await self.bot.db.execute(
                "INSERT INTO watchlist (user_id, listing_id) VALUES (?,?)",
                (interaction.user.id, listing_id),
            )
        except Exception:
            await self.bot.db.execute(
                "DELETE FROM watchlist WHERE user_id=? AND listing_id=?",
                (interaction.user.id, listing_id),
            )
            await interaction.response.send_message(
                f"🔔 Removed **{listing['title']}** from your watchlist.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🔖 Now watching **{listing['title']}** — you'll be notified on price drops!", ephemeral=True
        )

    @app_commands.command(name="my_watchlist", description="View your watchlisted listings")
    async def my_watchlist(self, interaction: discord.Interaction) -> None:
        rows = await self.bot.db.fetchall(
            """SELECT w.listing_id, l.title, l.asking_price, l.category, l.status
               FROM watchlist w
               JOIN listings l ON l.id = w.listing_id
               WHERE w.user_id=?
               ORDER BY w.created_at DESC LIMIT 15""",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="🔖 My Watchlist", colour=discord.Colour.blurple())
        if not rows:
            embed.description = "Your watchlist is empty. Use `/watchlist_add` on any active listing."
        else:
            for r in rows:
                status_icon = "🟢" if r["status"] == "active" else "🔴"
                embed.add_field(
                    name=f"{status_icon} #{r['listing_id']} — {r['title']}",
                    value=f"💰 ${r['asking_price']:,} | 🏷 {r['category'].capitalize()}",
                    inline=False,
                )
        embed.set_footer(text=f"{len(rows)} listing(s) watched ━━━━━━━━━━━━━━━━━━")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

EXTERNAL_COGS = [
    "cogs.database_cog",
    "cogs.finance",
    "cogs.community",
    "cogs.security",
    "cogs.events",
    "cogs.analytics",
    "cogs.staff",
    "cogs.admin_panel",
    "cogs.channel_config",
    "cogs.birthday",
    "cogs.ai_services",
    "cogs.escrow",
    "cogs.notifications",
    "cogs.tickets",
    "cogs.city_directory",
    "cogs.ownership_history",
    "cogs.coin_sinks",
    "cogs.marketplace_app",
]


class KATBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!kat ", intents=intents, help_command=None)
        self.db = Database(DATABASE_PATH)

    async def setup_hook(self) -> None:
        await self.db.init()
        await self._load_csv_data()

        inline_cogs = (
            MarketplaceCog, BountyCog, ContractCog, AdvertisingCog, BirthdayCog,
            NotificationCog, BrokerCog, EscrowCog, OwnershipCog,
            MarketAppCog, TicketCog, BadgeCog, ListingManagementCog,
            DatabaseCog, AdvancedDatabaseCog,
        )
        for cog in inline_cogs:
            await self.add_cog(cog(self))
            logger.info("Loaded inline cog: %s", cog.__name__)

        for cog_path in EXTERNAL_COGS:
            try:
                await self.load_extension(cog_path)
                logger.info("Loaded cog: %s", cog_path)
            except Exception as e:
                logger.warning("Skipped cog %s: %s", cog_path, e)

        logger.info("Syncing slash commands…")
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except Exception as e:
            logger.error("Failed to sync commands: %s", e)

    async def _load_csv_data(self) -> None:
        for table, csv_path, cols in [
            ("houses",    HOUSES_CSV,     ["number", "city", "type", "address"]),
            ("apartments",APARTMENTS_CSV, ["number", "city", "type", "address"]),
            ("businesses",BUSINESSES_CSV, ["number", "name", "location"]),
        ]:
            row = await self.db.fetchone(f"SELECT COUNT(*) as c FROM {table}")
            if row and row["c"] == 0:
                await self.db.load_csv(csv_path, table, cols)

    async def ensure_user(self, user: discord.User | discord.Member) -> None:
        exists = await self.db.fetchone("SELECT user_id FROM users WHERE user_id=?", (user.id,))
        if not exists:
            await self.db.execute(
                "INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
                (user.id, str(user)),
            )

    async def ensure_user_by_id(self, user_id: int) -> None:
        exists = await self.db.fetchone("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if not exists:
            await self.db.execute(
                "INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
                (user_id, f"User#{user_id}"),
            )

    async def get_channel_id(self, key: str) -> int:
        row = await self.db.fetchone("SELECT value FROM bot_config WHERE key=?", (f"channel_{key}",))
        if row and row["value"] and row["value"] != "0":
            return int(row["value"])
        return {
            "marketplace":   LISTINGS_CHANNEL_ID,
            "advertisement": AD_CHANNEL_ID,
            "rent":          AD_CHANNEL_ID,
            "bounty":        BOUNTY_CHANNEL_ID,
            "report":        REPORT_CHANNEL_ID,
            "coin_purchase": PAYMENT_REVIEW_CHANNEL_ID,
            "giveaway":      GIVEAWAY_CHANNEL_ID,
            "staff":         STAFF_LOG_CHANNEL_ID,
            "admin_log":     STAFF_LOG_CHANNEL_ID,
            "contract":      CONTRACT_CHANNEL_ID,
        }.get(key, 0)

    async def log_staff(
        self,
        staff_id: int,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        await self.db.execute(
            "INSERT INTO staff_logs (staff_id, action, target_type, target_id, note) VALUES (?,?,?,?,?)",
            (staff_id, action, target_type, target_id, note),
        )

    async def on_ready(self) -> None:
        logger.info("KAT Market Bot online as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="KAT Market | /sell_vehicle",
            )
        )

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, discord.app_commands.CheckFailure):
            return
        logger.error("App command error in %s: %s", interaction.command, error, exc_info=True)
        msg = "An unexpected error occurred. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
        except Exception:
            pass

    async def on_member_join(self, member: discord.Member) -> None:
        await self.ensure_user(member)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN is not set! Please add it to environment secrets.")
        return
    bot = KATBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
