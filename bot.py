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

# Load .env
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
SALES_CHANNEL_ID = int(os.getenv('SALES_CHANNEL_ID') or '0')
ADMIN_ID = int(os.getenv('ADMIN_ID') or '0')
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID')
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET')
PAYPAL_MODE = os.getenv('PAYPAL_MODE', 'sandbox')
PAYPAL_CURRENCY = os.getenv('PAYPAL_CURRENCY', 'EUR').upper()
USE_LOCAL = os.getenv('USE_LOCAL', 'false').lower() == 'true'
LOCAL_BASE_PATH = os.getenv('LOCAL_BASE_PATH')
BANKING_PATH = os.getenv('BANKING_PATH')  # New: Specific path for banking
FTP_HOST = os.getenv('FTP_HOST')
FTP_PORT = os.getenv('FTP_PORT', '21')
FTP_USER = os.getenv('FTP_USER')
FTP_PASS = os.getenv('FTP_PASS')
FTP_BASE_PATH = os.getenv('FTP_BASE_PATH')
SEGUROS_CHANNEL_ID = int(os.getenv('SEGUROS_CHANNEL_ID') or '0')
GUILD_ID = int(os.getenv('GUILD_ID') or '0')
PELTCURRENCY_PATH = os.getenv('PELTCURRENCY_PATH')
CAC_ROLE_ID = int(os.getenv('CAC_ROLE_ID') or '0')

# Minimum validations
if not BOT_TOKEN:
    print("Error: BOT_TOKEN not defined in .env"); sys.exit(1)
if not SALES_CHANNEL_ID:
    print("Error: SALES_CHANNEL_ID not defined in .env"); sys.exit(1)
if not ADMIN_ID:
    print("Error: ADMIN_ID not defined in .env"); sys.exit(1)
if not PAYPAL_CLIENT_ID:
    print("Error: PAYPAL_CLIENT_ID not defined in .env"); sys.exit(1)
if not PAYPAL_CLIENT_SECRET:
    print("Error: PAYPAL_CLIENT_SECRET not defined in .env"); sys.exit(1)
if USE_LOCAL and not LOCAL_BASE_PATH:
    print("Error: LOCAL_BASE_PATH not defined in .env (required when USE_LOCAL=true)"); sys.exit(1)
if not USE_LOCAL and (not FTP_HOST or not FTP_BASE_PATH):
    print("Error: FTP_HOST and FTP_BASE_PATH are required when USE_LOCAL=false"); sys.exit(1)
if not SEGUROS_CHANNEL_ID:
    print("Error: SEGUROS_CHANNEL_ID not defined in .env"); sys.exit(1)
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
ITEMS_LIST_TXT = "lista_itens_venda.txt"
PASSES_LIST_TXT = "lista_passes_venda.txt"
SEGUROS_FILE = "seguros.json"
SEGUROS_LOG = "seguros_acionados.txt"
COMPRAS_FILE = "compras.json"  # NEW: File to register purchases with insurance

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

def save_list_to_txt(filename, catalog):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            if not catalog:
                f.write("No items/passes registered.\n")
                return
            f.write(f"--- List Updated on {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} ---\n\n")
            for item_id, data in catalog.items():
                # Format price according to selected currency (simple symbol mapping)
                symbol = '€' if PAYPAL_CURRENCY == 'EUR' else (PAYPAL_CURRENCY + ' ')
                price_str = f"{symbol}{data.get('price', 0.0):.2f}"
                f.write(f"- {data.get('name', 'Undefined Name')} ({item_id}): {price_str}\n")
            f.write("\n--- End of List ---")
        logger.info(f"List saved in {filename}")
    except Exception as e:
        logger.error(f"Error saving list in {filename}: {str(e)}")

# Load data
items_catalog = load_json(ITEMS_FILE, {})
coupons = load_json(COUPONS_FILE, {})
passes_catalog = load_json(PASSES_FILE, {})
user_data = load_json(USER_DATA_FILE, {})
seguros = load_json(SEGUROS_FILE, {})
compras = load_json(COMPRAS_FILE, {})  # NEW: Load compras.json
save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
save_list_to_txt(PASSES_LIST_TXT, passes_catalog)

# Automatic migration function: converts old items (with root 'script') to new format with 'variations'
def migrate_items_to_variations():
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
        save_json(ITEMS_FILE, items_catalog)
        logger.info("Migration to 'variations' executed and items_catalog saved.")
