"""
╔══════════════════════════════════════════════╗
║         🐾 KAT MARKET NEKO — bot.py          ║
║   Complete Discord Bot for Grand RP Community ║
╚══════════════════════════════════════════════╝

Single-file bot with ALL slash commands stubbed and wired to a shared
SQLite database (same schema as db.py).  Drop this file alongside db.py,
config.py, and utils/helpers.py and run:

    python bot.py

Every command sends an ephemeral reply so you can see it works, then
replace the stub body with your real logic.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ── compatibility shim for Python 3.13 audioop removal ──────────────────────
if sys.version_info >= (3, 13):
    try:
        import audioop  # noqa: F401
    except ModuleNotFoundError:
        from types import ModuleType as _MT
        _stub = _MT("audioop")
        for _fn in ("add","adpcm2lin","alaw2lin","avg","avgpp","bias","byteswap",
                    "cross","findfactor","findfit","findmax","getsample","lin2adpcm",
                    "lin2alaw","lin2lin","lin2ulaw","max","maxpp","minmax","mul",
                    "ratecv","reverse","rms","tomono","tostereo","ulaw2lin"):
            setattr(_stub, _fn, lambda *a, **k: b"")
        sys.modules["audioop"] = _stub
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("katmarket")

# ── env / constants ──────────────────────────────────────────────────────────
TOKEN: str = os.getenv("DISCORD_TOKEN", "")

STAFF_ROLE:        str = os.getenv("STAFF_ROLE_NAME",        "Staff")
SENIOR_STAFF_ROLE: str = os.getenv("SENIOR_STAFF_ROLE_NAME", "Senior Staff")
ADMIN_ROLE:        str = os.getenv("ADMIN_ROLE_NAME",         "Administrator")

DB_PATH: str = os.path.join(os.path.dirname(__file__), "data", "katmarket.db")
UPI_ID:  str = os.getenv("UPI_ID", "adityaghatule30@okaxis")
UPI_QR:  str = os.getenv("UPI_QR_URL", "")

COIN_RATE_INR     = 1      # 1 coin = ₹1
GAME_CASH_PER_COIN = 5000  # 5,000 game cash = 1 coin

BUSINESS_TYPES = [
    "Shop 24/7", "Clothing Store", "Restaurant", "Weapons Shop",
    "Gas Station", "Parking Lot", "CargoConnect", "VectorCargo",
    "TransCargoLiz", "Parcel Terminal", "Notary", "Pickaxe Shop",
]

VEHICLE_TYPES  = ["Car", "Bike", "Boat", "Helicopter"]
LISTING_CATS   = ["vehicle", "property", "business", "skin", "item"]
PROPERTY_TYPES = ["House - Economy", "House - Standard", "House - Luxury",
                  "Apartment - Standard", "Apartment - Luxury"]


# ── helpers ──────────────────────────────────────────────────────────────────
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def fmt_cash(n: int) -> str:
    return f"${n:,}"


def parse_shorthand(s: str) -> int:
    """Convert '1m' → 1_000_000, '500k' → 500_000, '1b' → 1_000_000_000."""
    s = s.strip().lower()
    mults = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
    for suffix, mult in mults.items():
        if s.endswith(suffix):
            try:
                return int(float(s[:-1]) * mult)
            except ValueError:
                pass
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return 0


def has_role(*role_names: str):
    """Check decorator — user must have at least one of the given roles."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if not member:
            return False
        return any(r.name in role_names for r in member.roles)
    return app_commands.check(predicate)


# ── database (inline, no external import needed) ─────────────────────────────
import aiosqlite

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT    NOT NULL,
    kat_coins   INTEGER NOT NULL DEFAULT 0,
    game_cash   INTEGER NOT NULL DEFAULT 0,
    reputation  REAL    NOT NULL DEFAULT 5.0,
    trade_count INTEGER NOT NULL DEFAULT 0,
    total_sales INTEGER NOT NULL DEFAULT 0,
    is_verified INTEGER NOT NULL DEFAULT 0,
    is_banned   INTEGER NOT NULL DEFAULT 0,
    profile_msg TEXT,
    profile_contact TEXT,
    marital_status TEXT NOT NULL DEFAULT 'Single',
    spouse_id   INTEGER,
    birthday_day   INTEGER,
    birthday_month INTEGER,
    birthday_year  INTEGER,
    birthday_status TEXT NOT NULL DEFAULT 'unset',
    daily_last  TEXT,
    weekly_last TEXT,
    joined_at   TEXT    NOT NULL DEFAULT (datetime('now'))
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
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (seller_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS offers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id   INTEGER NOT NULL,
    buyer_id     INTEGER NOT NULL,
    offer_amount INTEGER NOT NULL DEFAULT 0,
    status       TEXT    NOT NULL DEFAULT 'pending',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coin_purchases (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    method         TEXT    NOT NULL,
    coins          INTEGER NOT NULL,
    price          TEXT    NOT NULL,
    screenshot_url TEXT,
    status         TEXT    NOT NULL DEFAULT 'pending',
    reviewed_by    INTEGER,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bounties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL,
    target_name TEXT    NOT NULL,
    reward      TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    max_hunters INTEGER NOT NULL DEFAULT 5,
    duration    INTEGER NOT NULL DEFAULT 1,
    coins_paid  INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'pending',
    message_id  INTEGER,
    channel_id  INTEGER,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id   INTEGER NOT NULL,
    title        TEXT    NOT NULL,
    description  TEXT,
    terms        TEXT,
    status       TEXT    NOT NULL DEFAULT 'draft',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id  INTEGER NOT NULL,
    target_type  TEXT    NOT NULL,
    target_id    TEXT    NOT NULL,
    reason       TEXT    NOT NULL,
    evidence_url TEXT,
    status       TEXT    NOT NULL DEFAULT 'pending',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS giveaways (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id    INTEGER NOT NULL,
    giveaway_type TEXT    NOT NULL,
    prize         TEXT    NOT NULL,
    description   TEXT,
    winners_count INTEGER NOT NULL DEFAULT 1,
    message_id    INTEGER,
    channel_id    INTEGER,
    status        TEXT    NOT NULL DEFAULT 'pending',
    ends_at       TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    giveaway_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    UNIQUE(giveaway_id, user_id)
);

CREATE TABLE IF NOT EXISTS advertisements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    ad_type       TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    duration_days INTEGER NOT NULL DEFAULT 1,
    message_id    INTEGER,
    channel_id    INTEGER,
    status        TEXT    NOT NULL DEFAULT 'active',
    expires_at    TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vouches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL,
    to_id      INTEGER NOT NULL,
    listing_id INTEGER,
    rating     INTEGER NOT NULL DEFAULT 5,
    message    TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trade_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id    INTEGER NOT NULL,
    buyer_id     INTEGER NOT NULL,
    listing_id   INTEGER NOT NULL,
    sale_price   INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS staff_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id    INTEGER NOT NULL,
    action      TEXT    NOT NULL,
    target_type TEXT,
    target_id   TEXT,
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT,
    prize       TEXT,
    location    TEXT,
    event_time  TEXT,
    cover_url   TEXT,
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_by  INTEGER,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS occasions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    occ_type    TEXT    NOT NULL,
    description TEXT    NOT NULL,
    location    TEXT    NOT NULL,
    occ_time    TEXT    NOT NULL,
    cover_url   TEXT,
    status      TEXT    NOT NULL DEFAULT 'pending',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cash_listings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id    INTEGER NOT NULL,
    amount       INTEGER NOT NULL,
    rate_per_m   INTEGER NOT NULL,
    total_inr    INTEGER NOT NULL,
    contact      TEXT    NOT NULL,
    pay_method   TEXT    NOT NULL,
    commission   REAL    NOT NULL DEFAULT 0.0,
    status       TEXT    NOT NULL DEFAULT 'pending',
    message_id   INTEGER,
    channel_id   INTEGER,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    category    TEXT    NOT NULL,
    subject     TEXT    NOT NULL,
    description TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'open',
    staff_id    INTEGER,
    resolution  TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS proposals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id      INTEGER NOT NULL,
    to_id        INTEGER NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'pending',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bot_config (
    key   TEXT PRIMARY KEY,
    value TEXT
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

CREATE TABLE IF NOT EXISTS watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    listing_id INTEGER NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, listing_id)
);

CREATE TABLE IF NOT EXISTS wanted_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    category    TEXT    NOT NULL,
    description TEXT    NOT NULL,
    max_budget  INTEGER NOT NULL DEFAULT 0,
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS auctions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id   INTEGER NOT NULL,
    listing_id  INTEGER,
    title       TEXT    NOT NULL,
    start_price INTEGER NOT NULL DEFAULT 0,
    current_bid INTEGER NOT NULL DEFAULT 0,
    top_bidder  INTEGER,
    status      TEXT    NOT NULL DEFAULT 'active',
    ends_at     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bids (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER NOT NULL,
    bidder_id  INTEGER NOT NULL,
    amount     INTEGER NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fixed_deposits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    amount     INTEGER NOT NULL,
    rate       REAL    NOT NULL DEFAULT 5.0,
    maturity   TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'active',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS redeem_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT    NOT NULL UNIQUE,
    reward     TEXT    NOT NULL,
    coins      INTEGER NOT NULL DEFAULT 0,
    uses_left  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS redeem_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    code       TEXT    NOT NULL,
    reward     TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


class DB:
    def __init__(self, path: str) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await db.commit()
        logger.info("DB ready: %s", self.path)

    async def exe(self, sql: str, p: tuple = ()) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(sql, p)
            await db.commit()

    async def one(self, sql: str, p: tuple = ()) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, p) as c:
                row = await c.fetchone()
                return dict(row) if row else None

    async def all(self, sql: str, p: tuple = ()) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, p) as c:
                return [dict(r) for r in await c.fetchall()]

    async def lid(self, sql: str, p: tuple = ()) -> int:
        async with aiosqlite.connect(self.path) as db:
            c = await db.execute(sql, p)
            await db.commit()
            return c.lastrowid or 0

    async def cfg(self, key: str) -> Optional[str]:
        r = await self.one("SELECT value FROM bot_config WHERE key=?", (key,))
        return r["value"] if r else None

    async def set_cfg(self, key: str, value: str) -> None:
        await self.exe("INSERT OR REPLACE INTO bot_config (key,value) VALUES (?,?)", (key, value))

    async def ensure_user(self, user: discord.User | discord.Member) -> None:
        await self.exe(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)",
            (user.id, str(user)),
        )

    async def get_coins(self, uid: int) -> int:
        r = await self.one("SELECT kat_coins FROM users WHERE user_id=?", (uid,))
        return r["kat_coins"] if r else 0

    async def add_coins(self, uid: int, amount: int) -> None:
        await self.exe(
            "UPDATE users SET kat_coins=kat_coins+? WHERE user_id=?",
            (amount, uid),
        )

    async def deduct_coins(self, uid: int, amount: int) -> bool:
        bal = await self.get_coins(uid)
        if bal < amount:
            return False
        await self.exe(
            "UPDATE users SET kat_coins=kat_coins-? WHERE user_id=?",
            (amount, uid),
        )
        return True

    async def channel(self, bot: "KATBot", key: str) -> Optional[discord.TextChannel]:
        val = await self.cfg(f"channel_{key}")
        if val:
            ch = bot.get_channel(int(val))
            if isinstance(ch, discord.TextChannel):
                return ch
        return None

    async def log_staff(self, staff_id: int, action: str,
                        target_type: str = None, target_id: str = None, note: str = None) -> None:
        await self.exe(
            "INSERT INTO staff_logs (staff_id,action,target_type,target_id,note) VALUES (?,?,?,?,?)",
            (staff_id, action, target_type, target_id, note),
        )


# ── Bot ───────────────────────────────────────────────────────────────────────
class KATBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!kat ", intents=intents, help_command=None)
        self.db = DB(DB_PATH)

    async def setup_hook(self) -> None:
        await self.db.init()
        await _register_all(self)
        logger.info("Syncing slash commands…")
        try:
            synced = await self.tree.sync()
            logger.info("Synced %d commands", len(synced))
        except Exception as e:
            logger.error("Sync failed: %s", e)

    async def on_ready(self) -> None:
        logger.info("🐾 KAT MARKET NEKO online as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="KAT Market | /sell_vehicle"))

    async def on_member_join(self, member: discord.Member) -> None:
        await self.db.ensure_user(member)

    async def on_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            try:
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command.", ephemeral=True)
            except Exception:
                pass
            return
        logger.error("Command error in %s: %s", interaction.command, error, exc_info=True)
        msg = "❌ An unexpected error occurred. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


bot = KATBot()


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER — quick ephemeral reply
# ═══════════════════════════════════════════════════════════════════════════════
async def eph(interaction: discord.Interaction, **kwargs) -> None:
    kwargs.setdefault("ephemeral", True)
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def require_channel(interaction: discord.Interaction, key: str) -> Optional[discord.TextChannel]:
    ch = await bot.db.channel(bot, key)
    if not ch:
        await eph(interaction, content=f"⚙️ Admin has not configured the `{key}` channel yet. Use `/set_channel`.")
    return ch


# ════════════════════════════════════════════════════════════════════════════════
# 1. MARKET TRADING
# ════════════════════════════════════════════════════════════════════════════════

class SellVehicleModal(discord.ui.Modal, title="Sell Vehicle"):
    vehicle_name  = discord.ui.TextInput(label="Vehicle Name",        placeholder="e.g. Tesla Model S",    max_length=100)
    state_price   = discord.ui.TextInput(label="State Price ($)",      placeholder="e.g. 25000",            max_length=20)
    num_owners    = discord.ui.TextInput(label="Number of Owners",     placeholder="1–10",                  max_length=3)
    selling_price = discord.ui.TextInput(label="Your Selling Price ($)",placeholder="e.g. 42000",           max_length=20)
    image_url     = discord.ui.TextInput(label="Vehicle Photo URL (optional)", required=False,              max_length=300)

    def __init__(self, vehicle_type: str) -> None:
        super().__init__()
        self.vehicle_type = vehicle_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        price = parse_shorthand(self.selling_price.value)
        lid = await bot.db.lid(
            "INSERT INTO listings (seller_id,category,title,description,asking_price,image_url,extra_data) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                interaction.user.id,
                "vehicle",
                f"{self.vehicle_type} — {self.vehicle_name.value}",
                f"State Price: ${self.state_price.value} | Owners: {self.num_owners.value}",
                price,
                self.image_url.value or None,
                self.vehicle_type,
            ),
        )
        embed = discord.Embed(
            title=f"🚗 {self.vehicle_type} FOR SALE — #{lid}",
            description=f"**{self.vehicle_name.value}**",
            colour=discord.Colour.green(),
        )
        embed.add_field(name="State Price",    value=f"${self.state_price.value}",   inline=True)
        embed.add_field(name="# of Owners",   value=self.num_owners.value,           inline=True)
        embed.add_field(name="Selling Price",  value=fmt_cash(price),                inline=True)
        embed.add_field(name="Seller",         value=interaction.user.mention,       inline=True)
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)
        embed.set_footer(text="Use /interested or /make_offer to buy")

        ch = await require_channel(interaction, "marketplace")
        view = ListingActionView(lid)
        if ch:
            msg = await ch.send(embed=embed, view=view)
            await bot.db.exe("UPDATE listings SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch.id, lid))
        await eph(interaction, content=f"✅ Vehicle listed! Listing #{lid} posted to marketplace.")


class VehicleTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        for vtype in VEHICLE_TYPES:
            self.add_item(VehicleTypeButton(vtype))


class VehicleTypeButton(discord.ui.Button):
    EMOJI = {"Car": "🚗", "Bike": "🏍️", "Boat": "⛵", "Helicopter": "🚁"}

    def __init__(self, vtype: str) -> None:
        super().__init__(label=vtype, emoji=self.EMOJI.get(vtype, ""), style=discord.ButtonStyle.primary)
        self.vtype = vtype

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SellVehicleModal(self.vtype))


