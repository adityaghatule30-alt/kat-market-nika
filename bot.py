"""
KAT Market Bot — Production-Ready Discord Marketplace System
Single-file architecture with SQLite persistence
"""

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import aiosqlite
import asyncio
import os
import sys
import random
import string
import json
import datetime
import math
import re
import logging
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONSTANTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOKEN = os.environ.get("DISCORD_TOKEN")
DB_PATH = "katmarket.db"
UPI_ID = "adityaghatule30@okaxis"
BOT_VERSION = "2.0.0"
BOT_NAME = "KAT Market"
OWNER_IDS: list[int] = []  # Set via /set_owner command first time

COIN_PACKAGES = [
    {"coins": 100,   "price_inr": 49,   "label": "Starter Pack",  "bonus": 0},
    {"coins": 500,   "price_inr": 199,  "label": "Silver Pack",   "bonus": 25},
    {"coins": 1200,  "price_inr": 449,  "label": "Gold Pack",     "bonus": 100},
    {"coins": 3000,  "price_inr": 999,  "label": "Platinum Pack", "bonus": 300},
    {"coins": 8000,  "price_inr": 2499, "label": "Diamond Pack",  "bonus": 1000},
]

CRATE_POOLS = {
    "basic":      [("Cash 500",5),("Cash 1000",4),("Badge:Trader",2),("Coupon:5%",3),("XP Boost",2),("Nothing",9)],
    "premium":    [("Cash 2500",4),("Cash 5000",3),("Badge:Elite",3),("VIP:1d",2),("Coupon:10%",3),("Title:Merchant",2),("Cash 1000",3)],
    "vip":        [("Cash 10000",3),("Badge:VIP",4),("VIP:7d",2),("Title:Tycoon",2),("Coupon:20%",2),("Cash 5000",4),("Badge:Rare",3)],
    "event":      [("EventItem:Exclusive",2),("Cash 25000",2),("VIP:30d",1),("Badge:Event",3),("Title:Legend",1),("Coupon:50%",1),("Cash 5000",5)],
    "anniversary":  [("Cash 100000",1),("VIP:365d",1),("Badge:Anniversary",2),("Title:Founder",1),("Coupon:100%",1),("Cash 50000",2),("Cash 10000",4)],
}

CRATE_PRICES = {"basic": 50, "premium": 150, "vip": 400, "event": 200, "anniversary": 999}

VIP_PERKS = {
    "bronze": {"extra_listings": 5,  "coin_discount": 5,  "priority_support": False},
    "silver": {"extra_listings": 15, "coin_discount": 10, "priority_support": False},
    "gold":   {"extra_listings": 50, "coin_discount": 20, "priority_support": True},
}

VIP_COSTS = {"bronze": 200, "silver": 500, "gold": 1500}