# Execute migration right after defining the function
migrate_items_to_variations()

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
            del items_catalog[self.item_id]
            save_json(ITEMS_FILE, items_catalog)
            save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            sales_channel = bot.get_channel(SALES_CHANNEL_ID)
            if sales_channel:
                async for message in sales_channel.history(limit=200):
                    if message.author == bot.user and message.embeds and message.embeds[0].title == items_catalog.get(self.item_id, {}).get('name', ''):
                        await message.delete()
                        break
            await interaction.response.send_message(f"✅ Item **{items_catalog.get(self.item_id, {}).get('name', '')}** deleted successfully.", ephemeral=True)
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
            save_json(COUPONS_FILE, coupons)
            await interaction.response.send_message(f"✅ Coupon **{self.code}** deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("Coupon not found.", ephemeral=True)

class DeletePassModal(Modal):
    def __init__(self, pass_id: str, pass_name: str):
        super().__init__(title=f"Delete Pass: {pass_name}")
        self.pass_id = pass_id
        self.confirm = TextInput(label="Type 'YES' to confirm deletion", required=True)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.strip().upper() != "YES":
            await interaction.response.send_message("Invalid confirmation. Type 'YES' to delete.", ephemeral=True)
            return
        if self.pass_id in passes_catalog:
            del passes_catalog[self.pass_id]
            save_json(PASSES_FILE, passes_catalog)
            save_list_to_txt(PASSES_LIST_TXT, passes_catalog)
            sales_channel = bot.get_channel(SALES_CHANNEL_ID)
            if sales_channel:
                async for message in sales_channel.history(limit=200):
                    if message.author == bot.user and message.embeds and message.embeds[0].title == passes_catalog.get(self.pass_id, {}).get('name', ''):
                        await message.delete()
                        break
            await interaction.response.send_message(f"✅ Pass **{passes_catalog.get(self.pass_id, {}).get('name', '')}** deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("Pass not found.", ephemeral=True)

class DeleteSaldoModal(Modal):
    def __init__(self, item_id: str, item_name: str):
        super().__init__(title=f"Delete Balance: {item_name}")
        self.item_id = item_id
        self.confirm = TextInput(label="Type 'YES' to confirm deletion", required=True)
        self.add_item(self.confirm)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value.strip().upper() != "YES":
            await interaction.response.send_message("Invalid confirmation. Type 'YES' to delete.", ephemeral=True)
            return
        if self.item_id in items_catalog:
            del items_catalog[self.item_id]
            save_json(ITEMS_FILE, items_catalog)
            save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            sales_channel = bot.get_channel(SALES_CHANNEL_ID)
            if sales_channel:
                async for message in sales_channel.history(limit=200):
                    if message.author == bot.user and message.embeds and message.embeds[0].title == items_catalog.get(self.item_id, {}).get('name', ''):
                        await message.delete()
                        break
            await interaction.response.send_message(f"✅ Balance Package **{items_catalog.get(self.item_id, {}).get('name', '')}** deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("Balance Package not found.", ephemeral=True)

class CreateItemModal(Modal):
    def __init__(self):
        super().__init__(title="Create New Item")
        self.name = TextInput(label="Item Name", placeholder="Ex: Backpack", required=True)
        currency_label = '€' if PAYPAL_CURRENCY == 'EUR' else PAYPAL_CURRENCY
        self.price = TextInput(label=f"Price ({currency_label})", placeholder="Ex: 10.00", required=True)
        self.image_url = TextInput(label="Image URL (optional)", placeholder="https://...", required=False)
        self.variations = TextInput(
            label="Variations (JSON)",
            placeholder='Ex: [{"name":"Black","script":{"itemsToGive":["Item"], "banking": true}}]',
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.vehicle_info = TextInput(
            label="Vehicle and Insurance (ex: y,3)",
            placeholder="Ex: y,3 (vehicle with 3 insurance) or n,0 (no vehicle)",
            required=False,
            default="n,0"
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
                await interaction.response.send_message("Price cannot be negative.", ephemeral=True); return

            variations_text = self.variations.value.strip()
            if not variations_text:
                await interaction.response.send_message("The 'Variations (JSON)' field is required.", ephemeral=True); return
            variations = json.loads(variations_text)
            # Validate each variation has name and script
            for v in variations:
                if 'name' not in v or 'script' not in v:
                    await interaction.response.send_message("Each variation needs 'name' and 'script'.", ephemeral=True); return

            vi = self.vehicle_info.value.strip().lower()
            is_vehicle = False
            drops = 0
            if vi:
                parts = [p.strip() for p in vi.split(',') if p.strip() != '']
                if parts:
                    is_vehicle = parts[0] in ('s','y','sim','yes','1','true')
                    if len(parts) > 1:
                        try:
                            drops = int(parts[1])
                        except:
                            drops = 0

            item_id = generate_unique_id("item")
            item_obj = {
                "name": self.name.value,
                "price": price,
                "image_url": self.image_url.value,
                "is_vehicle": is_vehicle,
                "insurance_drops": drops,
                "variations": variations
            }
            items_catalog[item_id] = item_obj
            save_json(ITEMS_FILE, items_catalog)
            save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            await interaction.response.send_message(f"✅ Item **{self.name.value}** created with ID `{item_id}`.", ephemeral=True)
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
            save_json(ITEMS_FILE, items_catalog)
            save_list_to_txt(ITEMS_LIST_TXT, items_catalog)

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
            save_json(COUPONS_FILE, coupons)
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
            save_json(COUPONS_FILE, coupons)
            await interaction.response.send_message(f"✅ Coupon {self.code} updated.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class CouponSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Coupon selection expired.", view=None)
            except:
                pass

    @discord.ui.select(
        placeholder="Choose a coupon to edit...",
        options=[discord.SelectOption(label=f"{code} — {data.get('discount',0)}% ({'unlimited' if data.get('uses',0)==-1 else data.get('uses',0)} uses)", value=code)
                 for code, data in coupons.items()] or [discord.SelectOption(label="No coupons available", value="none")]
    )
    async def select_coupon(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No coupons available.", ephemeral=True)
            return
        code = select.values[0]
        data = coupons.get(code, {})
        await interaction.response.send_modal(EditCouponModal(code, data))

class CreatePassModal(Modal):
    def __init__(self):
        super().__init__(title="Create Pass")
        self.name = TextInput(label="Pass Name", required=True)
        self.price = TextInput(label=f"Price ({'€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY})", required=True)
        self.image_url = TextInput(label="Image URL (optional)", required=False)
        self.script = TextInput(label="Script JSON", style=discord.TextStyle.paragraph, required=True)
        self.add_item(self.name)
        self.add_item(self.price)
        self.add_item(self.image_url)
        self.add_item(self.script)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.price.value.replace(',', '.'))
            json.loads(self.script.value)
            pass_id = generate_unique_id("pass")
            passes_catalog[pass_id] = {
                "name": self.name.value,
                "price": price,
                "image_url": self.image_url.value,
                "script": self.script.value
            }
            save_json(PASSES_FILE, passes_catalog)
            save_list_to_txt(PASSES_LIST_TXT, passes_catalog)
            await interaction.response.send_message(f"✅ Pass {self.name.value} created ({pass_id}).", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)

class CreateSaldoModal(Modal):
    def __init__(self):
        super().__init__(title="Create Balance Package")
        self.name = TextInput(label="Package Name", placeholder="Ex: 50K Balance", required=True)
        self.price = TextInput(label=f"Price ({'€' if PAYPAL_CURRENCY=='EUR' else PAYPAL_CURRENCY})", placeholder="Ex: 30.00", required=True)
        self.currency_amount = TextInput(label="Balance Amount", placeholder="Ex: 50000", required=True)
        self.image_url = TextInput(label="Image URL (optional)", placeholder="https://...", required=False)
        self.add_item(self.name)
        self.add_item(self.price)
        self.add_item(self.currency_amount)
        self.add_item(self.image_url)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            price = float(self.price.value.replace(',', '.'))
            if price < 0:
                await interaction.response.send_message("Price cannot be negative.", ephemeral=True); return

            amount = int(self.currency_amount.value)
            if amount <= 0:
                await interaction.response.send_message("Balance amount must be positive.", ephemeral=True); return

            item_id = generate_unique_id("saldo")
            item_obj = {
                "name": self.name.value,
                "price": price,
                "image_url": self.image_url.value,
                "is_vehicle": False,
                "insurance_drops": 0,
                "variations": [
                    {
                        "name": "Default",
                        "script": {
                            "itemsToGive": [],
                            "banking": True,
                            "currencyAmount": amount
                        },
                        "image_url": "",
                        "is_vehicle": False,
                        "insurance_drops": 0
                    }
                ]
            }
            items_catalog[item_id] = item_obj
            save_json(ITEMS_FILE, items_catalog)
            save_list_to_txt(ITEMS_LIST_TXT, items_catalog)
            await interaction.response.send_message(f"✅ Balance Package **{self.name.value}** created with ID `{item_id}`.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error creating balance package: {str(e)}", ephemeral=True)

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
        save_json(USER_DATA_FILE, user_data)
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
                    save_json(COUPONS_FILE, coupons)
                # Registrar seguros se aplicável
                is_vehicle = False
                drops = 0
                if variation:
                    is_vehicle = variation.get('is_vehicle', self.item_data.get('is_vehicle', False))
                    drops = int(variation.get('insurance_drops', self.item_data.get('insurance_drops', 0) or 0))
                if insurance_choice and is_vehicle and drops > 0:
                    seguros[steam_target] = seguros.get(steam_target, 0) + drops
                    save_json(SEGUROS_FILE, seguros)
                    compra_id = generate_unique_id("compra")
                    compras[compra_id] = {
                        "user_id": str(interaction.user.id),
                        "steam_id": steam_target,
                        "item_id": self.item_id,
                        "item_name": self.item_data.get("name"),
                        "drops": drops
                    }
                    save_json(COMPRAS_FILE, compras)
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
                                save_json(COMPRAS_FILE, compras)
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
                    save_json(SEGUROS_FILE, seguros)
                    await thread.send(f"✅ Insurance contracted! {drops} insurance(s) added for SteamID `{steam_target}`. Use the insurance channel to activate.")

            await interaction.followup.send(f"✅ Order created. Check the thread: {thread.mention}", ephemeral=True)
        else:
            logger.error(f"Error creating payment: {payment_result.get('message')}")
            await interaction.followup.send(f"Error creating payment: {payment_result.get('message')}", ephemeral=True)

# NEW: View for insurance channel
class SegurosView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚗 Activate Insurance", style=discord.ButtonStyle.secondary)
    async def acionar_seguro(self, interaction: discord.Interaction, button: Button):
        class AcionarSeguroModal(Modal):
            def __init__(self):
                super().__init__(title="Activate Insurance - Enter SteamID")
                self.steam = TextInput(label="SteamID64", placeholder="SteamID to receive vehicle", required=True)
                self.add_item(self.steam)

            async def on_submit(self, interaction2: discord.Interaction):
                steam = self.steam.value.strip()
                logger.info(f"Attempt to activate insurance for SteamID {steam} by {interaction2.user.id}")
                if not validate_steam_id(steam):
                    logger.error(f"Invalid SteamID provided: {steam}")
                    await interaction2.response.send_message("Invalid SteamID.", ephemeral=True)
                    return
                qtd = seguros.get(steam, 0)
                if qtd <= 0:
                    logger.error(f"No insurance available for SteamID {steam}")
                    await interaction2.response.send_message("No insurance available for this SteamID.", ephemeral=True)
                    return
                # NEW: Verify if user is the buyer
                user_id = str(interaction2.user.id)
                compra_id = None
                item_data = None
                for cid, compra in compras.items():
                    if compra["steam_id"] == steam and compra["user_id"] == user_id and compra["drops"] > 0:
                        compra_id = cid
                        item_data = items_catalog.get(compra["item_id"], {})
                        break
                if not item_data or not item_data.get("is_vehicle", False):
                    logger.error(f"User {user_id} is not the buyer or item is not a vehicle for SteamID {steam}")
                    await interaction2.response.send_message("You are not the buyer of this insurance or the item is not a vehicle.", ephemeral=True)
                    return
                try:
                    script_data = json.loads(item_data.get('script', '{}'))
                    logger.info(f"JSON script loaded for item {item_data.get('name')}: {script_data}")
                except Exception as e:
                    logger.error(f"Error parsing JSON script: {str(e)}")
                    await interaction2.response.send_message("Invalid item script.", ephemeral=True)
                    return
                success = FTPManager.update_player_file(steam, item_list=script_data.get('itemsToGive', []) or None, item_name=script_data.get('itemToGive'))
                if success:
                    seguros[steam] = max(0, seguros.get(steam, 0) - 1)
                    save_json(SEGUROS_FILE, seguros)
                    compras[compra_id]["drops"] = max(0, compras[compra_id]["drops"] - 1)  # NEW: Reduce drops in purchase
                    save_json(COMPRAS_FILE, compras)
                    logger.info(f"Insurance activated successfully for SteamID {steam}. Remaining insurance: {seguros.get(steam, 0)}")
                    with open(SEGUROS_LOG, 'a', encoding='utf-8') as f:
                        f.write(f"{datetime.now().isoformat()} - Insurance activated by {interaction2.user.id} for SteamID {steam} - Item {item_data.get('name')}\n")
                    await interaction2.response.send_message("✅ Insurance activated. Vehicle dropped.", ephemeral=True)
                else:
                    logger.error(f"Failed to drop vehicle for SteamID {steam}")
                    await interaction2.response.send_message("Error dropping vehicle.", ephemeral=True)
        modal = AcionarSeguroModal()
        await interaction.response.send_modal(modal)

class ItemSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Item selection expired.", view=None)
            except:
                pass

    @discord.ui.select(
        placeholder="Choose an item to edit...",
        options=[discord.SelectOption(label=data.get('name', 'Unknown Item'), value=item_id)
                 for item_id, data in items_catalog.items()] or [discord.SelectOption(label="No items available", value="none")]
    )
    async def select_item(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No items available for editing.", ephemeral=True)
            return
        item_id = select.values[0]
        item_data = items_catalog.get(item_id, {})
        if not item_data:
            await interaction.response.send_message("Item not found.", ephemeral=True)
            return
        await interaction.response.send_modal(EditItemModal(item_id, item_data))

class ItemDeleteSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Item selection expired.", view=None)
            except:
                pass

    @discord.ui.select(
        placeholder="Choose an item to delete...",
        options=[discord.SelectOption(label=data.get('name', 'Unknown Item'), value=item_id)
                 for item_id, data in items_catalog.items()] or [discord.SelectOption(label="No items available", value="none")]
    )
    async def select_item(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No items available for deletion.", ephemeral=True)
            return
        item_id = select.values[0]
        item_data = items_catalog.get(item_id, {})
        if not item_data:
            await interaction.response.send_message("Item not found.", ephemeral=True)
            return
        await interaction.response.send_modal(DeleteItemModal(item_id, item_data.get('name', '')))

class CouponDeleteSelectView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.message = None

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(content="⏳ Coupon selection expired.", view=None)
            except:
                pass

    @discord.ui.select(
        placeholder="Choose a coupon to delete...",
        options=[discord.SelectOption(label=code, value=code)
                 for code in coupons.keys()] or [discord.SelectOption(label="No coupons available", value="none")]
    )
    async def select_coupon(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "none":
            await interaction.response.send_message("No coupons available for deletion.", ephemeral=True)
            return
        code = select.values[0]
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
        if select.values[0] == "none":
            await interaction.response.send_message("No passes available for deletion.", ephemeral=True)
            return
        pass_id = select.values[0]
        pass_data = passes_catalog.get(pass_id, {})
        if not pass_data:
            await interaction.response.send_message("Pass not found.", ephemeral=True)
            return
        await interaction.response.send_modal(DeletePassModal(pass_id, pass_data.get('name', '')))

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
        if select.values[0] == "none":
            await interaction.response.send_message("No balance packages available for deletion.", ephemeral=True)
            return
        item_id = select.values[0]
        item_data = items_catalog.get(item_id, {})
        if not item_data or not item_data.get('variations', [{}])[0].get('script', {}).get('banking', False):
            await interaction.response.send_message("Balance package not found.", ephemeral=True)
            return
        await interaction.response.send_modal(DeleteSaldoModal(item_id, item_data.get('name', '')))

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
                    success = True  # Allow success if only banking
        else:
            items_to_give = script_data.get('itemsToGive', [])
            if items_to_give:
                success = FTPManager.update_player_file(steam_id, item_list=items_to_give)
            else:
                success = True  # Allow success if only banking

        # Add balance if "banking": true in script
        if script_data.get('banking', False):
            banking_amount = script_data.get('currencyAmount', 100000)  # Use currencyAmount if present, fallback to 100000
            banking_success = FTPManager.update_banking_file(steam_id, banking_amount)
            if not banking_success:
                logger.error("Failed to update banking balance")
                if interaction:
                    await interaction.followup.send("Error adding balance.", ephemeral=True)
                return False
            else:
                logger.info(f"Banking balance updated to {banking_amount} for {steam_id}")

        if not success:
            logger.error("Failed to deliver item via FTPManager")
            if interaction:
                await interaction.followup.send("Error delivering item.", ephemeral=True)
            return False

        # Decrease coupon uses if applied
        if coupon_code and coupon_code in coupons and coupons[coupon_code]['uses'] > 0:
            coupons[coupon_code]['uses'] -= 1
            save_json(COUPONS_FILE, coupons)
            logger.info(f"Coupon {coupon_code} used. {coupons[coupon_code]['uses']} remaining")

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

@bot.event
async def on_ready():
    logger.info(f"Bot connected as {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"Admin ID: {ADMIN_ID}")
    sales_channel = bot.get_channel(SALES_CHANNEL_ID)
    seguros_channel = bot.get_channel(SEGUROS_CHANNEL_ID)  # NEW: Insurance channel
    print(f"------\nBot {bot.user.name} is online!\nCommands: !c !vincular !desvincular !store\n------")
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
    # NEW: Configure insurance channel
    if seguros_channel:
        try:
            def is_bot_msg(m): return m.author == bot.user
            await seguros_channel.purge(limit=200, check=is_bot_msg)
            logger.info("Old bot messages deleted from insurance channel.")
            embed = discord.Embed(
                title="🚗 Activate Insurance",
                description="Click the button below to activate insurance for a purchased vehicle. You must be the original buyer and provide the SteamID used in the purchase.",
                color=discord.Color.blue()
            )
            view = SegurosView()
            await seguros_channel.send(embed=embed, view=view)
            logger.info("Insurance activation embed sent to insurance channel.")
        except Exception as e:
            logger.error(f"Error configuring insurance channel: {str(e)}")

# Prefix commands
@bot.command(name="vincular")
async def vincular_command(ctx, steam_id: str = None):
    if steam_id:
        if not validate_steam_id(steam_id):
            await ctx.send("Invalid SteamID."); return
        user_data[str(ctx.author.id)] = steam_id
        save_json(USER_DATA_FILE, user_data)
        await ctx.send("✅ SteamID linked.")
    else:
        await ctx.send("Usage: !vincular <steamid64>")

@bot.command(name="desvincular")
async def desvincular_command(ctx):
    uid = str(ctx.author.id)
    if uid in user_data:
        removed = user_data.pop(uid)
        save_json(USER_DATA_FILE, user_data)
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
    btn_pass = Button(label="🎖️ Create Pass", style=discord.ButtonStyle.secondary)
    async def cb_pass(interaction: discord.Interaction):
        await interaction.response.send_modal(CreatePassModal())
    btn_pass.callback = cb_pass
    view.add_item(btn_pass)
    btn_edit_item = Button(label="✏️ Edit Item", style=discord.ButtonStyle.blurple)
    async def cb_edit_item(interaction: discord.Interaction):
        if not items_catalog:
            await interaction.response.send_message("No items available for editing.", ephemeral=True)
            return
        select_view = ItemSelectView()
        message = await interaction.response.send_message("Select an item to edit:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_edit_item.callback = cb_edit_item
    view.add_item(btn_edit_item)

    # New button for Create Balance
    btn_saldo = Button(label="➕ Create Balance", style=discord.ButtonStyle.green)
    async def cb_saldo(interaction: discord.Interaction):
        await interaction.response.send_modal(CreateSaldoModal())
    btn_saldo.callback = cb_saldo
    view.add_item(btn_saldo)

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

    btn_delete_pass = Button(label="❌ Delete Pass", style=discord.ButtonStyle.danger)
    async def cb_delete_pass(interaction: discord.Interaction):
        if not passes_catalog:
            await interaction.response.send_message("No passes available for deletion.", ephemeral=True)
            return
        select_view = PassDeleteSelectView()
        message = await interaction.response.send_message("Select a pass to delete:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_delete_pass.callback = cb_delete_pass
    view.add_item(btn_delete_pass)

    btn_delete_saldo = Button(label="❌ Delete Balance", style=discord.ButtonStyle.danger)
    async def cb_delete_saldo(interaction: discord.Interaction):
        if not any(data.get('variations', [{}])[0].get('script', {}).get('banking', False) for data in items_catalog.values()):
            await interaction.response.send_message("No balance packages available for deletion.", ephemeral=True)
            return
        select_view = SaldoDeleteSelectView()
        message = await interaction.response.send_message("Select a balance package to delete:", view=select_view, ephemeral=True)
        select_view.message = message
    btn_delete_saldo.callback = cb_delete_saldo
    view.add_item(btn_delete_saldo)

    await ctx.send("Configuration panel:", view=view, ephemeral=True)

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