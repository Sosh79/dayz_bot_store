import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
import logging
import asyncio
import traceback
import paypalrestsdk
import qrcode
import io
import ftplib
import paramiko
import tempfile
from datetime import datetime
import sys
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

# Load .env
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
SALES_CHANNEL_ID = int(os.getenv('SALES_CHANNEL_ID') or '0')
ADMIN_ID = int(os.getenv('ADMIN_ID') or '0')
CONTROL_PANEL_CHANNEL_ID = int(os.getenv('CONTROL_PANEL_CHANNEL_ID') or '0')
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID')
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET')
PAYPAL_MODE = os.getenv('PAYPAL_MODE', 'sandbox')
PAYPAL_CURRENCY = os.getenv('PAYPAL_CURRENCY', 'EUR').upper()
USE_LOCAL = os.getenv('USE_LOCAL', 'false').lower() == 'true'
LOCAL_BASE_PATH = os.getenv('LOCAL_BASE_PATH')
BANKING_PATH = os.getenv('BANKING_PATH')  # New: Specific path for banking
VEHICLE_SPAWN_PATH = os.getenv('VEHICLE_SPAWN_PATH')  # New: Vehicle spawn files path
FTP_HOST = os.getenv('FTP_HOST')
FTP_PORT = os.getenv('FTP_PORT', '21')
FTP_USER = os.getenv('FTP_USER')
FTP_PASS = os.getenv('FTP_PASS')
FTP_BASE_PATH = os.getenv('FTP_BASE_PATH')
GUILD_ID = int(os.getenv('GUILD_ID') or '0')
PELTCURRENCY_PATH = os.getenv('PELTCURRENCY_PATH')
CAC_ROLE_ID = int(os.getenv('CAC_ROLE_ID') or '0')
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
MONGODB_DB_NAME = os.getenv('MONGODB_DB_NAME', 'dayz_store')

# Minimum validations
if not BOT_TOKEN:
    print("Error: BOT_TOKEN not defined in .env"); sys.exit(1)
if not SALES_CHANNEL_ID:
    print("Error: SALES_CHANNEL_ID not defined in .env"); sys.exit(1)
if not ADMIN_ID:
    print("Error: ADMIN_ID not defined in .env"); sys.exit(1)
if not CONTROL_PANEL_CHANNEL_ID:
    print("Error: CONTROL_PANEL_CHANNEL_ID not defined in .env"); sys.exit(1)
if not PAYPAL_CLIENT_ID:
    print("Error: PAYPAL_CLIENT_ID not defined in .env"); sys.exit(1)
if not PAYPAL_CLIENT_SECRET:
    print("Error: PAYPAL_CLIENT_SECRET not defined in .env"); sys.exit(1)
if USE_LOCAL and not LOCAL_BASE_PATH:
    print("Error: LOCAL_BASE_PATH not defined in .env (required when USE_LOCAL=true)"); sys.exit(1)
if not USE_LOCAL and (not FTP_HOST or not FTP_BASE_PATH):
    print("Error: FTP_HOST and FTP_BASE_PATH are required when USE_LOCAL=false"); sys.exit(1)
if not BANKING_PATH:  # New: Validate BANKING_PATH
    print("Error: BANKING_PATH not defined in .env"); sys.exit(1)
if USE_LOCAL and not os.path.exists(BANKING_PATH):
    os.makedirs(BANKING_PATH, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# MongoDB Connection
try:
    mongo_client = AsyncIOMotorClient(MONGODB_URI)
    db = mongo_client[MONGODB_DB_NAME]
    # Collections
    items_collection = db['items_catalog']
    coupons_collection = db['coupons']
    passes_collection = db['battle_passes']
    user_data_collection = db['user_data']
    seguros_collection = db['seguros']
    compras_collection = db['compras']
    pending_payments_collection = db['pending_payments']
    sales_lists_collection = db['sales_lists']  # New: For lista_itens and lista_passes
    linked_players_collection = db['linked_players']  # New: For !p and !u commands
    purchases_collection = db['purchases']  # New: For complete purchase records
    logger.info("MongoDB connected successfully")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {str(e)}")
    sys.exit(1)

# Initialize PayPal
try:
    paypalrestsdk.configure({
        "mode": PAYPAL_MODE,
        "client_id": PAYPAL_CLIENT_ID,
        "client_secret": PAYPAL_CLIENT_SECRET
    })
    logger.info("PayPal SDK initialized successfully")
except Exception as e:
    logger.error(f"Error initializing PayPal SDK: {str(e)}")
    sys.exit(1)

# Files
ITEMS_FILE = "items_catalog.json"
COUPONS_FILE = "coupons.json"
PASSES_FILE = "battle_passes.json"
USER_DATA_FILE = "user_data.json"
ITEMS_LIST_TXT = "list_items.txt"
SEGUROS_FILE = "seguros.json"
SEGUROS_LOG = "seguros_acionados.txt"
COMPRAS_FILE = "compras.json"  # NEW: File to register purchases with insurance

# MongoDB Helper Functions
async def load_from_mongodb(collection_name):
    """Load all documents from a MongoDB collection"""
    try:
        collection = db[collection_name]
        documents = await collection.find().to_list(length=None)
        result = {}
        for doc in documents:
            doc_id = doc.pop('_id', None)
            key = doc.pop('key', str(doc_id))
            result[key] = doc
        return result
    except Exception as e:
        logger.error(f"Error loading from MongoDB collection {collection_name}: {str(e)}")
        return {}

async def save_to_mongodb(collection_name, key, data):
    """Save a single document to MongoDB"""
    try:
        collection = db[collection_name]
        data_to_save = {'key': key, **data}
        await collection.replace_one({'key': key}, data_to_save, upsert=True)
        logger.info(f"Saved to MongoDB {collection_name}: {key}")
        return True
    except Exception as e:
        logger.error(f"Error saving to MongoDB {collection_name}: {str(e)}")
        return False

async def save_all_to_mongodb(collection_name, data_dict):
    """Save all data to MongoDB collection"""
    try:
        collection = db[collection_name]
        # Clear collection first
        await collection.delete_many({})
        # Insert all items
        for key, value in data_dict.items():
            data_to_save = {'key': key, **value}
            await collection.insert_one(data_to_save)
        logger.info(f"Saved all data to MongoDB {collection_name}: {len(data_dict)} items")
        return True
    except Exception as e:
        logger.error(f"Error saving all to MongoDB {collection_name}: {str(e)}")
        return False

async def delete_from_mongodb(collection_name, key):
    """Delete a document from MongoDB"""
    try:
        collection = db[collection_name]
        result = await collection.delete_one({'key': key})
        logger.info(f"Deleted from MongoDB {collection_name}: {key}")
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting from MongoDB {collection_name}: {str(e)}")
        return False

# Legacy JSON functions for backward compatibility and migration
def load_json(filename, default=None):
    if default is None:
        default = {}
    if not os.path.exists(filename):
        save_json(filename, default)
        return default
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {filename}: {str(e)}")
        save_json(filename, default)
        return default

def save_json(filename, data):
    logger.info(f"Saving {filename} with data: {data}")
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving {filename}: {str(e)}")

async def save_list_to_txt(filename, catalog):
    """Save items catalog list to MongoDB only (no local file)"""
    try:
        content_lines = []
        if not catalog:
            content_lines.append("No items registered.\n")
        else:
            content_lines.append(f"--- List Updated on {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ---\n\n")
            for item_id, data in catalog.items():
                # Format price according to selected currency (simple symbol mapping)
                symbol = '€' if PAYPAL_CURRENCY == 'EUR' else (PAYPAL_CURRENCY + ' ')
                price_str = f"{symbol}{data.get('price', 0.0):.2f}"
                content_lines.append(f"- {data.get('name', 'Undefined Name')} ({item_id}): {price_str}\n")
            content_lines.append("\n--- End of List ---")
        
        # Save to MongoDB only
        list_content = ''.join(content_lines)
        await save_to_mongodb('sales_lists', 'items', {
            'filename': filename,
            'content': list_content,
            'updated_at': datetime.now().isoformat()
        })
        
        logger.info(f"Items list saved to MongoDB (no local file)")
    except Exception as e:
        logger.error(f"Error saving items list to MongoDB: {str(e)}")

async def load_list_from_mongodb(list_type):
    """Load sales list content from MongoDB"""
    try:
        data = await load_from_mongodb('sales_lists')
        if list_type in data:
            return data[list_type].get('content', '')
        return None
    except Exception as e:
        logger.error(f"Error loading list from MongoDB: {str(e)}")
        return None

# Initialize data dictionaries (will be loaded from MongoDB on bot startup)
items_catalog = {}
coupons = {}
passes_catalog = {}
user_data = {}
seguros = {}
compras = {}

# Function to load all data from MongoDB
async def load_all_data():
    """Load all data from MongoDB into memory"""
    global items_catalog, coupons, passes_catalog, user_data, seguros, compras
    try:
        items_catalog = await load_from_mongodb('items_catalog')
        coupons = await load_from_mongodb('coupons')
        passes_catalog = await load_from_mongodb('battle_passes')
        
        # Load user_data and extract steam_id values
        user_data_raw = await load_from_mongodb('user_data')
        user_data = {k: v.get('steam_id', v) if isinstance(v, dict) else v for k, v in user_data_raw.items()}
        
        # Load seguros and extract count values
        seguros_raw = await load_from_mongodb('seguros')
        seguros = {k: v.get('count', v) if isinstance(v, dict) else v for k, v in seguros_raw.items()}
        
        compras = await load_from_mongodb('compras')
        logger.info(f"Loaded from MongoDB: {len(items_catalog)} items, {len(coupons)} coupons, {len(passes_catalog)} passes")
        await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
    except Exception as e:
        logger.error(f"Error loading data from MongoDB: {str(e)}")
        # Fallback to JSON files if MongoDB fails
        items_catalog = load_json(ITEMS_FILE, {})
        coupons = load_json(COUPONS_FILE, {})
        passes_catalog = load_json(PASSES_FILE, {})
        user_data = load_json(USER_DATA_FILE, {})
        seguros = load_json(SEGUROS_FILE, {})
        compras = load_json(COMPRAS_FILE, {})
        await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)