DISPUTE_STATUS = ["Open", "Under Review", "Resolved", "Dismissed"]
CONTRACT_STATUS = ["Active", "In Progress", "Under Review", "Completed", "Cancelled", "Expired"]

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("KATMarket")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATABASE LAYER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class Database:
    def __init__(self, path: str):
        self.path = path

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self._create_tables()
        log.info("Database connected and tables verified.")

    async def execute(self, sql: str, params=()):
        async with self.conn.execute(sql, params) as cur:
            await self.conn.commit()
            return cur.lastrowid

    async def fetchone(self, sql: str, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params=()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    async def _create_tables(self):
        sqls = [
            # Economy
            """CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY,
                cash INTEGER DEFAULT 0,
                coins INTEGER DEFAULT 0,
                bank INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER, receiver_id INTEGER,
                amount INTEGER, currency TEXT DEFAULT 'cash',
                reason TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS fixed_deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, amount INTEGER,
                interest_rate REAL DEFAULT 0.05,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                mature_at TEXT, claimed INTEGER DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS coin_purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, coins INTEGER, price_inr INTEGER,
                utr_number TEXT, status TEXT DEFAULT 'Pending',
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                approved_by INTEGER, approved_at TEXT
            )""",
            # Profiles
            """CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT, bio TEXT DEFAULT '',
                title TEXT DEFAULT 'Newcomer',
                badges TEXT DEFAULT '[]',
                vouches_positive INTEGER DEFAULT 0,
                vouches_neutral INTEGER DEFAULT 0,
                vouches_negative INTEGER DEFAULT 0,
                vip_tier TEXT DEFAULT 'none',
                vip_expires TEXT,
                total_trades INTEGER DEFAULT 0,
                rep_score INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Listings — Vehicle
            """CREATE TABLE IF NOT EXISTS vehicle_listings (
                id TEXT PRIMARY KEY,
                seller_id INTEGER, vehicle_name TEXT,
                model_year INTEGER, color TEXT,
                mileage TEXT, condition TEXT,
                price INTEGER, listing_type TEXT DEFAULT 'Standard',
                description TEXT, image_url TEXT,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )""",
            # Listings — Property
            """CREATE TABLE IF NOT EXISTS property_listings (
                id TEXT PRIMARY KEY,
                seller_id INTEGER, property_name TEXT,
                prop_type TEXT, location TEXT,
                bedrooms INTEGER, size TEXT,
                price INTEGER, listing_type TEXT DEFAULT 'Standard',
                description TEXT, image_url TEXT,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )""",
            # Listings — Business
            """CREATE TABLE IF NOT EXISTS business_listings (
                id TEXT PRIMARY KEY,
                seller_id INTEGER, business_name TEXT,
                business_type TEXT, location TEXT,
                monthly_revenue INTEGER, employees INTEGER,
                price INTEGER, listing_type TEXT DEFAULT 'Standard',
                description TEXT, image_url TEXT,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )""",
            # Listings — Skin
            """CREATE TABLE IF NOT EXISTS skin_listings (
                id TEXT PRIMARY KEY,
                seller_id INTEGER, skin_name TEXT,
                rarity TEXT, character TEXT,
                price INTEGER, listing_type TEXT DEFAULT 'Standard',
                description TEXT, image_url TEXT,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )""",
            # Listings — Item
            """CREATE TABLE IF NOT EXISTS item_listings (
                id TEXT PRIMARY KEY,
                seller_id INTEGER, item_name TEXT,
                category TEXT, quantity INTEGER DEFAULT 1,
                price INTEGER, listing_type TEXT DEFAULT 'Standard',
                description TEXT, image_url TEXT,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )""",
            # Auctions
            """CREATE TABLE IF NOT EXISTS auctions (
                id TEXT PRIMARY KEY,
                seller_id INTEGER, asset_type TEXT,
                asset_name TEXT, starting_bid INTEGER,
                current_bid INTEGER DEFAULT 0,
                highest_bidder INTEGER,
                min_increment INTEGER DEFAULT 100,
                description TEXT, image_url TEXT,
                status TEXT DEFAULT 'Active',
                ends_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS bids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_id TEXT, bidder_id INTEGER,
                amount INTEGER, ts TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Offers
            """CREATE TABLE IF NOT EXISTS offers (
                id TEXT PRIMARY KEY,
                listing_id TEXT, listing_type TEXT,
                buyer_id INTEGER, seller_id INTEGER,
                amount INTEGER, message TEXT,
                status TEXT DEFAULT 'Pending',
                ts TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Watchlist
            """CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, listing_id TEXT,
                listing_type TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Contracts
            """CREATE TABLE IF NOT EXISTS contracts (
                id TEXT PRIMARY KEY,
                poster_id INTEGER, worker_id INTEGER,
                title TEXT, description TEXT,
                reward_cash INTEGER DEFAULT 0,
                reward_coins INTEGER DEFAULT 0,
                deadline TEXT, status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Bounties
            """CREATE TABLE IF NOT EXISTS bounties (
                id TEXT PRIMARY KEY,
                poster_id INTEGER, target TEXT,
                description TEXT, reward INTEGER,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Disputes
            """CREATE TABLE IF NOT EXISTS disputes (
                id TEXT PRIMARY KEY,
                reporter_id INTEGER, reported_id INTEGER,
                reason TEXT, evidence TEXT,
                case_type TEXT DEFAULT 'Dispute',
                status TEXT DEFAULT 'Open',
                assigned_to INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT, resolution TEXT
            )""",
            # Daily rewards
            """CREATE TABLE IF NOT EXISTS daily_streaks (
                user_id INTEGER PRIMARY KEY,
                streak INTEGER DEFAULT 0,
                last_claim TEXT,
                total_claims INTEGER DEFAULT 0
            )""",
            # Weekly rewards
            """CREATE TABLE IF NOT EXISTS weekly_claims (
                user_id INTEGER PRIMARY KEY,
                last_claim TEXT,
                total_claims INTEGER DEFAULT 0
            )""",
            # Inventory
            """CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, item_type TEXT,
                item_name TEXT, quantity INTEGER DEFAULT 1,
                obtained_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Redeem codes
            """CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                reward_type TEXT, reward_value TEXT,
                max_uses INTEGER DEFAULT 1,
                uses INTEGER DEFAULT 0,
                role_required TEXT,
                expires_at TEXT,
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS code_uses (
                code TEXT, user_id INTEGER,
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (code, user_id)
            )""",
            # Birthdays
            """CREATE TABLE IF NOT EXISTS birthdays (
                user_id INTEGER PRIMARY KEY,
                birthday TEXT,
                announced_year INTEGER DEFAULT 0
            )""",
            # Relationships
            """CREATE TABLE IF NOT EXISTS relationships (
                user_id INTEGER PRIMARY KEY,
                partner_id INTEGER,
                status TEXT DEFAULT 'Single',
                married_at TEXT,
                anniversary_count INTEGER DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS families (
                id TEXT PRIMARY KEY,
                name TEXT, leader_id INTEGER,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS family_members (
                family_id TEXT, user_id INTEGER,
                rank TEXT DEFAULT 'Member',
                joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (family_id, user_id)
            )""",
            # Hall of Fame / Donations
            """CREATE TABLE IF NOT EXISTS donations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, tier TEXT,
                amount REAL, proof_url TEXT,
                status TEXT DEFAULT 'Pending',
                approved_by INTEGER,
                ts TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Admin config
            """CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER, key TEXT, value TEXT,
                PRIMARY KEY (guild_id, key)
            )""",
            # Ads
            """CREATE TABLE IF NOT EXISTS advertisements (
                id TEXT PRIMARY KEY,
                user_id INTEGER, ad_type TEXT,
                title TEXT, description TEXT,
                contact TEXT, premium INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )""",
            # Archive
            """CREATE TABLE IF NOT EXISTS archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_id TEXT, table_name TEXT,
                data TEXT, archived_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Staff metrics
            """CREATE TABLE IF NOT EXISTS staff_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER, action TEXT,
                target_id TEXT, notes TEXT,
                ts TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Vouches
            """CREATE TABLE IF NOT EXISTS vouches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id INTEGER, to_id INTEGER,
                vouch_type TEXT, comment TEXT,
                ts TEXT DEFAULT CURRENT_TIMESTAMP
            )""",
            # Maintenance
            """CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY, value TEXT
            )""",
        ]
        for sql in sqls:
            await self.conn.execute(sql)
        await self.conn.commit()

    # ── Wallet helpers ──────────────────────────────────────
    async def get_wallet(self, user_id: int) -> dict:
        row = await self.fetchone("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        if not row:
            await self.execute("INSERT INTO wallets (user_id,cash,coins) VALUES (?,5000,0)", (user_id,))
            row = await self.fetchone("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        return dict(row)

    async def add_cash(self, user_id: int, amount: int, reason="", from_id=0):
        await self.get_wallet(user_id)
        await self.execute("UPDATE wallets SET cash=cash+?,total_earned=total_earned+? WHERE user_id=?",
                           (amount, max(0, amount), user_id))
        if reason:
            await self.execute("INSERT INTO transactions(sender_id,receiver_id,amount,currency,reason) VALUES(?,?,?,?,?)",
                               (from_id, user_id, amount, "cash", reason))

    async def remove_cash(self, user_id: int, amount: int, reason=""):
        w = await self.get_wallet(user_id)
        if w["cash"] < amount:
            return False
        await self.execute("UPDATE wallets SET cash=cash-?,total_spent=total_spent+? WHERE user_id=?",
                           (amount, amount, user_id))
        if reason:
            await self.execute("INSERT INTO transactions(sender_id,receiver_id,amount,currency,reason) VALUES(?,?,?,?,?)",
                               (user_id, 0, amount, "cash", reason))
        return True

    async def add_coins(self, user_id: int, amount: int):
        await self.get_wallet(user_id)
        await self.execute("UPDATE wallets SET coins=coins+? WHERE user_id=?", (amount, user_id))

    async def remove_coins(self, user_id: int, amount: int) -> bool:
        w = await self.get_wallet(user_id)
        if w["coins"] < amount:
            return False
        await self.execute("UPDATE wallets SET coins=coins-? WHERE user_id=?", (amount, user_id))
        return True

    # ── Profile helpers ─────────────────────────────────────
    async def get_profile(self, user_id: int) -> dict:
        row = await self.fetchone("SELECT * FROM profiles WHERE user_id=?", (user_id,))
        if not row:
            await self.execute("INSERT INTO profiles (user_id) VALUES (?)", (user_id,))
            row = await self.fetchone("SELECT * FROM profiles WHERE user_id=?", (user_id,))
        return dict(row)

    # ── Listing ID generator ────────────────────────────────
    def new_id(self, prefix: str) -> str:
        chars = string.ascii_uppercase + string.digits
        return prefix + "-" + "".join(random.choices(chars, k=8))

    async def get_config(self, guild_id: int, key: str, default=None):
        row = await self.fetchone("SELECT value FROM guild_config WHERE guild_id=? AND key=?", (guild_id, key))
        return row["value"] if row else default

    async def set_config(self, guild_id: int, key: str, value: str):
        await self.execute("INSERT OR REPLACE INTO guild_config(guild_id,key,value) VALUES(?,?,?)", (guild_id, key, value))

    async def is_maintenance(self) -> bool:
        row = await self.fetchone("SELECT value FROM bot_settings WHERE key='maintenance'")
        return row and row["value"] == "1"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def expires_delta(days=30) -> str:
    return (datetime.datetime.utcnow() + datetime.timedelta(days=days)).isoformat()

def fmt_cash(n: int) -> str:
    return f"₹{n:,}"

def fmt_coins(n: int) -> str:
    return f"🪙 {n:,}"

def divider() -> str:
    return "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

def listing_embed(title: str, color=discord.Color.gold()) -> discord.Embed:
    e = discord.Embed(title=title, color=color)
    e.set_footer(text=f"{BOT_NAME} v{BOT_VERSION}")
    return e

def case_id(prefix="DSP") -> str:
    num = random.randint(10000, 99999)
    return f"Case #{prefix}-{num:05d}"

async def ensure_wallet(db: "Database", user_id: int):
    await db.get_wallet(user_id)

def rich_list(items: list, header: str = "") -> str:
    if not items:
        return f"**{header}**\n> No entries found."
    lines = [f"**{header}**"] if header else []
    for i, item in enumerate(items, 1):
        lines.append(f"**{i}.** {item}")
    return "\n".join(lines)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MODALS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class SellVehicleModal(ui.Modal, title="🚗 Sell a Vehicle"):
    vehicle_name = ui.TextInput(label="Vehicle Name", placeholder="e.g. BMW M3 2023")
    model_year   = ui.TextInput(label="Model Year", placeholder="e.g. 2023", max_length=4)
    color        = ui.TextInput(label="Color", placeholder="e.g. Midnight Black")
    price        = ui.TextInput(label="Price (₹)", placeholder="e.g. 500000")
    description  = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Details about the vehicle...", required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price.value.replace(",", "").replace("₹", "").strip())
            year = int(self.model_year.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Price and year must be numbers.", ephemeral=True)
            return
        lid = self.db.new_id("VEH")
        exp = expires_delta(30)
        await self.db.execute(
            "INSERT INTO vehicle_listings(id,seller_id,vehicle_name,model_year,color,price,description,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (lid, interaction.user.id, self.vehicle_name.value, year, self.color.value, price, self.description.value or "No description.", exp)
        )
        e = listing_embed(f"✅ Vehicle Listed — {lid}")
        e.add_field(name="Vehicle", value=self.vehicle_name.value, inline=True)
        e.add_field(name="Year", value=str(year), inline=True)
        e.add_field(name="Color", value=self.color.value, inline=True)
        e.add_field(name="Price", value=fmt_cash(price), inline=True)
        e.add_field(name="Expires", value=exp[:10], inline=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

class SellPropertyModal(ui.Modal, title="🏠 List a Property"):
    property_name = ui.TextInput(label="Property Name", placeholder="e.g. Sunset Villa")
    prop_type     = ui.TextInput(label="Type (House/Apartment/Plot)", placeholder="House")
    location      = ui.TextInput(label="Location", placeholder="e.g. Sector 12, City Center")
    price         = ui.TextInput(label="Price (₹)", placeholder="e.g. 2500000")
    description   = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price.value.replace(",", "").replace("₹", "").strip())
        except ValueError:
            await interaction.response.send_message("❌ Price must be a number.", ephemeral=True)
            return
        lid = self.db.new_id("PROP")
        await self.db.execute(
            "INSERT INTO property_listings(id,seller_id,property_name,prop_type,location,price,description,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (lid, interaction.user.id, self.property_name.value, self.prop_type.value, self.location.value, price, self.description.value or "No description.", expires_delta(30))
        )
        e = listing_embed(f"✅ Property Listed — {lid}")
        e.add_field(name="Property", value=self.property_name.value, inline=True)
        e.add_field(name="Type", value=self.prop_type.value, inline=True)
        e.add_field(name="Location", value=self.location.value, inline=True)
        e.add_field(name="Price", value=fmt_cash(price), inline=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

class SellBusinessModal(ui.Modal, title="🏢 List a Business"):
    business_name = ui.TextInput(label="Business Name", placeholder="e.g. Dragon Garage")
    business_type = ui.TextInput(label="Business Type", placeholder="e.g. Mechanic Shop, Restaurant")
    location      = ui.TextInput(label="Location", placeholder="e.g. Downtown")
    price         = ui.TextInput(label="Asking Price (₹)", placeholder="e.g. 1000000")
    description   = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price.value.replace(",", "").replace("₹", "").strip())
        except ValueError:
            await interaction.response.send_message("❌ Price must be a number.", ephemeral=True)
            return
        lid = self.db.new_id("BIZ")
        await self.db.execute(
            "INSERT INTO business_listings(id,seller_id,business_name,business_type,location,price,description,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (lid, interaction.user.id, self.business_name.value, self.business_type.value, self.location.value, price, self.description.value or "No description.", expires_delta(30))
        )
        e = listing_embed(f"✅ Business Listed — {lid}")
        e.add_field(name="Business", value=self.business_name.value, inline=True)
        e.add_field(name="Type", value=self.business_type.value, inline=True)
        e.add_field(name="Location", value=self.location.value, inline=True)
        e.add_field(name="Price", value=fmt_cash(price), inline=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

class SellSkinModal(ui.Modal, title="🎨 List a Skin"):
    skin_name   = ui.TextInput(label="Skin Name", placeholder="e.g. Dragon Warrior Skin")
    rarity      = ui.TextInput(label="Rarity", placeholder="Common / Rare / Epic / Legendary")
    character   = ui.TextInput(label="Character / Category", placeholder="e.g. Knight, Mage")
    price       = ui.TextInput(label="Price (₹)", placeholder="e.g. 10000")
    description = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price.value.replace(",", "").replace("₹", "").strip())
        except ValueError:
            await interaction.response.send_message("❌ Price must be a number.", ephemeral=True)
            return
        lid = self.db.new_id("SKN")
        await self.db.execute(
            "INSERT INTO skin_listings(id,seller_id,skin_name,rarity,character,price,description,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (lid, interaction.user.id, self.skin_name.value, self.rarity.value, self.character.value, price, self.description.value or "No description.", expires_delta(30))
        )
        e = listing_embed(f"✅ Skin Listed — {lid}", discord.Color.purple())
        e.add_field(name="Skin", value=self.skin_name.value, inline=True)
        e.add_field(name="Rarity", value=self.rarity.value, inline=True)
        e.add_field(name="Character", value=self.character.value, inline=True)
        e.add_field(name="Price", value=fmt_cash(price), inline=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

class SellItemModal(ui.Modal, title="📦 List an Item"):
    item_name   = ui.TextInput(label="Item Name", placeholder="e.g. Golden Sword")
    category    = ui.TextInput(label="Category", placeholder="e.g. Weapon, Collectible, Gear")
    quantity    = ui.TextInput(label="Quantity", placeholder="1", max_length=6)
    price       = ui.TextInput(label="Price (₹)", placeholder="e.g. 5000")
    description = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = int(self.price.value.replace(",", "").replace("₹", "").strip())
            qty   = int(self.quantity.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Price and quantity must be numbers.", ephemeral=True)
            return
        lid = self.db.new_id("ITM")
        await self.db.execute(
            "INSERT INTO item_listings(id,seller_id,item_name,category,quantity,price,description,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (lid, interaction.user.id, self.item_name.value, self.category.value, qty, price, self.description.value or "No description.", expires_delta(30))
        )
        e = listing_embed(f"✅ Item Listed — {lid}", discord.Color.teal())
        e.add_field(name="Item", value=self.item_name.value, inline=True)
        e.add_field(name="Category", value=self.category.value, inline=True)
        e.add_field(name="Qty", value=str(qty), inline=True)
        e.add_field(name="Price", value=fmt_cash(price), inline=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

class AuctionCreateModal(ui.Modal, title="🔨 Create Auction"):
    asset_name   = ui.TextInput(label="Asset Name", placeholder="e.g. Rare Dragon Vehicle")
    asset_type   = ui.TextInput(label="Asset Type", placeholder="Vehicle / Property / Item / Skin")
    starting_bid = ui.TextInput(label="Starting Bid (₹)", placeholder="e.g. 50000")
    duration_hrs = ui.TextInput(label="Duration (hours)", placeholder="e.g. 24", max_length=4)
    description  = ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sb   = int(self.starting_bid.value.replace(",", "").replace("₹", "").strip())
            hrs  = int(self.duration_hrs.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Bid and hours must be numbers.", ephemeral=True)
            return
        aid = self.db.new_id("AUC")
        ends = (datetime.datetime.utcnow() + datetime.timedelta(hours=hrs)).isoformat()
        await self.db.execute(
            "INSERT INTO auctions(id,seller_id,asset_type,asset_name,starting_bid,current_bid,description,ends_at) VALUES(?,?,?,?,?,?,?,?)",
            (aid, interaction.user.id, self.asset_type.value, self.asset_name.value, sb, sb, self.description.value or "No description.", ends)
        )
        e = listing_embed(f"🔨 Auction Created — {aid}", discord.Color.orange())
        e.add_field(name="Asset", value=self.asset_name.value, inline=True)
        e.add_field(name="Type", value=self.asset_type.value, inline=True)
        e.add_field(name="Starting Bid", value=fmt_cash(sb), inline=True)
        e.add_field(name="Ends At", value=ends[:16].replace("T", " ") + " UTC", inline=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

class DisputeModal(ui.Modal, title="⚠️ Open Dispute"):
    reported_user = ui.TextInput(label="Reported User ID", placeholder="Discord user ID (numbers only)")
    reason        = ui.TextInput(label="Reason", placeholder="Brief reason for dispute")
    evidence      = ui.TextInput(label="Evidence / Details", style=discord.TextStyle.paragraph)

    def __init__(self, db: Database, case_type="Dispute"):
        super().__init__()
        self.db = db
        self.case_type = case_type

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rid = int(self.reported_user.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ User ID must be a number.", ephemeral=True)
            return
        cid = case_id("DSP")
        await self.db.execute(
            "INSERT INTO disputes(id,reporter_id,reported_id,reason,evidence,case_type) VALUES(?,?,?,?,?,?)",
            (cid, interaction.user.id, rid, self.reason.value, self.evidence.value, self.case_type)
        )
        e = listing_embed(f"📋 {self.case_type} Filed — {cid}", discord.Color.red())
        e.add_field(name="Case ID", value=cid, inline=True)
        e.add_field(name="Reporter", value=interaction.user.mention, inline=True)
        e.add_field(name="Against User ID", value=str(rid), inline=True)
        e.add_field(name="Reason", value=self.reason.value, inline=False)
        e.add_field(name="Status", value="🔴 Open", inline=True)
        await interaction.response.send_message(embed=e)

class ContractModal(ui.Modal, title="📜 Post Contract / Job"):
    title_       = ui.TextInput(label="Contract Title", placeholder="e.g. Need delivery driver")
    description  = ui.TextInput(label="Description", style=discord.TextStyle.paragraph)
    reward_cash  = ui.TextInput(label="Cash Reward (₹)", placeholder="0", required=False)
    reward_coins = ui.TextInput(label="Coin Reward", placeholder="0", required=False)
    deadline     = ui.TextInput(label="Deadline (YYYY-MM-DD)", placeholder="e.g. 2025-12-31")

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rc  = int(self.reward_cash.value.strip() or 0)
            rco = int(self.reward_coins.value.strip() or 0)
        except ValueError:
            await interaction.response.send_message("❌ Rewards must be numbers.", ephemeral=True)
            return
        cid = self.db.new_id("CON")
        await self.db.execute(
            "INSERT INTO contracts(id,poster_id,title,description,reward_cash,reward_coins,deadline) VALUES(?,?,?,?,?,?,?)",
            (cid, interaction.user.id, self.title_.value, self.description.value, rc, rco, self.deadline.value)
        )
        e = listing_embed(f"📜 Contract Posted — {cid}", discord.Color.green())
        e.add_field(name="Title", value=self.title_.value, inline=True)
        e.add_field(name="Cash Reward", value=fmt_cash(rc), inline=True)
        e.add_field(name="Coin Reward", value=fmt_coins(rco), inline=True)
        e.add_field(name="Deadline", value=self.deadline.value, inline=True)
        e.add_field(name="Status", value="✅ Active", inline=True)
        e.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=e)

class CoinBuyModal(ui.Modal, title="💰 Buy Coins — Payment Proof"):
    utr_number = ui.TextInput(label="UTR / Transaction Reference Number", placeholder="12-digit UTR from your UPI app")
    screenshot = ui.TextInput(label="Screenshot URL (optional)", placeholder="Paste image URL of payment screenshot", required=False)

    def __init__(self, db: Database, package: dict):
        super().__init__()
        self.db = db
        self.pkg = package

    async def on_submit(self, interaction: discord.Interaction):
        pid = await self.db.execute(
            "INSERT INTO coin_purchases(user_id,coins,price_inr,utr_number) VALUES(?,?,?,?)",
            (interaction.user.id, self.pkg["coins"], self.pkg["price_inr"], self.utr_number.value)
        )
        e = listing_embed("⏳ Payment Submitted — Awaiting Admin Approval", discord.Color.yellow())
        e.add_field(name="Package", value=self.pkg["label"], inline=True)
        e.add_field(name="Coins", value=fmt_coins(self.pkg["coins"] + self.pkg["bonus"]), inline=True)
        e.add_field(name="Amount Paid", value=f"₹{self.pkg['price_inr']}", inline=True)
        e.add_field(name="UTR Number", value=self.utr_number.value, inline=True)
        e.add_field(name="Request ID", value=f"#{pid}", inline=True)
        e.description = "**Admin will verify your payment and credit coins within 24 hours.**\nIf not credited, contact support with your Request ID."
        await interaction.response.send_message(embed=e, ephemeral=True)

class VouchModal(ui.Modal, title="⭐ Leave a Vouch"):
    target_id  = ui.TextInput(label="User ID to Vouch", placeholder="Discord user ID")
    vouch_type = ui.TextInput(label="Vouch Type", placeholder="Positive / Neutral / Negative")
    comment    = ui.TextInput(label="Comment", style=discord.TextStyle.paragraph, placeholder="Your experience with this trader...")

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            tid = int(self.target_id.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ User ID must be a number.", ephemeral=True)
            return
        if tid == interaction.user.id:
            await interaction.response.send_message("❌ You cannot vouch yourself.", ephemeral=True)
            return
        vt = self.vouch_type.value.strip().capitalize()
        if vt not in ("Positive", "Neutral", "Negative"):
            await interaction.response.send_message("❌ Vouch type must be Positive, Neutral, or Negative.", ephemeral=True)
            return
        await self.db.execute(
            "INSERT INTO vouches(from_id,to_id,vouch_type,comment) VALUES(?,?,?,?)",
            (interaction.user.id, tid, vt, self.comment.value)
        )
        col_map = {"Positive": "vouches_positive", "Neutral": "vouches_neutral", "Negative": "vouches_negative"}
        await self.db.execute(f"UPDATE profiles SET {col_map[vt]}={col_map[vt]}+1 WHERE user_id=?", (tid,))
        icon = {"Positive": "✅", "Neutral": "🔶", "Negative": "❌"}[vt]
        e = listing_embed(f"{icon} Vouch Submitted", discord.Color.green())
        e.add_field(name="For", value=f"<@{tid}>", inline=True)
        e.add_field(name="Type", value=vt, inline=True)
        e.add_field(name="Comment", value=self.comment.value, inline=False)
        await interaction.response.send_message(embed=e)

class ProfileBioModal(ui.Modal, title="✏️ Edit Your Profile"):
    display_name = ui.TextInput(label="Display Name", max_length=32)
    bio          = ui.TextInput(label="Bio", style=discord.TextStyle.paragraph, max_length=300, required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await self.db.get_profile(interaction.user.id)
        await self.db.execute(
            "UPDATE profiles SET display_name=?,bio=? WHERE user_id=?",
            (self.display_name.value, self.bio.value, interaction.user.id)
        )
        e = listing_embed("✅ Profile Updated", discord.Color.green())
        e.add_field(name="Name", value=self.display_name.value, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

class RedeemCodeCreateModal(ui.Modal, title="🎟️ Create Redeem Code"):
    code         = ui.TextInput(label="Code", max_length=20, placeholder="e.g. SUMMER2025")
    reward_type  = ui.TextInput(label="Reward Type", placeholder="cash / coins / vip / badge")
    reward_value = ui.TextInput(label="Reward Value", placeholder="e.g. 5000 or gold")
    max_uses     = ui.TextInput(label="Max Uses", placeholder="1", max_length=6)
    expires_at   = ui.TextInput(label="Expires At (YYYY-MM-DD)", placeholder="2025-12-31", required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mu = int(self.max_uses.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Max uses must be a number.", ephemeral=True)
            return
        c = self.code.value.upper().strip()
        existing = await self.db.fetchone("SELECT code FROM redeem_codes WHERE code=?", (c,))
        if existing:
            await interaction.response.send_message("❌ Code already exists.", ephemeral=True)
            return
        await self.db.execute(
            "INSERT INTO redeem_codes(code,reward_type,reward_value,max_uses,expires_at,created_by) VALUES(?,?,?,?,?,?)",
            (c, self.reward_type.value, self.reward_value.value, mu, self.expires_at.value or None, interaction.user.id)
        )
        e = listing_embed("✅ Redeem Code Created", discord.Color.green())
        e.add_field(name="Code", value=f"`{c}`", inline=True)
        e.add_field(name="Reward", value=f"{self.reward_type.value}: {self.reward_value.value}", inline=True)
        e.add_field(name="Max Uses", value=str(mu), inline=True)
        if self.expires_at.value:
            e.add_field(name="Expires", value=self.expires_at.value, inline=True)
        await interaction.response.send_message(embed=e)

class OfferModal(ui.Modal, title="🤝 Make an Offer"):
    listing_id = ui.TextInput(label="Listing ID", placeholder="e.g. VEH-ABC12345")
    amount     = ui.TextInput(label="Your Offer (₹)", placeholder="e.g. 450000")
    message    = ui.TextInput(label="Message to Seller", style=discord.TextStyle.paragraph, required=False)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value.replace(",", "").replace("₹", "").strip())
        except ValueError:
            await interaction.response.send_message("❌ Amount must be a number.", ephemeral=True)
            return
        lid = self.listing_id.value.strip()
        prefix_map = {"VEH": "vehicle_listings", "PROP": "property_listings", "BIZ": "business_listings", "SKN": "skin_listings", "ITM": "item_listings"}
        table = None
        for k, v in prefix_map.items():
            if lid.startswith(k):
                table = v
                break
        if not table:
            await interaction.response.send_message("❌ Invalid listing ID prefix.", ephemeral=True)
            return
        row = await self.db.fetchone(f"SELECT seller_id FROM {table} WHERE id=?", (lid,))
        if not row:
            await interaction.response.send_message("❌ Listing not found.", ephemeral=True)
            return
        oid = self.db.new_id("OFR")
        lt = lid.split("-")[0].lower()
        await self.db.execute(
            "INSERT INTO offers(id,listing_id,listing_type,buyer_id,seller_id,amount,message) VALUES(?,?,?,?,?,?,?)",
            (oid, lid, lt, interaction.user.id, row["seller_id"], amount, self.message.value or "")
        )
        e = listing_embed(f"🤝 Offer Sent — {oid}", discord.Color.blue())
        e.add_field(name="Listing", value=lid, inline=True)
        e.add_field(name="Offer Amount", value=fmt_cash(amount), inline=True)
        if self.message.value:
            e.add_field(name="Message", value=self.message.value, inline=False)
        await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PERSISTENT VIEWS (Buttons)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class ListingView(ui.View):
    def __init__(self, db: Database, listing_id: str, seller_id: int):
        super().__init__(timeout=None)
        self.db = db
        self.listing_id = listing_id
        self.seller_id = seller_id

    @ui.button(label="👀 Interested", style=discord.ButtonStyle.secondary, custom_id="listing_interested")
    async def interested(self, interaction: discord.Interaction, button: ui.Button):
        e = discord.Embed(description=f"✅ You marked interest in listing **{self.listing_id}**. Contact <@{self.seller_id}> directly to negotiate.", color=discord.Color.green())
        await interaction.response.send_message(embed=e, ephemeral=True)

    @ui.button(label="❤️ Watchlist", style=discord.ButtonStyle.secondary, custom_id="listing_watchlist")
    async def add_watchlist(self, interaction: discord.Interaction, button: ui.Button):
        existing = await self.db.fetchone("SELECT id FROM watchlist WHERE user_id=? AND listing_id=?", (interaction.user.id, self.listing_id))
        if existing:
            await interaction.response.send_message("⚠️ Already on your watchlist.", ephemeral=True)
            return
        prefix_map = {"VEH": "vehicle", "PROP": "property", "BIZ": "business", "SKN": "skin", "ITM": "item", "AUC": "auction"}
        lt = prefix_map.get(self.listing_id.split("-")[0], "unknown")
        await self.db.execute("INSERT INTO watchlist(user_id,listing_id,listing_type) VALUES(?,?,?)", (interaction.user.id, self.listing_id, lt))
        await interaction.response.send_message("❤️ Added to watchlist.", ephemeral=True)

    @ui.button(label="📤 Share", style=discord.ButtonStyle.secondary, custom_id="listing_share")
    async def share(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(f"📤 Share this listing ID with others: `{self.listing_id}`", ephemeral=True)

    @ui.button(label="✅ Mark Sold", style=discord.ButtonStyle.success, custom_id="listing_sold")
    async def mark_sold(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.seller_id:
            await interaction.response.send_message("❌ Only the seller can mark this sold.", ephemeral=True)
            return
        prefix_map = {"VEH": "vehicle_listings", "PROP": "property_listings", "BIZ": "business_listings", "SKN": "skin_listings", "ITM": "item_listings"}
        table = prefix_map.get(self.listing_id.split("-")[0])
        if table:
            await self.db.execute(f"UPDATE {table} SET status='Sold' WHERE id=?", (self.listing_id,))
        e = discord.Embed(description=f"✅ Listing **{self.listing_id}** marked as Sold.", color=discord.Color.green())
        await interaction.response.send_message(embed=e)

class AuctionBidView(ui.View):
    def __init__(self, db: Database, auction_id: str):
        super().__init__(timeout=None)
        self.db = db
        self.auction_id = auction_id

    @ui.button(label="💰 Place Bid", style=discord.ButtonStyle.primary, custom_id="auction_bid")
    async def place_bid(self, interaction: discord.Interaction, button: ui.Button):
        auc = await self.db.fetchone("SELECT * FROM auctions WHERE id=?", (self.auction_id,))
        if not auc or auc["status"] != "Active":
            await interaction.response.send_message("❌ Auction is not active.", ephemeral=True)
            return
        if datetime.datetime.utcnow().isoformat() > auc["ends_at"]:
            await self.db.execute("UPDATE auctions SET status='Ended' WHERE id=?", (self.auction_id,))
            await interaction.response.send_message("❌ Auction has ended.", ephemeral=True)
            return

        class BidModal(ui.Modal, title="💰 Place Bid"):
            bid_amount = ui.TextInput(label=f"Bid Amount (min ₹{auc['current_bid'] + auc['min_increment']:,})", placeholder="Enter your bid")
            async def on_submit(modal_self, modal_interaction: discord.Interaction):
                try:
                    amt = int(modal_self.bid_amount.value.replace(",", "").replace("₹", "").strip())
                except ValueError:
                    await modal_interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
                    return
                if amt < auc["current_bid"] + auc["min_increment"]:
                    await modal_interaction.response.send_message(f"❌ Bid must be at least {fmt_cash(auc['current_bid'] + auc['min_increment'])}.", ephemeral=True)
                    return
                w = await self.db.get_wallet(modal_interaction.user.id)
                if w["cash"] < amt:
                    await modal_interaction.response.send_message(f"❌ Insufficient balance. You have {fmt_cash(w['cash'])}.", ephemeral=True)
                    return
                await self.db.execute("UPDATE auctions SET current_bid=?,highest_bidder=? WHERE id=?", (amt, modal_interaction.user.id, self.auction_id))
                await self.db.execute("INSERT INTO bids(auction_id,bidder_id,amount) VALUES(?,?,?)", (self.auction_id, modal_interaction.user.id, amt))
                e = discord.Embed(description=f"✅ Bid of **{fmt_cash(amt)}** placed on auction `{self.auction_id}`!", color=discord.Color.green())
                await modal_interaction.response.send_message(embed=e)

        await interaction.response.send_modal(BidModal())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COIN SHOP VIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class CoinShopView(ui.View):
    def __init__(self, db: Database):
        super().__init__(timeout=120)
        self.db = db
        for i, pkg in enumerate(COIN_PACKAGES):
            btn = ui.Button(
                label=f"{pkg['label']} — ₹{pkg['price_inr']} → 🪙{pkg['coins'] + pkg['bonus']}",
                style=discord.ButtonStyle.primary,
                custom_id=f"coin_buy_{i}",
                row=i // 2
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, idx: int):
        async def callback(interaction: discord.Interaction):
            pkg = COIN_PACKAGES[idx]
            await interaction.response.send_modal(CoinBuyModal(self.db, pkg))
        return callback

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# THE BOT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
db = Database(DB_PATH)
tree = bot.tree

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAINTENANCE GUARD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.error(f"Command error: {error}")
    msg = "❌ An unexpected error occurred. Please try again later."
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ You do not have permission to use this command."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 1 — MARKETPLACE COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="sell_vehicle", description="🚗 Create a new vehicle listing")
async def sell_vehicle(interaction: discord.Interaction):
    if await db.is_maintenance():
        return await interaction.response.send_message("🔧 Bot is under maintenance. Please try later.", ephemeral=True)
    await interaction.response.send_modal(SellVehicleModal(db))

@tree.command(name="vehicle_search", description="🔍 Search vehicle listings")
@app_commands.describe(name="Vehicle name filter", max_price="Maximum price filter", seller="Seller user (optional)")
async def vehicle_search(interaction: discord.Interaction, name: str = "", max_price: int = 0, seller: discord.Member = None):
    await interaction.response.defer()
    q = "SELECT * FROM vehicle_listings WHERE status='Active'"
    params = []
    if name:
        q += " AND vehicle_name LIKE ?"
        params.append(f"%{name}%")
    if max_price > 0:
        q += " AND price<=?"
        params.append(max_price)
    if seller:
        q += " AND seller_id=?"
        params.append(seller.id)
    q += " ORDER BY created_at DESC LIMIT 10"
    rows = await db.fetchall(q, tuple(params))
    if not rows:
        await interaction.followup.send("🔍 No vehicle listings found matching your criteria.")
        return
    e = listing_embed("🚗 Vehicle Search Results")
    for r in rows:
        e.add_field(
            name=f"{r['vehicle_name']} ({r['model_year']}) — {r['id']}",
            value=f"**Price:** {fmt_cash(r['price'])} | **Color:** {r['color']} | **Seller:** <@{r['seller_id']}>",
            inline=False
        )
    await interaction.followup.send(embed=e)

@tree.command(name="vehicle_info", description="📋 View full vehicle listing details")
@app_commands.describe(listing_id="Vehicle listing ID (e.g. VEH-XXXXXXXX)")
async def vehicle_info(interaction: discord.Interaction, listing_id: str):
    row = await db.fetchone("SELECT * FROM vehicle_listings WHERE id=?", (listing_id.upper(),))
    if not row:
        await interaction.response.send_message("❌ Listing not found.", ephemeral=True)
        return
    e = listing_embed(f"🚗 {row['vehicle_name']} — {row['id']}")
    e.add_field(name="Model Year", value=str(row["model_year"]), inline=True)
    e.add_field(name="Color", value=row["color"], inline=True)
    e.add_field(name="Price", value=fmt_cash(row["price"]), inline=True)
    e.add_field(name="Listing Type", value=row["listing_type"], inline=True)
    e.add_field(name="Status", value=row["status"], inline=True)
    e.add_field(name="Listed By", value=f"<@{row['seller_id']}>", inline=True)
    e.add_field(name="Description", value=row["description"], inline=False)
    e.add_field(name="Expires", value=row["expires_at"][:10] if row["expires_at"] else "N/A", inline=True)
    if row["image_url"]:
        e.set_image(url=row["image_url"])
    view = ListingView(db, row["id"], row["seller_id"])
    await interaction.response.send_message(embed=e, view=view)

@tree.command(name="my_listings", description="📋 View all your active listings (all types)")
@app_commands.describe(category="Filter by: vehicle / property / business / skin / item (leave blank for all)")
async def my_listings(interaction: discord.Interaction, category: str = ""):
    uid = interaction.user.id
    cat = category.lower()
    sections = [
        ("vehicle_listings", "vehicle_name", "price", "🚗 Vehicles"),
        ("property_listings", "property_name", "price", "🏠 Properties"),
        ("business_listings", "business_name", "price", "🏢 Businesses"),
        ("skin_listings", "skin_name", "price", "🎨 Skins"),
        ("item_listings", "item_name", "price", "📦 Items"),
    ]
    if cat:
        sections = [(t, n, p, l) for t, n, p, l in sections if cat in t]
    e = listing_embed("📋 Your Listings")
    any_found = False
    for table, name_col, price_col, label in sections:
        rows = await db.fetchall(f"SELECT * FROM {table} WHERE seller_id=? ORDER BY created_at DESC LIMIT 10", (uid,))
        if rows:
            any_found = True
            for r in rows:
                e.add_field(name=f"{label}: {r[name_col]} — {r['id']} [{r['status']}]", value=fmt_cash(r[price_col]), inline=False)
    if not any_found:
        return await interaction.response.send_message("📭 You have no listings.", ephemeral=True)
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="delete_listing", description="🗑️ Delete your listing (any type)")
@app_commands.describe(listing_id="Listing ID (e.g. VEH-XXXXXXXX, PROP-..., BIZ-..., SKN-..., ITM-...)")
async def delete_listing(interaction: discord.Interaction, listing_id: str):
    lid = listing_id.upper()
    prefix_map = {"VEH": "vehicle_listings", "PROP": "property_listings", "BIZ": "business_listings", "SKN": "skin_listings", "ITM": "item_listings"}
    table = prefix_map.get(lid.split("-")[0])
    if not table:
        return await interaction.response.send_message("❌ Unknown listing type prefix.", ephemeral=True)
    row = await db.fetchone(f"SELECT seller_id FROM {table} WHERE id=?", (lid,))
    if not row:
        return await interaction.response.send_message("❌ Listing not found.", ephemeral=True)
    if row["seller_id"] != interaction.user.id:
        return await interaction.response.send_message("❌ You can only delete your own listings.", ephemeral=True)
    await db.execute(f"UPDATE {table} SET status='Deleted' WHERE id=?", (lid,))
    await interaction.response.send_message(f"✅ Listing **{lid}** deleted.", ephemeral=True)

@tree.command(name="relist", description="🔄 Relist an expired listing (any type)")
@app_commands.describe(listing_id="Listing ID (VEH-..., PROP-..., BIZ-..., SKN-..., ITM-...)")
async def relist(interaction: discord.Interaction, listing_id: str):
    lid = listing_id.upper()
    prefix_map = {"VEH": "vehicle_listings", "PROP": "property_listings", "BIZ": "business_listings", "SKN": "skin_listings", "ITM": "item_listings"}
    table = prefix_map.get(lid.split("-")[0])
    if not table:
        return await interaction.response.send_message("❌ Unknown listing type prefix.", ephemeral=True)
    row = await db.fetchone(f"SELECT id FROM {table} WHERE id=? AND seller_id=?", (lid, interaction.user.id))
    if not row:
        return await interaction.response.send_message("❌ Not found or not yours.", ephemeral=True)
    new_exp = expires_delta(30)
    await db.execute(f"UPDATE {table} SET status='Active',expires_at=? WHERE id=?", (new_exp, lid))
    await interaction.response.send_message(f"✅ Listing **{lid}** relisted. New expiry: {new_exp[:10]}")

# Property commands
@tree.command(name="sell_property", description="🏠 Create a property listing")
async def sell_property(interaction: discord.Interaction):
    if await db.is_maintenance():
        return await interaction.response.send_message("🔧 Maintenance mode active.", ephemeral=True)
    await interaction.response.send_modal(SellPropertyModal(db))

@tree.command(name="property_search", description="🔍 Search property listings")
@app_commands.describe(location="Location filter", prop_type="Property type filter", max_price="Maximum price")
async def property_search(interaction: discord.Interaction, location: str = "", prop_type: str = "", max_price: int = 0):
    await interaction.response.defer()
    q = "SELECT * FROM property_listings WHERE status='Active'"
    params = []
    if location:
        q += " AND location LIKE ?"
        params.append(f"%{location}%")
    if prop_type:
        q += " AND prop_type LIKE ?"
        params.append(f"%{prop_type}%")
    if max_price > 0:
        q += " AND price<=?"
        params.append(max_price)
    q += " ORDER BY created_at DESC LIMIT 10"
    rows = await db.fetchall(q, tuple(params))
    if not rows:
        await interaction.followup.send("🔍 No property listings found.")
        return
    e = listing_embed("🏠 Property Search Results")
    for r in rows:
        e.add_field(
            name=f"{r['property_name']} ({r['prop_type']}) — {r['id']}",
            value=f"**Price:** {fmt_cash(r['price'])} | **Location:** {r['location']} | **Seller:** <@{r['seller_id']}>",
            inline=False
        )
    await interaction.followup.send(embed=e)

@tree.command(name="property_info", description="📋 View property listing details")
@app_commands.describe(listing_id="Property listing ID")
async def property_info(interaction: discord.Interaction, listing_id: str):
    row = await db.fetchone("SELECT * FROM property_listings WHERE id=?", (listing_id.upper(),))
    if not row:
        await interaction.response.send_message("❌ Listing not found.", ephemeral=True)
        return
    e = listing_embed(f"🏠 {row['property_name']} — {row['id']}")
    e.add_field(name="Type", value=row["prop_type"], inline=True)
    e.add_field(name="Location", value=row["location"], inline=True)
    e.add_field(name="Price", value=fmt_cash(row["price"]), inline=True)
    e.add_field(name="Status", value=row["status"], inline=True)
    e.add_field(name="Seller", value=f"<@{row['seller_id']}>", inline=True)
    e.add_field(name="Description", value=row["description"], inline=False)
    view = ListingView(db, row["id"], row["seller_id"])
    await interaction.response.send_message(embed=e, view=view)

# Business commands
@tree.command(name="sell_business", description="🏢 Create a business listing")
async def sell_business(interaction: discord.Interaction):
    if await db.is_maintenance():
        return await interaction.response.send_message("🔧 Maintenance mode active.", ephemeral=True)
    await interaction.response.send_modal(SellBusinessModal(db))

@tree.command(name="business_search", description="🔍 Search business listings")
@app_commands.describe(business_type="Type of business", max_price="Maximum price")
async def business_search(interaction: discord.Interaction, business_type: str = "", max_price: int = 0):
    await interaction.response.defer()
    q = "SELECT * FROM business_listings WHERE status='Active'"
    params = []
    if business_type:
        q += " AND business_type LIKE ?"
        params.append(f"%{business_type}%")
    if max_price > 0:
        q += " AND price<=?"
        params.append(max_price)
    q += " ORDER BY created_at DESC LIMIT 10"
    rows = await db.fetchall(q, tuple(params))
    if not rows:
        return await interaction.followup.send("🔍 No business listings found.")
    e = listing_embed("🏢 Business Search Results")
    for r in rows:
        e.add_field(
            name=f"{r['business_name']} ({r['business_type']}) — {r['id']}",
            value=f"**Price:** {fmt_cash(r['price'])} | **Location:** {r['location']} | **Seller:** <@{r['seller_id']}>",
            inline=False
        )
    await interaction.followup.send(embed=e)

@tree.command(name="business_info", description="📋 View business listing")
@app_commands.describe(listing_id="Business listing ID")
async def business_info(interaction: discord.Interaction, listing_id: str):
    row = await db.fetchone("SELECT * FROM business_listings WHERE id=?", (listing_id.upper(),))
    if not row:
        return await interaction.response.send_message("❌ Not found.", ephemeral=True)
    e = listing_embed(f"🏢 {row['business_name']} — {row['id']}")
    e.add_field(name="Type", value=row["business_type"], inline=True)
    e.add_field(name="Location", value=row["location"], inline=True)
    e.add_field(name="Price", value=fmt_cash(row["price"]), inline=True)
    e.add_field(name="Seller", value=f"<@{row['seller_id']}>", inline=True)
    e.add_field(name="Description", value=row["description"], inline=False)
    view = ListingView(db, row["id"], row["seller_id"])
    await interaction.response.send_message(embed=e, view=view)

# Skin commands
@tree.command(name="sell_skin", description="🎨 Create a skin listing")
async def sell_skin(interaction: discord.Interaction):
    if await db.is_maintenance():
        return await interaction.response.send_message("🔧 Maintenance mode active.", ephemeral=True)
    await interaction.response.send_modal(SellSkinModal(db))

@tree.command(name="skin_search", description="🔍 Search skin listings")
@app_commands.describe(rarity="Rarity filter", max_price="Maximum price")
async def skin_search(interaction: discord.Interaction, rarity: str = "", max_price: int = 0):
    await interaction.response.defer()
    q = "SELECT * FROM skin_listings WHERE status='Active'"
    params = []
    if rarity:
        q += " AND rarity LIKE ?"
        params.append(f"%{rarity}%")
    if max_price > 0:
        q += " AND price<=?"
        params.append(max_price)
    q += " ORDER BY created_at DESC LIMIT 10"
    rows = await db.fetchall(q, tuple(params))
    if not rows:
        return await interaction.followup.send("🔍 No skin listings found.")
    e = listing_embed("🎨 Skin Search Results", discord.Color.purple())
    for r in rows:
        e.add_field(name=f"{r['skin_name']} [{r['rarity']}] — {r['id']}", value=f"**Price:** {fmt_cash(r['price'])} | **Seller:** <@{r['seller_id']}>", inline=False)
    await interaction.followup.send(embed=e)

@tree.command(name="skin_info", description="📋 View skin listing details")
@app_commands.describe(listing_id="Skin listing ID")
async def skin_info(interaction: discord.Interaction, listing_id: str):
    row = await db.fetchone("SELECT * FROM skin_listings WHERE id=?", (listing_id.upper(),))
    if not row:
        return await interaction.response.send_message("❌ Not found.", ephemeral=True)
    e = listing_embed(f"🎨 {row['skin_name']} — {row['id']}", discord.Color.purple())
    e.add_field(name="Rarity", value=row["rarity"], inline=True)
    e.add_field(name="Character", value=row["character"], inline=True)
    e.add_field(name="Price", value=fmt_cash(row["price"]), inline=True)
    e.add_field(name="Seller", value=f"<@{row['seller_id']}>", inline=True)
    e.add_field(name="Description", value=row["description"], inline=False)
    view = ListingView(db, row["id"], row["seller_id"])
    await interaction.response.send_message(embed=e, view=view)

# Item commands
@tree.command(name="sell_item", description="📦 Create an item listing")
async def sell_item(interaction: discord.Interaction):
    if await db.is_maintenance():
        return await interaction.response.send_message("🔧 Maintenance mode active.", ephemeral=True)
    await interaction.response.send_modal(SellItemModal(db))

@tree.command(name="item_search", description="🔍 Search item listings")
@app_commands.describe(category="Item category", max_price="Maximum price")
async def item_search(interaction: discord.Interaction, category: str = "", max_price: int = 0):
    await interaction.response.defer()
    q = "SELECT * FROM item_listings WHERE status='Active'"
    params = []
    if category:
        q += " AND category LIKE ?"
        params.append(f"%{category}%")
    if max_price > 0:
        q += " AND price<=?"
        params.append(max_price)
    q += " ORDER BY created_at DESC LIMIT 10"
    rows = await db.fetchall(q, tuple(params))
    if not rows:
        return await interaction.followup.send("🔍 No item listings found.")
    e = listing_embed("📦 Item Search Results", discord.Color.teal())
    for r in rows:
        e.add_field(name=f"{r['item_name']} [{r['category']}] — {r['id']}", value=f"**Price:** {fmt_cash(r['price'])} | **Qty:** {r['quantity']} | **Seller:** <@{r['seller_id']}>", inline=False)
    await interaction.followup.send(embed=e)

@tree.command(name="item_info", description="📋 View item listing details")
@app_commands.describe(listing_id="Item listing ID")
async def item_info(interaction: discord.Interaction, listing_id: str):
    row = await db.fetchone("SELECT * FROM item_listings WHERE id=?", (listing_id.upper(),))
    if not row:
        return await interaction.response.send_message("❌ Not found.", ephemeral=True)
    e = listing_embed(f"📦 {row['item_name']} — {row['id']}", discord.Color.teal())
    e.add_field(name="Category", value=row["category"], inline=True)
    e.add_field(name="Quantity", value=str(row["quantity"]), inline=True)
    e.add_field(name="Price", value=fmt_cash(row["price"]), inline=True)
    e.add_field(name="Seller", value=f"<@{row['seller_id']}>", inline=True)
    e.add_field(name="Description", value=row["description"], inline=False)
    view = ListingView(db, row["id"], row["seller_id"])
    await interaction.response.send_message(embed=e, view=view)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 2 — AUCTION SYSTEM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="create_auction", description="🔨 Create an auction for an asset")
async def create_auction(interaction: discord.Interaction):
    if await db.is_maintenance():
        return await interaction.response.send_message("🔧 Maintenance mode active.", ephemeral=True)
    await interaction.response.send_modal(AuctionCreateModal(db))

@tree.command(name="auction_info", description="🔨 View auction details and bid")
@app_commands.describe(auction_id="Auction ID (e.g. AUC-XXXXXXXX)")
async def auction_info(interaction: discord.Interaction, auction_id: str):
    row = await db.fetchone("SELECT * FROM auctions WHERE id=?", (auction_id.upper(),))
    if not row:
        return await interaction.response.send_message("❌ Auction not found.", ephemeral=True)
    e = listing_embed(f"🔨 {row['asset_name']} — {row['id']}", discord.Color.orange())
    e.add_field(name="Asset Type", value=row["asset_type"], inline=True)
    e.add_field(name="Starting Bid", value=fmt_cash(row["starting_bid"]), inline=True)
    e.add_field(name="Current Bid", value=fmt_cash(row["current_bid"]), inline=True)
    e.add_field(name="Highest Bidder", value=f"<@{row['highest_bidder']}>" if row["highest_bidder"] else "None", inline=True)
    e.add_field(name="Status", value=row["status"], inline=True)
    e.add_field(name="Ends At", value=row["ends_at"][:16].replace("T", " ") + " UTC", inline=True)
    e.add_field(name="Seller", value=f"<@{row['seller_id']}>", inline=True)
    e.add_field(name="Description", value=row["description"], inline=False)
    view = AuctionBidView(db, row["id"])
    await interaction.response.send_message(embed=e, view=view)

@tree.command(name="my_bids", description="💰 View your active bids")
async def my_bids(interaction: discord.Interaction):
    rows = await db.fetchall(
        "SELECT b.*, a.asset_name, a.current_bid, a.status, a.ends_at FROM bids b JOIN auctions a ON b.auction_id=a.id WHERE b.bidder_id=? ORDER BY b.ts DESC LIMIT 10",
        (interaction.user.id,)
    )
    if not rows:
        return await interaction.response.send_message("📭 No bids placed.", ephemeral=True)
    e = listing_embed("💰 Your Bids")
    for r in rows:
        is_winning = r["current_bid"] == r["amount"] and r["status"] == "Active"
        e.add_field(
            name=f"{r['asset_name']} — {r['auction_id']}",
            value=f"**Your Bid:** {fmt_cash(r['amount'])} | **Status:** {'🏆 Winning' if is_winning else '❌ Outbid'} | **Ends:** {r['ends_at'][:10]}",
            inline=False
        )
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="auction_history", description="📜 View completed auctions")
async def auction_history(interaction: discord.Interaction):
    rows = await db.fetchall("SELECT * FROM auctions WHERE status='Ended' ORDER BY created_at DESC LIMIT 10")
    if not rows:
        return await interaction.response.send_message("📭 No completed auctions.")
    e = listing_embed("📜 Completed Auctions")
    for r in rows:
        e.add_field(
            name=f"{r['asset_name']} — {r['id']}",
            value=f"**Final Bid:** {fmt_cash(r['current_bid'])} | **Winner:** {'<@'+str(r['highest_bidder'])+'>' if r['highest_bidder'] else 'No winner'}",
            inline=False
        )
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 3 — OFFERS & NEGOTIATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="make_offer", description="🤝 Make a purchase offer on a listing")
async def make_offer(interaction: discord.Interaction):
    await interaction.response.send_modal(OfferModal(db))

@tree.command(name="accept_offer", description="✅ Accept an offer on your listing")
@app_commands.describe(offer_id="Offer ID (e.g. OFR-XXXXXXXX)")
async def accept_offer(interaction: discord.Interaction, offer_id: str):
    row = await db.fetchone("SELECT * FROM offers WHERE id=?", (offer_id.upper(),))
    if not row:
        return await interaction.response.send_message("❌ Offer not found.", ephemeral=True)
    if row["seller_id"] != interaction.user.id:
        return await interaction.response.send_message("❌ This offer is not for your listing.", ephemeral=True)
    if row["status"] != "Pending":
        return await interaction.response.send_message("❌ Offer already processed.", ephemeral=True)
    await db.execute("UPDATE offers SET status='Accepted' WHERE id=?", (offer_id.upper(),))
    e = discord.Embed(description=f"✅ You accepted the offer of **{fmt_cash(row['amount'])}** from <@{row['buyer_id']}>.\n\nPlease proceed with the trade and mark listing as sold.", color=discord.Color.green())
    await interaction.response.send_message(embed=e)

@tree.command(name="decline_offer", description="❌ Decline an offer")
@app_commands.describe(offer_id="Offer ID")
async def decline_offer(interaction: discord.Interaction, offer_id: str):
    row = await db.fetchone("SELECT * FROM offers WHERE id=?", (offer_id.upper(),))
    if not row:
        return await interaction.response.send_message("❌ Offer not found.", ephemeral=True)
    if row["seller_id"] != interaction.user.id:
        return await interaction.response.send_message("❌ Not your offer.", ephemeral=True)
    await db.execute("UPDATE offers SET status='Declined' WHERE id=?", (offer_id.upper(),))
    await interaction.response.send_message(f"❌ Offer **{offer_id}** declined.", ephemeral=True)

@tree.command(name="offer_history", description="📜 View your offer history")
async def offer_history(interaction: discord.Interaction):
    rows = await db.fetchall(
        "SELECT * FROM offers WHERE buyer_id=? OR seller_id=? ORDER BY ts DESC LIMIT 15",
        (interaction.user.id, interaction.user.id)
    )
    if not rows:
        return await interaction.response.send_message("📭 No offer history.", ephemeral=True)
    e = listing_embed("📜 Offer History")
    for r in rows:
        role = "Buyer" if r["buyer_id"] == interaction.user.id else "Seller"
        e.add_field(
            name=f"{r['id']} [{r['status']}]",
            value=f"**Role:** {role} | **Listing:** {r['listing_id']} | **Amount:** {fmt_cash(r['amount'])}",
            inline=False
        )
    await interaction.response.send_message(embed=e, ephemeral=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 4 — WATCHLIST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="watchlist", description="❤️ View your watchlist")
async def watchlist(interaction: discord.Interaction):
    rows = await db.fetchall("SELECT * FROM watchlist WHERE user_id=? ORDER BY ts DESC", (interaction.user.id,))
    if not rows:
        return await interaction.response.send_message("📭 Your watchlist is empty.", ephemeral=True)
    e = listing_embed("❤️ Your Watchlist")
    for r in rows:
        e.add_field(name=f"{r['listing_type'].upper()}: {r['listing_id']}", value=f"Added: {r['ts'][:10]}", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 5 — FINANCE & ECONOMY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="wallet", description="💼 Check your wallet balance")
async def wallet(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    w = await db.get_wallet(target.id)
    e = listing_embed(f"💼 Wallet — {target.display_name}", discord.Color.gold())
    e.add_field(name="💵 Cash", value=fmt_cash(w["cash"]), inline=True)
    e.add_field(name="🪙 Coins", value=fmt_coins(w["coins"]), inline=True)
    e.add_field(name="🏦 Bank", value=fmt_cash(w["bank"]), inline=True)
    e.add_field(name="📈 Total Earned", value=fmt_cash(w["total_earned"]), inline=True)
    e.add_field(name="📉 Total Spent", value=fmt_cash(w["total_spent"]), inline=True)
    net = w["cash"] + w["bank"]
    e.add_field(name="🏆 Net Worth", value=fmt_cash(net), inline=True)
    e.set_thumbnail(url=target.display_avatar.url)
    await interaction.response.send_message(embed=e)

@tree.command(name="pay", description="💸 Send cash to another user")
@app_commands.describe(user="User to pay", amount="Amount to send", reason="Reason for payment")
async def pay(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "Payment"):
    if user.id == interaction.user.id:
        return await interaction.response.send_message("❌ Cannot pay yourself.", ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    success = await db.remove_cash(interaction.user.id, amount, reason)
    if not success:
        w = await db.get_wallet(interaction.user.id)
        return await interaction.response.send_message(f"❌ Insufficient funds. You have {fmt_cash(w['cash'])}.", ephemeral=True)
    await db.add_cash(user.id, amount, reason, from_id=interaction.user.id)
    e = discord.Embed(
        description=f"✅ **{fmt_cash(amount)}** sent to {user.mention}\n**Reason:** {reason}",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=e)

@tree.command(name="deposit", description="🏦 Deposit cash into your bank")
@app_commands.describe(amount="Amount to deposit")
async def deposit(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    success = await db.remove_cash(interaction.user.id, amount, "Bank deposit")
    if not success:
        return await interaction.response.send_message("❌ Insufficient cash balance.", ephemeral=True)
    await db.execute("UPDATE wallets SET bank=bank+? WHERE user_id=?", (amount, interaction.user.id))
    await interaction.response.send_message(f"✅ Deposited **{fmt_cash(amount)}** into your bank.", ephemeral=True)

@tree.command(name="withdraw", description="🏦 Withdraw cash from your bank")
@app_commands.describe(amount="Amount to withdraw")
async def withdraw(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    w = await db.get_wallet(interaction.user.id)
    if w["bank"] < amount:
        return await interaction.response.send_message(f"❌ Only {fmt_cash(w['bank'])} in bank.", ephemeral=True)
    await db.execute("UPDATE wallets SET bank=bank-? WHERE user_id=?", (amount, interaction.user.id))
    await db.add_cash(interaction.user.id, amount, "Bank withdrawal")
    await interaction.response.send_message(f"✅ Withdrew **{fmt_cash(amount)}** from bank.", ephemeral=True)

@tree.command(name="fixed_deposit", description="📈 Create a fixed deposit (5% returns after 7 days)")
@app_commands.describe(amount="Amount to lock in FD")
async def fixed_deposit(interaction: discord.Interaction, amount: int):
    if amount < 1000:
        return await interaction.response.send_message("❌ Minimum FD amount is ₹1,000.", ephemeral=True)
    success = await db.remove_cash(interaction.user.id, amount, "Fixed Deposit")
    if not success:
        return await interaction.response.send_message("❌ Insufficient cash.", ephemeral=True)
    mature = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).isoformat()
    await db.execute("INSERT INTO fixed_deposits(user_id,amount,mature_at) VALUES(?,?,?)", (interaction.user.id, amount, mature))
    returns = int(amount * 1.05)
    e = discord.Embed(description=f"📈 Fixed deposit of **{fmt_cash(amount)}** created!\n**Returns:** {fmt_cash(returns)} after 7 days.\n**Matures:** {mature[:10]}", color=discord.Color.green())
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="claim_fd", description="📈 Claim matured fixed deposits")
async def claim_fd(interaction: discord.Interaction):
    now = datetime.datetime.utcnow().isoformat()
    rows = await db.fetchall("SELECT * FROM fixed_deposits WHERE user_id=? AND claimed=0 AND mature_at<=?", (interaction.user.id, now))
    if not rows:
        return await interaction.response.send_message("📭 No matured FDs to claim.", ephemeral=True)
    total = 0
    for r in rows:
        returns = int(r["amount"] * 1.05)
        total += returns
        await db.execute("UPDATE fixed_deposits SET claimed=1 WHERE id=?", (r["id"],))
        await db.add_cash(interaction.user.id, returns, "FD Maturity Return")
    e = discord.Embed(description=f"✅ Claimed **{len(rows)}** FD(s). Total received: **{fmt_cash(total)}**", color=discord.Color.green())
    await interaction.response.send_message(embed=e)

@tree.command(name="transaction_history", description="📜 View your recent transactions")
async def transaction_history(interaction: discord.Interaction):
    rows = await db.fetchall(
        "SELECT * FROM transactions WHERE sender_id=? OR receiver_id=? ORDER BY ts DESC LIMIT 15",
        (interaction.user.id, interaction.user.id)
    )
    if not rows:
        return await interaction.response.send_message("📭 No transaction history.", ephemeral=True)
    e = listing_embed("📜 Transaction History")
    for r in rows:
        direction = "📤 Sent" if r["sender_id"] == interaction.user.id else "📥 Received"
        other_id = r["receiver_id"] if r["sender_id"] == interaction.user.id else r["sender_id"]
        e.add_field(
            name=f"{direction} — {fmt_cash(r['amount'])}",
            value=f"**{'To' if direction=='📤 Sent' else 'From'}:** <@{other_id}> | **Reason:** {r['reason'] or 'N/A'} | **Date:** {r['ts'][:10]}",
            inline=False
        )
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="richlist", description="🏆 Top 10 richest players")
async def richlist(interaction: discord.Interaction):
    rows = await db.fetchall("SELECT user_id, cash+bank AS networth FROM wallets ORDER BY networth DESC LIMIT 10")
    e = listing_embed("🏆 Richlist — Top 10")
    for i, r in enumerate(rows, 1):
        e.add_field(name=f"#{i} — <@{r['user_id']}>", value=f"**Net Worth:** {fmt_cash(r['networth'])}", inline=False)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 6 — COIN SHOP & BUY COINS (UPI: adityaghatule30@okaxis)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="buy_coins", description="🪙 Buy KAT Coins using UPI payment")
async def buy_coins(interaction: discord.Interaction):
    e = listing_embed("🪙 KAT Coin Shop — Buy with UPI", discord.Color.gold())
    e.description = (
        f"Purchase KAT Coins using **UPI payment**.\n"
        f"{divider()}\n"
        f"**UPI ID:** `{UPI_ID}`\n"
        f"{divider()}\n"
        f"**How to Buy:**\n"
        f"**1.** Select a package below\n"
        f"**2.** Pay the exact amount to UPI: `{UPI_ID}`\n"
        f"**3.** Submit your UTR number as proof\n"
        f"**4.** Admin will verify and credit your coins within 24 hours\n"
        f"{divider()}\n"
        f"**Packages:**"
    )
    for pkg in COIN_PACKAGES:
        total = pkg["coins"] + pkg["bonus"]
        bonus_text = f" (+{pkg['bonus']} bonus)" if pkg["bonus"] > 0 else ""
        e.add_field(
            name=f"🪙 {pkg['label']}",
            value=f"**{total} Coins{bonus_text}** — ₹{pkg['price_inr']}",
            inline=True
        )
    e.set_footer(text=f"UPI ID: {UPI_ID} | Payments are manually verified")
    view = CoinShopView(db)
    await interaction.response.send_message(embed=e, view=view)

@tree.command(name="sell_coins", description="💱 Sell KAT Coins for in-game cash")
@app_commands.describe(amount="Number of coins to sell (1 coin = ₹500 cash)")
async def sell_coins(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    if amount < 10:
        return await interaction.response.send_message("❌ Minimum sell is 10 coins.", ephemeral=True)
    success = await db.remove_coins(interaction.user.id, amount)
    if not success:
        return await interaction.response.send_message("❌ Insufficient coins.", ephemeral=True)
    cash_earned = amount * 500
    await db.add_cash(interaction.user.id, cash_earned, f"Sold {amount} coins")
    e = discord.Embed(
        description=f"✅ Sold **{fmt_coins(amount)}** for **{fmt_cash(cash_earned)}** in-game cash.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=e)

@tree.command(name="coin_shop", description="🛒 Browse items available in the Coin Shop")
async def coin_shop_browse(interaction: discord.Interaction):
    e = listing_embed("🛒 KAT Coin Shop — Premium Items", discord.Color.gold())
    e.description = f"Spend your 🪙 KAT Coins on premium items!\nBuy coins via `/buy_coins` (UPI: `{UPI_ID}`)"
    e.add_field(name="VIP Bronze — 200 Coins", value="5 extra listing slots + 5% coin discount", inline=False)
    e.add_field(name="VIP Silver — 500 Coins", value="15 extra listing slots + 10% coin discount", inline=False)
    e.add_field(name="VIP Gold — 1500 Coins", value="50 extra listing slots + 20% discount + Priority support", inline=False)
    e.add_field(name="Basic Crate — 50 Coins", value="Contains cash, badges, or boosts", inline=False)
    e.add_field(name="Premium Crate — 150 Coins", value="Better rewards including VIP time", inline=False)
    e.add_field(name="VIP Crate — 400 Coins", value="High-tier rewards and rare titles", inline=False)
    e.add_field(name="Event Crate — 200 Coins", value="Limited-time exclusive rewards", inline=False)
    e.add_field(name="Anniversary Crate — 999 Coins", value="Top-tier ultra-rare rewards", inline=False)
    e.set_footer(text=f"Use /buy_vip or /open_crate to spend coins | UPI: {UPI_ID}")
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 7 — VIP SYSTEM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="buy_vip", description="👑 Purchase VIP membership with coins")
@app_commands.describe(tier="VIP tier: bronze / silver / gold")
async def buy_vip(interaction: discord.Interaction, tier: str):
    tier = tier.lower()
    if tier not in VIP_COSTS:
        return await interaction.response.send_message("❌ Valid tiers: bronze, silver, gold", ephemeral=True)
    cost = VIP_COSTS[tier]
    success = await db.remove_coins(interaction.user.id, cost)
    if not success:
        return await interaction.response.send_message(f"❌ Need {fmt_coins(cost)} coins. You don't have enough.", ephemeral=True)
    await db.get_profile(interaction.user.id)
    expires = expires_delta(30)
    await db.execute("UPDATE profiles SET vip_tier=?,vip_expires=? WHERE user_id=?", (tier, expires, interaction.user.id))
    perks = VIP_PERKS[tier]
    e = listing_embed(f"👑 VIP {tier.capitalize()} Activated!", discord.Color.gold())
    e.add_field(name="Tier", value=tier.capitalize(), inline=True)
    e.add_field(name="Cost", value=fmt_coins(cost), inline=True)
    e.add_field(name="Duration", value="30 days", inline=True)
    e.add_field(name="Extra Listings", value=str(perks["extra_listings"]), inline=True)
    e.add_field(name="Coin Discount", value=f"{perks['coin_discount']}%", inline=True)
    e.add_field(name="Priority Support", value="✅" if perks["priority_support"] else "❌", inline=True)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 8 — CRATE SYSTEM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="open_crate", description="📦 Open a crate using coins")
@app_commands.describe(crate_type="Crate type: basic / premium / vip / event / anniversary")
async def open_crate(interaction: discord.Interaction, crate_type: str):
    ct = crate_type.lower()
    if ct not in CRATE_POOLS:
        return await interaction.response.send_message(f"❌ Valid crates: {', '.join(CRATE_POOLS.keys())}", ephemeral=True)
    cost = CRATE_PRICES[ct]
    success = await db.remove_coins(interaction.user.id, cost)
    if not success:
        return await interaction.response.send_message(f"❌ Need {fmt_coins(cost)} to open a {ct} crate.", ephemeral=True)
    pool = CRATE_POOLS[ct]
    items, weights = zip(*pool)
    result = random.choices(items, weights=weights, k=1)[0]
    await _apply_crate_reward(interaction.user.id, result)
    e = listing_embed(f"📦 {ct.capitalize()} Crate Opened!", discord.Color.gold())
    e.add_field(name="🎁 You got", value=f"**{result}**", inline=False)
    e.add_field(name="Cost", value=fmt_coins(cost), inline=True)
    await interaction.response.send_message(embed=e)

async def _apply_crate_reward(user_id: int, result: str):
    if result.startswith("Cash "):
        amt = int(result.split(" ")[1])
        await db.add_cash(user_id, amt, "Crate reward")
    elif result.startswith("Badge:") or result.startswith("Title:") or result.startswith("VIP:") or result.startswith("EventItem:") or result.startswith("Coupon:") or result.startswith("XP Boost"):
        await db.execute("INSERT INTO inventory(user_id,item_type,item_name) VALUES(?,?,?)", (user_id, "crate_reward", result))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 9 — DAILY & WEEKLY REWARDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="daily", description="📅 Claim your daily reward")
async def daily(interaction: discord.Interaction):
    row = await db.fetchone("SELECT * FROM daily_streaks WHERE user_id=?", (interaction.user.id,))
    now = datetime.datetime.utcnow()
    if row:
        if row["last_claim"]:
            last = datetime.datetime.fromisoformat(row["last_claim"])
            if (now - last).total_seconds() < 86400:
                next_claim = last + datetime.timedelta(days=1)
                remaining = next_claim - now
                hrs = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                return await interaction.response.send_message(f"⏰ Daily already claimed. Come back in **{hrs}h {mins}m**.", ephemeral=True)
            days_since = (now - last).days
            new_streak = row["streak"] + 1 if days_since == 1 else 1
        else:
            new_streak = 1
        await db.execute("UPDATE daily_streaks SET streak=?,last_claim=?,total_claims=total_claims+1 WHERE user_id=?", (new_streak, now.isoformat(), interaction.user.id))
    else:
        new_streak = 1
        await db.execute("INSERT INTO daily_streaks(user_id,streak,last_claim,total_claims) VALUES(?,?,?,1)", (interaction.user.id, 1, now.isoformat()))
    base = 500
    streak_bonus = min(new_streak * 100, 2000)
    total = base + streak_bonus
    await db.add_cash(interaction.user.id, total, "Daily reward")
    e = listing_embed("📅 Daily Reward Claimed!", discord.Color.green())
    e.add_field(name="💵 Cash Received", value=fmt_cash(total), inline=True)
    e.add_field(name="🔥 Streak", value=f"{new_streak} days", inline=True)
    e.add_field(name="📈 Streak Bonus", value=fmt_cash(streak_bonus), inline=True)
    await interaction.response.send_message(embed=e)

@tree.command(name="weekly", description="📆 Claim your weekly reward")
async def weekly(interaction: discord.Interaction):
    row = await db.fetchone("SELECT * FROM weekly_claims WHERE user_id=?", (interaction.user.id,))
    now = datetime.datetime.utcnow()
    if row and row["last_claim"]:
        last = datetime.datetime.fromisoformat(row["last_claim"])
        if (now - last).total_seconds() < 604800:
            next_claim = last + datetime.timedelta(weeks=1)
            remaining = next_claim - now
            days = remaining.days
            hrs = int((remaining.total_seconds() % 86400) // 3600)
            return await interaction.response.send_message(f"⏰ Weekly already claimed. Come back in **{days}d {hrs}h**.", ephemeral=True)
        await db.execute("UPDATE weekly_claims SET last_claim=?,total_claims=total_claims+1 WHERE user_id=?", (now.isoformat(), interaction.user.id))
    else:
        await db.execute("INSERT OR REPLACE INTO weekly_claims(user_id,last_claim,total_claims) VALUES(?,?,1)", (interaction.user.id, now.isoformat()))
    cash_reward = 5000
    coin_reward = 20
    await db.add_cash(interaction.user.id, cash_reward, "Weekly reward")
    await db.add_coins(interaction.user.id, coin_reward)
    e = listing_embed("📆 Weekly Reward Claimed!", discord.Color.blue())
    e.add_field(name="💵 Cash", value=fmt_cash(cash_reward), inline=True)
    e.add_field(name="🪙 Coins", value=fmt_coins(coin_reward), inline=True)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 10 — PROFILES & REPUTATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="profile", description="👤 View a user's market profile")
async def profile(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    p = await db.get_profile(target.id)
    w = await db.get_wallet(target.id)
    e = listing_embed(f"👤 {p['display_name'] or target.display_name}'s Profile")
    e.set_thumbnail(url=target.display_avatar.url)
    e.add_field(name="🏷️ Title", value=p["title"], inline=True)
    e.add_field(name="👑 VIP", value=p["vip_tier"].capitalize() if p["vip_tier"] != "none" else "None", inline=True)
    e.add_field(name="💰 Net Worth", value=fmt_cash(w["cash"] + w["bank"]), inline=True)
    e.add_field(name="✅ Positive Vouches", value=str(p["vouches_positive"]), inline=True)
    e.add_field(name="🔶 Neutral Vouches", value=str(p["vouches_neutral"]), inline=True)
    e.add_field(name="❌ Negative Vouches", value=str(p["vouches_negative"]), inline=True)
    e.add_field(name="🔄 Total Trades", value=str(p["total_trades"]), inline=True)
    trust = p["vouches_positive"] - p["vouches_negative"]
    e.add_field(name="⭐ Trust Score", value=str(trust), inline=True)
    if p["bio"]:
        e.add_field(name="📝 Bio", value=p["bio"], inline=False)
    e.add_field(name="📅 Member Since", value=p["created_at"][:10], inline=True)
    await interaction.response.send_message(embed=e)

@tree.command(name="edit_profile", description="✏️ Edit your profile bio and display name")
async def edit_profile(interaction: discord.Interaction):
    await interaction.response.send_modal(ProfileBioModal(db))

@tree.command(name="vouch", description="⭐ Leave a vouch for a trader")
async def vouch(interaction: discord.Interaction):
    await interaction.response.send_modal(VouchModal(db))

@tree.command(name="leaderboard", description="🏆 View various leaderboards")
@app_commands.describe(category="Category: cash / vouches / trades")
async def leaderboard(interaction: discord.Interaction, category: str = "cash"):
    cat = category.lower()
    if cat == "cash":
        rows = await db.fetchall("SELECT user_id, cash+bank AS v FROM wallets ORDER BY v DESC LIMIT 10")
        title = "💵 Cash Leaderboard"
        fmt = lambda r: fmt_cash(r["v"])
    elif cat == "vouches":
        rows = await db.fetchall("SELECT user_id, vouches_positive AS v FROM profiles ORDER BY v DESC LIMIT 10")
        title = "✅ Vouch Leaderboard"
        fmt = lambda r: f"{r['v']} positive vouches"
    elif cat == "trades":
        rows = await db.fetchall("SELECT user_id, total_trades AS v FROM profiles ORDER BY v DESC LIMIT 10")
        title = "🔄 Trade Leaderboard"
        fmt = lambda r: f"{r['v']} trades"
    else:
        return await interaction.response.send_message("❌ Valid categories: cash, vouches, trades", ephemeral=True)
    e = listing_embed(title)
    if not rows:
        e.description = "No data yet."
    for i, r in enumerate(rows, 1):
        e.add_field(name=f"#{i} — <@{r['user_id']}>", value=fmt(r), inline=False)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 11 — CONTRACTS & BOUNTIES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="post_contract", description="📜 Post a contract or job listing")
async def post_contract(interaction: discord.Interaction):
    await interaction.response.send_modal(ContractModal(db))

@tree.command(name="contracts", description="📜 Browse active contracts")
async def contracts(interaction: discord.Interaction):
    rows = await db.fetchall("SELECT * FROM contracts WHERE status='Active' ORDER BY created_at DESC LIMIT 10")
    if not rows:
        return await interaction.response.send_message("📭 No active contracts.", ephemeral=True)
    e = listing_embed("📜 Active Contracts & Jobs")
    for r in rows:
        e.add_field(
            name=f"{r['title']} — {r['id']}",
            value=f"**Reward:** {fmt_cash(r['reward_cash'])} + {fmt_coins(r['reward_coins'])} | **Deadline:** {r['deadline']} | **Posted by:** <@{r['poster_id']}>",
            inline=False
        )
    await interaction.response.send_message(embed=e)

@tree.command(name="take_contract", description="✋ Accept a contract")
@app_commands.describe(contract_id="Contract ID")
async def take_contract(interaction: discord.Interaction, contract_id: str):
    row = await db.fetchone("SELECT * FROM contracts WHERE id=? AND status='Active'", (contract_id.upper(),))
    if not row:
        return await interaction.response.send_message("❌ Contract not found or not active.", ephemeral=True)
    if row["poster_id"] == interaction.user.id:
        return await interaction.response.send_message("❌ Cannot take your own contract.", ephemeral=True)
    await db.execute("UPDATE contracts SET worker_id=?,status='In Progress' WHERE id=?", (interaction.user.id, contract_id.upper()))
    e = discord.Embed(description=f"✅ You accepted contract **{contract_id}**. Contact <@{row['poster_id']}> to begin.", color=discord.Color.green())
    await interaction.response.send_message(embed=e)

@tree.command(name="complete_contract", description="✅ Mark contract as completed (poster only)")
@app_commands.describe(contract_id="Contract ID", worker="The worker who completed the contract")
async def complete_contract(interaction: discord.Interaction, contract_id: str, worker: discord.Member):
    row = await db.fetchone("SELECT * FROM contracts WHERE id=? AND poster_id=?", (contract_id.upper(), interaction.user.id))
    if not row:
        return await interaction.response.send_message("❌ Contract not found or not yours.", ephemeral=True)
    await db.execute("UPDATE contracts SET status='Completed' WHERE id=?", (contract_id.upper(),))
    if row["reward_cash"] > 0:
        await db.add_cash(worker.id, row["reward_cash"], f"Contract reward: {contract_id}")
    if row["reward_coins"] > 0:
        await db.add_coins(worker.id, row["reward_coins"])
    await db.execute("UPDATE profiles SET total_trades=total_trades+1 WHERE user_id=?", (worker.id,))
    e = discord.Embed(
        description=f"✅ Contract **{contract_id}** completed!\n{worker.mention} received **{fmt_cash(row['reward_cash'])}** + **{fmt_coins(row['reward_coins'])}**.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=e)

@tree.command(name="post_bounty", description="🎯 Post a bounty")
@app_commands.describe(target="Target description", description="What needs to be done", reward="Cash reward amount")
async def post_bounty(interaction: discord.Interaction, target: str, description: str, reward: int):
    if reward <= 0:
        return await interaction.response.send_message("❌ Reward must be positive.", ephemeral=True)
    success = await db.remove_cash(interaction.user.id, reward, "Bounty escrow")
    if not success:
        return await interaction.response.send_message("❌ Insufficient funds for bounty escrow.", ephemeral=True)
    bid = db.new_id("BNT")
    await db.execute("INSERT INTO bounties(id,poster_id,target,description,reward) VALUES(?,?,?,?,?)",
                     (bid, interaction.user.id, target, description, reward))
    e = listing_embed(f"🎯 Bounty Posted — {bid}", discord.Color.red())
    e.add_field(name="Target", value=target, inline=True)
    e.add_field(name="Reward", value=fmt_cash(reward), inline=True)
    e.add_field(name="Description", value=description, inline=False)
    await interaction.response.send_message(embed=e)

@tree.command(name="bounties", description="🎯 View active bounties")
async def bounties_list(interaction: discord.Interaction):
    rows = await db.fetchall("SELECT * FROM bounties WHERE status='Active' ORDER BY created_at DESC LIMIT 10")
    if not rows:
        return await interaction.response.send_message("📭 No active bounties.")
    e = listing_embed("🎯 Active Bounties", discord.Color.red())
    for r in rows:
        e.add_field(name=f"🎯 {r['target']} — {r['id']}", value=f"**Reward:** {fmt_cash(r['reward'])} | **Posted by:** <@{r['poster_id']}>", inline=False)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 12 — SECURITY & DISPUTES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="open_dispute", description="⚠️ Open a dispute against a user")
async def open_dispute(interaction: discord.Interaction):
    await interaction.response.send_modal(DisputeModal(db, "Dispute"))

@tree.command(name="report_user", description="🚨 Report a user for suspicious activity")
async def report_user(interaction: discord.Interaction):
    await interaction.response.send_modal(DisputeModal(db, "Report"))

@tree.command(name="scam_report", description="🚨 Report a scammer")
async def scam_report(interaction: discord.Interaction):
    await interaction.response.send_modal(DisputeModal(db, "Scam Report"))

@tree.command(name="my_cases", description="📋 View your dispute/report cases")
async def my_cases(interaction: discord.Interaction):
    rows = await db.fetchall("SELECT * FROM disputes WHERE reporter_id=? ORDER BY created_at DESC LIMIT 10", (interaction.user.id,))
    if not rows:
        return await interaction.response.send_message("📭 No cases filed.", ephemeral=True)
    e = listing_embed("📋 Your Cases")
    for r in rows:
        status_icon = {"Open": "🔴", "Under Review": "🟡", "Resolved": "🟢", "Dismissed": "⚫"}.get(r["status"], "⚪")
        e.add_field(name=f"{r['id']} [{r['case_type']}]", value=f"**Status:** {status_icon} {r['status']} | **Against:** <@{r['reported_id']}> | **Filed:** {r['created_at'][:10]}", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 13 — INVENTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="inventory", description="🎒 View your inventory")
async def inventory(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    rows = await db.fetchall("SELECT * FROM inventory WHERE user_id=? ORDER BY obtained_at DESC", (target.id,))
    if not rows:
        return await interaction.response.send_message("🎒 Inventory is empty.", ephemeral=True)
    e = listing_embed(f"🎒 {target.display_name}'s Inventory")
    for r in rows:
        e.add_field(name=r["item_name"], value=f"**Type:** {r['item_type']} | **Qty:** {r['quantity']} | **Since:** {r['obtained_at'][:10]}", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 14 — REDEEM CODES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="redeem", description="🎟️ Redeem a code for rewards")
@app_commands.describe(code="The redemption code")
async def redeem(interaction: discord.Interaction, code: str):
    c = code.upper().strip()
    row = await db.fetchone("SELECT * FROM redeem_codes WHERE code=?", (c,))
    if not row:
        return await interaction.response.send_message("❌ Invalid code.", ephemeral=True)
    if row["expires_at"] and datetime.datetime.utcnow().isoformat() > row["expires_at"]:
        return await interaction.response.send_message("❌ This code has expired.", ephemeral=True)
    if row["uses"] >= row["max_uses"]:
        return await interaction.response.send_message("❌ This code has reached its maximum uses.", ephemeral=True)
    already = await db.fetchone("SELECT code FROM code_uses WHERE code=? AND user_id=?", (c, interaction.user.id))
    if already:
        return await interaction.response.send_message("❌ You already used this code.", ephemeral=True)
    await db.execute("UPDATE redeem_codes SET uses=uses+1 WHERE code=?", (c,))
    await db.execute("INSERT INTO code_uses(code,user_id) VALUES(?,?)", (c, interaction.user.id))
    reward_type = row["reward_type"]
    reward_value = row["reward_value"]
    result_text = ""
    if reward_type == "cash":
        amt = int(reward_value)
        await db.add_cash(interaction.user.id, amt, f"Redeem code: {c}")
        result_text = f"**{fmt_cash(amt)}** cash"
    elif reward_type == "coins":
        amt = int(reward_value)
        await db.add_coins(interaction.user.id, amt)
        result_text = f"**{fmt_coins(amt)}** coins"
    elif reward_type in ("vip", "badge", "title"):
        await db.execute("INSERT INTO inventory(user_id,item_type,item_name) VALUES(?,?,?)", (interaction.user.id, reward_type, reward_value))
        result_text = f"**{reward_type.capitalize()}: {reward_value}**"
    e = listing_embed("🎟️ Code Redeemed!", discord.Color.green())
    e.add_field(name="Code", value=f"`{c}`", inline=True)
    e.add_field(name="Reward", value=result_text, inline=True)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 15 — BIRTHDAY SYSTEM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="set_birthday", description="🎂 Set your birthday (one-time only)")
@app_commands.describe(birthday="Your birthday in MM-DD format (e.g. 08-25)")
async def set_birthday(interaction: discord.Interaction, birthday: str):
    existing = await db.fetchone("SELECT user_id FROM birthdays WHERE user_id=?", (interaction.user.id,))
    if existing:
        return await interaction.response.send_message("❌ Birthday already set. Contact admin to change.", ephemeral=True)
    try:
        datetime.datetime.strptime(birthday, "%m-%d")
    except ValueError:
        return await interaction.response.send_message("❌ Use MM-DD format, e.g. 08-25", ephemeral=True)
    await db.execute("INSERT INTO birthdays(user_id,birthday) VALUES(?,?)", (interaction.user.id, birthday))
    await interaction.response.send_message(f"🎂 Birthday set to **{birthday}**! You'll receive a special reward on your birthday.", ephemeral=True)

@tree.command(name="birthday", description="🎂 Check a user's birthday")
async def birthday_check(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    row = await db.fetchone("SELECT birthday FROM birthdays WHERE user_id=?", (target.id,))
    if not row:
        return await interaction.response.send_message(f"📭 {target.display_name} hasn't set a birthday.")
    await interaction.response.send_message(f"🎂 **{target.display_name}'s** birthday is on **{row['birthday']}**!")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 16 — RELATIONSHIPS & FAMILY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="propose", description="💍 Propose to another user")
async def propose(interaction: discord.Interaction, user: discord.Member):
    if user.id == interaction.user.id:
        return await interaction.response.send_message("❌ Cannot propose to yourself.", ephemeral=True)
    row = await db.fetchone("SELECT status FROM relationships WHERE user_id=?", (interaction.user.id,))
    if row and row["status"] == "Married":
        return await interaction.response.send_message("❌ You are already married.", ephemeral=True)

    class ProposeView(ui.View):
        def __init__(self):
            super().__init__(timeout=60)
        @ui.button(label="💍 Accept", style=discord.ButtonStyle.success)
        async def accept(self, btn_inter: discord.Interaction, button: ui.Button):
            if btn_inter.user.id != user.id:
                return await btn_inter.response.send_message("❌ Only the recipient can accept.", ephemeral=True)
            now = datetime.datetime.utcnow().isoformat()
            await db.execute("INSERT OR REPLACE INTO relationships(user_id,partner_id,status,married_at) VALUES(?,?,?,?)", (interaction.user.id, user.id, "Married", now))
            await db.execute("INSERT OR REPLACE INTO relationships(user_id,partner_id,status,married_at) VALUES(?,?,?,?)", (user.id, interaction.user.id, "Married", now))
            e = discord.Embed(description=f"💍 {interaction.user.mention} and {user.mention} are now married! Congratulations! 🎉", color=discord.Color.pink())
            await btn_inter.response.send_message(embed=e)
            self.stop()
        @ui.button(label="❌ Decline", style=discord.ButtonStyle.danger)
        async def decline(self, btn_inter: discord.Interaction, button: ui.Button):
            if btn_inter.user.id != user.id:
                return await btn_inter.response.send_message("❌ Only the recipient can decline.", ephemeral=True)
            await btn_inter.response.send_message(f"💔 {user.mention} declined the proposal.", ephemeral=False)
            self.stop()

    e = discord.Embed(description=f"💍 {interaction.user.mention} has proposed to {user.mention}!\n\n{user.mention}, do you accept?", color=discord.Color.pink())
    await interaction.response.send_message(embed=e, view=ProposeView())

@tree.command(name="divorce", description="💔 Divorce your partner")
async def divorce(interaction: discord.Interaction):
    row = await db.fetchone("SELECT * FROM relationships WHERE user_id=? AND status='Married'", (interaction.user.id,))
    if not row:
        return await interaction.response.send_message("❌ You are not married.", ephemeral=True)
    await db.execute("UPDATE relationships SET status='Divorced',partner_id=NULL WHERE user_id=?", (interaction.user.id,))
    await db.execute("UPDATE relationships SET status='Single',partner_id=NULL WHERE user_id=?", (row["partner_id"],))
    await interaction.response.send_message(f"💔 You are now divorced.")

@tree.command(name="relationship", description="💑 Check your or someone's relationship status")
async def relationship(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    row = await db.fetchone("SELECT * FROM relationships WHERE user_id=?", (target.id,))
    if not row:
        return await interaction.response.send_message(f"💔 {target.display_name} is **Single**.")
    e = discord.Embed(color=discord.Color.pink())
    e.set_author(name=f"{target.display_name}'s Relationship")
    e.add_field(name="Status", value=row["status"], inline=True)
    if row["partner_id"]:
        e.add_field(name="Partner", value=f"<@{row['partner_id']}>", inline=True)
    if row["married_at"]:
        e.add_field(name="Married Since", value=row["married_at"][:10], inline=True)
    await interaction.response.send_message(embed=e)

@tree.command(name="create_family", description="👨‍👩‍👧 Create a family faction")
@app_commands.describe(name="Family name", description="Family description")
async def create_family(interaction: discord.Interaction, name: str, description: str = ""):
    existing = await db.fetchone("SELECT family_id FROM family_members WHERE user_id=?", (interaction.user.id,))
    if existing:
        return await interaction.response.send_message("❌ You are already in a family.", ephemeral=True)
    fid = db.new_id("FAM")
    await db.execute("INSERT INTO families(id,name,leader_id,description) VALUES(?,?,?,?)", (fid, name, interaction.user.id, description))
    await db.execute("INSERT INTO family_members(family_id,user_id,rank) VALUES(?,?,?)", (fid, interaction.user.id, "Leader"))
    e = listing_embed(f"👨‍👩‍👧 Family Created — {name}", discord.Color.green())
    e.add_field(name="Family ID", value=fid, inline=True)
    e.add_field(name="Leader", value=interaction.user.mention, inline=True)
    await interaction.response.send_message(embed=e)

@tree.command(name="family_info", description="👨‍👩‍👧 View family information")
@app_commands.describe(family_id="Family ID")
async def family_info(interaction: discord.Interaction, family_id: str):
    fam = await db.fetchone("SELECT * FROM families WHERE id=?", (family_id.upper(),))
    if not fam:
        return await interaction.response.send_message("❌ Family not found.", ephemeral=True)
    members = await db.fetchall("SELECT * FROM family_members WHERE family_id=?", (family_id.upper(),))
    e = listing_embed(f"👨‍👩‍👧 {fam['name']}")
    e.add_field(name="Leader", value=f"<@{fam['leader_id']}>", inline=True)
    e.add_field(name="Members", value=str(len(members)), inline=True)
    if fam["description"]:
        e.add_field(name="Description", value=fam["description"], inline=False)
    member_list = []
    for m in members[:10]:
        member_list.append(f"**{m['rank']}** — <@{m['user_id']}>")
    if member_list:
        e.add_field(name="Member List", value="\n".join(member_list), inline=False)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 17 — MARKET ANALYTICS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="market_stats", description="📊 View overall market statistics")
async def market_stats(interaction: discord.Interaction):
    await interaction.response.defer()
    veh_count = (await db.fetchone("SELECT COUNT(*) AS c FROM vehicle_listings WHERE status='Active'"))["c"]
    prop_count = (await db.fetchone("SELECT COUNT(*) AS c FROM property_listings WHERE status='Active'"))["c"]
    biz_count  = (await db.fetchone("SELECT COUNT(*) AS c FROM business_listings WHERE status='Active'"))["c"]
    skin_count = (await db.fetchone("SELECT COUNT(*) AS c FROM skin_listings WHERE status='Active'"))["c"]
    item_count = (await db.fetchone("SELECT COUNT(*) AS c FROM item_listings WHERE status='Active'"))["c"]
    auc_count  = (await db.fetchone("SELECT COUNT(*) AS c FROM auctions WHERE status='Active'"))["c"]
    tx_count   = (await db.fetchone("SELECT COUNT(*) AS c FROM transactions"))["c"]
    tx_vol     = (await db.fetchone("SELECT SUM(amount) AS v FROM transactions"))["v"] or 0
    total_users = (await db.fetchone("SELECT COUNT(*) AS c FROM wallets"))["c"]
    top_vehicle = await db.fetchone("SELECT vehicle_name, price FROM vehicle_listings WHERE status='Active' ORDER BY price DESC LIMIT 1")
    e = listing_embed("📊 KAT Market — Live Statistics", discord.Color.blue())
    e.add_field(name="🚗 Vehicle Listings", value=str(veh_count), inline=True)
    e.add_field(name="🏠 Property Listings", value=str(prop_count), inline=True)
    e.add_field(name="🏢 Business Listings", value=str(biz_count), inline=True)
    e.add_field(name="🎨 Skin Listings", value=str(skin_count), inline=True)
    e.add_field(name="📦 Item Listings", value=str(item_count), inline=True)
    e.add_field(name="🔨 Active Auctions", value=str(auc_count), inline=True)
    e.add_field(name="💸 Total Transactions", value=str(tx_count), inline=True)
    e.add_field(name="💰 Total Volume", value=fmt_cash(int(tx_vol)), inline=True)
    e.add_field(name="👥 Total Users", value=str(total_users), inline=True)
    if top_vehicle:
        e.add_field(name="🏆 Most Expensive Vehicle", value=f"{top_vehicle['vehicle_name']} — {fmt_cash(top_vehicle['price'])}", inline=False)
    await interaction.followup.send(embed=e)

@tree.command(name="price_check", description="🔍 AI-powered price check for any asset")
@app_commands.describe(asset="Asset name to check price for", asset_type="Type: vehicle / property / business / skin / item")
async def price_check(interaction: discord.Interaction, asset: str, asset_type: str = "vehicle"):
    await interaction.response.defer()
    table_map = {"vehicle": "vehicle_listings", "property": "property_listings", "business": "business_listings", "skin": "skin_listings", "item": "item_listings"}
    name_col = {"vehicle": "vehicle_name", "property": "property_name", "business": "business_name", "skin": "skin_name", "item": "item_name"}
    t = asset_type.lower()
    if t not in table_map:
        return await interaction.followup.send("❌ Valid types: vehicle, property, business, skin, item")
    rows = await db.fetchall(f"SELECT price FROM {table_map[t]} WHERE {name_col[t]} LIKE ? AND status='Active' LIMIT 20", (f"%{asset}%",))
    if not rows:
        return await interaction.followup.send(f"🔍 No listings found for **{asset}**. Insufficient data for price analysis.")
    prices = [r["price"] for r in rows]
    avg = int(sum(prices) / len(prices))
    min_p = min(prices)
    max_p = max(prices)
    suggested_low = int(avg * 0.90)
    suggested_high = int(avg * 1.10)
    e = listing_embed(f"🔍 Price Analysis — {asset}", discord.Color.teal())
    e.add_field(name="📊 Listings Analyzed", value=str(len(prices)), inline=True)
    e.add_field(name="💵 Average Price", value=fmt_cash(avg), inline=True)
    e.add_field(name="⬇️ Lowest Listed", value=fmt_cash(min_p), inline=True)
    e.add_field(name="⬆️ Highest Listed", value=fmt_cash(max_p), inline=True)
    e.add_field(name="✅ Suggested Range", value=f"{fmt_cash(suggested_low)} — {fmt_cash(suggested_high)}", inline=False)
    e.description = f"**Analysis for:** {asset} ({asset_type})\n**Recommendation:** List between {fmt_cash(suggested_low)} and {fmt_cash(suggested_high)} for fast sale."
    await interaction.followup.send(embed=e)

@tree.command(name="dashboard", description="📈 Your personal market dashboard")
async def dashboard(interaction: discord.Interaction):
    await interaction.response.defer()
    uid = interaction.user.id
    w = await db.get_wallet(uid)
    p = await db.get_profile(uid)
    veh = (await db.fetchone("SELECT COUNT(*) AS c FROM vehicle_listings WHERE seller_id=? AND status='Active'", (uid,)))["c"]
    prop = (await db.fetchone("SELECT COUNT(*) AS c FROM property_listings WHERE seller_id=? AND status='Active'", (uid,)))["c"]
    biz  = (await db.fetchone("SELECT COUNT(*) AS c FROM business_listings WHERE seller_id=? AND status='Active'", (uid,)))["c"]
    skin = (await db.fetchone("SELECT COUNT(*) AS c FROM skin_listings WHERE seller_id=? AND status='Active'", (uid,)))["c"]
    items = (await db.fetchone("SELECT COUNT(*) AS c FROM item_listings WHERE seller_id=? AND status='Active'", (uid,)))["c"]
    streak = await db.fetchone("SELECT streak FROM daily_streaks WHERE user_id=?", (uid,))
    e = listing_embed(f"📈 {interaction.user.display_name}'s Dashboard", discord.Color.blue())
    e.set_thumbnail(url=interaction.user.display_avatar.url)
    e.add_field(name="💵 Cash", value=fmt_cash(w["cash"]), inline=True)
    e.add_field(name="🪙 Coins", value=fmt_coins(w["coins"]), inline=True)
    e.add_field(name="🏦 Bank", value=fmt_cash(w["bank"]), inline=True)
    e.add_field(name="🔥 Daily Streak", value=f"{streak['streak']} days" if streak else "0 days", inline=True)
    e.add_field(name="👑 VIP", value=p["vip_tier"].capitalize() if p["vip_tier"] != "none" else "None", inline=True)
    e.add_field(name="⭐ Trust Score", value=str(p["vouches_positive"] - p["vouches_negative"]), inline=True)
    e.add_field(name="Active Listings", value=f"🚗 {veh} | 🏠 {prop} | 🏢 {biz} | 🎨 {skin} | 📦 {items}", inline=False)
    await interaction.followup.send(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 18 — ADVERTISEMENTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="post_ad", description="📢 Post an advertisement")
@app_commands.describe(title="Ad title", ad_type="Ad type: business / recruitment / rental", description="Ad details", contact="Contact info")
async def post_ad(interaction: discord.Interaction, title: str, ad_type: str, description: str, contact: str):
    aid = db.new_id("AD")
    exp = expires_delta(7)
    await db.execute("INSERT INTO advertisements(id,user_id,ad_type,title,description,contact,expires_at) VALUES(?,?,?,?,?,?,?)",
                     (aid, interaction.user.id, ad_type, title, description, contact, exp))
    e = listing_embed(f"📢 Advertisement Posted — {aid}", discord.Color.orange())
    e.add_field(name="Title", value=title, inline=True)
    e.add_field(name="Type", value=ad_type, inline=True)
    e.add_field(name="Contact", value=contact, inline=True)
    e.add_field(name="Description", value=description, inline=False)
    e.add_field(name="Expires", value=exp[:10], inline=True)
    await interaction.response.send_message(embed=e)

@tree.command(name="browse_ads", description="📢 Browse active advertisements")
@app_commands.describe(ad_type="Filter by type: business / recruitment / rental")
async def browse_ads(interaction: discord.Interaction, ad_type: str = ""):
    q = "SELECT * FROM advertisements WHERE status='Active'"
    params = []
    if ad_type:
        q += " AND ad_type LIKE ?"
        params.append(f"%{ad_type}%")
    q += " ORDER BY premium DESC, created_at DESC LIMIT 10"
    rows = await db.fetchall(q, tuple(params))
    if not rows:
        return await interaction.response.send_message("📭 No active advertisements.")
    e = listing_embed("📢 Active Advertisements", discord.Color.orange())
    for r in rows:
        premium_tag = "⭐ " if r["premium"] else ""
        e.add_field(name=f"{premium_tag}{r['title']} [{r['ad_type']}] — {r['id']}", value=f"**Contact:** {r['contact']} | **By:** <@{r['user_id']}>", inline=False)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 19 — ADMIN PANEL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        raise app_commands.MissingPermissions(["administrator"])
    return app_commands.check(predicate)

@tree.command(name="admin_panel", description="🔧 [ADMIN] Open the admin control panel")
@is_admin()
async def admin_panel(interaction: discord.Interaction):
    pending_coins = (await db.fetchone("SELECT COUNT(*) AS c FROM coin_purchases WHERE status='Pending'"))["c"]
    open_disputes = (await db.fetchone("SELECT COUNT(*) AS c FROM disputes WHERE status='Open'"))["c"]
    pending_donations = (await db.fetchone("SELECT COUNT(*) AS c FROM donations WHERE status='Pending'"))["c"]
    total_users = (await db.fetchone("SELECT COUNT(*) AS c FROM wallets"))["c"]
    total_cash = (await db.fetchone("SELECT SUM(cash)+SUM(bank) AS v FROM wallets"))["v"] or 0
    active_listings = sum([
        (await db.fetchone("SELECT COUNT(*) AS c FROM vehicle_listings WHERE status='Active'"))["c"],
        (await db.fetchone("SELECT COUNT(*) AS c FROM property_listings WHERE status='Active'"))["c"],
        (await db.fetchone("SELECT COUNT(*) AS c FROM business_listings WHERE status='Active'"))["c"],
        (await db.fetchone("SELECT COUNT(*) AS c FROM skin_listings WHERE status='Active'"))["c"],
        (await db.fetchone("SELECT COUNT(*) AS c FROM item_listings WHERE status='Active'"))["c"],
    ])
    e = listing_embed("🔧 KAT Market — Admin Control Panel", discord.Color.dark_red())
    e.add_field(name="⚠️ Pending Coin Requests", value=str(pending_coins), inline=True)
    e.add_field(name="🔴 Open Disputes", value=str(open_disputes), inline=True)
    e.add_field(name="💝 Pending Donations", value=str(pending_donations), inline=True)
    e.add_field(name="👥 Total Users", value=str(total_users), inline=True)
    e.add_field(name="💰 Total Economy", value=fmt_cash(int(total_cash)), inline=True)
    e.add_field(name="📋 Active Listings", value=str(active_listings), inline=True)
    e.description = (
        f"**Admin Commands:**\n"
        f"• `/approve_coins` — Approve a coin purchase\n"
        f"• `/reject_coins` — Reject a coin purchase\n"
        f"• `/pending_coins` — View pending coin requests\n"
        f"• `/add_cash` — Add cash to a user\n"
        f"• `/remove_cash` — Remove cash from a user\n"
        f"• `/add_coins` — Credit coins to a user\n"
        f"• `/review_dispute` — Review a dispute case\n"
        f"• `/resolve_dispute` — Resolve a dispute\n"
        f"• `/create_code` — Create a redeem code\n"
        f"• `/maintenance_mode` — Toggle maintenance\n"
        f"• `/ban_trader` — Restrict a trader\n"
        f"• `/force_delete_listing` — Delete any listing\n"
        f"• `/give_vip` — Grant VIP to a user\n"
        f"• `/set_title` — Set a user's title\n"
        f"• `/broadcast` — Send a server-wide message\n"
    )
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="pending_coins", description="💰 [ADMIN] View pending coin purchase requests")
@is_admin()
async def pending_coins(interaction: discord.Interaction):
    rows = await db.fetchall("SELECT * FROM coin_purchases WHERE status='Pending' ORDER BY ts ASC LIMIT 20")
    if not rows:
        return await interaction.response.send_message("✅ No pending coin requests.", ephemeral=True)
    e = listing_embed("⏳ Pending Coin Purchase Requests", discord.Color.yellow())
    for r in rows:
        pkg = next((p for p in COIN_PACKAGES if p["coins"] == r["coins"]), None)
        label = pkg["label"] if pkg else "Custom"
        e.add_field(
            name=f"Request #{r['id']} — {label}",
            value=f"**User:** <@{r['user_id']}> | **Coins:** {fmt_coins(r['coins'])} | **Paid:** ₹{r['price_inr']} | **UTR:** `{r['utr_number']}` | **Date:** {r['ts'][:10]}",
            inline=False
        )
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="approve_coins", description="✅ [ADMIN] Approve a coin purchase request")
@app_commands.describe(request_id="Coin purchase request ID number")
@is_admin()
async def approve_coins(interaction: discord.Interaction, request_id: int):
    row = await db.fetchone("SELECT * FROM coin_purchases WHERE id=?", (request_id,))
    if not row:
        return await interaction.response.send_message("❌ Request not found.", ephemeral=True)
    if row["status"] != "Pending":
        return await interaction.response.send_message("❌ Request already processed.", ephemeral=True)
    pkg = next((p for p in COIN_PACKAGES if p["coins"] == row["coins"]), None)
    total = row["coins"] + (pkg["bonus"] if pkg else 0)
    await db.add_coins(row["user_id"], total)
    await db.execute("UPDATE coin_purchases SET status='Approved',approved_by=?,approved_at=? WHERE id=?",
                     (interaction.user.id, datetime.datetime.utcnow().isoformat(), request_id))
    await db.execute(
        "INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
        (interaction.user.id, "approve_coins", str(row["user_id"]), f"Request #{request_id} — {total} coins")
    )
    try:
        user = await bot.fetch_user(row["user_id"])
        dm_e = discord.Embed(description=f"✅ Your coin purchase of **{fmt_coins(total)}** has been approved and credited to your account!", color=discord.Color.green())
        await user.send(embed=dm_e)
    except Exception:
        pass
    await interaction.response.send_message(f"✅ Approved Request #{request_id}. {fmt_coins(total)} credited to <@{row['user_id']}>.", ephemeral=True)

@tree.command(name="reject_coins", description="❌ [ADMIN] Reject a coin purchase request")
@app_commands.describe(request_id="Coin purchase request ID", reason="Reason for rejection")
@is_admin()
async def reject_coins(interaction: discord.Interaction, request_id: int, reason: str = "Payment not found or invalid UTR"):
    row = await db.fetchone("SELECT * FROM coin_purchases WHERE id=?", (request_id,))
    if not row:
        return await interaction.response.send_message("❌ Request not found.", ephemeral=True)
    if row["status"] != "Pending":
        return await interaction.response.send_message("❌ Already processed.", ephemeral=True)
    await db.execute("UPDATE coin_purchases SET status='Rejected',approved_by=?,approved_at=? WHERE id=?",
                     (interaction.user.id, datetime.datetime.utcnow().isoformat(), request_id))
    try:
        user = await bot.fetch_user(row["user_id"])
        dm_e = discord.Embed(description=f"❌ Your coin purchase request #{request_id} was rejected.\n**Reason:** {reason}\n\nPlease verify your payment and contact support if you believe this is an error.", color=discord.Color.red())
        await user.send(embed=dm_e)
    except Exception:
        pass
    await interaction.response.send_message(f"❌ Request #{request_id} rejected.", ephemeral=True)

@tree.command(name="add_cash", description="💵 [ADMIN] Add cash to a user's wallet")
@app_commands.describe(user="Target user", amount="Amount to add", reason="Reason")
@is_admin()
async def admin_add_cash(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "Admin grant"):
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    await db.add_cash(user.id, amount, f"[Admin] {reason}", from_id=interaction.user.id)
    await db.execute("INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
                     (interaction.user.id, "add_cash", str(user.id), f"{fmt_cash(amount)} — {reason}"))
    await interaction.response.send_message(f"✅ Added {fmt_cash(amount)} to {user.mention}. Reason: {reason}", ephemeral=True)

@tree.command(name="remove_cash", description="💵 [ADMIN] Remove cash from a user")
@app_commands.describe(user="Target user", amount="Amount to remove", reason="Reason")
@is_admin()
async def admin_remove_cash(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "Admin deduction"):
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    success = await db.remove_cash(user.id, amount, f"[Admin] {reason}")
    if not success:
        return await interaction.response.send_message("❌ User has insufficient funds.", ephemeral=True)
    await db.execute("INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
                     (interaction.user.id, "remove_cash", str(user.id), f"{fmt_cash(amount)} — {reason}"))
    await interaction.response.send_message(f"✅ Removed {fmt_cash(amount)} from {user.mention}.", ephemeral=True)

@tree.command(name="add_coins", description="🪙 [ADMIN] Add coins to a user")
@app_commands.describe(user="Target user", amount="Coins to add", reason="Reason")
@is_admin()
async def admin_add_coins(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str = "Admin grant"):
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
    await db.add_coins(user.id, amount)
    await db.execute("INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
                     (interaction.user.id, "add_coins", str(user.id), f"{fmt_coins(amount)} — {reason}"))
    await interaction.response.send_message(f"✅ Added {fmt_coins(amount)} to {user.mention}.", ephemeral=True)

@tree.command(name="review_dispute", description="📋 [ADMIN] Review an open dispute")
@app_commands.describe(case_id_="Dispute case ID")
@is_admin()
async def review_dispute(interaction: discord.Interaction, case_id_: str):
    row = await db.fetchone("SELECT * FROM disputes WHERE id=?", (case_id_,))
    if not row:
        return await interaction.response.send_message("❌ Case not found.", ephemeral=True)
    await db.execute("UPDATE disputes SET status='Under Review',assigned_to=? WHERE id=?", (interaction.user.id, case_id_))
    e = listing_embed(f"📋 Case Under Review — {case_id_}", discord.Color.yellow())
    e.add_field(name="Case ID", value=case_id_, inline=True)
    e.add_field(name="Type", value=row["case_type"], inline=True)
    e.add_field(name="Reporter", value=f"<@{row['reporter_id']}>", inline=True)
    e.add_field(name="Against", value=f"<@{row['reported_id']}>", inline=True)
    e.add_field(name="Reason", value=row["reason"], inline=False)
    e.add_field(name="Evidence", value=row["evidence"], inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="resolve_dispute", description="✅ [ADMIN] Resolve a dispute")
@app_commands.describe(case_id_="Case ID", resolution="Resolution details")
@is_admin()
async def resolve_dispute(interaction: discord.Interaction, case_id_: str, resolution: str):
    row = await db.fetchone("SELECT * FROM disputes WHERE id=?", (case_id_,))
    if not row:
        return await interaction.response.send_message("❌ Case not found.", ephemeral=True)
    now = datetime.datetime.utcnow().isoformat()
    await db.execute("UPDATE disputes SET status='Resolved',resolved_at=?,resolution=? WHERE id=?", (now, resolution, case_id_))
    await db.execute("INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
                     (interaction.user.id, "resolve_dispute", case_id_, resolution))
    try:
        reporter = await bot.fetch_user(row["reporter_id"])
        dm_e = discord.Embed(description=f"✅ Your case **{case_id_}** has been resolved.\n**Resolution:** {resolution}", color=discord.Color.green())
        await reporter.send(embed=dm_e)
    except Exception:
        pass
    await interaction.response.send_message(f"✅ Case **{case_id_}** resolved.", ephemeral=True)

@tree.command(name="give_vip", description="👑 [ADMIN] Grant VIP to a user")
@app_commands.describe(user="Target user", tier="VIP tier: bronze/silver/gold", days="Duration in days")
@is_admin()
async def give_vip(interaction: discord.Interaction, user: discord.Member, tier: str, days: int = 30):
    tier = tier.lower()
    if tier not in ("bronze", "silver", "gold"):
        return await interaction.response.send_message("❌ Valid tiers: bronze, silver, gold", ephemeral=True)
    await db.get_profile(user.id)
    exp = expires_delta(days)
    await db.execute("UPDATE profiles SET vip_tier=?,vip_expires=? WHERE user_id=?", (tier, exp, user.id))
    await interaction.response.send_message(f"✅ Granted **VIP {tier.capitalize()}** to {user.mention} for {days} days.", ephemeral=True)

@tree.command(name="set_title", description="🏷️ [ADMIN] Set a user's title")
@app_commands.describe(user="Target user", title="Title to assign")
@is_admin()
async def set_title(interaction: discord.Interaction, user: discord.Member, title: str):
    await db.get_profile(user.id)
    await db.execute("UPDATE profiles SET title=? WHERE user_id=?", (title, user.id))
    await interaction.response.send_message(f"✅ Set title **{title}** for {user.mention}.", ephemeral=True)

@tree.command(name="create_code", description="🎟️ [ADMIN] Create a redeem code")
@is_admin()
async def create_code(interaction: discord.Interaction):
    await interaction.response.send_modal(RedeemCodeCreateModal(db))

@tree.command(name="ban_trader", description="🚫 [ADMIN] Restrict a trader from listings")
@app_commands.describe(user="User to restrict", reason="Reason for restriction")
@is_admin()
async def ban_trader(interaction: discord.Interaction, user: discord.Member, reason: str):
    await db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES(?,?)", (f"banned_{user.id}", reason))
    await db.execute("INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
                     (interaction.user.id, "ban_trader", str(user.id), reason))
    await interaction.response.send_message(f"🚫 **{user.mention}** has been restricted from the marketplace.\n**Reason:** {reason}", ephemeral=True)

@tree.command(name="unban_trader", description="✅ [ADMIN] Remove a trader restriction")
@app_commands.describe(user="User to unrestrict")
@is_admin()
async def unban_trader(interaction: discord.Interaction, user: discord.Member):
    await db.execute("DELETE FROM bot_settings WHERE key=?", (f"banned_{user.id}",))
    await interaction.response.send_message(f"✅ {user.mention} has been unrestricted.", ephemeral=True)

@tree.command(name="force_delete_listing", description="🗑️ [ADMIN] Force delete any listing")
@app_commands.describe(listing_id="Listing ID to force delete")
@is_admin()
async def force_delete_listing(interaction: discord.Interaction, listing_id: str):
    lid = listing_id.upper()
    prefix_map = {"VEH": "vehicle_listings", "PROP": "property_listings", "BIZ": "business_listings", "SKN": "skin_listings", "ITM": "item_listings"}
    table = prefix_map.get(lid.split("-")[0])
    if not table:
        return await interaction.response.send_message("❌ Unknown listing prefix.", ephemeral=True)
    await db.execute(f"UPDATE {table} SET status='AdminDeleted' WHERE id=?", (lid,))
    await db.execute("INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
                     (interaction.user.id, "force_delete", lid, "Admin forced deletion"))
    await interaction.response.send_message(f"✅ Listing **{lid}** force deleted.", ephemeral=True)

@tree.command(name="maintenance_mode", description="🔧 [ADMIN] Toggle maintenance mode")
@is_admin()
async def maintenance_mode(interaction: discord.Interaction):
    current = await db.is_maintenance()
    new_val = "0" if current else "1"
    await db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES('maintenance',?)", (new_val,))
    status = "🔧 ENABLED" if new_val == "1" else "✅ DISABLED"
    await interaction.response.send_message(f"Maintenance mode is now **{status}**.", ephemeral=True)

@tree.command(name="broadcast", description="📢 [ADMIN] Send a broadcast message to all channels")
@app_commands.describe(message="The broadcast message", channel="Channel to broadcast in")
@is_admin()
async def broadcast(interaction: discord.Interaction, message: str, channel: discord.TextChannel = None):
    target = channel or interaction.channel
    e = discord.Embed(
        title="📢 KAT Market Announcement",
        description=message,
        color=discord.Color.gold()
    )
    e.set_footer(text=f"Announced by {interaction.user.display_name}")
    e.timestamp = datetime.datetime.utcnow()
    await target.send(embed=e)
    await interaction.response.send_message(f"✅ Broadcast sent to {target.mention}.", ephemeral=True)

@tree.command(name="staff_log", description="📋 [ADMIN] View staff action log")
@is_admin()
async def staff_log(interaction: discord.Interaction, staff: discord.Member = None):
    q = "SELECT * FROM staff_actions"
    params = []
    if staff:
        q += " WHERE staff_id=?"
        params.append(staff.id)
    q += " ORDER BY ts DESC LIMIT 15"
    rows = await db.fetchall(q, tuple(params))
    if not rows:
        return await interaction.response.send_message("📭 No staff actions recorded.", ephemeral=True)
    e = listing_embed("📋 Staff Action Log", discord.Color.dark_blue())
    for r in rows:
        e.add_field(
            name=f"{r['action'].upper()} — {r['ts'][:16]}",
            value=f"**Staff:** <@{r['staff_id']}> | **Target:** {r['target_id']} | **Notes:** {r['notes'] or 'N/A'}",
            inline=False
        )
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="approve_verification", description="✅ [ADMIN] Approve a user's trader verification")
@app_commands.describe(user="User to verify")
@is_admin()
async def approve_verification(interaction: discord.Interaction, user: discord.Member):
    await db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES(?,?)", (f"verified_{user.id}", "1"))
    await db.execute("INSERT INTO staff_actions(staff_id,action,target_id,notes) VALUES(?,?,?,?)",
                     (interaction.user.id, "verify_trader", str(user.id), "Verified as legitimate trader"))
    await interaction.response.send_message(f"✅ {user.mention} has been verified as a trusted trader.", ephemeral=True)

@tree.command(name="set_log_channel", description="📋 [ADMIN] Set the bot log channel")
@app_commands.describe(channel="Log channel")
@is_admin()
async def set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await db.set_config(interaction.guild_id, "log_channel", str(channel.id))
    await interaction.response.send_message(f"✅ Log channel set to {channel.mention}.", ephemeral=True)

@tree.command(name="emergency_lockdown", description="🚨 [ADMIN] Emergency lockdown — disables all commands")
@is_admin()
async def emergency_lockdown(interaction: discord.Interaction):
    await db.execute("INSERT OR REPLACE INTO bot_settings(key,value) VALUES('maintenance','1')")
    e = discord.Embed(
        title="🚨 EMERGENCY LOCKDOWN ACTIVATED",
        description="The KAT Market bot has been placed in emergency lockdown. All commands are temporarily disabled. Contact the server owner for status updates.",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=e)
    if interaction.channel:
        await interaction.channel.send(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 20 — OWNER-ONLY CONTROLS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        app = await bot.application_info()
        if interaction.user.id == app.owner.id:
            return True
        raise app_commands.CheckFailure("Owner-only command.")
    return app_commands.check(predicate)

@tree.command(name="sync", description="🔄 [OWNER] Sync slash commands globally")
@is_owner()
async def sync_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    synced = await tree.sync()
    await interaction.followup.send(f"✅ Synced {len(synced)} commands globally.", ephemeral=True)

@tree.command(name="system_health", description="📊 [OWNER] View bot system health")
@is_owner()
async def system_health(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guilds = len(bot.guilds)
    users = sum(g.member_count or 0 for g in bot.guilds)
    latency = round(bot.latency * 1000, 2)
    total_rows = {
        "wallets": (await db.fetchone("SELECT COUNT(*) AS c FROM wallets"))["c"],
        "listings": sum([
            (await db.fetchone("SELECT COUNT(*) AS c FROM vehicle_listings"))["c"],
            (await db.fetchone("SELECT COUNT(*) AS c FROM property_listings"))["c"],
            (await db.fetchone("SELECT COUNT(*) AS c FROM business_listings"))["c"],
            (await db.fetchone("SELECT COUNT(*) AS c FROM skin_listings"))["c"],
            (await db.fetchone("SELECT COUNT(*) AS c FROM item_listings"))["c"],
        ]),
        "transactions": (await db.fetchone("SELECT COUNT(*) AS c FROM transactions"))["c"],
        "disputes": (await db.fetchone("SELECT COUNT(*) AS c FROM disputes"))["c"],
    }
    e = listing_embed("📊 KAT Market System Health", discord.Color.dark_green())
    e.add_field(name="🏓 Latency", value=f"{latency}ms", inline=True)
    e.add_field(name="🌐 Servers", value=str(guilds), inline=True)
    e.add_field(name="👥 Total Members", value=str(users), inline=True)
    e.add_field(name="💼 Wallet Records", value=str(total_rows["wallets"]), inline=True)
    e.add_field(name="📋 Total Listings", value=str(total_rows["listings"]), inline=True)
    e.add_field(name="💸 Transactions", value=str(total_rows["transactions"]), inline=True)
    e.add_field(name="⚠️ Disputes", value=str(total_rows["disputes"]), inline=True)
    e.add_field(name="🔧 Maintenance", value="Yes" if await db.is_maintenance() else "No", inline=True)
    e.add_field(name="🤖 Bot Version", value=BOT_VERSION, inline=True)
    await interaction.followup.send(embed=e, ephemeral=True)

@tree.command(name="ghost_scan", description="👻 [OWNER] Scan for orphaned/broken asset entries")
@is_owner()
async def ghost_scan(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    expired_vehs = (await db.fetchone(
        "SELECT COUNT(*) AS c FROM vehicle_listings WHERE status='Active' AND expires_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    ))["c"]
    expired_props = (await db.fetchone(
        "SELECT COUNT(*) AS c FROM property_listings WHERE status='Active' AND expires_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    ))["c"]
    expired_bizs = (await db.fetchone(
        "SELECT COUNT(*) AS c FROM business_listings WHERE status='Active' AND expires_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    ))["c"]
    expired_aucs = (await db.fetchone(
        "SELECT COUNT(*) AS c FROM auctions WHERE status='Active' AND ends_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    ))["c"]
    await db.execute(
        "UPDATE vehicle_listings SET status='Expired' WHERE status='Active' AND expires_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    )
    await db.execute(
        "UPDATE property_listings SET status='Expired' WHERE status='Active' AND expires_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    )
    await db.execute(
        "UPDATE business_listings SET status='Expired' WHERE status='Active' AND expires_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    )
    await db.execute(
        "UPDATE auctions SET status='Ended' WHERE status='Active' AND ends_at < ?",
        (datetime.datetime.utcnow().isoformat(),)
    )
    e = listing_embed("👻 Ghost Scan Complete", discord.Color.dark_purple())
    e.add_field(name="Expired Vehicles Fixed", value=str(expired_vehs), inline=True)
    e.add_field(name="Expired Properties Fixed", value=str(expired_props), inline=True)
    e.add_field(name="Expired Businesses Fixed", value=str(expired_bizs), inline=True)
    e.add_field(name="Ended Auctions Fixed", value=str(expired_aucs), inline=True)
    await interaction.followup.send(embed=e, ephemeral=True)

@tree.command(name="system_audit", description="🧪 [OWNER] Two-pass scan: DB tables, commands, integrity check and auto-repair")
@is_owner()
async def system_audit(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    REQUIRED_TABLES = [
        "wallets", "transactions", "fixed_deposits", "coin_purchases",
        "profiles", "vouches",
        "vehicle_listings", "property_listings", "business_listings",
        "skin_listings", "item_listings",
        "auctions", "bids",
        "offers", "watchlist",
        "contracts", "bounties",
        "disputes",
        "daily_streaks", "weekly_claims",
        "inventory",
        "redeem_codes", "code_uses",
        "birthdays",
        "relationships", "families", "family_members",
        "donations",
        "guild_config",
        "advertisements",
        "archive",
        "staff_actions",
        "bot_settings",
    ]

    log_lines: list[str] = []
    issues = 0
    fixed  = 0
    now    = datetime.datetime.utcnow().isoformat()

    # ── PASS 1 — Database integrity ───────────────────────
    log_lines.append("🧪 **PASS 1 — DATABASE TABLE INTEGRITY SCAN**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    for table in REQUIRED_TABLES:
        try:
            row = await db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")
            log_lines.append(f"✅ `{table}` — {row['c']} rows")
        except Exception as exc:
            issues += 1
            log_lines.append(f"❌ `{table}` — MISSING or CORRUPT: {exc}")

    # ── PASS 1 — Slash command registration ───────────────
    log_lines.append("\n🤖 **SLASH COMMAND REGISTRATION CHECK**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    total_cmds = len(tree.get_commands())
    log_lines.append(f"📦 Registered command nodes in tree: **{total_cmds}**")
    if total_cmds == 0:
        issues += 1
        log_lines.append("⚠️ Tree is empty — triggering re-sync...")
        try:
            synced = await tree.sync()
            fixed += 1
            log_lines.append(f"🔧 Fixed: Re-synced {len(synced)} commands to Discord gateway.")
        except Exception as exc:
            log_lines.append(f"❌ Re-sync failed: {exc}")
    elif total_cmds > 100:
        issues += 1
        log_lines.append(f"⚠️ Command count {total_cmds} exceeds Discord's 100-command global limit!")
    else:
        log_lines.append(f"✅ Command count is within Discord's limit (≤ 100).")

    # ── PASS 1 — Maintenance / lockdown check ─────────────
    log_lines.append("\n🔧 **MAINTENANCE STATE CHECK**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    maint = await db.is_maintenance()
    if maint:
        issues += 1
        log_lines.append("⚠️ Bot is currently in **MAINTENANCE MODE** — users cannot run commands.")
    else:
        log_lines.append("✅ Maintenance mode is OFF — bot is fully operational.")

    # ── PASS 1 — Orphaned / ghost record detection ────────
    log_lines.append("\n👻 **ORPHANED RECORD DETECTION**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    ghost_tables = [
        ("vehicle_listings",  "expires_at"),
        ("property_listings", "expires_at"),
        ("business_listings", "expires_at"),
        ("skin_listings",     "expires_at"),
        ("item_listings",     "expires_at"),
    ]
    ghost_total = 0
    for gtable, gcol in ghost_tables:
        try:
            row = await db.fetchone(
                f"SELECT COUNT(*) AS c FROM {gtable} WHERE status='Active' AND {gcol} IS NOT NULL AND {gcol} < ?",
                (now,)
            )
            n = row["c"]
            ghost_total += n
            if n:
                log_lines.append(f"⚠️ `{gtable}`: {n} Active listing(s) past expiry")
            else:
                log_lines.append(f"✅ `{gtable}`: no ghost records")
        except Exception as exc:
            log_lines.append(f"❌ `{gtable}` scan error: {exc}")

    ended_aucs = 0
    try:
        row = await db.fetchone("SELECT COUNT(*) AS c FROM auctions WHERE status='Active' AND ends_at < ?", (now,))
        ended_aucs = row["c"]
        if ended_aucs:
            log_lines.append(f"⚠️ `auctions`: {ended_aucs} Active auction(s) past end time")
        else:
            log_lines.append("✅ `auctions`: no ghost records")
    except Exception as exc:
        log_lines.append(f"❌ `auctions` scan error: {exc}")

    # ── PASS 2 — Auto-repair ghost records ────────────────
    log_lines.append("\n🔧 **PASS 2 — AUTO-REPAIR GHOST RECORDS**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if ghost_total > 0 or ended_aucs > 0:
        try:
            for gtable, gcol in ghost_tables:
                await db.execute(
                    f"UPDATE {gtable} SET status='Expired' WHERE status='Active' AND {gcol} IS NOT NULL AND {gcol} < ?",
                    (now,)
                )
            await db.execute("UPDATE auctions SET status='Ended' WHERE status='Active' AND ends_at < ?", (now,))
            fixed += ghost_total + ended_aucs
            issues += ghost_total + ended_aucs
            log_lines.append(f"🔧 Fixed: Expired {ghost_total} listing(s) and ended {ended_aucs} auction(s).")
        except Exception as exc:
            log_lines.append(f"❌ Ghost repair failed: {exc}")
    else:
        log_lines.append("✅ No ghost repairs needed.")

    # ── PASS 2 — Pending queue check ──────────────────────
    log_lines.append("\n📋 **PENDING QUEUE STATUS**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    try:
        pc = (await db.fetchone("SELECT COUNT(*) AS c FROM coin_purchases WHERE status='Pending'"))["c"]
        od = (await db.fetchone("SELECT COUNT(*) AS c FROM disputes WHERE status='Open'"))["c"]
        pd_ = (await db.fetchone("SELECT COUNT(*) AS c FROM donations WHERE status='Pending'"))["c"]
        log_lines.append(f"🪙 Pending coin requests: **{pc}**")
        log_lines.append(f"⚠️ Open disputes: **{od}**")
        log_lines.append(f"💝 Pending donations: **{pd_}**")
        if pc > 0:
            issues += 1
            log_lines.append("  ↳ Action needed: run `/pending_coins` to process.")
        if od > 0:
            issues += 1
            log_lines.append("  ↳ Action needed: run `/review_dispute <case_id>` to process.")
    except Exception as exc:
        log_lines.append(f"❌ Queue check error: {exc}")

    # ── PASS 2 — Economy sanity check ─────────────────────
    log_lines.append("\n💰 **ECONOMY SANITY CHECK**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    try:
        neg_cash = (await db.fetchone("SELECT COUNT(*) AS c FROM wallets WHERE cash < 0"))["c"]
        neg_bank = (await db.fetchone("SELECT COUNT(*) AS c FROM wallets WHERE bank < 0"))["c"]
        neg_coins = (await db.fetchone("SELECT COUNT(*) AS c FROM wallets WHERE coins < 0"))["c"]
        if neg_cash or neg_bank or neg_coins:
            issues += neg_cash + neg_bank + neg_coins
            if neg_cash:
                log_lines.append(f"⚠️ {neg_cash} wallet(s) with negative cash — clamping to 0")
                await db.execute("UPDATE wallets SET cash=0 WHERE cash<0")
                fixed += neg_cash
            if neg_bank:
                log_lines.append(f"⚠️ {neg_bank} wallet(s) with negative bank — clamping to 0")
                await db.execute("UPDATE wallets SET bank=0 WHERE bank<0")
                fixed += neg_bank
            if neg_coins:
                log_lines.append(f"⚠️ {neg_coins} wallet(s) with negative coins — clamping to 0")
                await db.execute("UPDATE wallets SET coins=0 WHERE coins<0")
                fixed += neg_coins
        else:
            log_lines.append("✅ All wallets have non-negative balances.")
        total_cash = (await db.fetchone("SELECT SUM(cash)+SUM(bank) AS v FROM wallets"))["v"] or 0
        total_users = (await db.fetchone("SELECT COUNT(*) AS c FROM wallets"))["c"]
        log_lines.append(f"✅ Economy: {fmt_cash(int(total_cash))} across {total_users} wallets.")
    except Exception as exc:
        log_lines.append(f"❌ Economy check error: {exc}")

    # ── Final score ───────────────────────────────────────
    log_lines.append("\n📊 **AUDIT RESULT SUMMARY**")
    log_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log_lines.append(f"📌 Issues detected: **{issues}**")
    log_lines.append(f"🔧 Repairs applied: **{fixed}**")
    remaining = max(0, issues - fixed)
    health = max(0, 100 - remaining * 3)
    log_lines.append(f"⭐ System health score: **{health}%**")
    if health == 100:
        log_lines.append("🟢 **All systems operational. Pristine environment.**")
    elif health >= 70:
        log_lines.append("🟡 **Minor issues found and repaired. Re-run to confirm steady state.**")
    else:
        log_lines.append("🔴 **Critical issues remain. Manual admin intervention required.**")

    # Send in chunks to stay within Discord's 2000-char message limit
    full_text = "\n".join(log_lines)
    chunks = [full_text[i:i+1900] for i in range(0, len(full_text), 1900)]
    for idx, chunk in enumerate(chunks):
        header = f"📝 **KAT Market System Audit — Block {idx+1}/{len(chunks)}**\n" if len(chunks) > 1 else ""
        await interaction.followup.send(content=f"{header}{chunk}", ephemeral=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚡ SECTION 21 — GENERAL / HELP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tree.command(name="help", description="📖 View all KAT Market commands")
async def help_command(interaction: discord.Interaction):
    e = listing_embed("📖 KAT Market — Command Guide", discord.Color.blurple())
    e.description = f"**KAT Market v{BOT_VERSION}** — Your complete RPG marketplace system"
    e.add_field(name="🚗 Vehicle Market", value="`/sell_vehicle` `/vehicle_search` `/vehicle_info` `/my_vehicle_listings` `/delete_vehicle_listing` `/relist_vehicle`", inline=False)
    e.add_field(name="🏠 Property Market", value="`/sell_property` `/property_search` `/property_info` `/my_property_listings` `/delete_property_listing` `/relist_property`", inline=False)
    e.add_field(name="🏢 Business Market", value="`/sell_business` `/business_search` `/business_info` `/my_business_listings` `/delete_business_listing` `/relist_business`", inline=False)
    e.add_field(name="🎨 Skin Market", value="`/sell_skin` `/skin_search` `/skin_info` `/my_skin_listings` `/delete_skin_listing` `/relist_skin`", inline=False)
    e.add_field(name="📦 Item Market", value="`/sell_item` `/item_search` `/item_info` `/my_item_listings` `/delete_item_listing` `/relist_item`", inline=False)
    e.add_field(name="🔨 Auctions", value="`/create_auction` `/auction_info` `/my_bids` `/auction_history`", inline=False)
    e.add_field(name="💵 Economy", value="`/wallet` `/pay` `/deposit` `/withdraw` `/fixed_deposit` `/claim_fd` `/transaction_history` `/richlist`", inline=False)
    e.add_field(name="🪙 Coins & Shop", value=f"`/buy_coins` — UPI: `{UPI_ID}`\n`/sell_coins` `/coin_balance` `/coin_shop` `/buy_vip` `/open_crate`", inline=False)
    e.add_field(name="📜 Contracts", value="`/post_contract` `/contracts` `/take_contract` `/complete_contract` `/post_bounty` `/bounties`", inline=False)
    e.add_field(name="👤 Profile", value="`/profile` `/edit_profile` `/vouch` `/leaderboard` `/dashboard`", inline=False)
    e.add_field(name="🎒 Inventory & Codes", value="`/inventory` `/redeem` `/daily` `/weekly`", inline=False)
    e.add_field(name="❤️ Social", value="`/propose` `/divorce` `/relationship` `/create_family` `/family_info` `/set_birthday` `/birthday`", inline=False)
    e.add_field(name="⚠️ Disputes", value="`/open_dispute` `/report_user` `/scam_report` `/my_cases`", inline=False)
    e.add_field(name="📊 Analytics", value="`/market_stats` `/price_check` `/dashboard`", inline=False)
    e.add_field(name="📢 Ads", value="`/post_ad` `/browse_ads`", inline=False)
    e.add_field(name="🔧 Admin", value="`/admin_panel` for full admin command list", inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@tree.command(name="ping", description="🏓 Check bot latency")
async def ping(interaction: discord.Interaction):
    ms = round(bot.latency * 1000, 2)
    e = discord.Embed(description=f"🏓 Pong! Latency: **{ms}ms**", color=discord.Color.green())
    await interaction.response.send_message(embed=e)

@tree.command(name="info", description="ℹ️ About KAT Market bot")
async def info(interaction: discord.Interaction):
    e = listing_embed(f"ℹ️ {BOT_NAME}", discord.Color.blurple())
    e.description = (
        f"**KAT Market** is an advanced RPG marketplace Discord bot.\n"
        f"{divider()}\n"
        f"**Version:** {BOT_VERSION}\n"
        f"**Servers:** {len(bot.guilds)}\n"
        f"**UPI for Coins:** `{UPI_ID}`\n"
        f"{divider()}\n"
        f"Use `/help` for a full command list."
    )
    e.set_thumbnail(url=bot.user.display_avatar.url if bot.user else discord.Embed.Empty)
    await interaction.response.send_message(embed=e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCHEDULED TASKS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@tasks.loop(hours=1)
async def expire_listings_task():
    now = datetime.datetime.utcnow().isoformat()
    for table in ("vehicle_listings", "property_listings", "business_listings", "skin_listings", "item_listings"):
        await db.execute(f"UPDATE {table} SET status='Expired' WHERE status='Active' AND expires_at IS NOT NULL AND expires_at < ?", (now,))
    await db.execute("UPDATE auctions SET status='Ended' WHERE status='Active' AND ends_at < ?", (now,))
    log.info("Expired listings cleanup run.")

@tasks.loop(hours=24)
async def birthday_check_task():
    today = datetime.datetime.utcnow().strftime("%m-%d")
    year  = datetime.datetime.utcnow().year
    rows = await db.fetchall("SELECT * FROM birthdays WHERE birthday=? AND announced_year!=?", (today, year))
    for r in rows:
        await db.execute("UPDATE birthdays SET announced_year=? WHERE user_id=?", (year, r["user_id"]))
        await db.add_cash(r["user_id"], 2500, "Birthday bonus!")
        await db.add_coins(r["user_id"], 50)
        log.info(f"Birthday reward sent to user {r['user_id']}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BOT EVENTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.event
async def on_ready():
    await db.connect()
    log.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info(f"  KAT Market Bot — v{BOT_VERSION} ONLINE")
    log.info(f"  Logged in as: {bot.user} ({bot.user.id})")
    log.info(f"  Guilds: {len(bot.guilds)}")
    log.info(f"  UPI ID: {UPI_ID}")
    log.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="KAT Market | /help"),
        status=discord.Status.online
    )
    synced = await tree.sync()
    log.info(f"Synced {len(synced)} slash commands globally.")
    expire_listings_task.start()
    birthday_check_task.start()

@bot.event
async def on_guild_join(guild: discord.Guild):
    log.info(f"Joined guild: {guild.name} ({guild.id}) — {guild.member_count} members")

@bot.event
async def on_member_join(member: discord.Member):
    await db.get_wallet(member.id)
    await db.get_profile(member.id)
    log.info(f"New member initialized: {member} in {member.guild.name}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENTRY POINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if not TOKEN:
    log.critical("DISCORD_TOKEN environment variable not set. Exiting.")
    sys.exit(1)

bot.run(TOKEN, log_handler=None)
