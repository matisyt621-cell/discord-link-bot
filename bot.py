import discord
import re
import urllib.parse
import os
import asyncio  # DODANE: Wymagane do funkcji oczekiwania (sleep)
from flask import Flask
import threading

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# --- WZORCE DLA AGENTÓW (które nie są standardowymi URLami) ---
KAKAOBUY_SIMPLE_ITEM_ID_REGEX = r"goods\.php\?id=(\d+)"
CNFANS_ITEM_ID_REGEX = r"cnfans\.com.*id=(\d+)"
ACBUY_ITEM_ID_REGEX = r"acbuy\.com.*id=(\d+)"
OOPBUY_ITEM_ID_REGEX = r"oopbuy\.com\/product\/(weidian|taobao)\/(\d+)"

# --- SZABLONY LINKÓW ŹRÓDŁOWYCH I DOCELOWYCH ---
WEIDIAN_SOURCE_URL_PATTERN = "https://weidian.com/item.html?itemID={}"
TAOBAO_SOURCE_URL_PATTERN = "https://item.taobao.com/item.htm?id={}"
OFFER_SOURCE_URL_PATTERN = "https://detail.1688.com/offer/{}.html"

KAKAOBUY_URL_PATTERN = "https://www.kakobuy.com/item/details?url={ENCODED_SOURCE_URL}&affcode=Matisek"
QC_URL_PATTERN = "https://findqc.com/detail/{SOURCE_CODE}/{ID}"

# --------------------------
# AKTUALIZACJA INTENTÓW
# --------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # DODANE: Wymagane dla on_member_join
client = discord.Client(intents=intents)
# --------------------------


def fully_unquote(text):
    old_text = text
    new_text = urllib.parse.unquote(old_text)
    while new_text != old_text:
        old_text = new_text
        new_text = urllib.parse.unquote(old_text)
    return new_text


def parse_url_for_id_and_platform(url):
    """
    Parsuje URL z uwzględnieniem wielkości liter i lokalizacji ID w query/path.
    Zwraca (item_id, platform_name) lub (None, None).
    """

    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc.lower()
    path = parsed_url.path.lower()

    # Używamy parse_qs, ale tworzymy słownik bez wrażliwości na wielkość liter
    query_params_raw = urllib.parse.parse_qs(parsed_url.query)
    query_params = {k.lower(): v for k, v in query_params_raw.items()}

    item_id = None
    platform = None

    if "weidian.com" in domain:
        platform = "Weidian"
        # Sprawdzamy klucze niezależnie od wielkości liter ('itemid', 'itemID')
        if 'itemid' in query_params:
            item_id = query_params['itemid'][0]

    elif "taobao.com" in domain:
        platform = "Taobao"
        if 'id' in query_params:
            item_id = query_params['id'][0]

    elif "1688.com" in domain:
        platform = "1688"
        # 1688 używa ID w ścieżce URL (/offer/ID.html)
        match = re.search(r"offer\/(\d+)", path)
        if match:
            item_id = match.group(1)

    if item_id:
        # Finalne czyszczenie
        item_id = str(item_id).strip()

    return item_id, platform


def konwertuj_linki(text):
    item_id = None
    source_type = None
    source_platform = None
    text_lower = text.lower()

    # KROK 1: Parsowanie linków zakodowanych Kakobuy
    if "kakobuy.com" in text_lower and "url=https%" in text_lower:

        source_type = "Kakobuy (encoded)"

        match = re.search(r"url=(https%3A%2F%2F.*)", text_lower)
        if match:
            encoded_source_url_part = match.group(1)
            decoded_url = fully_unquote(encoded_source_url_part)

            item_id, source_platform = parse_url_for_id_and_platform(decoded_url)

    # KROK 2: Parsowanie bezpośrednich linków
    if not item_id:
        if any(domain in text_lower for domain in ["weidian.com", "taobao.com", "1688.com"]):
            item_id, source_platform = parse_url_for_id_and_platform(text)
            if item_id:
                source_type = source_platform

    # KROK 3: Parsowanie prostych linków agentów
    if not item_id:

        if "cnfans.com" in text_lower:
            match = re.search(CNFANS_ITEM_ID_REGEX, text_lower)
            if match:
                item_id = match.group(1)
                source_type = "CNFans"
                source_platform = "Weidian"

        elif "acbuy.com" in text_lower:
            match = re.search(ACBUY_ITEM_ID_REGEX, text_lower)
            if match:
                item_id = match.group(1)
                source_type = "ACBuy"
                source_platform = "Weidian"

        elif "oopbuy.com" in text_lower:
            match = re.search(OOPBUY_ITEM_ID_REGEX, text_lower)
            if match:
                platform_str = match.group(1)
                source_platform = platform_str.capitalize()
                item_id = match.group(2)
                source_type = "OOPBuy"

        elif "kakobuy.com/goods" in text_lower:
            match = re.search(KAKAOBUY_SIMPLE_ITEM_ID_REGEX, text_lower)
            if match:
                item_id = match.group(1)
                source_type = "Kakobuy (simple)"
                source_platform = "Weidian"

    if item_id and source_platform:

        platform_check = source_platform.lower()

        if platform_check == "weidian":
            source_url = WEIDIAN_SOURCE_URL_PATTERN.format(item_id)
            source_code = "WD"
        elif platform_check == "taobao" or platform_check == "1688":
            if platform_check == "1688":
                source_url = OFFER_SOURCE_URL_PATTERN.format(item_id)
            else:
                source_url = TAOBAO_SOURCE_URL_PATTERN.format(item_id)

            source_code = "TB"
        else:
            source_url = TAOBAO_SOURCE_URL_PATTERN.format(item_id)
            source_code = "TB"

        encoded_source_url = urllib.parse.quote(source_url, safe='')
        kakao_buy_link = KAKAOBUY_URL_PATTERN.replace("{ENCODED_SOURCE_URL}", encoded_source_url)

        qc_link = QC_URL_PATTERN.replace("{SOURCE_CODE}", source_code).replace("{ID}", item_id)

        return {
            "Kakobuy": kakao_buy_link,
            "ID": item_id,
            "QC_Link": qc_link
        }, source_type

    return None, None