# Automatic migration function: converts old items (with root 'script') to new format with 'variations'
async def migrate_items_to_variations():
    migrated = False
    for iid, data in list(items_catalog.items()):
        if 'variations' not in data:
            # if there is old 'script' key or 'itemsToGive' keys
            if data.get('script'):
                try:
                    script_obj = data.get('script')
                    if isinstance(script_obj, str):
                        script_obj = json.loads(script_obj)
                    items_catalog[iid]['variations'] = [{"name": "Default", "script": script_obj, "image_url": data.get('image_url', ''), "is_vehicle": data.get('is_vehicle', False), "insurance_drops": data.get('insurance_drops', 0)}]
                    # remove legacy 'script' to avoid confusion
                    if 'script' in items_catalog[iid]:
                        del items_catalog[iid]['script']
                    migrated = True
                except Exception as e:
                    logger.error(f"Error migrating item {iid}: {str(e)}")
    if migrated:
        await save_all_to_mongodb('items_catalog', items_catalog)
        logger.info("Migration to 'variations' executed and items_catalog saved to MongoDB.")
# Note: migrate_items_to_variations will be called after load_all_data in bot startup

# Bot
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Pending payment
pending_payments = {}  # payment_id -> {user_id, item_id, type, steam_target, insurance, amount, coupon}

def validate_steam_id(steam_id: str) -> bool:
    return isinstance(steam_id, str) and steam_id.isdigit() and len(steam_id) == 17

def generate_unique_id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now().timestamp())}"