class SellPropertyModal(discord.ui.Modal, title="Sell Property"):
    prop_number   = discord.ui.TextInput(label="Property Number / ID",   placeholder="e.g. 45",             max_length=10)
    prop_type     = discord.ui.TextInput(label="Property Type",           placeholder="House STD / APT LUX", max_length=50)
    city          = discord.ui.TextInput(label="City / District",         placeholder="e.g. Arzamas South",  max_length=100)
    selling_price = discord.ui.TextInput(label="Selling Price ($)",       placeholder="e.g. 2500000",        max_length=20)
    image_url     = discord.ui.TextInput(label="Screenshot URL (optional)",required=False,                   max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        price = parse_shorthand(self.selling_price.value)
        lid = await bot.db.lid(
            "INSERT INTO listings (seller_id,category,title,description,asking_price,image_url) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, "property",
             f"Property #{self.prop_number.value} — {self.city.value}",
             f"Type: {self.prop_type.value}", price, self.image_url.value or None),
        )
        embed = discord.Embed(title=f"🏠 PROPERTY FOR SALE — #{lid}", colour=discord.Colour.blue())
        embed.add_field(name="Property #",  value=self.prop_number.value, inline=True)
        embed.add_field(name="Type",        value=self.prop_type.value,   inline=True)
        embed.add_field(name="City",        value=self.city.value,        inline=True)
        embed.add_field(name="Price",       value=fmt_cash(price),        inline=True)
        embed.add_field(name="Seller",      value=interaction.user.mention, inline=True)
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)

        ch = await require_channel(interaction, "marketplace")
        view = ListingActionView(lid)
        if ch:
            msg = await ch.send(embed=embed, view=view)
            await bot.db.exe("UPDATE listings SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch.id, lid))
        await eph(interaction, content=f"✅ Property listed! Listing #{lid}")


class SellBusinessModal(discord.ui.Modal, title="Sell Business"):
    biz_number    = discord.ui.TextInput(label="Business Number (1-76)", max_length=4)
    biz_type      = discord.ui.TextInput(label="Business Type",          placeholder="e.g. Shop 24/7", max_length=50)
    daily_profit  = discord.ui.TextInput(label="Daily Average Profit ($)", placeholder="e.g. 50000",  max_length=20)
    selling_price = discord.ui.TextInput(label="Asking Price ($)",         placeholder="e.g. 500000", max_length=20)
    image_url     = discord.ui.TextInput(label="Profit Screenshot URL (optional)", required=False,    max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        price = parse_shorthand(self.selling_price.value)
        biz = await bot.db.one("SELECT * FROM businesses WHERE number=?", (self.biz_number.value,))
        location = biz["location"] if biz else "Unknown"
        lid = await bot.db.lid(
            "INSERT INTO listings (seller_id,category,title,description,asking_price,image_url) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, "business",
             f"Business #{self.biz_number.value} — {self.biz_type.value}",
             f"Location: {location} | Daily Profit: ${self.daily_profit.value}",
             price, self.image_url.value or None),
        )
        embed = discord.Embed(title=f"🏢 BUSINESS FOR SALE — #{lid}", colour=discord.Colour.gold())
        embed.add_field(name="Business #",    value=self.biz_number.value,  inline=True)
        embed.add_field(name="Type",          value=self.biz_type.value,    inline=True)
        embed.add_field(name="Location",      value=location,               inline=True)
        embed.add_field(name="Daily Profit",  value=f"${self.daily_profit.value}", inline=True)
        embed.add_field(name="Asking Price",  value=fmt_cash(price),        inline=True)
        embed.add_field(name="Seller",        value=interaction.user.mention, inline=True)
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)

        ch = await require_channel(interaction, "marketplace")
        view = ListingActionView(lid)
        if ch:
            msg = await ch.send(embed=embed, view=view)
            await bot.db.exe("UPDATE listings SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch.id, lid))
        await eph(interaction, content=f"✅ Business listed! Listing #{lid}")


class SellSkinModal(discord.ui.Modal, title="Sell Skin / Accessory"):
    item_id       = discord.ui.TextInput(label="Item ID (in-game)",     placeholder="e.g. SKN-1234", max_length=30)
    skin_type     = discord.ui.TextInput(label="Type",                  placeholder="Skin / Accessory", max_length=30)
    description   = discord.ui.TextInput(label="Description",           style=discord.TextStyle.paragraph, max_length=500)
    asking_price  = discord.ui.TextInput(label="Asking Price ($)",      placeholder="e.g. 100000", max_length=20)
    image_url     = discord.ui.TextInput(label="Screenshot URL (optional)", required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        price = parse_shorthand(self.asking_price.value)
        lid = await bot.db.lid(
            "INSERT INTO listings (seller_id,category,title,description,asking_price,image_url,extra_data) VALUES (?,?,?,?,?,?,?)",
            (interaction.user.id, "skin",
             f"{self.skin_type.value} — ID:{self.item_id.value}",
             self.description.value, price, self.image_url.value or None, self.item_id.value),
        )
        embed = discord.Embed(title=f"🎨 SKIN FOR SALE — #{lid}", colour=discord.Colour.purple())
        embed.add_field(name="Item ID",       value=self.item_id.value,    inline=True)
        embed.add_field(name="Type",          value=self.skin_type.value,  inline=True)
        embed.add_field(name="Asking Price",  value=fmt_cash(price),       inline=True)
        embed.add_field(name="Seller",        value=interaction.user.mention, inline=True)
        embed.add_field(name="Description",   value=self.description.value, inline=False)
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)

        ch = await require_channel(interaction, "marketplace")
        view = ListingActionView(lid)
        if ch:
            msg = await ch.send(embed=embed, view=view)
            await bot.db.exe("UPDATE listings SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch.id, lid))
        await eph(interaction, content=f"✅ Skin listed! Listing #{lid}")


class ListingActionView(discord.ui.View):
    def __init__(self, lid: int) -> None:
        super().__init__(timeout=None)
        self.lid = lid

    @discord.ui.button(label="Interested", emoji="👀", style=discord.ButtonStyle.primary,
                       custom_id="listing_interested")
    async def interested_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        listing = await bot.db.one("SELECT * FROM listings WHERE id=?", (self.lid,))
        if not listing:
            await eph(interaction, content="Listing not found.")
            return
        if interaction.user.id == listing["seller_id"]:
            await eph(interaction, content="You cannot show interest in your own listing.")
            return
        seller = interaction.guild.get_member(listing["seller_id"]) if interaction.guild else None
        if seller:
            try:
                await seller.send(f"👀 **{interaction.user}** is interested in your listing #{self.lid}!")
            except discord.Forbidden:
                pass
        await eph(interaction, content="✅ Seller notified of your interest!")

    @discord.ui.button(label="Make Offer", emoji="💰", style=discord.ButtonStyle.success,
                       custom_id="listing_offer")
    async def offer_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(MakeOfferModal(self.lid))


class MakeOfferModal(discord.ui.Modal, title="Make an Offer"):
    amount = discord.ui.TextInput(label="Your Offer ($)", placeholder="e.g. 38000", max_length=20)
    note   = discord.ui.TextInput(label="Note (optional)", required=False, max_length=200)

    def __init__(self, lid: int) -> None:
        super().__init__()
        self.lid = lid

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        listing = await bot.db.one("SELECT * FROM listings WHERE id=?", (self.lid,))
        if not listing:
            await eph(interaction, content="Listing not found.")
            return
        offer_amt = parse_shorthand(self.amount.value)
        await bot.db.exe(
            "INSERT INTO offers (listing_id,buyer_id,offer_amount) VALUES (?,?,?)",
            (self.lid, interaction.user.id, offer_amt),
        )
        seller = interaction.guild.get_member(listing["seller_id"]) if interaction.guild else None
        if seller:
            try:
                await seller.send(
                    f"💰 **{interaction.user}** made an offer of **{fmt_cash(offer_amt)}** "
                    f"on your listing #{self.lid}!"
                    + (f"\nNote: {self.note.value}" if self.note.value else "")
                )
            except discord.Forbidden:
                pass
        await eph(interaction, content=f"✅ Offer of {fmt_cash(offer_amt)} sent to seller!")


# ════════════════════════════════════════════════════════════════════════════════
# 2. BOUNTY SYSTEM
# ════════════════════════════════════════════════════════════════════════════════

BOUNTY_PRICES = {1: 0, 2: 5, 3: 7, 4: 10}


class BountyModal(discord.ui.Modal, title="Create Bounty Contract"):
    target     = discord.ui.TextInput(label="Target Name (in-game)",      max_length=100)
    reason     = discord.ui.TextInput(label="Reason",    style=discord.TextStyle.paragraph, max_length=500)
    reward     = discord.ui.TextInput(label="Reward (game cash / item)",   max_length=200)
    max_hunters = discord.ui.TextInput(label="Max Hunters (1-10)",          max_length=3)

    def __init__(self, duration: int) -> None:
        super().__init__()
        self.duration = duration

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        cost = BOUNTY_PRICES.get(self.duration, 0)
        if cost > 0:
            ok = await bot.db.deduct_coins(interaction.user.id, cost)
            if not ok:
                await eph(interaction, content=f"❌ You need {cost} KAT Coins for a {self.duration}-day bounty.")
                return
        try:
            max_h = max(1, min(10, int(self.max_hunters.value)))
        except ValueError:
            max_h = 5

        expires = (utcnow() + timedelta(days=self.duration)).isoformat()
        bid = await bot.db.lid(
            "INSERT INTO bounties (creator_id,target_name,reward,reason,max_hunters,duration,coins_paid,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (interaction.user.id, self.target.value, self.reward.value,
             self.reason.value, max_h, self.duration, cost, expires),
        )
        embed = discord.Embed(title=f"🎯 BOUNTY CONTRACT — #{bid}", colour=discord.Colour.red())
        embed.add_field(name="🎯 Target",     value=self.target.value,   inline=True)
        embed.add_field(name="💰 Reward",     value=self.reward.value,   inline=True)
        embed.add_field(name="⏰ Duration",   value=f"{self.duration} day(s)", inline=True)
        embed.add_field(name="👥 Max Hunters",value=str(max_h),          inline=True)
        embed.add_field(name="📋 Reason",     value=self.reason.value,   inline=False)
        embed.set_footer(text=f"Posted by {interaction.user} • Pending staff review")

        # Send to staff for review
        ch_staff = await bot.db.channel(bot, "staff")
        if ch_staff:
            view = BountyReviewView(bid)
            msg = await ch_staff.send(embed=embed, view=view)
            await bot.db.exe("UPDATE bounties SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch_staff.id, bid))
        await eph(interaction, content=f"✅ Bounty #{bid} submitted for staff review!")


class BountyDurationView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        labels = ["1 Day — Free", "2 Days — 5 Coins", "3 Days — 7 Coins", "4 Days — 10 Coins"]
        for i, label in enumerate(labels, 1):
            self.add_item(BountyDurBtn(label, i))


class BountyDurBtn(discord.ui.Button):
    def __init__(self, label: str, days: int) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.days = days

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(BountyModal(self.days))


class BountyReviewView(discord.ui.View):
    def __init__(self, bid: int) -> None:
        super().__init__(timeout=None)
        self.bid = bid

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="bounty_approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        bounty = await bot.db.one("SELECT * FROM bounties WHERE id=?", (self.bid,))
        if not bounty:
            await eph(interaction, content="Bounty not found.")
            return
        await bot.db.exe("UPDATE bounties SET status='active' WHERE id=?", (self.bid,))
        await bot.db.log_staff(interaction.user.id, "approve_bounty", "bounty", str(self.bid))

        ch = await bot.db.channel(bot, "bounty")
        if ch:
            embed = discord.Embed(title=f"🎯 BOUNTY #{self.bid} — {bounty['target_name']}", colour=discord.Colour.red())
            embed.add_field(name="Reward",  value=bounty["reward"],  inline=True)
            embed.add_field(name="Reason",  value=bounty["reason"],  inline=False)
            accept_view = BountyAcceptView(self.bid)
            await ch.send(embed=embed, view=accept_view)
        await eph(interaction, content="✅ Bounty approved and posted!")

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger, custom_id="bounty_reject")
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await bot.db.exe("UPDATE bounties SET status='rejected' WHERE id=?", (self.bid,))
        await bot.db.log_staff(interaction.user.id, "reject_bounty", "bounty", str(self.bid))
        await eph(interaction, content="🗑️ Bounty rejected.")


class BountyAcceptView(discord.ui.View):
    def __init__(self, bid: int) -> None:
        super().__init__(timeout=None)
        self.bid = bid

    @discord.ui.button(label="Accept Contract", emoji="✅", style=discord.ButtonStyle.success,
                       custom_id="bounty_accept_contract")
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        bounty = await bot.db.one("SELECT * FROM bounties WHERE id=?", (self.bid,))
        if not bounty or bounty["status"] != "active":
            await eph(interaction, content="This bounty is no longer available.")
            return
        if interaction.user.id == bounty["creator_id"]:
            await eph(interaction, content="You cannot accept your own bounty.")
            return
        await eph(interaction, content=f"✅ You have accepted bounty #{self.bid}. Upload proof when done!")

    @discord.ui.button(label="Submit Proof", emoji="📸", style=discord.ButtonStyle.primary,
                       custom_id="bounty_proof")
    async def proof(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BountyProofModal(self.bid))


class BountyProofModal(discord.ui.Modal, title="Submit Bounty Proof"):
    image_url = discord.ui.TextInput(label="Screenshot URL",           max_length=300)
    note      = discord.ui.TextInput(label="Note (optional)", required=False, max_length=300)

    def __init__(self, bid: int) -> None:
        super().__init__()
        self.bid = bid

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ch_staff = await bot.db.channel(bot, "staff")
        embed = discord.Embed(title=f"📸 Bounty Proof — #{self.bid}", colour=discord.Colour.orange())
        embed.add_field(name="Submitted by", value=interaction.user.mention, inline=True)
        embed.set_image(url=self.image_url.value)
        if self.note.value:
            embed.add_field(name="Note", value=self.note.value, inline=False)
        if ch_staff:
            await ch_staff.send(embed=embed)
        await eph(interaction, content="✅ Proof submitted to staff for review!")


# ════════════════════════════════════════════════════════════════════════════════
# 3. COIN ECONOMY
# ════════════════════════════════════════════════════════════════════════════════

class BuyCoinsView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    @discord.ui.button(label="💳 Real Cash (UPI)", style=discord.ButtonStyle.primary)
    async def real_cash(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BuyCoinsRealModal())

    @discord.ui.button(label="🎮 Game Cash (5k/coin)", style=discord.ButtonStyle.secondary)
    async def game_cash(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BuyCoinsGameModal())

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await eph(interaction, content="Cancelled.")


class BuyCoinsRealModal(discord.ui.Modal, title="Buy Coins via UPI"):
    coins      = discord.ui.TextInput(label="How many coins? (₹1 each)", placeholder="e.g. 50", max_length=6)
    screenshot = discord.ui.TextInput(label="Payment Screenshot URL", max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        try:
            n = int(self.coins.value)
        except ValueError:
            await eph(interaction, content="❌ Invalid amount.")
            return
        price = f"₹{n}"
        pid = await bot.db.lid(
            "INSERT INTO coin_purchases (user_id,method,coins,price,screenshot_url) VALUES (?,?,?,?,?)",
            (interaction.user.id, "real_cash", n, price, self.screenshot.value),
        )
        embed = discord.Embed(title="💳 Coin Purchase Review", colour=discord.Colour.yellow())
        embed.add_field(name="User",   value=interaction.user.mention, inline=True)
        embed.add_field(name="Coins",  value=str(n),                   inline=True)
        embed.add_field(name="Price",  value=price,                    inline=True)
        embed.set_image(url=self.screenshot.value)
        embed.set_footer(text=f"Purchase #{pid}")

        ch = await bot.db.channel(bot, "coin_purchase")
        if ch:
            v = CoinApproveView(pid, n, interaction.user.id)
            await ch.send(embed=embed, view=v)
        await eph(interaction, content=f"✅ Payment submitted! Waiting for admin approval. (Ref #{pid})")


class BuyCoinsGameModal(discord.ui.Modal, title="Buy Coins via Game Cash"):
    amount = discord.ui.TextInput(label="Game Cash Amount", placeholder="e.g. 50000 or 50k", max_length=20)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        gc = parse_shorthand(self.amount.value)
        coins = gc // GAME_CASH_PER_COIN
        if coins < 1:
            await eph(interaction, content=f"❌ Minimum is {GAME_CASH_PER_COIN:,} game cash (= 1 coin).")
            return
        pid = await bot.db.lid(
            "INSERT INTO coin_purchases (user_id,method,coins,price) VALUES (?,?,?,?)",
            (interaction.user.id, "game_cash", coins, f"{gc:,} game cash"),
        )
        ch = await bot.db.channel(bot, "coin_purchase")
        embed = discord.Embed(title="🎮 Game Cash Coin Exchange", colour=discord.Colour.blurple())
        embed.add_field(name="User",        value=interaction.user.mention,      inline=True)
        embed.add_field(name="Game Cash",   value=f"{gc:,}",                     inline=True)
        embed.add_field(name="Coins",       value=str(coins),                    inline=True)
        embed.set_footer(text=f"Request #{pid} • Staff: collect game cash and approve")
        if ch:
            v = CoinApproveView(pid, coins, interaction.user.id)
            await ch.send(embed=embed, view=v)
        await eph(interaction, content=f"✅ Request sent! A staff member will collect {gc:,} game cash from you. (Ref #{pid})")


class CoinApproveView(discord.ui.View):
    def __init__(self, pid: int, coins: int, uid: int) -> None:
        super().__init__(timeout=None)
        self.pid   = pid
        self.coins = coins
        self.uid   = uid

    @discord.ui.button(label="✅ Approve & Credit", style=discord.ButtonStyle.success, custom_id="coin_approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await bot.db.exe("UPDATE coin_purchases SET status='approved',reviewed_by=? WHERE id=?",
                         (interaction.user.id, self.pid))
        await bot.db.ensure_user(discord.Object(id=self.uid))  # type: ignore
        await bot.db.add_coins(self.uid, self.coins)
        await bot.db.log_staff(interaction.user.id, "approve_coin_purchase", "purchase", str(self.pid))
        member = interaction.guild.get_member(self.uid) if interaction.guild else None
        if member:
            try:
                await member.send(f"🎉 {self.coins} KAT Coins have been credited to your wallet!")
            except discord.Forbidden:
                pass
        await eph(interaction, content=f"✅ {self.coins} coins credited to <@{self.uid}>.")

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger, custom_id="coin_reject")
    async def reject(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await bot.db.exe("UPDATE coin_purchases SET status='rejected',reviewed_by=? WHERE id=?",
                         (interaction.user.id, self.pid))
        member = interaction.guild.get_member(self.uid) if interaction.guild else None
        if member:
            try:
                await member.send("❌ Your coin purchase request was rejected. Contact staff for details.")
            except discord.Forbidden:
                pass
        await eph(interaction, content="🗑️ Purchase rejected.")


# ════════════════════════════════════════════════════════════════════════════════
# 4. GIVEAWAY
# ════════════════════════════════════════════════════════════════════════════════

class GiveawayTypeView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    @discord.ui.button(label="🎮 Game Cash", style=discord.ButtonStyle.primary)
    async def gc(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(GiveawayModal("game_cash"))

    @discord.ui.button(label="💵 Real Cash", style=discord.ButtonStyle.success)
    async def rc(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(GiveawayModal("real_cash"))

    @discord.ui.button(label="🚗 Game Items", style=discord.ButtonStyle.secondary)
    async def gi(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(GiveawayModal("items"))


class GiveawayModal(discord.ui.Modal, title="Setup Giveaway"):
    prize       = discord.ui.TextInput(label="Prize",             placeholder="e.g. $5,000,000 game cash", max_length=200)
    description = discord.ui.TextInput(label="Description",       style=discord.TextStyle.paragraph, max_length=500)
    duration    = discord.ui.TextInput(label="Duration (hours)",  placeholder="e.g. 24",           max_length=5)
    winners     = discord.ui.TextInput(label="Number of Winners", placeholder="1",                  max_length=3)

    def __init__(self, gtype: str) -> None:
        super().__init__()
        self.gtype = gtype

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        try:
            hrs  = max(1, int(self.duration.value))
            wins = max(1, int(self.winners.value))
        except ValueError:
            await eph(interaction, content="❌ Invalid numbers.")
            return

        ends_at = (utcnow() + timedelta(hours=hrs)).isoformat()
        gid = await bot.db.lid(
            "INSERT INTO giveaways (creator_id,giveaway_type,prize,description,winners_count,ends_at) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, self.gtype, self.prize.value, self.description.value, wins, ends_at),
        )
        embed = discord.Embed(title=f"🎉 GIVEAWAY — {self.prize.value}", colour=discord.Colour.gold())
        embed.add_field(name="Type",     value=self.gtype.replace("_", " ").title(), inline=True)
        embed.add_field(name="Winners",  value=str(wins),                            inline=True)
        embed.add_field(name="Ends",     value=f"<t:{int(utcnow().timestamp()) + hrs*3600}:R>", inline=True)
        embed.add_field(name="Hosted by", value=interaction.user.mention,            inline=True)
        if self.description.value:
            embed.add_field(name="Details", value=self.description.value, inline=False)
        embed.set_footer(text=f"Giveaway #{gid} • Pending approval")

        ch_staff = await bot.db.channel(bot, "staff")
        if ch_staff:
            await ch_staff.send(f"📋 New giveaway from {interaction.user.mention}", embed=embed,
                                view=GiveawayApproveView(gid))
        await eph(interaction, content=f"✅ Giveaway submitted for approval! (#{gid})")


class GiveawayApproveView(discord.ui.View):
    def __init__(self, gid: int) -> None:
        super().__init__(timeout=None)
        self.gid = gid

    @discord.ui.button(label="✅ Post Giveaway", style=discord.ButtonStyle.success, custom_id="gw_approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        gw = await bot.db.one("SELECT * FROM giveaways WHERE id=?", (self.gid,))
        if not gw:
            await eph(interaction, content="Giveaway not found.")
            return
        await bot.db.exe("UPDATE giveaways SET status='active' WHERE id=?", (self.gid,))
        ch = await bot.db.channel(bot, "giveaway")
        if ch:
            embed = discord.Embed(title=f"🎉 GIVEAWAY — {gw['prize']}", colour=discord.Colour.gold())
            embed.add_field(name="Winners", value=str(gw["winners_count"]), inline=True)
            embed.add_field(name="Ends",    value=f"<t:{int(datetime.fromisoformat(gw['ends_at']).timestamp())}:R>", inline=True)
            if gw["description"]:
                embed.add_field(name="Details", value=gw["description"], inline=False)
            msg = await ch.send(embed=embed, view=GiveawayEnterView(self.gid))
            await bot.db.exe("UPDATE giveaways SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch.id, self.gid))
        await eph(interaction, content="✅ Giveaway posted!")


class GiveawayEnterView(discord.ui.View):
    def __init__(self, gid: int) -> None:
        super().__init__(timeout=None)
        self.gid = gid

    @discord.ui.button(label="🎉 Participate", style=discord.ButtonStyle.success, custom_id="gw_enter")
    async def enter(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await bot.db.ensure_user(interaction.user)
        try:
            await bot.db.exe("INSERT INTO giveaway_entries (giveaway_id,user_id) VALUES (?,?)",
                             (self.gid, interaction.user.id))
            count = await bot.db.one("SELECT COUNT(*) as c FROM giveaway_entries WHERE giveaway_id=?",
                                     (self.gid,))
            await eph(interaction, content=f"✅ You're in! Total entries: {count['c']}")
        except Exception:
            await eph(interaction, content="You've already entered this giveaway!")


# ════════════════════════════════════════════════════════════════════════════════
# 5. REAL CASH MARKET (RCM)
# ════════════════════════════════════════════════════════════════════════════════

PAY_METHODS = ["UPI", "Google Pay Redeem Code", "USD", "Crypto", "Other"]


class SellCashModal(discord.ui.Modal, title="Sell Game Cash (RCM)"):
    amount     = discord.ui.TextInput(label="Amount of Game Cash",  placeholder="e.g. 100m or 100000000", max_length=20)
    rate       = discord.ui.TextInput(label="Rate per 1M (₹15–30)", placeholder="e.g. 20",               max_length=5)
    contact    = discord.ui.TextInput(label="Phone Number (private)",placeholder="Staff only",             max_length=20)
    pay_method = discord.ui.TextInput(label="Payment Method",       placeholder="UPI / Crypto / USD etc.", max_length=50)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        gc = parse_shorthand(self.amount.value)
        try:
            rate = int(self.rate.value)
            if not (15 <= rate <= 30):
                raise ValueError
        except ValueError:
            await eph(interaction, content="❌ Rate must be between ₹15 and ₹30 per million.")
            return

        total_inr = int((gc / 1_000_000) * rate)
        commission = 0.015 if gc < 50_000_000 else 0.01
        comm_gc = int(gc * commission)

        clid = await bot.db.lid(
            "INSERT INTO cash_listings (seller_id,amount,rate_per_m,total_inr,contact,pay_method,commission) "
            "VALUES (?,?,?,?,?,?,?)",
            (interaction.user.id, gc, rate, total_inr, self.contact.value, self.pay_method.value, commission),
        )
        embed = discord.Embed(title=f"💵 GAME CASH FOR SALE — #{clid}", colour=discord.Colour.green())
        embed.add_field(name="Amount",     value=f"{gc:,}",       inline=True)
        embed.add_field(name="Rate",       value=f"₹{rate}/1M",   inline=True)
        embed.add_field(name="Total",      value=f"₹{total_inr}", inline=True)
        embed.add_field(name="Commission", value=f"{comm_gc:,} game cash ({commission*100:.1f}%)", inline=True)
        embed.add_field(name="Payment",    value=self.pay_method.value, inline=True)
        embed.add_field(name="⚠️ Buyer Fee", value="₹20 transaction fee to admin UPI", inline=False)
        embed.set_footer(text=f"Listing #{clid} • Pending admin review")

        ch_staff = await bot.db.channel(bot, "staff")
        if ch_staff:
            await ch_staff.send(embed=embed, view=RCMApproveView(clid))
        await eph(interaction, content=f"✅ Cash listing #{clid} submitted for review!")


class RCMApproveView(discord.ui.View):
    def __init__(self, clid: int) -> None:
        super().__init__(timeout=None)
        self.clid = clid

    @discord.ui.button(label="✅ Approve & Post", style=discord.ButtonStyle.success, custom_id="rcm_approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cl = await bot.db.one("SELECT * FROM cash_listings WHERE id=?", (self.clid,))
        if not cl:
            await eph(interaction, content="Listing not found.")
            return
        await bot.db.exe("UPDATE cash_listings SET status='active' WHERE id=?", (self.clid,))
        ch = await bot.db.channel(bot, "marketplace")
        if ch:
            embed = discord.Embed(title=f"💵 GAME CASH — #{self.clid}", colour=discord.Colour.green())
            embed.add_field(name="Amount",  value=f"{cl['amount']:,}",    inline=True)
            embed.add_field(name="Rate",    value=f"₹{cl['rate_per_m']}/1M", inline=True)
            embed.add_field(name="Total",   value=f"₹{cl['total_inr']}", inline=True)
            embed.add_field(name="Payment", value=cl["pay_method"],       inline=True)
            embed.set_footer(text="Click 'Ask for Staff' to purchase • ₹20 buyer fee applies")
            msg = await ch.send(embed=embed, view=RCMBuyView(self.clid))
            await bot.db.exe("UPDATE cash_listings SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch.id, self.clid))
        await eph(interaction, content="✅ Posted to marketplace!")


class RCMBuyView(discord.ui.View):
    def __init__(self, clid: int) -> None:
        super().__init__(timeout=None)
        self.clid = clid

    @discord.ui.button(label="Ask for Staff", emoji="🛡️", style=discord.ButtonStyle.primary,
                       custom_id="rcm_buy")
    async def buy(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cl = await bot.db.one("SELECT * FROM cash_listings WHERE id=?", (self.clid,))
        if not cl:
            await eph(interaction, content="Listing not found.")
            return
        tid = await bot.db.lid(
            "INSERT INTO tickets (user_id,category,subject,description) VALUES (?,?,?,?)",
            (interaction.user.id, "rcm_buy",
             f"Buy Game Cash #{self.clid}",
             f"Buyer: {interaction.user} | Amount: {cl['amount']:,} | ₹{cl['total_inr']} + ₹20 fee"),
        )
        ch_staff = await bot.db.channel(bot, "staff")
        if ch_staff:
            embed = discord.Embed(title=f"🛒 RCM Purchase Ticket #{tid}", colour=discord.Colour.blurple())
            embed.add_field(name="Buyer",  value=interaction.user.mention,          inline=True)
            embed.add_field(name="Listing",value=f"#{self.clid}",                   inline=True)
            embed.add_field(name="Amount", value=f"{cl['amount']:,} game cash",     inline=True)
            embed.add_field(name="Price",  value=f"₹{cl['total_inr']} + ₹20 fee",  inline=True)
            await ch_staff.send(embed=embed)
        await eph(interaction, content=f"✅ Staff ticket #{tid} opened! Staff will contact you shortly. Remember to pay the ₹20 transaction fee first.")


# ════════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS — all registered here
# ════════════════════════════════════════════════════════════════════════════════

async def _register_all(bot_: KATBot) -> None:
    tree = bot_.tree
    db   = bot_.db

    # ── 1. MARKET TRADING ───────────────────────────────────────────────────
    @tree.command(name="sell_vehicle", description="List a vehicle for sale (Car, Bike, Boat, Helicopter)")
    async def sell_vehicle(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        view = VehicleTypeView()
        await interaction.response.send_message("🚗 **Select your vehicle type:**", view=view, ephemeral=True)

    @tree.command(name="sell_property", description="List a house or apartment for sale")
    async def sell_property(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SellPropertyModal())

    @tree.command(name="sell_business", description="List a business for sale (from the 76 business directory)")
    async def sell_business(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SellBusinessModal())

    @tree.command(name="sell_skin", description="List a skin or accessory for sale")
    async def sell_skin(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SellSkinModal())

    @tree.command(name="sell_item", description="List any game item for sale")
    @app_commands.describe(title="Item name", price="Asking price in game cash", description="Details about the item")
    async def sell_item(interaction: discord.Interaction, title: str, price: str, description: str = "") -> None:
        await db.ensure_user(interaction.user)
        p = parse_shorthand(price)
        lid = await db.lid(
            "INSERT INTO listings (seller_id,category,title,description,asking_price) VALUES (?,?,?,?,?)",
            (interaction.user.id, "item", title, description, p),
        )
        embed = discord.Embed(title=f"📦 ITEM FOR SALE — #{lid}", colour=discord.Colour.teal())
        embed.add_field(name="Item",    value=title,                    inline=True)
        embed.add_field(name="Price",   value=fmt_cash(p),              inline=True)
        embed.add_field(name="Seller",  value=interaction.user.mention, inline=True)
        if description:
            embed.add_field(name="Details", value=description, inline=False)
        ch = await require_channel(interaction, "marketplace")
        view = ListingActionView(lid)
        if ch:
            msg = await ch.send(embed=embed, view=view)
            await db.exe("UPDATE listings SET message_id=?,channel_id=? WHERE id=?",
                         (msg.id, ch.id, lid))
        await eph(interaction, content=f"✅ Item listed! #{lid}")

    @tree.command(name="my_listings", description="View your active listings")
    async def my_listings(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        rows = await db.all(
            "SELECT * FROM listings WHERE seller_id=? ORDER BY created_at DESC LIMIT 10",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="📋 My Listings", colour=discord.Colour.blurple())
        if not rows:
            embed.description = "You have no listings."
        for r in rows:
            s = "🟢" if r["status"] == "active" else "🔴"
            embed.add_field(
                name=f"{s} #{r['id']} — {r['category'].upper()}",
                value=f"**{r['title']}** | {fmt_cash(r['asking_price'])} | {r['status']}",
                inline=False,
            )
        await eph(interaction, embed=embed)

    @tree.command(name="delete_listing", description="Delete one of your listings")
    @app_commands.describe(listing_id="The listing ID to delete")
    async def delete_listing(interaction: discord.Interaction, listing_id: int) -> None:
        row = await db.one("SELECT * FROM listings WHERE id=? AND seller_id=?",
                           (listing_id, interaction.user.id))
        if not row:
            await eph(interaction, content="❌ Listing not found or not yours.")
            return
        await db.exe("UPDATE listings SET status='deleted' WHERE id=?", (listing_id,))
        await eph(interaction, content=f"✅ Listing #{listing_id} deleted.")

    @tree.command(name="market", description="Browse the marketplace")
    @app_commands.describe(category="Filter by category (vehicle/property/business/skin/item)")
    async def market(interaction: discord.Interaction, category: str = "all") -> None:
        if category.lower() == "all":
            rows = await db.all("SELECT * FROM listings WHERE status='active' ORDER BY created_at DESC LIMIT 8")
        else:
            rows = await db.all(
                "SELECT * FROM listings WHERE status='active' AND category=? ORDER BY created_at DESC LIMIT 8",
                (category.lower(),),
            )
        embed = discord.Embed(title=f"🛒 KAT Market — {category.upper()}", colour=discord.Colour.teal())
        if not rows:
            embed.description = "No active listings in this category."
        for r in rows:
            embed.add_field(
                name=f"#{r['id']} {r['title']}",
                value=f"💰 {fmt_cash(r['asking_price'])} | `{r['category']}`",
                inline=True,
            )
        await eph(interaction, embed=embed)

    @tree.command(name="market_search", description="Search listings by keyword")
    @app_commands.describe(keyword="Search term")
    async def market_search(interaction: discord.Interaction, keyword: str) -> None:
        rows = await db.all(
            "SELECT * FROM listings WHERE status='active' AND (title LIKE ? OR description LIKE ?) LIMIT 8",
            (f"%{keyword}%", f"%{keyword}%"),
        )
        embed = discord.Embed(title=f"🔍 Results for '{keyword}'", colour=discord.Colour.blue())
        if not rows:
            embed.description = "No listings found."
        for r in rows:
            embed.add_field(name=f"#{r['id']} {r['title']}",
                            value=fmt_cash(r["asking_price"]), inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="interested", description="Express interest in a listing")
    @app_commands.describe(listing_id="Listing ID")
    async def interested(interaction: discord.Interaction, listing_id: int) -> None:
        listing = await db.one("SELECT * FROM listings WHERE id=?", (listing_id,))
        if not listing:
            await eph(interaction, content="❌ Listing not found.")
            return
        if interaction.user.id == listing["seller_id"]:
            await eph(interaction, content="❌ You can't show interest in your own listing.")
            return
        seller = interaction.guild.get_member(listing["seller_id"]) if interaction.guild else None
        if seller:
            try:
                await seller.send(f"👀 **{interaction.user}** is interested in your listing #{listing_id}!")
            except discord.Forbidden:
                pass
        await eph(interaction, content="✅ Seller has been notified!")

    @tree.command(name="make_offer", description="Make an offer on a listing")
    @app_commands.describe(listing_id="Listing ID", amount="Your offer in game cash")
    async def make_offer(interaction: discord.Interaction, listing_id: int, amount: str) -> None:
        await db.ensure_user(interaction.user)
        listing = await db.one("SELECT * FROM listings WHERE id=?", (listing_id,))
        if not listing:
            await eph(interaction, content="❌ Listing not found.")
            return
        offer_amt = parse_shorthand(amount)
        await db.exe("INSERT INTO offers (listing_id,buyer_id,offer_amount) VALUES (?,?,?)",
                     (listing_id, interaction.user.id, offer_amt))
        seller = interaction.guild.get_member(listing["seller_id"]) if interaction.guild else None
        if seller:
            try:
                await seller.send(f"💰 **{interaction.user}** offered **{fmt_cash(offer_amt)}** on listing #{listing_id}!")
            except discord.Forbidden:
                pass
        await eph(interaction, content=f"✅ Offer of {fmt_cash(offer_amt)} sent!")

    @tree.command(name="watchlist", description="View your watchlist")
    async def watchlist_cmd(interaction: discord.Interaction) -> None:
        rows = await db.all(
            "SELECT w.*,l.title,l.asking_price FROM watchlist w JOIN listings l ON w.listing_id=l.id "
            "WHERE w.user_id=? LIMIT 10", (interaction.user.id,))
        embed = discord.Embed(title="👁️ My Watchlist", colour=discord.Colour.blurple())
        if not rows:
            embed.description = "Your watchlist is empty."
        for r in rows:
            embed.add_field(name=f"#{r['listing_id']} {r['title']}",
                            value=fmt_cash(r["asking_price"]), inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="watchlist_add", description="Add a listing to your watchlist")
    @app_commands.describe(listing_id="Listing ID to watch")
    async def watchlist_add(interaction: discord.Interaction, listing_id: int) -> None:
        await db.ensure_user(interaction.user)
        try:
            await db.exe("INSERT INTO watchlist (user_id,listing_id) VALUES (?,?)",
                         (interaction.user.id, listing_id))
            await eph(interaction, content=f"✅ Listing #{listing_id} added to watchlist!")
        except Exception:
            await eph(interaction, content="Already on your watchlist.")

    @tree.command(name="watchlist_remove", description="Remove a listing from your watchlist")
    @app_commands.describe(listing_id="Listing ID to remove")
    async def watchlist_remove(interaction: discord.Interaction, listing_id: int) -> None:
        await db.exe("DELETE FROM watchlist WHERE user_id=? AND listing_id=?",
                     (interaction.user.id, listing_id))
        await eph(interaction, content=f"✅ Listing #{listing_id} removed from watchlist.")

    @tree.command(name="create_auction", description="Create a timed auction for a listing")
    @app_commands.describe(title="Auction title", start_price="Starting bid", hours="Duration in hours")
    async def create_auction(interaction: discord.Interaction, title: str, start_price: str, hours: int = 24) -> None:
        await db.ensure_user(interaction.user)
        sp = parse_shorthand(start_price)
        ends = (utcnow() + timedelta(hours=hours)).isoformat()
        aid = await db.lid(
            "INSERT INTO auctions (seller_id,title,start_price,current_bid,ends_at) VALUES (?,?,?,?,?)",
            (interaction.user.id, title, sp, sp, ends),
        )
        embed = discord.Embed(title=f"🔨 AUCTION #{aid} — {title}", colour=discord.Colour.gold())
        embed.add_field(name="Start Bid", value=fmt_cash(sp), inline=True)
        embed.add_field(name="Ends",      value=f"<t:{int(utcnow().timestamp()) + hours*3600}:R>", inline=True)
        ch = await require_channel(interaction, "marketplace")
        if ch:
            msg = await ch.send(embed=embed, view=BidView(aid))
            await db.exe("UPDATE auctions SET message_id=?,channel_id=? WHERE id=?",
                         (msg.id, ch.id, aid))
        await eph(interaction, content=f"✅ Auction #{aid} created!")

    @tree.command(name="bid", description="Place a bid on an auction")
    @app_commands.describe(auction_id="Auction ID", amount="Your bid")
    async def bid_cmd(interaction: discord.Interaction, auction_id: int, amount: str) -> None:
        await db.ensure_user(interaction.user)
        auction = await db.one("SELECT * FROM auctions WHERE id=?", (auction_id,))
        if not auction or auction["status"] != "active":
            await eph(interaction, content="❌ Auction not found or ended.")
            return
        bid_amt = parse_shorthand(amount)
        if bid_amt <= auction["current_bid"]:
            await eph(interaction, content=f"❌ Bid must be higher than current bid of {fmt_cash(auction['current_bid'])}.")
            return
        await db.exe("INSERT INTO bids (auction_id,bidder_id,amount) VALUES (?,?,?)",
                     (auction_id, interaction.user.id, bid_amt))
        await db.exe("UPDATE auctions SET current_bid=?,top_bidder=? WHERE id=?",
                     (bid_amt, interaction.user.id, auction_id))
        await eph(interaction, content=f"✅ Bid of {fmt_cash(bid_amt)} placed on auction #{auction_id}!")

    @tree.command(name="recent_sales", description="View recent completed sales")
    async def recent_sales(interaction: discord.Interaction) -> None:
        rows = await db.all("SELECT * FROM trade_history ORDER BY completed_at DESC LIMIT 10")
        embed = discord.Embed(title="📜 Recent Sales", colour=discord.Colour.green())
        if not rows:
            embed.description = "No sales yet."
        for r in rows:
            embed.add_field(name=f"Listing #{r['listing_id']}",
                            value=f"💰 {fmt_cash(r['sale_price'])}", inline=True)
        await eph(interaction, embed=embed)

    # ── 2. DATABASE & LOCATION ──────────────────────────────────────────────
    @tree.command(name="whereis", description="Find the location of a business or property")
    @app_commands.describe(query="Business name or property number")
    async def whereis(interaction: discord.Interaction, query: str) -> None:
        biz = await db.all("SELECT * FROM businesses WHERE name LIKE ? OR location LIKE ?",
                           (f"%{query}%", f"%{query}%"))
        house = await db.all("SELECT * FROM houses WHERE address LIKE ? OR city LIKE ?",
                             (f"%{query}%", f"%{query}%"))
        apt = await db.all("SELECT * FROM apartments WHERE address LIKE ? OR city LIKE ?",
                           (f"%{query}%", f"%{query}%"))
        embed = discord.Embed(title=f"📍 Location: '{query}'", colour=discord.Colour.blue())
        for b in biz[:5]:
            embed.add_field(name=f"🏢 #{b['number']} {b['name']}", value=b["location"], inline=False)
        for h in house[:3]:
            embed.add_field(name=f"🏠 House #{h['number']}", value=f"{h['city']} — {h.get('address','')}", inline=False)
        for a in apt[:3]:
            embed.add_field(name=f"🏢 Apt #{a['number']}", value=f"{a['city']} — {a.get('address','')}", inline=False)
        if not embed.fields:
            embed.description = "Nothing found."
        await eph(interaction, embed=embed)

    @tree.command(name="find_property", description="Search available houses/apartments by city or type")
    @app_commands.describe(city="City name", prop_type="eco/std/lux or std/lux for apartments")
    async def find_property(interaction: discord.Interaction, city: str = "", prop_type: str = "") -> None:
        q = "SELECT * FROM houses WHERE 1=1"
        p: list = []
        if city:
            q += " AND city LIKE ?"; p.append(f"%{city}%")
        if prop_type:
            q += " AND type LIKE ?"; p.append(f"%{prop_type}%")
        q += " LIMIT 10"
        rows = await db.all(q, tuple(p))
        embed = discord.Embed(title="🏠 Property Search", colour=discord.Colour.blue())
        if not rows:
            embed.description = "No properties found."
        for r in rows:
            embed.add_field(name=f"#{r['number']} — {r['city']}",
                            value=f"Type: {r.get('type','—')} | {r.get('address','')}", inline=False)
        await eph(interaction, embed=embed)

    @tree.command(name="find_business", description="Find businesses by type")
    @app_commands.describe(biz_type="e.g. Shop 24/7, Restaurant, Gas Station")
    async def find_business(interaction: discord.Interaction, biz_type: str) -> None:
        rows = await db.all("SELECT * FROM businesses WHERE name LIKE ? LIMIT 15", (f"%{biz_type}%",))
        embed = discord.Embed(title=f"🏢 Businesses: {biz_type}", colour=discord.Colour.gold())
        if not rows:
            embed.description = "None found."
        for r in rows:
            embed.add_field(name=f"#{r['number']} {r['name']}", value=r["location"], inline=False)
        await eph(interaction, embed=embed)

    @tree.command(name="ownership_history", description="View ownership history of a property/vehicle")
    @app_commands.describe(asset_type="vehicle/property/business", asset_ref="ID or number")
    async def ownership_history_cmd(interaction: discord.Interaction, asset_type: str, asset_ref: str) -> None:
        rows = await db.all(
            "SELECT * FROM ownership_history WHERE asset_type=? AND asset_ref=? ORDER BY acquired_at DESC LIMIT 10",
            (asset_type, asset_ref),
        )
        embed = discord.Embed(title=f"📜 Ownership History — {asset_type} #{asset_ref}", colour=discord.Colour.blurple())
        if not rows:
            embed.description = "No history found."
        for r in rows:
            embed.add_field(name=r["owner_name"],
                            value=f"💰 {fmt_cash(r['price'])} | {r['acquired_at'][:10]}", inline=False)
        await eph(interaction, embed=embed)

    # ── 3. FINANCE & ECONOMY ────────────────────────────────────────────────
    @tree.command(name="wallet", description="Check your KAT Coins balance")
    async def wallet(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        row = await db.one("SELECT kat_coins, game_cash FROM users WHERE user_id=?", (interaction.user.id,))
        embed = discord.Embed(title="💰 My Wallet", colour=discord.Colour.gold())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="🪙 KAT Coins",  value=str(row["kat_coins"]),       inline=True)
        embed.add_field(name="💵 Game Cash",   value=fmt_cash(row["game_cash"]),  inline=True)
        view = WalletView()
        await eph(interaction, embed=embed, view=view)

    @tree.command(name="buy_coins", description="Purchase KAT Coins via UPI or game cash")
    async def buy_coins(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        embed = discord.Embed(
            title="🪙 Buy KAT Coins",
            description=f"**Rate:** ₹1 = 1 Coin | 5,000 Game Cash = 1 Coin\n\nUPI: `{UPI_ID}`",
            colour=discord.Colour.gold(),
        )
        await interaction.response.send_message(embed=embed, view=BuyCoinsView(), ephemeral=True)

    @tree.command(name="daily", description="Claim your daily reward (5 coins + $50,000)")
    async def daily(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        row = await db.one("SELECT daily_last FROM users WHERE user_id=?", (interaction.user.id,))
        last = row["daily_last"]
        now  = utcnow()
        if last:
            last_dt = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
            if (now - last_dt).total_seconds() < 86400:
                remaining = 86400 - int((now - last_dt).total_seconds())
                h, m = divmod(remaining // 60, 60)
                await eph(interaction, content=f"⏰ Daily already claimed. Come back in {h}h {m}m.")
                return
        await db.exe("UPDATE users SET kat_coins=kat_coins+5, game_cash=game_cash+50000, daily_last=? WHERE user_id=?",
                     (now.isoformat(), interaction.user.id))
        embed = discord.Embed(title="🎁 Daily Reward!", colour=discord.Colour.gold())
        embed.add_field(name="🪙 +5 KAT Coins", value="", inline=True)
        embed.add_field(name="💵 +$50,000",      value="", inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="weekly", description="Claim your weekly reward (25 coins + $500,000 + 2 crates)")
    async def weekly(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        row = await db.one("SELECT weekly_last FROM users WHERE user_id=?", (interaction.user.id,))
        last = row["weekly_last"]
        now  = utcnow()
        if last:
            last_dt = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
            if (now - last_dt).total_seconds() < 604800:
                remaining = 604800 - int((now - last_dt).total_seconds())
                d, rem = divmod(remaining, 86400)
                h = rem // 3600
                await eph(interaction, content=f"⏰ Weekly already claimed. Come back in {d}d {h}h.")
                return
        await db.exe(
            "UPDATE users SET kat_coins=kat_coins+25, game_cash=game_cash+500000, weekly_last=? WHERE user_id=?",
            (now.isoformat(), interaction.user.id),
        )
        embed = discord.Embed(title="🎁 Weekly Reward!", colour=discord.Colour.purple())
        embed.add_field(name="🪙 +25 KAT Coins",  value="", inline=True)
        embed.add_field(name="💵 +$500,000",       value="", inline=True)
        embed.add_field(name="📦 +2 Crates",       value="", inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="richlist", description="Top 10 richest players by KAT Coins")
    async def richlist(interaction: discord.Interaction) -> None:
        rows = await db.all("SELECT username,kat_coins FROM users ORDER BY kat_coins DESC LIMIT 10")
        embed = discord.Embed(title="💎 Rich List", colour=discord.Colour.gold())
        medals = ["🥇","🥈","🥉"] + ["🏅"]*7
        for i, r in enumerate(rows):
            embed.add_field(name=f"{medals[i]} {r['username']}", value=f"🪙 {r['kat_coins']}", inline=False)
        await eph(interaction, embed=embed)

    @tree.command(name="networth", description="Check your net worth")
    @app_commands.describe(user="User to check (optional)")
    async def networth(interaction: discord.Interaction, user: discord.Member = None) -> None:
        target = user or interaction.user
        await db.ensure_user(target)
        row = await db.one("SELECT kat_coins,game_cash,trade_count FROM users WHERE user_id=?", (target.id,))
        embed = discord.Embed(title=f"💰 Net Worth — {target.display_name}", colour=discord.Colour.gold())
        embed.add_field(name="🪙 KAT Coins", value=str(row["kat_coins"]),      inline=True)
        embed.add_field(name="💵 Game Cash", value=fmt_cash(row["game_cash"]), inline=True)
        embed.add_field(name="🤝 Trades",    value=str(row["trade_count"]),    inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="deposit", description="Lock game cash into a fixed deposit")
    @app_commands.describe(amount="Amount to deposit", days="Lock period in days")
    async def deposit(interaction: discord.Interaction, amount: str, days: int = 30) -> None:
        await db.ensure_user(interaction.user)
        amt = parse_shorthand(amount)
        row = await db.one("SELECT game_cash FROM users WHERE user_id=?", (interaction.user.id,))
        if row["game_cash"] < amt:
            await eph(interaction, content="❌ Insufficient game cash.")
            return
        await db.exe("UPDATE users SET game_cash=game_cash-? WHERE user_id=?", (amt, interaction.user.id))
        maturity = (utcnow() + timedelta(days=days)).isoformat()
        await db.lid(
            "INSERT INTO fixed_deposits (user_id,amount,maturity) VALUES (?,?,?)",
            (interaction.user.id, amt, maturity),
        )
        await eph(interaction, content=f"✅ Deposited {fmt_cash(amt)} for {days} days. Matures: {maturity[:10]}")

    @tree.command(name="transaction_history", description="View your recent transactions")
    async def transaction_history(interaction: discord.Interaction) -> None:
        rows = await db.all(
            "SELECT * FROM trade_history WHERE seller_id=? OR buyer_id=? ORDER BY completed_at DESC LIMIT 10",
            (interaction.user.id, interaction.user.id),
        )
        embed = discord.Embed(title="📜 Transaction History", colour=discord.Colour.blurple())
        if not rows:
            embed.description = "No transactions yet."
        for r in rows:
            role = "Seller" if r["seller_id"] == interaction.user.id else "Buyer"
            embed.add_field(name=f"#{r['listing_id']} ({role})",
                            value=fmt_cash(r["sale_price"]), inline=True)
        await eph(interaction, embed=embed)

    # ── 4. COMMUNITY & PROFILES ─────────────────────────────────────────────
    @tree.command(name="create_profile", description="Set up your in-game identity")
    @app_commands.describe(in_game_msg="Your in-game message/status", contact="Your in-game phone number")
    async def create_profile(interaction: discord.Interaction, in_game_msg: str, contact: str) -> None:
        await db.ensure_user(interaction.user)
        await db.exe("UPDATE users SET profile_msg=?,profile_contact=? WHERE user_id=?",
                     (in_game_msg, contact, interaction.user.id))
        await eph(interaction, content="✅ Profile updated!")

    @tree.command(name="profile", description="View a player's KAT Market profile")
    @app_commands.describe(user="User to view (optional)")
    async def profile(interaction: discord.Interaction, user: discord.Member = None) -> None:
        target = user or interaction.user
        await db.ensure_user(target)
        row = await db.one("SELECT * FROM users WHERE user_id=?", (target.id,))
        embed = discord.Embed(title=f"👤 {target.display_name}", colour=discord.Colour.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🪙 KAT Coins",    value=str(row["kat_coins"]),           inline=True)
        embed.add_field(name="⭐ Reputation",    value=f"{row['reputation']:.1f}/10.0", inline=True)
        embed.add_field(name="🤝 Trades",        value=str(row["trade_count"]),         inline=True)
        embed.add_field(name="💍 Status",        value=row["marital_status"],           inline=True)
        embed.add_field(name="✅ Verified",      value="Yes" if row["is_verified"] else "No", inline=True)
        if row.get("profile_msg"):
            embed.add_field(name="💬 In-Game Status", value=row["profile_msg"], inline=False)
        await eph(interaction, embed=embed)

    @tree.command(name="lookingfor", description="Look up another player's in-game contact")
    @app_commands.describe(user="The player to look up")
    async def lookingfor(interaction: discord.Interaction, user: discord.Member) -> None:
        row = await db.one("SELECT profile_msg,profile_contact FROM users WHERE user_id=?", (user.id,))
        if not row or not row.get("profile_contact"):
            await eph(interaction, content=f"❌ {user.display_name} has not set up their profile yet.")
            return
        embed = discord.Embed(title=f"🔍 {user.display_name}", colour=discord.Colour.blue())
        embed.add_field(name="💬 Message",  value=row.get("profile_msg") or "—", inline=False)
        embed.add_field(name="📱 Contact",  value=row["profile_contact"],       inline=False)
        await eph(interaction, embed=embed)

    @tree.command(name="vouch", description="Leave a vouch/review for a trader")
    @app_commands.describe(user="Who to vouch for", rating="1–10", message="Your review")
    async def vouch(interaction: discord.Interaction, user: discord.Member, rating: int, message: str = "") -> None:
        if user.id == interaction.user.id:
            await eph(interaction, content="❌ Cannot vouch for yourself.")
            return
        rating = max(1, min(10, rating))
        await db.exe("INSERT INTO vouches (from_id,to_id,rating,message) VALUES (?,?,?,?)",
                     (interaction.user.id, user.id, rating, message))
        avg = await db.one("SELECT AVG(rating) as avg FROM vouches WHERE to_id=?", (user.id,))
        if avg:
            await db.exe("UPDATE users SET reputation=? WHERE user_id=?",
                         (round(avg["avg"], 2), user.id))
        await eph(interaction, content=f"✅ Vouch submitted for {user.display_name}! Rating: {rating}/10")

    @tree.command(name="give_comment", description="Give +/- reputation feedback to a player")
    @app_commands.describe(user="Target player", positive="True = positive, False = negative", comment="Your comment")
    async def give_comment(interaction: discord.Interaction, user: discord.Member, positive: bool, comment: str) -> None:
        delta = 0.5 if positive else -0.5
        await db.ensure_user(user)
        await db.exe("UPDATE users SET reputation=MAX(0,MIN(10,reputation+?)) WHERE user_id=?",
                     (delta, user.id))
        ch = await db.channel(bot_, "report")
        embed = discord.Embed(title="💬 Reputation Comment",
                              colour=discord.Colour.green() if positive else discord.Colour.red())
        embed.add_field(name="From",    value=interaction.user.mention, inline=True)
        embed.add_field(name="To",      value=user.mention,             inline=True)
        embed.add_field(name="Type",    value="✅ Positive" if positive else "❌ Negative", inline=True)
        embed.add_field(name="Comment", value=comment, inline=False)
        if ch:
            await ch.send(embed=embed)
        await eph(interaction, content=f"✅ Feedback submitted for {user.display_name}!")

    @tree.command(name="reputation", description="View reputation of a player")
    @app_commands.describe(user="User to check")
    async def reputation(interaction: discord.Interaction, user: discord.Member = None) -> None:
        target = user or interaction.user
        row = await db.one("SELECT reputation,trade_count FROM users WHERE user_id=?", (target.id,))
        if not row:
            await eph(interaction, content="User has no profile.")
            return
        embed = discord.Embed(title=f"⭐ Reputation — {target.display_name}", colour=discord.Colour.gold())
        embed.add_field(name="Score",  value=f"{row['reputation']:.1f}/10.0", inline=True)
        embed.add_field(name="Trades", value=str(row["trade_count"]),         inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="leaderboard", description="Top traders leaderboard")
    async def leaderboard(interaction: discord.Interaction) -> None:
        rows = await db.all("SELECT username,trade_count,reputation FROM users ORDER BY trade_count DESC LIMIT 10")
        embed = discord.Embed(title="🏆 Trade Leaderboard", colour=discord.Colour.gold())
        medals = ["🥇","🥈","🥉"] + ["🏅"]*7
        for i, r in enumerate(rows):
            embed.add_field(name=f"{medals[i]} {r['username']}",
                            value=f"🤝 {r['trade_count']} trades | ⭐ {r['reputation']:.1f}", inline=False)
        await eph(interaction, embed=embed)

    # ── 5. BOUNTY SYSTEM ────────────────────────────────────────────────────
    @tree.command(name="bounty_request", description="Post a bounty contract (/kill)")
    async def bounty_request(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        view = BountyDurationView()
        embed = discord.Embed(
            title="🎯 Bounty Contract",
            description="Select listing duration:\n• 1 Day — Free\n• 2 Days — 5 Coins\n• 3 Days — 7 Coins\n• 4 Days — 10 Coins",
            colour=discord.Colour.red(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @tree.command(name="contract_dossier", description="View all active bounty contracts")
    async def contract_dossier(interaction: discord.Interaction) -> None:
        rows = await db.all("SELECT * FROM bounties WHERE status='active' ORDER BY created_at DESC LIMIT 10")
        embed = discord.Embed(title="🎯 Active Bounties", colour=discord.Colour.red())
        if not rows:
            embed.description = "No active bounties."
        for r in rows:
            embed.add_field(name=f"#{r['id']} — {r['target_name']}",
                            value=f"💰 {r['reward']} | {r['duration']} day(s)", inline=False)
        await eph(interaction, embed=embed)

    @tree.command(name="create_contract", description="Create a custom written contract")
    @app_commands.describe(title="Contract title", terms="Contract terms")
    async def create_contract(interaction: discord.Interaction, title: str, terms: str) -> None:
        await db.ensure_user(interaction.user)
        cid = await db.lid(
            "INSERT INTO contracts (creator_id,title,terms) VALUES (?,?,?)",
            (interaction.user.id, title, terms),
        )
        await eph(interaction, content=f"✅ Contract #{cid} created! Use `/accept_contract` to get someone to sign.")

    @tree.command(name="accept_contract", description="Accept/sign a contract")
    @app_commands.describe(contract_id="Contract ID")
    async def accept_contract(interaction: discord.Interaction, contract_id: int) -> None:
        c = await db.one("SELECT * FROM contracts WHERE id=?", (contract_id,))
        if not c:
            await eph(interaction, content="❌ Contract not found.")
            return
        await db.exe("UPDATE contracts SET status='active' WHERE id=?", (contract_id,))
        await eph(interaction, content=f"✅ You have accepted and signed contract #{contract_id}.")

    @tree.command(name="cancel_contract", description="Cancel a contract you created")
    @app_commands.describe(contract_id="Contract ID")
    async def cancel_contract(interaction: discord.Interaction, contract_id: int) -> None:
        c = await db.one("SELECT * FROM contracts WHERE id=? AND creator_id=?",
                         (contract_id, interaction.user.id))
        if not c:
            await eph(interaction, content="❌ Contract not found or not yours.")
            return
        await db.exe("UPDATE contracts SET status='cancelled' WHERE id=?", (contract_id,))
        await eph(interaction, content=f"✅ Contract #{contract_id} cancelled.")

    # ── 6. SECURITY & VERIFICATION ──────────────────────────────────────────
    @tree.command(name="report_user", description="Report a player for scamming or misconduct")
    @app_commands.describe(user="User to report", reason="Reason for report", evidence="Screenshot URL (optional)")
    async def report_user(interaction: discord.Interaction, user: discord.Member, reason: str, evidence: str = "") -> None:
        rid = await db.lid(
            "INSERT INTO reports (reporter_id,target_type,target_id,reason,evidence_url) VALUES (?,?,?,?,?)",
            (interaction.user.id, "user", str(user.id), reason, evidence or None),
        )
        ch = await db.channel(bot_, "report")
        embed = discord.Embed(title=f"🚨 User Report #{rid}", colour=discord.Colour.red())
        embed.add_field(name="Reporter", value=interaction.user.mention, inline=True)
        embed.add_field(name="Target",   value=user.mention,             inline=True)
        embed.add_field(name="Reason",   value=reason,                   inline=False)
        if evidence:
            embed.set_image(url=evidence)
        if ch:
            await ch.send(embed=embed)
        await eph(interaction, content=f"✅ Report #{rid} submitted to staff.")

    @tree.command(name="report_listing", description="Report a suspicious listing")
    @app_commands.describe(listing_id="Listing ID", reason="Reason")
    async def report_listing(interaction: discord.Interaction, listing_id: int, reason: str) -> None:
        rid = await db.lid(
            "INSERT INTO reports (reporter_id,target_type,target_id,reason) VALUES (?,?,?,?)",
            (interaction.user.id, "listing", str(listing_id), reason),
        )
        ch = await db.channel(bot_, "report")
        if ch:
            await ch.send(f"🚨 **Listing Report #{rid}**: Listing #{listing_id} reported by {interaction.user.mention}\n**Reason:** {reason}")
        await eph(interaction, content=f"✅ Listing report #{rid} submitted.")

    @tree.command(name="dispute", description="Open a trade dispute")
    @app_commands.describe(description="Describe the dispute", evidence="Screenshot URL (optional)")
    async def dispute(interaction: discord.Interaction, description: str, evidence: str = "") -> None:
        tid = await db.lid(
            "INSERT INTO tickets (user_id,category,subject,description) VALUES (?,?,?,?)",
            (interaction.user.id, "dispute", "Trade Dispute", description),
        )
        ch = await db.channel(bot_, "staff")
        embed = discord.Embed(title=f"⚖️ Dispute #{tid}", colour=discord.Colour.orange())
        embed.add_field(name="User", value=interaction.user.mention, inline=True)
        embed.add_field(name="Details", value=description, inline=False)
        if evidence:
            embed.set_image(url=evidence)
        if ch:
            await ch.send(embed=embed)
        await eph(interaction, content=f"✅ Dispute #{tid} opened with staff.")

    # ── 7. EVENTS & GIVEAWAYS ───────────────────────────────────────────────
    @tree.command(name="giveaway", description="Host a community giveaway")
    async def giveaway(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        embed = discord.Embed(title="🎉 Setup Giveaway", description="Select your giveaway type:", colour=discord.Colour.gold())
        await interaction.response.send_message(embed=embed, view=GiveawayTypeView(), ephemeral=True)

    @tree.command(name="events", description="View upcoming community events")
    async def events_cmd(interaction: discord.Interaction) -> None:
        rows = await db.all("SELECT * FROM events WHERE status='approved' ORDER BY event_time ASC LIMIT 8")
        embed = discord.Embed(title="📅 Upcoming Events", colour=discord.Colour.blurple())
        if not rows:
            embed.description = "No upcoming events."
        for r in rows:
            embed.add_field(name=r["name"],
                            value=f"🏆 {r.get('prize','?')} | 📍 {r.get('location','?')} | ⏰ {r.get('event_time','?')[:16]}",
                            inline=False)
        await eph(interaction, embed=embed)

    @tree.command(name="create_event", description="[Staff] Create a community event")
    @has_role(STAFF_ROLE, SENIOR_STAFF_ROLE, ADMIN_ROLE)
    async def create_event(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateEventModal())

    @tree.command(name="creat_occasion", description="Propose a special occasion/event")
    async def creat_occasion(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(OccasionModal())

    # ── 8. ADVERTISING ──────────────────────────────────────────────────────
    @tree.command(name="rent_channel", description="Post a housing, rental, or personal advertisement (20 coins)")
    async def rent_channel(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        ok = await db.deduct_coins(interaction.user.id, 20)
        if not ok:
            await eph(interaction, content="❌ You need 20 KAT Coins to post an ad.")
            return
        await interaction.response.send_modal(AdvertiseModal("rental"))

    @tree.command(name="promote_business", description="Promote your business (20 coins)")
    async def promote_business(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        ok = await db.deduct_coins(interaction.user.id, 20)
        if not ok:
            await eph(interaction, content="❌ You need 20 KAT Coins.")
            return
        await interaction.response.send_modal(AdvertiseModal("business"))

    @tree.command(name="promote_family", description="Post a family recruitment ad (20 coins)")
    async def promote_family(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        ok = await db.deduct_coins(interaction.user.id, 20)
        if not ok:
            await eph(interaction, content="❌ You need 20 KAT Coins.")
            return
        await interaction.response.send_modal(AdvertiseModal("family"))

    @tree.command(name="ad_ledger", description="View your active advertisements")
    async def ad_ledger(interaction: discord.Interaction) -> None:
        rows = await db.all(
            "SELECT * FROM advertisements WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
            (interaction.user.id,),
        )
        embed = discord.Embed(title="📋 My Advertisements", colour=discord.Colour.teal())
        if not rows:
            embed.description = "No advertisements."
        for r in rows:
            s = "🟢" if r["status"] == "active" else "🔴"
            embed.add_field(name=f"{s} #{r['id']} — {r['ad_type']}",
                            value=f"{r['content'][:60]}…", inline=False)
        await eph(interaction, embed=embed)

    # ── 9. SOCIAL — MARRIAGE & DATING ───────────────────────────────────────
    @tree.command(name="lookingfor_date", description="Post a dating listing (20 coins)")
    async def lookingfor_date(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        row = await db.one("SELECT marital_status FROM users WHERE user_id=?", (interaction.user.id,))
        if row and row["marital_status"] == "Married":
            await eph(interaction, content="❌ You are already married!")
            return
        ok = await db.deduct_coins(interaction.user.id, 20)
        if not ok:
            await eph(interaction, content="❌ You need 20 KAT Coins.")
            return
        await interaction.response.send_modal(DatingModal())

    @tree.command(name="rightto", description="Propose marriage to another player")
    @app_commands.describe(user="The player you want to propose to")
    async def rightto(interaction: discord.Interaction, user: discord.Member) -> None:
        await db.ensure_user(interaction.user)
        if user.id == interaction.user.id:
            await eph(interaction, content="❌ You cannot propose to yourself.")
            return
        pid = await db.lid(
            "INSERT INTO proposals (from_id,to_id) VALUES (?,?)",
            (interaction.user.id, user.id),
        )
        embed = discord.Embed(title="💍 Marriage Proposal", colour=discord.Colour.pink())
        embed.description = f"**{interaction.user.display_name}** has proposed to **{user.display_name}**!"
        view = ProposalResponseView(pid, interaction.user.id, user.id)
        try:
            await user.send(embed=embed, view=view)
        except discord.Forbidden:
            pass
        await eph(interaction, content=f"💍 Proposal sent to {user.display_name}!")

    @tree.command(name="letter_to", description="Send a love letter to another player (10 coins)")
    @app_commands.describe(user="Recipient", message="Your letter")
    async def letter_to(interaction: discord.Interaction, user: discord.Member, message: str) -> None:
        ok = await db.deduct_coins(interaction.user.id, 10)
        if not ok:
            await eph(interaction, content="❌ You need 10 KAT Coins.")
            return
        embed = discord.Embed(title=f"💌 Love Letter from {interaction.user.display_name}", colour=discord.Colour.pink())
        embed.description = message
        embed.set_footer(text="Reply via /rightto to propose!")
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass
        await eph(interaction, content=f"💌 Letter sent to {user.display_name}!")

    @tree.command(name="divorce", description="File for divorce")
    async def divorce(interaction: discord.Interaction) -> None:
        row = await db.one("SELECT marital_status,spouse_id FROM users WHERE user_id=?", (interaction.user.id,))
        if not row or row["marital_status"] != "Married":
            await eph(interaction, content="❌ You are not married.")
            return
        spouse_id = row["spouse_id"]
        await db.exe("UPDATE users SET marital_status='Single',spouse_id=NULL WHERE user_id=?",
                     (interaction.user.id,))
        if spouse_id:
            await db.exe("UPDATE users SET marital_status='Single',spouse_id=NULL WHERE user_id=?",
                         (spouse_id,))
        await eph(interaction, content="💔 Divorce processed.")

    @tree.command(name="spouse", description="View your spouse's profile")
    async def spouse(interaction: discord.Interaction) -> None:
        row = await db.one("SELECT marital_status,spouse_id FROM users WHERE user_id=?", (interaction.user.id,))
        if not row or row["marital_status"] != "Married":
            await eph(interaction, content="You are not married.")
            return
        if not row["spouse_id"]:
            await eph(interaction, content="No spouse linked.")
            return
        sp = bot_.get_user(row["spouse_id"])
        await eph(interaction, content=f"💍 Your spouse: {sp.mention if sp else f'<@{row[\"spouse_id\"]}>'}")

    # ── 10. BIRTHDAY ────────────────────────────────────────────────────────
    @tree.command(name="set_birthday", description="Register your birthday")
    @app_commands.describe(day="Day (1-31)", month="Month (1-12)", year="Year (e.g. 2000)")
    async def set_birthday(interaction: discord.Interaction, day: int, month: int, year: int) -> None:
        await db.ensure_user(interaction.user)
        await db.exe(
            "UPDATE users SET birthday_day=?,birthday_month=?,birthday_year=?,birthday_status='pending' WHERE user_id=?",
            (day, month, year, interaction.user.id),
        )
        ch = await db.channel(bot_, "staff")
        if ch:
            embed = discord.Embed(title="🎂 Birthday Registration", colour=discord.Colour.orange())
            embed.add_field(name="User", value=interaction.user.mention, inline=True)
            embed.add_field(name="Date", value=f"{day:02d}/{month:02d}/{year}", inline=True)
            await ch.send(embed=embed, view=BirthdayApproveView(interaction.user.id))
        await eph(interaction, content=f"✅ Birthday {day:02d}/{month:02d}/{year} submitted for verification!")

    @tree.command(name="my_birthday", description="Check your registered birthday status")
    async def my_birthday(interaction: discord.Interaction) -> None:
        row = await db.one("SELECT birthday_day,birthday_month,birthday_year,birthday_status FROM users WHERE user_id=?",
                           (interaction.user.id,))
        if not row or not row.get("birthday_day"):
            await eph(interaction, content="No birthday registered. Use /set_birthday.")
            return
        embed = discord.Embed(title="🎂 My Birthday", colour=discord.Colour.gold())
        embed.add_field(name="Date",   value=f"{row['birthday_day']:02d}/{row['birthday_month']:02d}/{row['birthday_year']}", inline=True)
        embed.add_field(name="Status", value=row["birthday_status"].capitalize(), inline=True)
        await eph(interaction, embed=embed)

    # ── 11. SELL CASH (RCM) ─────────────────────────────────────────────────
    @tree.command(name="sell_cash", description="List game cash for real money sale (RCM)")
    async def sell_cash(interaction: discord.Interaction) -> None:
        await db.ensure_user(interaction.user)
        await interaction.response.send_modal(SellCashModal())

    # ── 12. AI SERVICES ─────────────────────────────────────────────────────
    @tree.command(name="generate_listing", description="Use AI to generate a professional listing description")
    @app_commands.describe(item="What are you selling?", details="Any key details")
    async def generate_listing(interaction: discord.Interaction, item: str, details: str = "") -> None:
        await eph(interaction, content=f"🤖 AI listing for **{item}**: *[Connect your AI service in the ai_services cog to enable this feature]*")

    @tree.command(name="price_check", description="Get an AI price estimate for your item")
    @app_commands.describe(item="Item to price check")
    async def price_check(interaction: discord.Interaction, item: str) -> None:
        await eph(interaction, content=f"🤖 Price check for **{item}**: *[Connect your AI service in the ai_services cog]*")

    @tree.command(name="market_advisor", description="Get AI market advice")
    @app_commands.describe(question="Your market question")
    async def market_advisor(interaction: discord.Interaction, question: str) -> None:
        await eph(interaction, content=f"🤖 *[Connect your AI service in the ai_services cog]*\n**Question:** {question}")

    # ── 13. ANALYTICS ───────────────────────────────────────────────────────
    @tree.command(name="market_stats", description="View overall marketplace statistics")
    async def market_stats(interaction: discord.Interaction) -> None:
        listings   = await db.one("SELECT COUNT(*) as c FROM listings WHERE status='active'")
        users      = await db.one("SELECT COUNT(*) as c FROM users")
        trades     = await db.one("SELECT COUNT(*) as c FROM trade_history")
        embed = discord.Embed(title="📊 Market Statistics", colour=discord.Colour.blurple())
        embed.add_field(name="Active Listings", value=str(listings["c"]),  inline=True)
        embed.add_field(name="Total Members",   value=str(users["c"]),     inline=True)
        embed.add_field(name="Completed Trades",value=str(trades["c"]),    inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="top_sellers", description="Top 10 sellers by trade count")
    async def top_sellers(interaction: discord.Interaction) -> None:
        rows = await db.all("SELECT username,trade_count,total_sales FROM users ORDER BY trade_count DESC LIMIT 10")
        embed = discord.Embed(title="🏆 Top Sellers", colour=discord.Colour.gold())
        for i, r in enumerate(rows, 1):
            embed.add_field(name=f"#{i} {r['username']}",
                            value=f"🤝 {r['trade_count']} trades | 💰 {fmt_cash(r['total_sales'])}", inline=False)
        await eph(interaction, embed=embed)

    # ── 14. WISHLIST / WANTED ───────────────────────────────────────────────
    @tree.command(name="wanted_post", description="Post a 'wanted' ad for something you're looking to buy")
    @app_commands.describe(category="Category", description="What you want", max_budget="Maximum budget")
    async def wanted_post(interaction: discord.Interaction, category: str, description: str, max_budget: str = "0") -> None:
        await db.ensure_user(interaction.user)
        budget = parse_shorthand(max_budget)
        await db.lid(
            "INSERT INTO wanted_alerts (user_id,category,description,max_budget) VALUES (?,?,?,?)",
            (interaction.user.id, category, description, budget),
        )
        embed = discord.Embed(title=f"🔍 WANTED — {category.upper()}", colour=discord.Colour.orange())
        embed.add_field(name="Looking For", value=description, inline=False)
        embed.add_field(name="Max Budget",  value=fmt_cash(budget), inline=True)
        embed.add_field(name="Contact",     value=interaction.user.mention, inline=True)
        ch = await require_channel(interaction, "marketplace")
        if ch:
            await ch.send(embed=embed)
        await eph(interaction, content="✅ Wanted post submitted!")

    @tree.command(name="redeem", description="Redeem a bonus code")
    @app_commands.describe(code="Your redeem code")
    async def redeem(interaction: discord.Interaction, code: str) -> None:
        await db.ensure_user(interaction.user)
        row = await db.one("SELECT * FROM redeem_codes WHERE code=? AND uses_left>0", (code.upper(),))
        if not row:
            await eph(interaction, content="❌ Invalid or expired code.")
            return
        already = await db.one("SELECT id FROM redeem_history WHERE user_id=? AND code=?",
                               (interaction.user.id, code.upper()))
        if already:
            await eph(interaction, content="❌ You already redeemed this code.")
            return
        await db.exe("UPDATE redeem_codes SET uses_left=uses_left-1 WHERE code=?", (code.upper(),))
        await db.add_coins(interaction.user.id, row["coins"])
        await db.lid("INSERT INTO redeem_history (user_id,code,reward) VALUES (?,?,?)",
                     (interaction.user.id, code.upper(), row["reward"]))
        await eph(interaction, content=f"🎉 Code redeemed! Reward: **{row['reward']}** (+{row['coins']} coins)")

    # ── 15. STAFF COMMANDS ──────────────────────────────────────────────────
    @tree.command(name="review_queue", description="[Staff] View pending reviews")
    @has_role(STAFF_ROLE, SENIOR_STAFF_ROLE, ADMIN_ROLE)
    async def review_queue(interaction: discord.Interaction) -> None:
        purchases  = await db.one("SELECT COUNT(*) as c FROM coin_purchases WHERE status='pending'")
        bounties   = await db.one("SELECT COUNT(*) as c FROM bounties WHERE status='pending'")
        giveaways  = await db.one("SELECT COUNT(*) as c FROM giveaways WHERE status='pending'")
        reports    = await db.one("SELECT COUNT(*) as c FROM reports WHERE status='pending'")
        embed = discord.Embed(title="📋 Review Queue", colour=discord.Colour.orange())
        embed.add_field(name="💳 Coin Purchases", value=str(purchases["c"]), inline=True)
        embed.add_field(name="🎯 Bounties",       value=str(bounties["c"]),  inline=True)
        embed.add_field(name="🎉 Giveaways",      value=str(giveaways["c"]), inline=True)
        embed.add_field(name="🚨 Reports",         value=str(reports["c"]),   inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="staff_logs", description="[Staff] View recent staff actions")
    @has_role(STAFF_ROLE, SENIOR_STAFF_ROLE, ADMIN_ROLE)
    async def staff_logs(interaction: discord.Interaction) -> None:
        rows = await db.all("SELECT * FROM staff_logs ORDER BY created_at DESC LIMIT 15")
        embed = discord.Embed(title="🛡️ Staff Logs", colour=discord.Colour.blurple())
        for r in rows:
            embed.add_field(
                name=f"<@{r['staff_id']}> — {r['action']}",
                value=f"{r.get('target_type','') or ''} {r.get('target_id','') or ''} | {r['created_at'][:16]}",
                inline=False,
            )
        await eph(interaction, embed=embed)

    @tree.command(name="add_coins", description="[Staff] Add coins to a user")
    @has_role(SENIOR_STAFF_ROLE, ADMIN_ROLE)
    @app_commands.describe(user="Target user", amount="Coins to add", reason="Reason")
    async def add_coins_cmd(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "") -> None:
        await db.ensure_user(user)
        await db.add_coins(user.id, amount)
        await db.log_staff(interaction.user.id, "add_coins", "user", str(user.id), f"+{amount} {reason}")
        await eph(interaction, content=f"✅ Added {amount} coins to {user.mention}.")

    @tree.command(name="remove_coins", description="[Staff] Remove coins from a user")
    @has_role(SENIOR_STAFF_ROLE, ADMIN_ROLE)
    @app_commands.describe(user="Target user", amount="Coins to remove", reason="Reason")
    async def remove_coins_cmd(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "") -> None:
        await db.deduct_coins(user.id, amount)
        await db.log_staff(interaction.user.id, "remove_coins", "user", str(user.id), f"-{amount} {reason}")
        await eph(interaction, content=f"✅ Removed {amount} coins from {user.mention}.")

    @tree.command(name="verify_user", description="[Staff] Grant Verified Trader status")
    @has_role(SENIOR_STAFF_ROLE, ADMIN_ROLE)
    @app_commands.describe(user="User to verify")
    async def verify_user(interaction: discord.Interaction, user: discord.Member) -> None:
        await db.exe("UPDATE users SET is_verified=1 WHERE user_id=?", (user.id,))
        await db.log_staff(interaction.user.id, "verify_user", "user", str(user.id))
        await eph(interaction, content=f"✅ {user.mention} is now a Verified Trader.")

    @tree.command(name="ban_user", description="[Admin] Ban a user from KAT Market")
    @has_role(ADMIN_ROLE)
    @app_commands.describe(user="User to ban", reason="Reason")
    async def ban_user(interaction: discord.Interaction, user: discord.Member, reason: str = "") -> None:
        await db.exe("UPDATE users SET is_banned=1 WHERE user_id=?", (user.id,))
        await db.log_staff(interaction.user.id, "ban_user", "user", str(user.id), reason)
        await eph(interaction, content=f"✅ {user.mention} banned from KAT Market.")

    @tree.command(name="staff_work", description="[Staff] Open the staff operations panel")
    @has_role(STAFF_ROLE, SENIOR_STAFF_ROLE, ADMIN_ROLE)
    async def staff_work(interaction: discord.Interaction) -> None:
        purchases = await db.one("SELECT COUNT(*) as c FROM coin_purchases WHERE status='pending'")
        bounties  = await db.one("SELECT COUNT(*) as c FROM bounties WHERE status='pending'")
        reports   = await db.one("SELECT COUNT(*) as c FROM reports WHERE status='pending'")
        giveaways = await db.one("SELECT COUNT(*) as c FROM giveaways WHERE status='pending'")
        embed = discord.Embed(
            title="╔══════════════════╗\n🐾 KAT MARKET NEKO\nSTAFF PANEL\n╚══════════════════╝",
            colour=discord.Colour.gold(),
        )
        embed.add_field(name="💳 Pending Purchases",  value=str(purchases["c"]), inline=True)
        embed.add_field(name="🎯 Pending Bounties",   value=str(bounties["c"]),  inline=True)
        embed.add_field(name="🚨 Open Reports",        value=str(reports["c"]),   inline=True)
        embed.add_field(name="🎉 Pending Giveaways",  value=str(giveaways["c"]), inline=True)
        embed.add_field(name="Quick Commands",
                        value="`/review_queue` `/staff_logs` `/verify_user` `/ban_user`",
                        inline=False)
        await eph(interaction, embed=embed)

    # ── 16. ADMIN / SETUP ───────────────────────────────────────────────────
    @tree.command(name="set_channel", description="[Admin] Set a bot channel")
    @has_role(ADMIN_ROLE)
    @app_commands.describe(
        channel_type="marketplace/bounty/advertisement/giveaway/coin_purchase/staff/report/birthday/events/occasions/rcm",
        channel="The Discord channel",
    )
    async def set_channel(interaction: discord.Interaction, channel_type: str, channel: discord.TextChannel) -> None:
        await db.set_cfg(f"channel_{channel_type}", str(channel.id))
        await db.log_staff(interaction.user.id, "set_channel", "channel", channel_type, str(channel.id))
        await eph(interaction, content=f"✅ `{channel_type}` channel set to {channel.mention}.")

    @tree.command(name="view_channels", description="[Admin] View all configured channels")
    @has_role(STAFF_ROLE, SENIOR_STAFF_ROLE, ADMIN_ROLE)
    async def view_channels(interaction: discord.Interaction) -> None:
        keys = ["marketplace","bounty","advertisement","giveaway","coin_purchase",
                "staff","report","birthday","events","occasions","rcm"]
        embed = discord.Embed(title="⚙️ Channel Configuration", colour=discord.Colour.blurple())
        for k in keys:
            val = await db.cfg(f"channel_{k}")
            embed.add_field(name=k, value=f"<#{val}>" if val and val != "0" else "❌ Not set", inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="admin_panel", description="[Admin] Full admin overview")
    @has_role(ADMIN_ROLE)
    async def admin_panel(interaction: discord.Interaction) -> None:
        users_count = await db.one("SELECT COUNT(*) as c FROM users")
        listings    = await db.one("SELECT COUNT(*) as c FROM listings WHERE status='active'")
        embed = discord.Embed(title="🛡️ Admin Panel", colour=discord.Colour.red())
        embed.add_field(name="👥 Total Members", value=str(users_count["c"]), inline=True)
        embed.add_field(name="📦 Active Listings",value=str(listings["c"]),   inline=True)
        embed.set_footer(text="KAT MARKET NEKO Admin Panel")
        await eph(interaction, embed=embed)

    @tree.command(name="setup", description="[Admin] Run first-time bot setup")
    @has_role(ADMIN_ROLE)
    async def setup_cmd(interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="⚙️ KAT Market Setup", colour=discord.Colour.blurple(),
                              description="Use `/set_channel` to configure each channel:\n"
                                          "• `marketplace` — listings channel\n"
                                          "• `bounty` — bounty board\n"
                                          "• `giveaway` — giveaway channel\n"
                                          "• `coin_purchase` — payment reviews\n"
                                          "• `staff` — staff log\n"
                                          "• `report` — reports channel\n"
                                          "• `birthday` — birthday announcements\n"
                                          "• `events` — events channel\n"
                                          "• `occasions` — occasions channel\n"
                                          "• `advertisement` — ads channel")
        await eph(interaction, embed=embed)

    @tree.command(name="system_check", description="[Admin] Run a system health check")
    @has_role(ADMIN_ROLE)
    async def system_check(interaction: discord.Interaction) -> None:
        try:
            await db.one("SELECT 1")
            db_ok = "✅"
        except Exception:
            db_ok = "❌"
        embed = discord.Embed(title="🔧 System Check", colour=discord.Colour.green())
        embed.add_field(name="Database",       value=db_ok,      inline=True)
        embed.add_field(name="Bot Latency",    value=f"{round(bot_.latency*1000)}ms", inline=True)
        embed.add_field(name="Slash Commands", value=f"{len(bot_.tree.get_commands())} registered", inline=True)
        await eph(interaction, embed=embed)

    @tree.command(name="resync_commands", description="[Admin] Force re-sync slash commands")
    @has_role(ADMIN_ROLE)
    async def resync_commands(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        synced = await bot_.tree.sync()
        await interaction.followup.send(f"✅ Synced {len(synced)} commands.", ephemeral=True)

    logger.info("All commands registered.")


# ════════════════════════════════════════════════════════════════════════════════
# ADDITIONAL MODALS & VIEWS
# ════════════════════════════════════════════════════════════════════════════════

class WalletView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    @discord.ui.button(label="🪙 Top-up", style=discord.ButtonStyle.primary)
    async def topup(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await eph(interaction, content="Use `/buy_coins` to top up your wallet!")

    @discord.ui.button(label="✖ Close", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.delete_original_response()


class AdvertiseModal(discord.ui.Modal, title="Post Advertisement"):
    ad_title    = discord.ui.TextInput(label="Title",             max_length=100)
    description = discord.ui.TextInput(label="Description",       style=discord.TextStyle.paragraph, max_length=800)
    location    = discord.ui.TextInput(label="Location (optional)", required=False, max_length=100)
    contact     = discord.ui.TextInput(label="Contact / Price (optional)", required=False, max_length=200)

    def __init__(self, ad_type: str) -> None:
        super().__init__()
        self.ad_type = ad_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        content = f"**{self.ad_title.value}**\n{self.description.value}"
        if self.location.value:
            content += f"\n📍 {self.location.value}"
        if self.contact.value:
            content += f"\n💬 {self.contact.value}"
        aid = await bot.db.lid(
            "INSERT INTO advertisements (user_id,ad_type,content,duration_days) VALUES (?,?,?,?)",
            (interaction.user.id, self.ad_type, content, 1),
        )
        embed = discord.Embed(title=f"📢 {self.ad_type.upper()} AD — #{aid}", colour=discord.Colour.teal())
        embed.description = content
        embed.add_field(name="Posted by", value=interaction.user.mention, inline=True)
        ch = await bot.db.channel(bot, "advertisement")
        if ch:
            msg = await ch.send(embed=embed)
            await bot.db.exe("UPDATE advertisements SET message_id=?,channel_id=? WHERE id=?",
                             (msg.id, ch.id, aid))
        await eph(interaction, content=f"✅ Ad #{aid} posted!")


class CreateEventModal(discord.ui.Modal, title="Create Event"):
    name        = discord.ui.TextInput(label="Event Name",    max_length=100)
    description = discord.ui.TextInput(label="Description",   style=discord.TextStyle.paragraph, max_length=800)
    prize       = discord.ui.TextInput(label="Prize",         max_length=200)
    location_time = discord.ui.TextInput(label="Location & Time", max_length=200)
    cover_url   = discord.ui.TextInput(label="Cover Image URL (optional)", required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        eid = await bot.db.lid(
            "INSERT INTO events (name,description,prize,location,event_time,cover_url,status,created_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.name.value, self.description.value, self.prize.value,
             self.location_time.value, self.location_time.value,
             self.cover_url.value or None, "pending", interaction.user.id),
        )
        embed = discord.Embed(title=f"📅 EVENT — {self.name.value}", colour=discord.Colour.blurple())
        embed.add_field(name="🏆 Prize",    value=self.prize.value,        inline=True)
        embed.add_field(name="📍 Location", value=self.location_time.value, inline=True)
        embed.add_field(name="📋 Details",  value=self.description.value,  inline=False)
        if self.cover_url.value:
            embed.set_image(url=self.cover_url.value)
        embed.set_footer(text=f"Event #{eid} • Pending admin approval")
        ch_staff = await bot.db.channel(bot, "staff")
        if ch_staff:
            await ch_staff.send(embed=embed, view=EventApproveView(eid))
        await eph(interaction, content=f"✅ Event #{eid} submitted for approval!")


class EventApproveView(discord.ui.View):
    def __init__(self, eid: int) -> None:
        super().__init__(timeout=None)
        self.eid = eid

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="event_approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        ev = await bot.db.one("SELECT * FROM events WHERE id=?", (self.eid,))
        if not ev:
            await eph(interaction, content="Event not found.")
            return
        await bot.db.exe("UPDATE events SET status='approved' WHERE id=?", (self.eid,))
        ch = await bot.db.channel(bot, "events")
        if ch:
            embed = discord.Embed(title=f"📅 {ev['name']}", colour=discord.Colour.green())
            embed.add_field(name="🏆 Prize",  value=ev.get("prize","?"),    inline=True)
            embed.add_field(name="📍 Where",  value=ev.get("location","?"), inline=True)
            if ev.get("cover_url"):
                embed.set_image(url=ev["cover_url"])
            await ch.send(embed=embed)
        await eph(interaction, content="✅ Event approved and posted!")


class OccasionModal(discord.ui.Modal, title="Propose an Occasion"):
    occ_type    = discord.ui.TextInput(label="Occasion Type",   placeholder="Race / Meeting / Hunt…", max_length=50)
    description = discord.ui.TextInput(label="Description",     style=discord.TextStyle.paragraph, max_length=500)
    location    = discord.ui.TextInput(label="Location",        max_length=100)
    occ_time    = discord.ui.TextInput(label="Date & Time",     placeholder="e.g. 14 Jun 2025, 8 PM IST", max_length=100)
    cover_url   = discord.ui.TextInput(label="Cover Image URL (optional)", required=False, max_length=300)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.lid(
            "INSERT INTO occasions (user_id,occ_type,description,location,occ_time,cover_url) VALUES (?,?,?,?,?,?)",
            (interaction.user.id, self.occ_type.value, self.description.value,
             self.location.value, self.occ_time.value, self.cover_url.value or None),
        )
        embed = discord.Embed(title=f"🎪 OCCASION — {self.occ_type.value}", colour=discord.Colour.purple())
        embed.add_field(name="📍 Location", value=self.location.value,    inline=True)
        embed.add_field(name="⏰ Time",     value=self.occ_time.value,    inline=True)
        embed.add_field(name="📋 Details",  value=self.description.value, inline=False)
        if self.cover_url.value:
            embed.set_image(url=self.cover_url.value)
        embed.set_footer(text=f"Proposed by {interaction.user} • Pending staff review")
        ch_staff = await bot.db.channel(bot, "staff")
        if ch_staff:
            await ch_staff.send(f"📋 Occasion from {interaction.user.mention}", embed=embed)
        await eph(interaction, content="✅ Occasion submitted for staff review!")


class DatingModal(discord.ui.Modal, title="Looking for Date"):
    gender      = discord.ui.TextInput(label="Your Gender",           placeholder="Male / Female / Other", max_length=20)
    preferences = discord.ui.TextInput(label="Preferences",           placeholder="e.g. loyal, kind, active", max_length=200)
    description = discord.ui.TextInput(label="About You",             style=discord.TextStyle.paragraph, max_length=400)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        content = (f"**Gender:** {self.gender.value}\n"
                   f"**Looking for:** {self.preferences.value}\n"
                   f"**About:** {self.description.value}")
        await bot.db.lid(
            "INSERT INTO advertisements (user_id,ad_type,content,duration_days) VALUES (?,?,?,?)",
            (interaction.user.id, "dating", content, 7),
        )
        embed = discord.Embed(title="💕 Looking for Date", colour=discord.Colour.pink())
        embed.description = content
        embed.add_field(name="Posted by", value=interaction.user.mention, inline=True)
        embed.set_footer(text="Pending admin approval")
        ch_staff = await bot.db.channel(bot, "staff")
        if ch_staff:
            await ch_staff.send(f"💕 Dating post from {interaction.user.mention}", embed=embed)
        await eph(interaction, content="✅ Dating listing submitted for approval!")


class ProposalResponseView(discord.ui.View):
    def __init__(self, pid: int, from_id: int, to_id: int) -> None:
        super().__init__(timeout=None)
        self.pid     = pid
        self.from_id = from_id
        self.to_id   = to_id

    @discord.ui.button(label="💍 Accept", style=discord.ButtonStyle.success, custom_id="proposal_accept")
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.to_id:
            await eph(interaction, content="This proposal is not for you.")
            return
        await bot.db.exe(
            "UPDATE users SET marital_status='Married',spouse_id=? WHERE user_id=?",
            (self.from_id, self.to_id),
        )
        await bot.db.exe(
            "UPDATE users SET marital_status='Married',spouse_id=? WHERE user_id=?",
            (self.to_id, self.from_id),
        )
        await bot.db.exe("UPDATE proposals SET status='accepted' WHERE id=?", (self.pid,))
        ch = await bot.db.channel(bot, "events")
        if ch:
            from_ = bot.get_user(self.from_id)
            to_   = bot.get_user(self.to_id)
            embed = discord.Embed(title="💒 MARRIAGE ANNOUNCEMENT", colour=discord.Colour.pink())
            embed.description = f"🎉 {from_.mention if from_ else f'<@{self.from_id}>'} and {to_.mention if to_ else f'<@{self.to_id}>'} are now married!"
            await ch.send(embed=embed)
        await eph(interaction, content="💍 You accepted! Congratulations!")

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger, custom_id="proposal_decline")
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.to_id:
            await eph(interaction, content="This proposal is not for you.")
            return
        await bot.db.exe("UPDATE proposals SET status='declined' WHERE id=?", (self.pid,))
        await eph(interaction, content="You declined the proposal.")


class BirthdayApproveView(discord.ui.View):
    def __init__(self, uid: int) -> None:
        super().__init__(timeout=None)
        self.uid = uid

    @discord.ui.button(label="✅ Approve Birthday", style=discord.ButtonStyle.success, custom_id="bday_approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await bot.db.exe("UPDATE users SET birthday_status='approved' WHERE user_id=?", (self.uid,))
        await bot.db.log_staff(interaction.user.id, "approve_birthday", "user", str(self.uid))
        member = interaction.guild.get_member(self.uid) if interaction.guild else None
        if member:
            try:
                await member.send("🎂 Your birthday has been verified and registered!")
            except discord.Forbidden:
                pass
        await eph(interaction, content="✅ Birthday approved!")


class BidView(discord.ui.View):
    def __init__(self, auction_id: int) -> None:
        super().__init__(timeout=None)
        self.auction_id = auction_id

    @discord.ui.button(label="🔨 Place Bid", style=discord.ButtonStyle.primary, custom_id="place_bid")
    async def bid_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(BidModal(self.auction_id))


class BidModal(discord.ui.Modal, title="Place Bid"):
    amount = discord.ui.TextInput(label="Your Bid ($)", placeholder="e.g. 500000", max_length=20)

    def __init__(self, auction_id: int) -> None:
        super().__init__()
        self.auction_id = auction_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await bot.db.ensure_user(interaction.user)
        auction = await bot.db.one("SELECT * FROM auctions WHERE id=?", (self.auction_id,))
        if not auction or auction["status"] != "active":
            await eph(interaction, content="❌ Auction not available.")
            return
        bid_amt = parse_shorthand(self.amount.value)
        if bid_amt <= auction["current_bid"]:
            await eph(interaction, content=f"❌ Must exceed current bid: {fmt_cash(auction['current_bid'])}")
            return
        await bot.db.exe("INSERT INTO bids (auction_id,bidder_id,amount) VALUES (?,?,?)",
                         (self.auction_id, interaction.user.id, bid_amt))
        await bot.db.exe("UPDATE auctions SET current_bid=?,top_bidder=? WHERE id=?",
                         (bid_amt, interaction.user.id, self.auction_id))
        await eph(interaction, content=f"✅ Bid of {fmt_cash(bid_amt)} placed!")


# ════════════════════════════════════════════════════════════════════════════════
# BACKGROUND TASKS
# ════════════════════════════════════════════════════════════════════════════════

@tasks.loop(hours=1)
async def birthday_check() -> None:
    now = utcnow()
    rows = await bot.db.all(
        "SELECT * FROM users WHERE birthday_status='approved' AND birthday_day=? AND birthday_month=?",
        (now.day, now.month),
    )
    ch = await bot.db.channel(bot, "birthday")
    if not ch:
        return
    for r in rows:
        last = r.get("daily_last")  # reuse as birthday check
        if last and last[:10] == now.strftime("%Y-%m-%d"):
            continue
        member = ch.guild.get_member(r["user_id"])
        if member:
            embed = discord.Embed(
                title=f"🎂 Happy Birthday {member.display_name}!",
                colour=discord.Colour.gold(),
                description=f"🎉 Wishing you a wonderful birthday from KAT MARKET NEKO!\n🎁 You've received a small gift!",
            )
            await ch.send(f"🎂 {member.mention}", embed=embed)
            await bot.db.add_coins(r["user_id"], 10)


@tasks.loop(minutes=5)
async def expire_listings() -> None:
    now = utcnow().isoformat()
    await bot.db.exe(
        "UPDATE listings SET status='expired' WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    )
    await bot.db.exe(
        "UPDATE bounties SET status='expired' WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    )


@birthday_check.before_loop
@expire_listings.before_loop
async def wait_ready() -> None:
    await bot.wait_until_ready()


# ════════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    if not TOKEN:
        logger.critical("❌ DISCORD_TOKEN not set! Add it to your environment secrets.")
        return
    birthday_check.start()
    expire_listings.start()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