@client.event
async def on_ready():
    print(f'Zalogowano jako {client.user}!')

# ------------------------------------
# NOWA FUNKCJA POWITALNA (on_member_join)
# ------------------------------------
# ID kanałów, na których ma pojawić się powitanie.
# Grupa ID serwera to 1440822254437928990 (niepotrzebna do kodu, tylko ID kanałów są wymagane)
WELCOME_CHANNEL_IDS = [1457134422712123392, 1457134318152323270] 

@client.event
async def on_member_join(member):
    # Szukamy kanału powitalnego w serwerze, do którego dołączył użytkownik
    for target_id in WELCOME_CHANNEL_IDS:
        channel = member.guild.get_channel(target_id)
        
        if channel:
            # member.mention taguje nowego użytkownika
            welcome_message_content = f"Witamy na serwerze, {member.mention}! Pamiętaj, aby zapoznać się z regulaminem."
            
            try:
                # Wysyłamy wiadomość
                sent_message = await channel.send(welcome_message_content)
                print(f"DIAGNOZA: Wysłano powitanie do {member.name} na kanale {channel.name}.")
                
                # Czekamy 3 sekundy
                await asyncio.sleep(3)
                
                # Usuwamy wiadomość
                await sent_message.delete()
                print(f"DIAGNOZA: Usunięto wiadomość powitalną.")
            except discord.Forbidden:
                print(f"BŁĄD: Nie mam uprawnień do wysłania/usunięcia wiadomości na kanale {channel.name}.")
# ------------------------------------


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    text_lower = message.content.lower()

    if any(agent_url in text_lower for agent_url in
           ["weidian.com", "taobao.com", "kakobuy.com", "cnfans.com", "acbuy.com", "oopbuy.com", "1688.com"]):

        print(f"DIAGNOZA: Wykryto potencjalny link do konwersji: {message.content[:50]}...")

        wyniki, source_type = konwertuj_linki(message.content)

        if wyniki:

            view = discord.ui.View()

            view.add_item(
                discord.ui.Button(label="🛒 Kakobuy", url=wyniki["Kakobuy"], style=discord.ButtonStyle.primary))
            view.add_item(
                discord.ui.Button(label=f"🔍 Sprawdź QC", style=discord.ButtonStyle.secondary, url=wyniki["QC_Link"],
                                  emoji="🔍"))

            await message.reply(
                "🔗 Konwersja linku na Kakobuy:",
                view=view
            )
        else:
            print(f"DIAGNOZA: NIE UDAŁO SIĘ sparsować ID z linku: {message.content}")
            await message.reply(
                f"❌ Błąd konwersji: Wykryłem link, ale nie udało się z niego poprawnie odczytać ID przedmiotu."
            )

# ----------------------------------------------------
# SEKCJA: Minimalny Serwer Flask dla Rendera (PRZED RUN)
# ----------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Discord Bot Running - OK"

def run_flask_server():
    port = os.environ.get('PORT', 5000)
    print(f"DIAGNOZA: Uruchamianie serwera Flask na porcie {port}...")
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# Uruchom serwer Flask w oddzielnym wątku
flask_thread = threading.Thread(target=run_flask_server)
flask_thread.start()
# ----------------------------------------------------


client.run(DISCORD_TOKEN)