# FTP / local manager
class FTPManager:
    @staticmethod
    def _get_sftp_connection():
        """Create SFTP connection using paramiko"""
        transport = paramiko.Transport((FTP_HOST, int(FTP_PORT)))
        transport.connect(username=FTP_USER, password=FTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        return sftp, transport

    @staticmethod
    def update_player_file(steam_id: str, item_name: str = None, item_list: list = None) -> bool:
        if not validate_steam_id(steam_id):
            logger.error(f"Attempt to update file with invalid SteamID: {steam_id}")
            return False
        filename = f"{steam_id}.json"
        if USE_LOCAL:
            local_base = LOCAL_BASE_PATH
            full_path = os.path.join(local_base, filename)
            try:
                os.makedirs(local_base, exist_ok=True)
                existing_data = {}
                if os.path.exists(full_path):
                    with open(full_path, 'r', encoding='utf-8') as f:
                        try:
                            existing_data = json.load(f)
                        except:
                            existing_data = {}
                else:
                    existing_data = {"itemToGive": "none", "itemsToGive": []}
                # Avoid duplication
                current_items = set(existing_data.get('itemsToGive', []))
                if item_list:
                    new_items = [item for item in item_list if item not in current_items]
                    existing_data['itemsToGive'].extend(new_items)
                    existing_data['itemToGive'] = "none"
                elif item_name and item_name != "none" and item_name not in current_items:
                    existing_data['itemsToGive'].append(item_name)
                    existing_data['itemToGive'] = "none"
                with open(full_path, 'w', encoding='utf-8') as f:
                    json.dump(existing_data, f, indent=4, ensure_ascii=False)
                logger.info(f"File {filename} updated at {full_path} for SteamID {steam_id}")
                return True
            except Exception as e:
                logger.error(f"Error saving local file {filename}: {str(e)}")
                return False
        else:
            # SFTP Mode
            sftp = None
            transport = None
            try:
                remote_path = FTP_BASE_PATH
                if not remote_path.startswith('/'):
                    remote_path = '/' + remote_path
                remote_file = f"{remote_path}/{filename}"
                
                sftp, transport = FTPManager._get_sftp_connection()
                existing_data = {}
                # Try to download existing file
                try:
                    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
                        tmp_path = tmp.name
                    sftp.get(remote_file, tmp_path)
                    with open(tmp_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    existing_data = {"itemToGive": "none", "itemsToGive": []}
                except Exception as e:
                    logger.warning(f"Could not read existing file {remote_file}: {str(e)}")
                    existing_data = {"itemToGive": "none", "itemsToGive": []}
                
                # Avoid duplication
                current_items = set(existing_data.get('itemsToGive', []))
                if item_list:
                    new_items = [item for item in item_list if item not in current_items]
                    existing_data['itemsToGive'].extend(new_items)
                    existing_data['itemToGive'] = "none"
                elif item_name and item_name != "none" and item_name not in current_items:
                    existing_data['itemsToGive'].append(item_name)
                    existing_data['itemToGive'] = "none"
                
                # Upload updated file
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
                    json.dump(existing_data, tmp, indent=4, ensure_ascii=False)
                    tmp_path = tmp.name
                
                sftp.put(tmp_path, remote_file)
                os.unlink(tmp_path)
                logger.info(f"File {filename} updated via SFTP at {remote_file} for SteamID {steam_id}")
                return True
            except Exception as e:
                logger.error(f"Error updating file via SFTP {filename}: {str(e)}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                return False
            finally:
                if sftp:
                    sftp.close()
                if transport:
                    transport.close()

    @staticmethod
    def update_banking_file(steam_id: str, amount: int = 100000) -> bool:
        if not validate_steam_id(steam_id):
            logger.error(f"Attempt to update banking with invalid SteamID: {steam_id}")
            return False
        
        filename = f"{steam_id}.json"
        
        if USE_LOCAL:
            full_path = os.path.join(BANKING_PATH, filename)
            try:
                os.makedirs(BANKING_PATH, exist_ok=True)
                data = {}
                # Load existing file without overwriting
                if os.path.exists(full_path):
                    with open(full_path, 'r', encoding='utf-8') as f:
                        try:
                            data = json.load(f)
                        except:
                            data = {}
                # Only update m_OwnedCurrency, keeping other fields
                data['m_OwnedCurrency'] = amount
                with open(full_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                logger.info(f"Balance updated to {amount} in {full_path} for SteamID {steam_id}")
                return True
            except Exception as e:
                logger.error(f"Error updating banking {filename}: {str(e)}")
                return False
        else:
            # SFTP mode for banking
            sftp = None
            transport = None
            try:
                remote_path = BANKING_PATH
                if not remote_path.startswith('/'):
                    remote_path = '/' + remote_path
                remote_file = f"{remote_path}/{filename}"
                
                sftp, transport = FTPManager._get_sftp_connection()
                data = {}
                # Try to download existing file
                try:
                    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json') as tmp:
                        tmp_path = tmp.name
                    sftp.get(remote_file, tmp_path)
                    with open(tmp_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    os.unlink(tmp_path)
                except FileNotFoundError:
                    pass  # File doesn't exist, will create new
                except Exception as e:
                    logger.warning(f"Could not read existing banking file {remote_file}: {str(e)}")
                
                # Only update m_OwnedCurrency, keeping other fields
                data['m_OwnedCurrency'] = amount
                
                # Upload updated file
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
                    json.dump(data, tmp, indent=4, ensure_ascii=False)
                    tmp_path = tmp.name
                
                sftp.put(tmp_path, remote_file)
                os.unlink(tmp_path)
                logger.info(f"Banking file {filename} updated via SFTP at {remote_file} with balance {amount} for SteamID {steam_id}")
                return True
            except Exception as e:
                logger.error(f"Error updating banking via SFTP {filename}: {str(e)}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                return False
            finally:
                if sftp:
                    sftp.close()
                if transport:
                    transport.close()

    @staticmethod
    def create_vehicle_file(steam_id: str, class_name: str, spawns: int, cooldown: int, guarantee: int, unique: bool, vehicle_path: str) -> bool:
        """Create vehicle spawn file for player"""
        if not validate_steam_id(steam_id):
            logger.error(f"Attempt to create vehicle file with invalid SteamID: {steam_id}")
            return False
        
        # Vehicle filename: use className as filename
        filename = f"{class_name}.json"
        
        vehicle_data = {
            "steamID": steam_id,
            "className": class_name,
            "amountOfAvailableSpawns": spawns,
            "timeBeforeNextSpawn": cooldown,
            "guaranteePeriod": guarantee,
            "isUnique": 1 if unique else 0
        }
        
        if USE_LOCAL:
            full_path = os.path.join(vehicle_path, filename)
            try:
                os.makedirs(vehicle_path, exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    json.dump(vehicle_data, f, indent=4, ensure_ascii=False)
                logger.info(f"Vehicle file {filename} created at {full_path} for SteamID {steam_id}")
                return True
            except Exception as e:
                logger.error(f"Error creating vehicle file {filename}: {str(e)}")
                return False
        else:
            # SFTP mode for vehicle
            sftp = None
            transport = None
            try:
                remote_path = vehicle_path
                if not remote_path.startswith('/'):
                    remote_path = '/' + remote_path
                remote_file = f"{remote_path}/{filename}"
                
                sftp, transport = FTPManager._get_sftp_connection()
                
                # Upload vehicle file directly
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json', encoding='utf-8') as tmp:
                    json.dump(vehicle_data, tmp, indent=4, ensure_ascii=False)
                    tmp_path = tmp.name
                
                sftp.put(tmp_path, remote_file)
                os.unlink(tmp_path)
                logger.info(f"Vehicle file {filename} created via SFTP at {remote_file} for SteamID {steam_id}")
                return True
            except Exception as e:
                logger.error(f"Error creating vehicle file via SFTP {filename}: {str(e)}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                return False
            finally:
                if sftp:
                    sftp.close()
                if transport:
                    transport.close()

# PayPal helpers
class PayPalPayment:
    @staticmethod
    async def create_payment(amount: float, description: str, user_id: int, item_id: str, item_type: str, steam_target: str, insurance: bool, coupon_code: str = None):
        if amount <= 0:
            return {"status": "free", "message": "Free item"}
        try:
            payment = paypalrestsdk.Payment({
                "intent": "sale",
                "payer": {
                    "payment_method": "paypal"
                },
                "transactions": [{
                    "amount": {
                        "total": f"{amount:.2f}",
                        "currency": PAYPAL_CURRENCY
                    },
                    "description": description[:200]
                }],
                "redirect_urls": {
                    "return_url": "http://return.url",
                    "cancel_url": "http://cancel.url"
                }
            })
            
            if payment.create():
                payment_id = payment.id
                approval_url = None
                for link in payment.links:
                    if link.rel == "approval_url":
                        approval_url = link.href
                        break
                
                pending_payments[payment_id] = {
                    "user_id": user_id,
                    "item_id": item_id,
                    "type": item_type,
                    "steam_target": steam_target,
                    "insurance": insurance,
                    "amount": amount,
                    "coupon": coupon_code
                }
                return {"status": "pending", "payment_id": payment_id, "approval_url": approval_url}
            else:
                logger.error(f"Error creating PayPal payment: {payment.error}")
                return {"status": "error", "message": str(payment.error)}
        except Exception as e:
            logger.error(f"Error creating payment: {str(e)}")
            return {"status": "error", "message": str(e)}

    @staticmethod
    async def check_payment_status(payment_id: str) -> str:
        try:
            payment = paypalrestsdk.Payment.find(payment_id)
            if payment.state == "approved":
                return "approved"
            elif payment.state == "created":
                return "pending"
            else:
                return payment.state
        except Exception as e:
            logger.error(f"Error checking payment status {payment_id}: {str(e)}")
            return "error"

# Modals and Views

class DeleteItemModal(Modal):
    def __init__(self, item_id: str, item_name: str):
        super().__init__(title=f"Delete Item: {item_name}")
        self.item_id = item_id
        self.confirm = TextInput(label="Type 'YES' to confirm deletion", required=True)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.strip().upper() != "YES":
            await interaction.response.send_message("Invalid confirmation. Type 'YES' to delete.", ephemeral=True)
            return
        if self.item_id in items_catalog:
            item_name = items_catalog[self.item_id].get('name', '')
            del items_catalog[self.item_id]
            await delete_from_mongodb('items_catalog', self.item_id)
            await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            sales_channel = bot.get_channel(SALES_CHANNEL_ID)
            if sales_channel:
                async for message in sales_channel.history(limit=200):
                    if message.author == bot.user and message.embeds and message.embeds[0].title == item_name:
                        await message.delete()
                        break
            await interaction.response.send_message(f"✅ Item **{item_name}** deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("Item not found.", ephemeral=True)

class DeleteCouponModal(Modal):
    def __init__(self, code: str):
        super().__init__(title=f"Delete Coupon: {code}")
        self.code = code
        self.confirm = TextInput(label="Type 'YES' to confirm deletion", required=True)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.strip().upper() != "YES":
            await interaction.response.send_message("Invalid confirmation. Type 'YES' to delete.", ephemeral=True)
            return
        if self.code in coupons:
            del coupons[self.code]
            await delete_from_mongodb('coupons', self.code)
            await interaction.response.send_message(f"✅ Coupon **{self.code}** deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("Coupon not found.", ephemeral=True)


class DeleteVehicleModal(Modal):
    def __init__(self, item_id: str, item_name: str):
        super().__init__(title=f"Delete Vehicle: {item_name}")
        self.item_id = item_id
        self.confirm = TextInput(label="Type 'YES' to confirm deletion", required=True)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.strip().upper() != "YES":
            await interaction.response.send_message("Invalid confirmation. Type 'YES' to delete.", ephemeral=True)
            return
        if self.item_id in items_catalog:
            del items_catalog[self.item_id]
            await delete_from_mongodb('items_catalog', self.item_id)
            await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            sales_channel = bot.get_channel(SALES_CHANNEL_ID)
            if sales_channel:
                async for message in sales_channel.history(limit=200):
                    if message.author == bot.user and message.embeds and message.embeds[0].title == items_catalog.get(self.item_id, {}).get('name', ''):
                        await message.delete()
                        break
            await interaction.response.send_message(f"✅ Vehicle **{items_catalog.get(self.item_id, {}).get('name', '')}** deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("Vehicle not found.", ephemeral=True)

class CreateItemModal(Modal):
    def __init__(self):
        super().__init__(title="Create New Item")
        self.name_desc = TextInput(
            label="Name | Description",
            placeholder="Ex: Backpack | High capacity backpack for survival",
            style=discord.TextStyle.short,
            required=True
        )
        currency_label = '€' if PAYPAL_CURRENCY == 'EUR' else PAYPAL_CURRENCY
        self.price = TextInput(label=f"Price ({currency_label})", placeholder="Ex: 10.00", required=True)
        self.image_url = TextInput(
            label="Image URL (optional)",
            placeholder="https://...",
            required=False
        )
        self.variations = TextInput(
            label="Variations (JSON)",
            placeholder='Ex: [{"name":"Black","script":{"itemsToGive":["Item"]}}]',
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.vehicle_info = TextInput(
            label="Is Vehicle? (optional)",
            placeholder="Ex: y (vehicle) or n (item)",
            required=False
        )
        self.add_item(self.name_desc)
        self.add_item(self.price)
        self.add_item(self.image_url)
        self.add_item(self.variations)
        self.add_item(self.vehicle_info)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Parse name and description
            name_desc_parts = self.name_desc.value.split('|')
            item_name = name_desc_parts[0].strip()
            item_description = name_desc_parts[1].strip() if len(name_desc_parts) > 1 else ""
            
            if not item_name:
                await interaction.response.send_message("Item name is required.", ephemeral=True)
                return
            
            price = float(self.price.value.replace(',', '.'))
            if price < 0:
                await interaction.response.send_message("Price cannot be negative.", ephemeral=True); return

            variations_text = self.variations.value.strip()
            if not variations_text:
                await interaction.response.send_message("The 'Variations (JSON)' field is required.", ephemeral=True); return
            variations = json.loads(variations_text)
            # Validate each variation has name and script
            for v in variations:
                if 'name' not in v or 'script' not in v:
                    await interaction.response.send_message("Each variation needs 'name' and 'script'.", ephemeral=True); return

            # Parse vehicle info
            is_vehicle = False
            if self.vehicle_info.value:
                vi = self.vehicle_info.value.strip().lower()
                is_vehicle = vi in ('s','y','sim','yes','1','true')

            item_id = generate_unique_id("item")
            item_obj = {
                "name": item_name,
                "description": item_description,
                "price": price,
                "image_url": self.image_url.value if self.image_url.value else "",
                "is_vehicle": is_vehicle,
                "insurance_drops": 0,
                "variations": variations
            }
            items_catalog[item_id] = item_obj
            await save_to_mongodb('items_catalog', item_id, item_obj)
            await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            await interaction.response.send_message(f"✅ Item **{item_name}** created with ID `{item_id}`.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error creating item: {str(e)}", ephemeral=True)

class EditItemModal(Modal):
    def __init__(self, item_id: str, item_data: dict):
        super().__init__(title=f"Edit Item: {item_data.get('name', 'Item')}")
        self.item_id = item_id
        self.name = TextInput(
            label="Item Name",
            default=item_data.get('name', ''),
            placeholder="Ex: Backpack",
            required=True
        )
        self.price = TextInput(
            label=f"Preço ({'€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY})",
            default=str(item_data.get('price', 0.0)).replace('.', ','),
            placeholder="Ex: 10,00",
            required=True
        )
        self.image_url = TextInput(
            label="Image URL (optional)",
            default=item_data.get('image_url', ''),
            placeholder="https://...",
            required=False
        )
        default_variations = json.dumps(item_data.get('variations', []), ensure_ascii=False)
        self.variations = TextInput(
            label="Variations (JSON)",
            placeholder='Ex: [{"name":"Black","script":{"itemsToGive":["Item"], "banking": true}}]',
            default=default_variations,
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.vehicle_info = TextInput(
            label="Vehicle and Insurance (ex: y,3)",
            placeholder="Ex: y,3 (vehicle with 3 insurance) or n,0 (no vehicle)",
            default=f"{'y' if item_data.get('is_vehicle', False) else 'n'},{item_data.get('insurance_drops', 0)}",
            required=False
        )
        self.add_item(self.name)
        self.add_item(self.price)
        self.add_item(self.image_url)
        self.add_item(self.variations)
        self.add_item(self.vehicle_info)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.price.value.replace(',', '.'))
            if price < 0:
                await interaction.response.send_message("Price cannot be negative.", ephemeral=True)
                return

            variations = json.loads(self.variations.value)
            for v in variations:
                if 'name' not in v or 'script' not in v:
                    await interaction.response.send_message("Each variation needs 'name' and 'script'.", ephemeral=True); return

            vi = self.vehicle_info.value.strip().lower()
            is_vehicle = False
            drops = 0
            if vi:
                parts = [p.strip() for p in vi.split(',') if p.strip() != '']
                if parts:
                    is_vehicle = parts[0] in ('s', 'y', 'sim', 'yes', '1', 'true')
                    if len(parts) > 1:
                        try:
                            drops = int(parts[1])
                        except:
                            drops = 0

            items_catalog[self.item_id] = {
                "name": self.name.value,
                "price": price,
                "image_url": self.image_url.value,
                "variations": variations,
                "is_vehicle": is_vehicle,
                "insurance_drops": drops
            }
            await save_to_mongodb('items_catalog', self.item_id, items_catalog[self.item_id])
            await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)

            sales_channel = bot.get_channel(SALES_CHANNEL_ID)
            if sales_channel:
                async for message in sales_channel.history(limit=200):
                    if message.author == bot.user and message.embeds and message.embeds[0].title == self.name.value:
                        embed = discord.Embed(
                            title=self.name.value,
                            description=items_catalog[self.item_id].get('description', ''),
                            color=discord.Color.green()
                        )
                        curr_symbol = '€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY
                        embed.add_field(name="Preço", value=f"{curr_symbol} {price:.2f}", inline=True)
                        if self.image_url.value:
                            embed.set_image(url=self.image_url.value)
                        view = ItemViewForChannel(self.item_id, items_catalog[self.item_id])
                        await message.edit(embed=embed, view=view)
                        break
            await interaction.response.send_message(f"✅ Item **{self.name.value}** updated successfully.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error editing item: {str(e)}", ephemeral=True)

class CreateCouponModal(Modal):
    def __init__(self):
        super().__init__(title="Create Coupon")
        self.code = TextInput(label="Code (ex: DISCOUNT10)", required=True)
        self.discount = TextInput(label="Discount (%)", placeholder="10", required=True)
        self.uses = TextInput(label="Uses (-1 for unlimited)", placeholder="5", required=True)
        self.add_item(self.code)
        self.add_item(self.discount)
        self.add_item(self.uses)

    async def on_submit(self, interaction: discord.Interaction):
        code = self.code.value.strip().upper()
        try:
            discount = float(self.discount.value.replace(',', '.'))
            uses = int(self.uses.value)
            if code in coupons:
                await interaction.response.send_message("Code already exists.", ephemeral=True); return
            if discount < 0 or discount > 100:
                await interaction.response.send_message("Invalid discount.", ephemeral=True); return
            coupons[code] = {"discount": discount, "uses": uses}
            await save_to_mongodb('coupons', code, coupons[code])
            await interaction.response.send_message(f"✅ Coupon {code} created.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class EditCouponModal(Modal):
    def __init__(self, code: str, data: dict):
        super().__init__(title=f"Edit Coupon: {code}")
        self.code = code
        self.discount = TextInput(label="Discount (%)", default=str(data.get('discount',0)).replace('.',','), required=True)
        self.uses = TextInput(label="Uses (-1 for unlimited)", default=str(data.get('uses',0)), required=True)
        self.add_item(self.discount)
        self.add_item(self.uses)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            discount = float(self.discount.value.replace(',', '.'))
            uses = int(self.uses.value)
            if discount < 0 or discount > 100:
                await interaction.response.send_message("Invalid discount.", ephemeral=True); return
            coupons[self.code] = {"discount": discount, "uses": uses}
            await save_to_mongodb('coupons', self.code, coupons[self.code])
            await interaction.response.send_message(f"✅ Coupon {self.code} updated.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class CouponSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None
        # Build options dynamically
        options = []
        if coupons:
            for code, data in coupons.items():
                uses_text = 'unlimited' if data.get('uses', 0) == -1 else str(data.get('uses', 0))
                label = f"{code} — {data.get('discount', 0)}% ({uses_text} uses)"
                options.append(discord.SelectOption(label=label[:100], value=code))
        else:
            options = [discord.SelectOption(label="No coupons available", value="none")]
        
        if len(options) > 25:
            options = options[:25]
        
        self.select_menu = discord.ui.Select(
            placeholder="Choose a coupon to edit...",
            options=options
        )
        self.select_menu.callback = self.select_coupon
        self.add_item(self.select_menu)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Coupon selection expired.", view=None)
            except:
                pass

    async def select_coupon(self, interaction: discord.Interaction):
        if self.select_menu.values[0] == "none":
            await interaction.response.send_message("No coupons available.", ephemeral=True)
            return
        code = self.select_menu.values[0]
        data = coupons.get(code, {})
        await interaction.response.send_modal(EditCouponModal(code, data))



class CreateVehicleModal(Modal):
    def __init__(self):
        super().__init__(title="Create Vehicle")
        self.name = TextInput(label="Vehicle Name", placeholder="Ex: RAM 1500 TRX Black", required=True)
        currency_label = '€' if PAYPAL_CURRENCY == 'EUR' else PAYPAL_CURRENCY
        self.price = TextInput(label=f"Price ({currency_label})", placeholder="Ex: 50.00", required=True)
        self.description = TextInput(
            label="Description (optional)",
            placeholder="Ex: Powerful off-road vehicle",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1024
        )
        self.class_name = TextInput(label="Vehicle Class Name", placeholder="Ex: CrSk_RAM_1500_TRX_Black", required=True)
        self.vehicle_config = TextInput(
            label="Vehicle Config (spawns,cooldown,guarantee)",
            placeholder="Ex: 7,600,604800 (7 spawns, 10min cooldown, 7 days guarantee)",
            required=True,
            default="7,600,604800"
        )
        self.add_item(self.name)
        self.add_item(self.price)
        self.add_item(self.description)
        self.add_item(self.class_name)
        self.add_item(self.vehicle_config)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.price.value.replace(',', '.'))
            if price < 0:
                await interaction.response.send_message("Price cannot be negative.", ephemeral=True)
                return
            
            class_name = self.class_name.value.strip()
            if not class_name:
                await interaction.response.send_message("Vehicle class name is required.", ephemeral=True)
                return
            
            # Parse vehicle config: spawns,cooldown,guarantee
            config_parts = [p.strip() for p in self.vehicle_config.value.split(',')]
            if len(config_parts) != 3:
                await interaction.response.send_message("Invalid vehicle config format. Use: spawns,cooldown,guarantee", ephemeral=True)
                return
            
            try:
                spawns = int(config_parts[0])
                cooldown = int(config_parts[1])
                guarantee = int(config_parts[2])
            except ValueError:
                await interaction.response.send_message("Vehicle config must be numbers.", ephemeral=True)
                return
            
            # Create as special vehicle item
            item_id = generate_unique_id("vehicle")
            item_obj = {
                "name": self.name.value,
                "description": self.description.value if self.description.value else "",
                "price": price,
                "image_url": "",
                "is_vehicle": True,
                "vehicle_type": "spawn_vehicle",  # Special marker for vehicle spawn system
                "insurance_drops": 0,
                "variations": [
                    {
                        "name": "Default",
                        "script": {
                            "vehicleClassName": class_name,
                            "amountOfAvailableSpawns": spawns,
                            "timeBeforeNextSpawn": cooldown,
                            "guaranteePeriod": guarantee,
                            "isUnique": True
                        },
                        "image_url": "",
                        "is_vehicle": True,
                        "insurance_drops": 0
                    }
                ]
            }
            items_catalog[item_id] = item_obj
            await save_to_mongodb('items_catalog', item_id, item_obj)
            await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            await interaction.response.send_message(f"✅ Vehicle **{self.name.value}** created with ID `{item_id}`.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error creating vehicle: {str(e)}", ephemeral=True)

class EditVehicleModal(Modal):
    def __init__(self, vehicle_id: str, vehicle_data: dict):
        super().__init__(title=f"Edit Vehicle: {vehicle_data.get('name', 'Vehicle')}")
        self.vehicle_id = vehicle_id
        
        # Get current vehicle data
        current_variation = vehicle_data.get('variations', [{}])[0]
        current_script = current_variation.get('script', {})
        
        self.name = TextInput(
            label="Vehicle Name",
            default=vehicle_data.get('name', ''),
            placeholder="Ex: RAM 1500 TRX Black",
            required=True
        )
        currency_label = '€' if PAYPAL_CURRENCY == 'EUR' else PAYPAL_CURRENCY
        self.price = TextInput(
            label=f"Price ({currency_label})",
            default=str(vehicle_data.get('price', 0.0)),
            placeholder="Ex: 50.00",
            required=True
        )
        self.description = TextInput(
            label="Description (optional)",
            default=vehicle_data.get('description', ''),
            placeholder="Ex: Powerful off-road vehicle",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1024
        )
        self.class_name = TextInput(
            label="Vehicle Class Name",
            default=current_script.get('vehicleClassName', ''),
            placeholder="Ex: CrSk_RAM_1500_TRX_Black",
            required=True
        )
        
        # Format current config
        current_config = f"{current_script.get('amountOfAvailableSpawns', 7)},{current_script.get('timeBeforeNextSpawn', 600)},{current_script.get('guaranteePeriod', 604800)}"
        self.vehicle_config = TextInput(
            label="Vehicle Config (spawns,cooldown,guarantee)",
            default=current_config,
            placeholder="Ex: 7,600,604800",
            required=True
        )
        
        self.add_item(self.name)
        self.add_item(self.price)
        self.add_item(self.description)
        self.add_item(self.class_name)
        self.add_item(self.vehicle_config)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.price.value.replace(',', '.'))
            if price < 0:
                await interaction.response.send_message("Price cannot be negative.", ephemeral=True)
                return
            
            class_name = self.class_name.value.strip()
            if not class_name:
                await interaction.response.send_message("Vehicle class name is required.", ephemeral=True)
                return
            
            # Parse vehicle config
            config_parts = [p.strip() for p in self.vehicle_config.value.split(',')]
            if len(config_parts) != 3:
                await interaction.response.send_message("Invalid vehicle config format. Use: spawns,cooldown,guarantee", ephemeral=True)
                return
            
            try:
                spawns = int(config_parts[0])
                cooldown = int(config_parts[1])
                guarantee = int(config_parts[2])
            except ValueError:
                await interaction.response.send_message("Vehicle config must be numbers.", ephemeral=True)
                return
            
            # Update vehicle data
            item_obj = {
                "name": self.name.value,
                "description": self.description.value if self.description.value else "",
                "price": price,
                "image_url": "",
                "is_vehicle": True,
                "vehicle_type": "spawn_vehicle",
                "insurance_drops": 0,
                "variations": [
                    {
                        "name": "Default",
                        "script": {
                            "vehicleClassName": class_name,
                            "amountOfAvailableSpawns": spawns,
                            "timeBeforeNextSpawn": cooldown,
                            "guaranteePeriod": guarantee,
                            "isUnique": True
                        },
                        "image_url": "",
                        "is_vehicle": True,
                        "insurance_drops": 0
                    }
                ]
            }
            items_catalog[self.vehicle_id] = item_obj
            await save_to_mongodb('items_catalog', self.vehicle_id, item_obj)
            await save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            await interaction.response.send_message(f"✅ Vehicle **{self.name.value}** updated successfully.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error updating vehicle: {str(e)}", ephemeral=True)

class VincularSteamModal(Modal):
    def __init__(self):
        super().__init__(title="Link SteamID (insurance)")
        self.steam_id = TextInput(label="SteamID64 (17 digits)", required=True)
        self.add_item(self.steam_id)

    async def on_submit(self, interaction: discord.Interaction):
        steam = self.steam_id.value.strip()
        if not validate_steam_id(steam):
            await interaction.response.send_message("Invalid SteamID.", ephemeral=True); return
        user_data[str(interaction.user.id)] = steam
        await save_to_mongodb('user_data', str(interaction.user.id), {"steam_id": steam})
        await interaction.response.send_message("✅ SteamID linked (used for insurance).", ephemeral=True)

class PurchaseSteamModal(Modal):
    def __init__(self, item_id: str, item_type: str, item_data: dict, variation_index: int = 0):
        title = "Enter SteamID for delivery"
        super().__init__(title=title)
        self.item_id = item_id
        self.item_type = item_type
        self.item_data = item_data
        self.variation_index = variation_index
        self.steam_id = TextInput(label="SteamID64 (destination)", required=True)
        # Determine if insurance should be prompted: check variation or item flags
        variation = None
        if item_data.get('variations'):
            try:
                variation = item_data['variations'][variation_index]
            except:
                variation = item_data['variations'][0] if item_data['variations'] else None
        is_vehicle = False
        drops = int(item_data.get('insurance_drops', 0) or 0)
        if variation:
            is_vehicle = variation.get('is_vehicle', item_data.get('is_vehicle', False))
            drops = int(variation.get('insurance_drops', drops) or drops)
        else:
            is_vehicle = item_data.get('is_vehicle', False)
        # Only show insurance choice if vehicle and drops > 0
        if is_vehicle and drops > 0:
            self.insurance_choice = TextInput(label="Want insurance? (y/n)", default="n", required=False)
            self.add_item(self.insurance_choice)
        else:
            # keep a hidden field by not adding; we'll assume default False later
            self.insurance_choice = None

        self.coupon_code = TextInput(
            label="Coupon code (optional)",
            required=False,
            placeholder="Ex: DISCOUNT10"
        )
        self.add_item(self.steam_id)
        self.add_item(self.coupon_code)

    async def on_submit(self, interaction: discord.Interaction):
        steam_target = self.steam_id.value.strip()
        if not validate_steam_id(steam_target):
            logger.error(f"Invalid SteamID provided: {steam_target}")
            await interaction.response.send_message("Invalid SteamID.", ephemeral=True)
            return
        insurance_choice = False
        if self.insurance_choice:
            insurance_choice = self.insurance_choice.value.strip().lower() in ("s", "sim", "y", "yes", "1")
        coupon_code = self.coupon_code.value.strip().upper() if self.coupon_code.value else None

        original_price = self.item_data.get('price', 0.0)
        final_price = original_price
        applied_coupon = None

        # Validate and apply coupon
        if coupon_code:
            if coupon_code not in coupons:
                logger.error(f"Invalid coupon: {coupon_code}")
                await interaction.response.send_message("Invalid coupon.", ephemeral=True)
                return
            if coupons[coupon_code]['uses'] == 0:
                logger.error(f"Coupon {coupon_code} has no uses available")
                await interaction.response.send_message("Coupon has no uses available.", ephemeral=True)
                return
            discount = coupons[coupon_code]['discount']
            final_price = max(0.0, original_price * (1 - discount / 100))
            applied_coupon = coupon_code

        # Determine override_script from variation
        override_script = None
        try:
            variation = self.item_data.get('variations', [None])[self.variation_index]
            if variation:
                override_script = variation.get('script')
        except Exception:
            override_script = None

        # If final price is 0 -> immediate delivery
        if final_price == 0.0:
            # Defer response immediately to avoid timeout
            await interaction.response.defer(ephemeral=True)
            
            success = await process_approved_payment(
                None,
                self.item_id,
                self.item_type,
                steam_target,
                applied_coupon,
                0.0,
                "free_item",
                interaction.user.id,
                override_script=override_script
            )
            if success:
                if applied_coupon and coupons[applied_coupon]['uses'] > 0:
                    coupons[applied_coupon]['uses'] -= 1
                    await save_to_mongodb('coupons', applied_coupon, coupons[applied_coupon])
                # Registrar seguros se aplicável
                is_vehicle = False
                drops = 0
                if variation:
                    is_vehicle = variation.get('is_vehicle', self.item_data.get('is_vehicle', False))
                    drops = int(variation.get('insurance_drops', self.item_data.get('insurance_drops', 0) or 0))
                if insurance_choice and is_vehicle and drops > 0:
                    seguros[steam_target] = seguros.get(steam_target, 0) + drops
                    await save_to_mongodb('seguros', steam_target, {"count": seguros[steam_target]})
                    compra_id = generate_unique_id("compra")
                    compras[compra_id] = {
                        "user_id": str(interaction.user.id),
                        "steam_id": steam_target,
                        "item_id": self.item_id,
                        "item_name": self.item_data.get("name"),
                        "drops": drops
                    }
                    await save_to_mongodb('compras', compra_id, compras[compra_id])
                await interaction.followup.send("✅ Free item delivered successfully! Use the insurance channel to activate.", ephemeral=True)
            else:
                await interaction.followup.send("Error delivering free item.", ephemeral=True)
            return

        # Defer response to avoid timeout (payment creation takes time)
        await interaction.response.defer(ephemeral=True)

        # Create payment for non-free items
        payment_result = await PayPalPayment.create_payment(
            amount=final_price,
            description=f"Purchase: {self.item_data.get('name')} - User: {interaction.user.id}" + (f" (Coupon: {applied_coupon})" if applied_coupon else ""),
            user_id=interaction.user.id,
            item_id=self.item_id,
            item_type=self.item_type,
            steam_target=steam_target,
            insurance=insurance_choice,
            coupon_code=applied_coupon
        )
        sales_channel = bot.get_channel(SALES_CHANNEL_ID)
        if not sales_channel:
            logger.error("Sales channel not found")
            await interaction.followup.send("Sales channel not found.", ephemeral=True)
            return
        try:
            thread = await sales_channel.create_thread(
                name=f"Purchase of {self.item_data.get('name')} - {interaction.user.name}",
                type=discord.ChannelType.private_thread,
                auto_archive_duration=60,
                invitable=False
            )
            await thread.add_user(interaction.user)
        except Exception as e:
            logger.error(f"Error creating thread: {str(e)}")
            await interaction.followup.send("Error creating thread.", ephemeral=True)
            return

        if payment_result["status"] == "pending":
            payment_id = payment_result["payment_id"]
            approval_url = payment_result["approval_url"]
            embed = discord.Embed(
                title="💳 Pay with PayPal to Complete",
                description=f"Order for **{self.item_data.get('name')}** created.\nAmount: {'€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY + ' '}{final_price:.2f}" + (f" (Coupon: {applied_coupon})" if applied_coupon else "") + f"\n\n[Click here to pay with PayPal]({approval_url})\n\nAfter payment, click the 'Check Payment' button.",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Payment ID: {payment_id}")

            class ThreadPaymentView(View):
                def __init__(self, thread_obj, payment_id, steam_target, item_id, item_type, item_data, insurance_choice, variation_index, override_script):
                    super().__init__(timeout=None)
                    self.thread = thread_obj
                    self.payment_id = payment_id
                    self.steam_target = steam_target
                    self.item_id = item_id
                    self.item_type = item_type
                    self.item_data = item_data
                    self.insurance_choice = insurance_choice
                    self.variation_index = variation_index
                    self.override_script = override_script

                @discord.ui.button(label="🔁 Check Payment", style=discord.ButtonStyle.primary)
                async def check_payment(self, interaction: discord.Interaction, button: Button):
                    status = await PayPalPayment.check_payment_status(self.payment_id)
                    if status == "approved":
                        info = pending_payments.get(self.payment_id)
                        if not info:
                            logger.error(f"Payment {self.payment_id} not found in pending_payments")
                            await interaction.response.send_message("Payment not found (bot restart?).", ephemeral=True)
                            return
                        success = await process_approved_payment(
                            interaction,
                            self.item_id,
                            self.item_type,
                            info.get("steam_target"),
                            info.get("coupon"),
                            info.get("amount"),
                            self.payment_id,
                            interaction.user.id,
                            override_script=self.override_script,
                            variation_index=self.variation_index
                        )
                        if success:
                            try:
                                del pending_payments[self.payment_id]
                            except:
                                pass
                            # Registrar compra com seguro se aplicável
                            is_vehicle = False
                            drops = 0
                            try:
                                var = self.item_data.get('variations', [None])[self.variation_index]
                                if var:
                                    is_vehicle = var.get('is_vehicle', self.item_data.get('is_vehicle', False))
                                    drops = int(var.get('insurance_drops', self.item_data.get('insurance_drops', 0) or 0))
                            except:
                                pass
                            if self.insurance_choice and is_vehicle and drops > 0:
                                compra_id = generate_unique_id("compra")
                                compras[compra_id] = {
                                    "user_id": str(interaction.user.id),
                                    "steam_id": self.steam_target,
                                    "item_id": self.item_id,
                                    "item_name": self.item_data.get("name"),
                                    "drops": drops
                                }
                                await save_to_mongodb('compras', compra_id, compras[compra_id])
                                logger.info(f"Purchase registered: {compra_id} for user {interaction.user.id}, SteamID {self.steam_target}")
                            await interaction.response.send_message("✅ Payment approved and item delivered! Use the insurance channel to activate.", ephemeral=True)
                        else:
                            logger.error(f"Failed to process delivery for payment {self.payment_id}")
                            await interaction.response.send_message("❌ Error processing delivery.", ephemeral=True)
                    elif status in ("pending", "in_process"):
                        await interaction.response.send_message(f"ℹ️ Payment still pending ({status}).", ephemeral=True)
                    else:
                        logger.error(f"Invalid payment status: {status} for payment {self.payment_id}")
                        await interaction.response.send_message(f"❌ Status: {status}.", ephemeral=True)

                @discord.ui.button(label="✅ Confirm Receipt", style=discord.ButtonStyle.success)
                async def confirm_receipt(self, interaction: discord.Interaction, button: Button):
                    await interaction.response.send_message("Thread will be closed.", ephemeral=True)
                    try:
                        await self.thread.delete()
                    except Exception as e:
                        logger.error(f"Erro ao deletar thread: {str(e)}")

                @discord.ui.button(label="❌ Cancel Purchase", style=discord.ButtonStyle.danger)
                async def cancel_purchase(self, interaction: discord.Interaction, button: Button):
                    try:
                        if self.payment_id in pending_payments:
                            del pending_payments[self.payment_id]
                    except:
                        pass
                    await interaction.response.send_message("Purchase canceled. Thread will be closed.", ephemeral=True)
                    try:
                        await self.thread.delete()
                    except Exception as e:
                        logger.error(f"Erro ao deletar thread: {str(e)}")

            view_thread = ThreadPaymentView(thread, payment_id, steam_target, self.item_id, self.item_type, self.item_data, insurance_choice, self.variation_index, override_script)
            try:
                await thread.send(embed=embed, view=view_thread)
            except Exception as e:
                logger.error(f"Error sending message in thread: {str(e)}")
                await interaction.response.send_message("Error sending message in thread.", ephemeral=True)
                return

            # Register insurance temporarily (only warning in thread)
            if insurance_choice:
                is_vehicle = False
                drops = 0
                try:
                    variation = self.item_data.get('variations', [None])[self.variation_index]
                    if variation:
                        is_vehicle = variation.get('is_vehicle', self.item_data.get('is_vehicle', False))
                        drops = int(variation.get('insurance_drops', self.item_data.get('insurance_drops', 0) or 0))
                except:
                    pass
                if is_vehicle and drops > 0:
                    seguros[steam_target] = seguros.get(steam_target, 0) + drops
                    await save_to_mongodb('seguros', steam_target, {"count": seguros[steam_target]})
                    await thread.send(f"✅ Insurance contracted! {drops} insurance(s) added for SteamID `{steam_target}`. Use the insurance channel to activate.")

            await interaction.followup.send(f"✅ Order created. Check the thread: {thread.mention}", ephemeral=True)
        else:
            logger.error(f"Error creating payment: {payment_result.get('message')}")
            await interaction.followup.send(f"Error creating payment: {payment_result.get('message')}", ephemeral=True)
class ItemSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None
        # Build options dynamically - only non-vehicle items
        options = []
        if items_catalog:
            for item_id, data in items_catalog.items():
                # Skip vehicles
                if data.get('vehicle_type') == 'spawn_vehicle' or data.get('is_vehicle', False):
                    continue
                options.append(discord.SelectOption(
                    label=data.get('name', 'Unknown Item')[:100],  # Discord limit
                    value=item_id
                ))
        
        if not options:
            options = [discord.SelectOption(label="No items available", value="none")]
        
        # Limit to 25 options (Discord limit)
        if len(options) > 25:
            options = options[:25]
        
        self.select_menu = discord.ui.Select(
            placeholder="Choose an item to edit...",
            options=options
        )
        self.select_menu.callback = self.select_item
        self.add_item(self.select_menu)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Item selection expired.", view=None)
            except:
                pass

    async def select_item(self, interaction: discord.Interaction):
        if self.select_menu.values[0] == "none":
            await interaction.response.send_message("No items available for editing.", ephemeral=True)
            return
        item_id = self.select_menu.values[0]
        item_data = items_catalog.get(item_id, {})
        if not item_data:
            await interaction.response.send_message("Item not found.", ephemeral=True)
            return
        await interaction.response.send_modal(EditItemModal(item_id, item_data))

class ItemDeleteSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None
        # Build options dynamically - only non-vehicle items
        options = []
        if items_catalog:
            for item_id, data in items_catalog.items():
                # Skip vehicles
                if data.get('vehicle_type') == 'spawn_vehicle' or data.get('is_vehicle', False):
                    continue
                options.append(discord.SelectOption(
                    label=data.get('name', 'Unknown Item')[:100],
                    value=item_id
                ))
        
        if not options:
            options = [discord.SelectOption(label="No items available", value="none")]
        
        if len(options) > 25:
            options = options[:25]
        
        self.select_menu = discord.ui.Select(
            placeholder="Choose an item to delete...",
            options=options
        )
        self.select_menu.callback = self.select_item
        self.add_item(self.select_menu)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Item selection expired.", view=None)
            except:
                pass

    async def select_item(self, interaction: discord.Interaction):
        if self.select_menu.values[0] == "none":
            await interaction.response.send_message("No items available for deletion.", ephemeral=True)
            return
        item_id = self.select_menu.values[0]
        item_data = items_catalog.get(item_id, {})
        if not item_data:
            await interaction.response.send_message("Item not found.", ephemeral=True)
            return
        await interaction.response.send_modal(DeleteItemModal(item_id, item_data.get('name', '')))

class CouponDeleteSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None
        # Build options dynamically
        options = []
        if coupons:
            for code in coupons.keys():
                options.append(discord.SelectOption(label=code[:100], value=code))
        else:
            options = [discord.SelectOption(label="No coupons available", value="none")]
        
        if len(options) > 25:
            options = options[:25]
        
        self.select_menu = discord.ui.Select(
            placeholder="Choose a coupon to delete...",
            options=options
        )
        self.select_menu.callback = self.select_coupon
        self.add_item(self.select_menu)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Coupon selection expired.", view=None)
            except:
                pass

    async def select_coupon(self, interaction: discord.Interaction):
        if self.select_menu.values[0] == "none":
            await interaction.response.send_message("No coupons available for deletion.", ephemeral=True)
            return
        code = self.select_menu.values[0]
        await interaction.response.send_modal(DeleteCouponModal(code))

class PassDeleteSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Pass selection expired.", view=None)
            except:
                pass

    @discord.ui.select(
        placeholder="Choose a pass to delete...",
        options=[discord.SelectOption(label=data.get('name', 'Unknown Pass'), value=pass_id)
                 for pass_id, data in passes_catalog.items()] or [discord.SelectOption(label="No passes available", value="none")]
    )
    async def select_pass(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_message("Pass deletion disabled.", ephemeral=True)

class SaldoDeleteSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Balance selection expired.", view=None)
            except:
                pass

    @discord.ui.select(
        placeholder="Choose a balance package to delete...",
        options=[discord.SelectOption(label=data.get('name', 'Unknown Balance'), value=item_id)
                 for item_id, data in items_catalog.items() if data.get('variations', [{}])[0].get('script', {}).get('banking', False)]
                 or [discord.SelectOption(label="No balance packages available", value="none")]
    )
    async def select_saldo(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_message("Balance deletion disabled.", ephemeral=True)

class VehicleSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None
        # Build options dynamically for vehicles only
        options = []
        for item_id, data in items_catalog.items():
            if data.get('vehicle_type') == 'spawn_vehicle':
                options.append(discord.SelectOption(
                    label=data.get('name', 'Unknown Vehicle')[:100],
                    value=item_id
                ))
        
        if not options:
            options = [discord.SelectOption(label="No vehicles available", value="none")]
        
        if len(options) > 25:
            options = options[:25]
        
        self.select_menu = discord.ui.Select(
            placeholder="Choose a vehicle to edit...",
            options=options
        )
        self.select_menu.callback = self.select_vehicle
        self.add_item(self.select_menu)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Vehicle selection expired.", view=None)
            except:
                pass

    async def select_vehicle(self, interaction: discord.Interaction):
        if self.select_menu.values[0] == "none":
            await interaction.response.send_message("No vehicles available for editing.", ephemeral=True)
            return
        item_id = self.select_menu.values[0]
        item_data = items_catalog.get(item_id, {})
        if not item_data or item_data.get('vehicle_type') != 'spawn_vehicle':
            await interaction.response.send_message("Vehicle not found.", ephemeral=True)
            return
        await interaction.response.send_modal(EditVehicleModal(item_id, item_data))

class VehicleDeleteSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None
        # Build options dynamically for vehicles only
        options = []
        for item_id, data in items_catalog.items():
            if data.get('vehicle_type') == 'spawn_vehicle':
                options.append(discord.SelectOption(
                    label=data.get('name', 'Unknown Vehicle')[:100],
                    value=item_id
                ))
        
        if not options:
            options = [discord.SelectOption(label="No vehicles available", value="none")]
        
        if len(options) > 25:
            options = options[:25]
        
        self.select_menu = discord.ui.Select(
            placeholder="Choose a vehicle to delete...",
            options=options
        )
        self.select_menu.callback = self.select_vehicle
        self.add_item(self.select_menu)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Vehicle selection expired.", view=None)
            except:
                pass

    async def select_vehicle(self, interaction: discord.Interaction):
        if self.select_menu.values[0] == "none":
            await interaction.response.send_message("No vehicles available for deletion.", ephemeral=True)
            return
        item_id = self.select_menu.values[0]
        item_data = items_catalog.get(item_id, {})
        if not item_data or item_data.get('vehicle_type') != 'spawn_vehicle':
            await interaction.response.send_message("Vehicle not found.", ephemeral=True)
            return
        await interaction.response.send_modal(DeleteVehicleModal(item_id, item_data.get('name', '')))

async def process_approved_payment(interaction, item_id, item_type, steam_id, coupon_code, amount, payment_id, user_id, override_script=None, variation_index=0):
    try:
        catalog = items_catalog if item_type == 'item' else passes_catalog
        if item_id not in catalog:
            logger.error(f"Item/Pass {item_id} not found.")
            if interaction:
                await interaction.followup.send("Item not found.", ephemeral=True)
            return False
        item_data = catalog[item_id]
        # Use override_script if provided (from selected variation)
        if override_script:
            script_data = override_script
        else:
            # try to get script from item (Pass/Item compatibility)
            if item_type == 'item':
                # look for selected variation
                variations = item_data.get('variations', [])
                try:
                    var = variations[variation_index]
                    script_data = var.get('script', {})
                except:
                    # fallback
                    script_data = variations[0].get('script', {}) if variations else {}
            else:
                # passes use main script
                try:
                    script_data = json.loads(item_data.get('script','{}'))
                except:
                    script_data = item_data.get('script', {}) if isinstance(item_data.get('script'), dict) else {}

        # Check if this is a vehicle spawn item
        vehicle_type = item_data.get('vehicle_type')
        if vehicle_type == 'spawn_vehicle':
            # Vehicle spawn delivery - extract from script_data
            class_name = script_data.get('vehicleClassName', '')
            spawns = script_data.get('amountOfAvailableSpawns', 1)
            cooldown = script_data.get('timeBeforeNextSpawn', 600)
            guarantee = script_data.get('guaranteePeriod', 604800)
            is_unique = script_data.get('isUnique', True)
            
            success = FTPManager.create_vehicle_file(
                steam_id=steam_id,
                class_name=class_name,
                spawns=spawns,
                cooldown=cooldown,
                guarantee=guarantee,
                unique=is_unique,
                vehicle_path=VEHICLE_SPAWN_PATH
            )
            
            if not success:
                logger.error(f"Failed to create vehicle spawn file for {class_name}")
                if interaction:
                    await interaction.followup.send("Error delivering vehicle spawn.", ephemeral=True)
                return False
            
            logger.info(f"Vehicle spawn {class_name} delivered to {steam_id}")
        else:
            # Deliver normal items
            success = False
            if item_type == 'item':
                item_to_give = script_data.get('itemToGive')
                if item_to_give and item_to_give != "none":
                    success = FTPManager.update_player_file(steam_id, item_name=item_to_give)
                else:
                    items_to_give = script_data.get('itemsToGive', [])
                    if items_to_give:
                        success = FTPManager.update_player_file(steam_id, item_list=items_to_give)
                    else:
                        success = True
            else:
                items_to_give = script_data.get('itemsToGive', [])
                if items_to_give:
                    success = FTPManager.update_player_file(steam_id, item_list=items_to_give)
                else:
                    success = True

            if not success:
                logger.error("Failed to deliver item via FTPManager")
                if interaction:
                    await interaction.followup.send("Error delivering item.", ephemeral=True)
                return False

        # Decrease coupon uses if applied
        if coupon_code and coupon_code in coupons and coupons[coupon_code]['uses'] > 0:
            coupons[coupon_code]['uses'] -= 1
            await save_to_mongodb('coupons', coupon_code, coupons[coupon_code])
            logger.info(f"Coupon {coupon_code} used. {coupons[coupon_code]['uses']} remaining")

        # Save purchase information to database
        try:
            purchase_id = generate_unique_id("purchase")
            
            # Get buyer information
            buyer_info = {}
            if interaction:
                buyer_info = {
                    'discord_id': str(interaction.user.id),
                    'discord_name': interaction.user.name,
                    'discord_display_name': interaction.user.display_name,
                }
            else:
                buyer_info = {
                    'discord_id': str(user_id),
                    'discord_name': 'Unknown',
                    'discord_display_name': 'Unknown',
                }
            
            # Get variation name if applicable
            variation_name = None
            if item_type == 'item' and override_script:
                variations = item_data.get('variations', [])
                try:
                    variation_name = variations[variation_index].get('name', f'Variation {variation_index}')
                except:
                    variation_name = None
            
            # Determine if it's a vehicle or item
            delivery_type = 'vehicle' if (vehicle_type == 'spawn_vehicle' or item_data.get('is_vehicle', False)) else 'item'
            
            # Get delivered content based on type
            if delivery_type == 'vehicle':
                delivered_content = {
                    'vehicle_class': script_data.get('vehicleClassName', ''),
                    'spawns': script_data.get('amountOfAvailableSpawns', 1),
                    'cooldown': script_data.get('timeBeforeNextSpawn', 600),
                    'guarantee': script_data.get('guaranteePeriod', 604800),
                    'is_unique': script_data.get('isUnique', True)
                }
            else:
                delivered_content = {
                    'items_delivered': script_data.get('itemsToGive', []) or ([script_data.get('itemToGive')] if script_data.get('itemToGive') else [])
                }
            
            purchase_data = {
                'purchase_id': purchase_id,
                'timestamp': datetime.now().isoformat(),
                'payment_id': payment_id,
                'amount': amount,
                'currency': PAYPAL_CURRENCY,
                'item_info': {
                    'item_id': item_id,
                    'item_name': item_data.get('name', 'Unknown'),
                    'delivery_type': delivery_type,
                    'item_price': item_data.get('price', 0.0),
                    'variation': variation_name,
                    'vehicle_type': item_data.get('vehicle_type'),
                    'is_vehicle': item_data.get('is_vehicle', False),
                    'insurance_drops': item_data.get('insurance_drops', 0),
                },
                'buyer_info': buyer_info,
                'delivery_info': {
                    'steam_id': steam_id,
                    **delivered_content
                },
                'coupon_info': {
                    'coupon_code': coupon_code if coupon_code else None,
                    'discount_applied': coupons.get(coupon_code, {}).get('discount', 0) if coupon_code else 0,
                },
                'status': 'completed'
            }
            
            await save_to_mongodb('purchases', purchase_id, purchase_data)
            logger.info(f"Purchase {purchase_id} saved to database")
            
        except Exception as e:
            logger.error(f"Error saving purchase to database: {str(e)}")
        
        # Notify sales channel
        sales_channel = bot.get_channel(SALES_CHANNEL_ID)
        if sales_channel:
            try:
                await sales_channel.send(f"🎉 Item **{item_data.get('name')}** delivered to SteamID `{steam_id}` (payment {payment_id}).")
            except Exception as e:
                logger.error(f"Error notifying sales channel: {str(e)}")

        if interaction:
            try:
                await interaction.followup.send("✅ Item delivered successfully.", ephemeral=True)
            except:
                pass

        logger.info(f"Item {item_id} delivered to {steam_id}")
        return True
    except Exception as e:
        logger.error(f"Error process_approved_payment: {traceback.format_exc()}")
        if interaction:
            try:
                await interaction.followup.send("Internal error processing payment.", ephemeral=True)
            except:
                pass
        return False

# View displayed in sales channel: only Buy button
class ItemViewForChannel(View):
    def __init__(self, item_id: str, item_data: dict):
        super().__init__(timeout=None)
        self.item_id = item_id
        self.item_data = item_data

    @discord.ui.button(label="🛒 Buy", style=discord.ButtonStyle.success)
    async def confirm_purchase(self, interaction: discord.Interaction, button: Button):
        # If item has multiple variations -> show selection view
        variations = self.item_data.get('variations', [])
        if variations and len(variations) > 1:
            # Build a temporary view with Select
            options = []
            for idx, v in enumerate(variations):
                label = v.get('name', f"Var{idx}")
                desc = ""
                # optionally show if vehicle
                if v.get('is_vehicle', False):
                    desc = " (Vehicle)"
                options.append(discord.SelectOption(label=label, value=str(idx), description=desc))
            class VariationSelectView(View):
                def __init__(self, item_id, item_data):
                    super().__init__(timeout=60)
                    self.item_id = item_id
                    self.item_data = item_data
                    self.message = None

                @discord.ui.select(placeholder="Choose color/model...", options=options, min_values=1, max_values=1)
                async def select_callback(self, interaction2: discord.Interaction, select: discord.ui.Select):
                    idx = int(select.values[0])
                    # open steam modal with selected variation
                    modal = PurchaseSteamModal(self.item_id, 'item' if self.item_id in items_catalog else 'pass', self.item_data, variation_index=idx)
                    await interaction2.response.send_modal(modal)

            view = VariationSelectView(self.item_id, self.item_data)
            await interaction.response.send_message("Choose desired variation:", view=view, ephemeral=True)
            return
        else:
            # only one variation or none -> open default modal (variation 0)
            modal = PurchaseSteamModal(self.item_id, 'item' if self.item_id in items_catalog else 'pass', self.item_data, variation_index=0)
            await interaction.response.send_modal(modal)

async def send_control_panel_info():
    """Send admin control panel information to dedicated channel"""
    try:
        control_channel = bot.get_channel(CONTROL_PANEL_CHANNEL_ID)
        if not control_channel:
            logger.error(f"Control Panel Channel ID {CONTROL_PANEL_CHANNEL_ID} not found")
            return
        
        # Delete all messages in the channel
        try:
            await control_channel.purge(limit=100)
            logger.info("Control panel channel cleared")
        except Exception as e:
            logger.error(f"Error clearing control panel channel: {str(e)}")
        
        # Create main embed with bot information
        embed_main = discord.Embed(
            title="🎮 Admin Control Panel",
            description="Welcome to the DayZ Store Bot Admin Control Panel",
            color=discord.Color.blue()
        )
        embed_main.add_field(
            name="📊 Bot Status",
            value=f"✅ Online and Ready\n🤖 Bot: {bot.user.name}\n🆔 ID: {bot.user.id}",
            inline=False
        )
        embed_main.set_thumbnail(url=bot.user.display_avatar.url if bot.user.display_avatar else None)
        embed_main.timestamp = datetime.now()
        await control_channel.send(embed=embed_main)
        
        # Commands embed
        embed_commands = discord.Embed(
            title="📝 Available Admin Commands",
            description="List of all commands you can use",
            color=discord.Color.green()
        )
        embed_commands.add_field(
            name="!c",
            value="Open the configuration panel with all management buttons",
            inline=False
        )
        embed_commands.add_field(
            name="!store",
            value="Send the store catalog via DM to the user",
            inline=False
        )
        embed_commands.add_field(
            name="!p <steam_id> <discord_id>",
            value="Link a Steam ID with Discord ID and save to database",
            inline=False
        )
        embed_commands.add_field(
            name="!u",
            value="List all linked players (Steam ID, Discord ID, Discord Name)",
            inline=False
        )
        await control_channel.send(embed=embed_commands)
        
        # Statistics embed
        embed_stats = discord.Embed(
            title="📈 Current Statistics",
            description="Overview of store data",
            color=discord.Color.purple()
        )
        embed_stats.add_field(
            name="🛒 Items",
            value=f"{len(items_catalog)} items in catalog",
            inline=True
        )
        embed_stats.add_field(
            name="🎫 Coupons",
            value=f"{len(coupons)} active coupons",
            inline=True
        )
        embed_stats.add_field(
            name="🛡️ Insurance",
            value=f"{len(seguros)} active insurances",
            inline=True
        )
        await control_channel.send(embed=embed_stats)
        
        logger.info("Control panel information sent successfully")
    except Exception as e:
        logger.error(f"Error sending control panel info: {str(e)}")

@bot.event
async def on_ready():
    # Load all data from MongoDB first
    await load_all_data()
    # Run migration if needed
    await migrate_items_to_variations()
    
    # Send control panel information
    await send_control_panel_info()
    
    logger.info(f"Bot connected as {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"Admin ID: {ADMIN_ID}")
    sales_channel = bot.get_channel(SALES_CHANNEL_ID)
    print(f"------\nBot {bot.user.name} is online!\nCommands: !c !store !p !u\n------")
    # Sales channel
    if sales_channel:
        try:
            def is_bot_msg(m): return m.author == bot.user
            await sales_channel.purge(limit=200, check=is_bot_msg)
            logger.info("Old bot messages deleted from sales channel.")
        except Exception as e:
            logger.error(f"Error deleting old messages from sales channel: {str(e)}")
        # Resend items
        for item_id, data in items_catalog.items():
            embed = discord.Embed(title=f"{data.get('name')}", description=data.get('description',''), color=discord.Color.green())
            curr_symbol = '€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY
            embed.add_field(name="Price", value=f"{curr_symbol} {data.get('price',0.0):.2f}", inline=True)
            if data.get('image_url'):
                embed.set_image(url=data.get('image_url'))
            view = ItemViewForChannel(item_id, data)
            try:
                await sales_channel.send(embed=embed, view=view)
            except Exception as e:
                logger.error(f"Error sending item embed {item_id}: {str(e)}")
        # Resend passes
        for pass_id, data in passes_catalog.items():
            embed = discord.Embed(title=f"{data.get('name')}", description=data.get('description',''), color=discord.Color.gold())
            curr_symbol = '€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY
            embed.add_field(name="Price", value=f"{curr_symbol} {data.get('price',0.0):.2f}", inline=True)
            if data.get('image_url'):
                embed.set_image(url=data.get('image_url'))
            view = ItemViewForChannel(pass_id, data)
            try:
                await sales_channel.send(embed=embed, view=view)
            except Exception as e:
                logger.error(f"Error sending pass embed {pass_id}: {str(e)}")

# Prefix commands
@bot.command(name="vincular")
async def vincular_command(ctx, steam_id: str = None):
    if steam_id:
        if not validate_steam_id(steam_id):
            await ctx.send("Invalid SteamID."); return
        user_data[str(ctx.author.id)] = steam_id
        await save_to_mongodb('user_data', str(ctx.author.id), {"steam_id": steam_id})
        await ctx.send("✅ SteamID linked.")
    else:
        await ctx.send("Usage: !vincular <steamid64>")

@bot.command(name="desvincular")
async def desvincular_command(ctx):
    uid = str(ctx.author.id)
    if uid in user_data:
        removed = user_data.pop(uid)
        await delete_from_mongodb('user_data', uid)
        await ctx.send(f"✅ Unlinked {removed}")
    else:
        await ctx.send("You don't have a linked SteamID.")

@bot.command(name="store")
async def loja_command(ctx):
    try:
        dm = await ctx.author.create_dm()
        for item_id, data in items_catalog.items():
            embed = discord.Embed(title=f"{data.get('name')}", description=data.get('description',''), color=discord.Color.green())
            curr_symbol = '€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY
            embed.add_field(name="Price", value=f"{curr_symbol} {data.get('price',0.0):.2f}")
            if data.get('image_url'):
                embed.set_image(url=data.get('image_url'))
            view = ItemViewForChannel(item_id, data)
            await dm.send(embed=embed, view=view)
        await ctx.send("✅ Store sent to DM.", delete_after=8)
    except Exception as e:
        logger.error(f"Error store DM: {str(e)}"); await ctx.send("Error sending store via DM.")

@bot.command(name="c")
async def config_command(ctx):
    if ctx.author.id != ADMIN_ID:
        await ctx.send("You don't have permission."); return
    view = View(timeout=None)
    btn_item = Button(label="➕ Create Item", style=discord.ButtonStyle.green)
    async def cb_item(interaction: discord.Interaction):
        await interaction.response.send_modal(CreateItemModal())
    btn_item.callback = cb_item
    view.add_item(btn_item)
    btn_coupon = Button(label="🎫 Create Coupon", style=discord.ButtonStyle.primary)
    async def cb_coupon(interaction: discord.Interaction):
        await interaction.response.send_modal(CreateCouponModal())
    btn_coupon.callback = cb_coupon
    view.add_item(btn_coupon)

    btn_edit_coupon = Button(label="✏️ Edit Coupon", style=discord.ButtonStyle.blurple)
    async def cb_edit_coupon(interaction: discord.Interaction):
        if not coupons:
            await interaction.response.send_message("No coupons available for editing.", ephemeral=True)
            return
        select_view = CouponSelectView()
        message = await interaction.response.send_message("Select a coupon to edit:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_edit_coupon.callback = cb_edit_coupon
    view.add_item(btn_edit_coupon)
    btn_edit_item = Button(label="✏️ Edit Item", style=discord.ButtonStyle.blurple)
    async def cb_edit_item(interaction: discord.Interaction):
        # Check if there are non-vehicle items
        has_items = any(not (data.get('vehicle_type') == 'spawn_vehicle' or data.get('is_vehicle', False)) 
                       for data in items_catalog.values())
        if not has_items:
            await interaction.response.send_message("No items available for editing.", ephemeral=True)
            return
        select_view = ItemSelectView()
        message = await interaction.response.send_message("Select an item to edit:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_edit_item.callback = cb_edit_item
    view.add_item(btn_edit_item)

    # New button for Create Vehicle
    btn_vehicle = Button(label="🚗 Create Vehicle", style=discord.ButtonStyle.green)
    async def cb_vehicle(interaction: discord.Interaction):
        await interaction.response.send_modal(CreateVehicleModal())
    btn_vehicle.callback = cb_vehicle
    view.add_item(btn_vehicle)
    
    # New button for Edit Vehicle
    btn_edit_vehicle = Button(label="✏️ Edit Vehicle", style=discord.ButtonStyle.blurple)
    async def cb_edit_vehicle(interaction: discord.Interaction):
        # Check if there are vehicles
        has_vehicles = any(data.get('vehicle_type') == 'spawn_vehicle' for data in items_catalog.values())
        if not has_vehicles:
            await interaction.response.send_message("No vehicles available for editing.", ephemeral=True)
            return
        select_view = VehicleSelectView()
        message = await interaction.response.send_message("Select a vehicle to edit:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_edit_vehicle.callback = cb_edit_vehicle
    view.add_item(btn_edit_vehicle)

    # New button for Refresh Store
    btn_refresh = Button(label="🔄 Refresh Store", style=discord.ButtonStyle.secondary)
    async def cb_refresh(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        sales_channel = bot.get_channel(SALES_CHANNEL_ID)
        if not sales_channel:
            await interaction.followup.send("Sales channel not found.", ephemeral=True)
            return
        try:
            # Clear old bot messages
            def is_bot_msg(m): return m.author == bot.user
            deleted = await sales_channel.purge(limit=200, check=is_bot_msg)
            logger.info(f"Deleted {len(deleted)} old messages from sales channel")
            
            # Resend all items
            for item_id, data in items_catalog.items():
                embed = discord.Embed(title=f"{data.get('name')}", description=data.get('description',''), color=discord.Color.green())
                curr_symbol = '€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY
                embed.add_field(name="Price", value=f"{curr_symbol} {data.get('price',0.0):.2f}", inline=True)
                if data.get('image_url'):
                    embed.set_image(url=data.get('image_url'))
                view_item = ItemViewForChannel(item_id, data)
                await sales_channel.send(embed=embed, view=view_item)
            
            # Resend all passes
            for pass_id, data in passes_catalog.items():
                embed = discord.Embed(title=f"{data.get('name')}", description=data.get('description',''), color=discord.Color.gold())
                curr_symbol = '€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY
                embed.add_field(name="Price", value=f"{curr_symbol} {data.get('price',0.0):.2f}", inline=True)
                if data.get('image_url'):
                    embed.set_image(url=data.get('image_url'))
                view_pass = ItemViewForChannel(pass_id, data)
                await sales_channel.send(embed=embed, view=view_pass)
            
            await interaction.followup.send(f"✅ Store refreshed! {len(items_catalog)} items and {len(passes_catalog)} passes displayed.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error refreshing store: {str(e)}")
            await interaction.followup.send(f"Error refreshing store: {str(e)}", ephemeral=True)
    btn_refresh.callback = cb_refresh
    view.add_item(btn_refresh)

    # Delete buttons
    btn_delete_item = Button(label="❌ Delete Item", style=discord.ButtonStyle.danger)
    async def cb_delete_item(interaction: discord.Interaction):
        if not items_catalog:
            await interaction.response.send_message("No items available for deletion.", ephemeral=True)
            return
        select_view = ItemDeleteSelectView()
        message = await interaction.response.send_message("Select an item to delete:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_delete_item.callback = cb_delete_item
    view.add_item(btn_delete_item)

    btn_delete_coupon = Button(label="❌ Delete Coupon", style=discord.ButtonStyle.danger)
    async def cb_delete_coupon(interaction: discord.Interaction):
        if not coupons:
            await interaction.response.send_message("No coupons available for deletion.", ephemeral=True)
            return
        select_view = CouponDeleteSelectView()
        message = await interaction.response.send_message("Select a coupon to delete:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_delete_coupon.callback = cb_delete_coupon
    view.add_item(btn_delete_coupon)

    btn_delete_vehicle = Button(label="❌ Delete Vehicle", style=discord.ButtonStyle.danger)
    async def cb_delete_vehicle(interaction: discord.Interaction):
        if not any(data.get('vehicle_type') == 'spawn_vehicle' for data in items_catalog.values()):
            await interaction.response.send_message("No vehicles available for deletion.", ephemeral=True)
            return
        select_view = VehicleDeleteSelectView()
        message = await interaction.response.send_message("Select a vehicle to delete:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_delete_vehicle.callback = cb_delete_vehicle
    view.add_item(btn_delete_vehicle)

    await ctx.send("Configuration panel:", view=view, ephemeral=True)

@bot.command(name="p")
async def link_player(ctx, steam_id: str = None, discord_id: str = None):
    """Link a Steam ID with Discord ID and save to database"""
    if ctx.author.id != ADMIN_ID:
        await ctx.send("You don't have permission."); return
    
    # Show usage if parameters are missing
    if not steam_id or not discord_id:
        usage_embed = discord.Embed(
            title="📖 Command Usage: !p",
            description="Link a Steam ID with Discord ID",
            color=discord.Color.blue()
        )
        usage_embed.add_field(
            name="Format",
            value="`!p <steam_id> <discord_id>`",
            inline=False
        )
        usage_embed.add_field(
            name="Example",
            value="`!p 76561198012345678 328736347298988032`",
            inline=False
        )
        usage_embed.add_field(
            name="Parameters",
            value="• `steam_id`: The player's Steam ID (17 digits)\n• `discord_id`: The user's Discord ID (right-click user → Copy ID)",
            inline=False
        )
        usage_embed.add_field(
            name="What it does",
            value="Saves the Steam ID, Discord ID, and Discord username to the database",
            inline=False
        )
        await ctx.send(embed=usage_embed)
        return
    
    try:
        # Convert discord_id to int
        discord_id_int = int(discord_id)
        
        # Get Discord user info
        try:
            discord_user = await bot.fetch_user(discord_id_int)
            discord_name = discord_user.name
        except:
            discord_name = "Unknown User"
        
        # Save to MongoDB
        player_data = {
            'steam_id': steam_id,
            'discord_id': str(discord_id_int),
            'discord_name': discord_name,
            'linked_at': datetime.now().isoformat()
        }
        
        await save_to_mongodb('linked_players', steam_id, player_data)
        
        embed = discord.Embed(
            title="✅ Player Linked Successfully",
            color=discord.Color.green()
        )
        embed.add_field(name="Steam ID", value=steam_id, inline=False)
        embed.add_field(name="Discord ID", value=discord_id, inline=False)
        embed.add_field(name="Discord Name", value=discord_name, inline=False)
        
        await ctx.send(embed=embed)
        logger.info(f"Linked player: {steam_id} -> {discord_id} ({discord_name})")
        
    except ValueError:
        await ctx.send("❌ Invalid Discord ID. Must be a number.")
    except Exception as e:
        await ctx.send(f"❌ Error linking player: {str(e)}")
        logger.error(f"Error linking player: {str(e)}")

@bot.command(name="u")
async def list_linked_players(ctx):
    """List all linked players from database"""
    if ctx.author.id != ADMIN_ID:
        await ctx.send("You don't have permission."); return
    
    try:
        # Load all linked players from MongoDB
        linked_players = await load_from_mongodb('linked_players')
        
        if not linked_players:
            await ctx.send("📋 No linked players found in database.")
            return
        
        # Create embed
        embed = discord.Embed(
            title="📋 Linked Players List",
            description=f"Total: {len(linked_players)} players",
            color=discord.Color.blue()
        )
        
        # Add players to embed (max 25 fields)
        count = 0
        for steam_id, data in linked_players.items():
            if count >= 25:  # Discord embed limit
                break
            
            discord_id = data.get('discord_id', 'N/A')
            discord_name = data.get('discord_name', 'Unknown')
            
            embed.add_field(
                name=f"🎮 {discord_name}",
                value=f"Steam: `{steam_id}`\nDiscord: `{discord_id}`",
                inline=True
            )
            count += 1
        
        if len(linked_players) > 25:
            embed.set_footer(text=f"Showing 25 of {len(linked_players)} players")
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"❌ Error retrieving linked players: {str(e)}")
        logger.error(f"Error retrieving linked players: {str(e)}")

@bot.command(name="limpar")
async def limpar_command(ctx, steam_id: str):
    if ctx.author.id != ADMIN_ID:
        await ctx.send("You don't have permission."); return
    if not validate_steam_id(steam_id):
        await ctx.send("Invalid SteamID."); return
    filename = f"{steam_id}.json"
    full_path = os.path.join(LOCAL_BASE_PATH, filename)
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
            await ctx.send("File cleared successfully.")
        except Exception as e:
            await ctx.send(f"Error deleting file: {str(e)}")
    else:
        await ctx.send("File not found.")

async def main():
    try:
        async with bot:
            await bot.start(BOT_TOKEN)
    except Exception:
        logger.error(f"Error starting bot: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())