# main.py — Fazenda Handøx • Sistema de Farm (versão final)
# Requisitos: Python 3.10+ | pip install -U discord.py==2.4.0

import asyncio
from datetime import datetime
from typing import Callable, Awaitable

import discord
from discord.ext import commands
from discord import app_commands

TOKEN = "COLE O TOKEN DO DISCORD AQUI"  # Substitua pelo token do seu bot (mantenha em segredo!)

# ---------- Configuração do Bot ----------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Dados do Farm ----------
VALOR_PLANTA = 0.15
VALOR_ANIMAL = 80.00
ANIMAIS_POR_VENDA = 4

PLANTAS = ["milho", "junco", "trigo"]
ANIMAIS = ["porco", "vaca", "bode", "cabra", "ovelha", "jumento", "mula", "galinha", "galo", "touro"]

# farms[user_id] = {"plantas": {nome: {"qtd": int, "imgs": [url,...]}}, "animais": {...}}
farms: dict[int, dict] = {}
# tickets[channel_id] = owner_user_id
tickets: dict[int, int] = {}

# ---------- Helpers de tema ----------
def theme_color_green(): return discord.Color.from_str("#1f8b4c")  # verde premium
def theme_color_gold():  return discord.Color.from_str("#daa520")  # dourado
def theme_color_brown(): return discord.Color.from_str("#6b4f2f")  # marrom/terra

# ---------- Utilidades ----------
def get_user_farm(uid: int):
    if uid not in farms:
        farms[uid] = {"plantas": {}, "animais": {}}
    return farms[uid]

def calcular_totais(uid: int):
    f = get_user_farm(uid)
    tot_p = sum(e["qtd"] * VALOR_PLANTA for e in f["plantas"].values())
    tot_a = sum((e["qtd"] // ANIMAIS_POR_VENDA) * VALOR_ANIMAL for e in f["animais"].values())
    return tot_p, tot_a, tot_p + tot_a

async def pedir_print_obrigatorio(
    canal: discord.abc.Messageable,
    user: discord.User | discord.Member,
    prompt_ephemeral: Callable[[str], Awaitable[discord.Message]],
    timeout: int = 120
) -> str | None:
    """Solicita um print (imagem) e retorna a URL ou None em caso de timeout."""
    await prompt_ephemeral("📸 Envie **agora** o print para concluir o registro (tempo: 2 min).")
    def check(m: discord.Message):
        return m.author.id == user.id and m.channel.id == canal.id and len(m.attachments) > 0
    try:
        msg_img: discord.Message = await bot.wait_for("message", timeout=timeout, check=check)
        return msg_img.attachments[0].url
    except asyncio.TimeoutError:
        await prompt_ephemeral("⏰ Tempo esgotado. Registro cancelado. Use `/menu` ou `!menu` para tentar novamente.")
        return None

# ---------- Modal de quantidade ----------
class QuantidadeModal(discord.ui.Modal):
    def __init__(self, tipo: str, nome_item: str):
        super().__init__(title="Registrar Planta" if tipo == "plantas" else "Registrar Animal")
        self.tipo = tipo
        self.nome_item = nome_item
        self.qtd = discord.ui.TextInput(label="Quantidade", placeholder="Ex: 500 (somente números)", required=True)
        self.add_item(self.qtd)

    async def on_submit(self, inter: discord.Interaction):
        # Defer primeiro (evita "algo deu errado")
        await inter.response.defer(ephemeral=True)

        # Validação de quantidade
        try:
            qtd = int(self.qtd.value)
            if qtd <= 0:
                raise ValueError
        except ValueError:
            return await inter.followup.send("⚠️ Informe uma **quantidade válida** (inteiro positivo).", ephemeral=True)

        # Solicitar print obrigatório
        async def prompt_ephemeral(msg: str):
            return await inter.followup.send(msg, ephemeral=True)

        img_url = await pedir_print_obrigatorio(inter.channel, inter.user, prompt_ephemeral)
        if not img_url:
            return  # já avisado

        # Persistir no "banco"
        farm = get_user_farm(inter.user.id)
        bucket = farm[self.tipo].setdefault(self.nome_item, {"qtd": 0, "imgs": []})
        bucket["qtd"] += qtd
        bucket["imgs"].append(img_url)

        # Calcular e compor embed
        if self.tipo == "plantas":
            total = bucket["qtd"] * VALOR_PLANTA
            color, titulo = theme_color_green(), "🌿 Planta Registrada!"
            valor_txt = f"💵 Total desta planta: **R${total:.2f}**"
        else:
            grupos = bucket["qtd"] // ANIMAIS_POR_VENDA
            total = grupos * VALOR_ANIMAL
            color, titulo = theme_color_brown(), "🐗 Animal Registrado!"
            valor_txt = f"💵 Total vendável (4 = R$80,00): **R${total:.2f}**"

        e = discord.Embed(
            title=titulo,
            description=f"**{inter.user.mention}** registrou **{qtd}x {self.nome_item.capitalize()}**.\n{valor_txt}",
            color=color
        )
        e.add_field(name="📦 Quantidade acumulada", value=str(bucket["qtd"]), inline=True)
        e.add_field(name="📅 Data", value=datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"), inline=True)
        e.set_image(url=img_url)
        e.set_footer(text="🌾 Fazenda Handøx • Registro de Produção")

        await inter.followup.send(embed=e)
        await inter.followup.send("💡 Dica: se o painel sumir, use `/menu` ou `!menu`.", ephemeral=True)

# ---------- Selects e Painel ----------
class PlantaSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🌿 Escolha uma planta…",
            options=[discord.SelectOption(label=p.capitalize(), value=p, emoji="🌿") for p in PLANTAS]
        )
    async def callback(self, inter: discord.Interaction):
        owner = tickets.get(inter.channel.id)
        if owner is not None and inter.user.id != owner:
            return await inter.response.send_message("🚫 Apenas o dono deste ticket pode registrar.", ephemeral=True)
        await inter.response.send_modal(QuantidadeModal("plantas", self.values[0]))

class AnimalSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🐗 Escolha um animal…",
            options=[discord.SelectOption(label=a.capitalize(), value=a, emoji="🐾") for a in ANIMAIS]
        )
    async def callback(self, inter: discord.Interaction):
        owner = tickets.get(inter.channel.id)
        if owner is not None and inter.user.id != owner:
            return await inter.response.send_message("🚫 Apenas o dono deste ticket pode registrar.", ephemeral=True)
        await inter.response.send_modal(QuantidadeModal("animais", self.values[0]))

class FarmPanel(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.add_item(PlantaSelect())
        self.add_item(AnimalSelect())

    @discord.ui.button(label="📊 Ver Totais", style=discord.ButtonStyle.secondary)
    async def ver_totais(self, inter: discord.Interaction, _):
        t_p, t_a, t_g = calcular_totais(self.owner_id)
        e = discord.Embed(
            title="📊 Relatório de Produção — Fazenda Handøx",
            color=theme_color_gold()
        )
        e.add_field(name="🌿 Plantas", value=f"**R${t_p:.2f}**", inline=False)
        e.add_field(name="🐗 Animais", value=f"**R${t_a:.2f}**", inline=False)
        e.add_field(name="💵 Total Geral", value=f"**R${t_g:.2f}**", inline=False)
        e.set_footer(text="🌾 Fazenda Handøx • Sistema de Produção")
        await inter.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="🔒 Fechar Ticket", style=discord.ButtonStyle.danger)
    async def fechar_ticket(self, inter: discord.Interaction, _):
        owner = tickets.get(inter.channel.id)
        # dono do ticket OU quem tem permissão de gerenciar canais/admin
        has_perm = inter.user.guild_permissions.manage_channels or inter.user.guild_permissions.administrator
        if inter.user.id != owner and not has_perm:
            return await inter.response.send_message("🚫 Você não tem permissão para fechar este ticket.", ephemeral=True)

        view = ConfirmCloseView(channel=inter.channel, owner_id=owner, closer=inter.user)
        await inter.response.send_message("Tem certeza que deseja **encerrar** este ticket?", view=view, ephemeral=True)

# ---------- Fechamento + Log ----------
class ConfirmCloseView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, owner_id: int, closer: discord.Member):
        super().__init__(timeout=60)
        self.channel = channel
        self.owner_id = owner_id
        self.closer = closer

    @discord.ui.button(label="✅ Sim, encerrar", style=discord.ButtonStyle.success)
    async def confirmar(self, inter: discord.Interaction, _):
        # Resumo final
        t_p, t_a, t_g = calcular_totais(self.owner_id)
        final_embed = discord.Embed(
            title="💰 Ticket Encerrado — Resumo Final",
            description=f"📦 Produção de <@{self.owner_id}>",
            color=theme_color_green()
        )
        final_embed.add_field(name="🌿 Plantas", value=f"**R${t_p:.2f}**", inline=True)
        final_embed.add_field(name="🐗 Animais", value=f"**R${t_a:.2f}**", inline=True)
        final_embed.add_field(name="💵 Total Geral", value=f"**R${t_g:.2f}**", inline=False)
        final_embed.add_field(name="👤 Fechado por", value=self.closer.mention, inline=False)
        final_embed.timestamp = datetime.utcnow()
        final_embed.set_footer(text="🌾 Fazenda Handøx • Fechamento")

        await inter.response.send_message(embed=final_embed)

        # Log no canal 🌾-registros
        try:
            log_ch = discord.utils.get(inter.guild.text_channels, name="🌾-registros")
            if log_ch is None:
                log_ch = await inter.guild.create_text_channel("🌾-registros")

            log = discord.Embed(title="🧾 Registro de Farm Concluído", color=theme_color_gold())
            log.add_field(name="👤 Trabalhador", value=f"<@{self.owner_id}>", inline=True)
            log.add_field(name="👨‍🌾 Fechado por", value=self.closer.mention, inline=True)
            log.add_field(name="🌿 Plantas", value=f"R${t_p:.2f}", inline=True)
            log.add_field(name="🐗 Animais", value=f"R${t_a:.2f}", inline=True)
            log.add_field(name="💵 Total", value=f"**R${t_g:.2f}**", inline=False)
            log.timestamp = datetime.utcnow()
            log.set_footer(text="🌾 Fazenda Handøx • Registro Oficial")
            await log_ch.send(embed=log)
        except discord.Forbidden:
            await inter.followup.send("⚠️ Não consegui escrever em **#🌾-registros**. Verifique minhas permissões.", ephemeral=True)

        # Limpar dados e deletar o canal
        if self.owner_id in farms:
            del farms[self.owner_id]
        if self.channel.id in tickets:
            del tickets[self.channel.id]

        await self.channel.send("🔒 Ticket encerrado. Este canal será apagado em **5s**…")
        await asyncio.sleep(5)
        try:
            await self.channel.delete(reason="Ticket encerrado — Fazenda Handøx")
        except discord.Forbidden:
            pass

    @discord.ui.button(label="❌ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancelar(self, inter: discord.Interaction, _):
        await inter.response.send_message("Operação cancelada.", ephemeral=True)
        self.stop()

# ---------- /abrir_farm ----------
@bot.tree.command(name="abrir_farm", description="Abre um ticket da Fazenda Handøx 🌾")
async def abrir_farm(inter: discord.Interaction):
    g, u = inter.guild, inter.user

    # categoria: 🌾 Farms (cria se não existir)
    cat = discord.utils.get(g.categories, name="🌾 Farms")
    if cat is None:
        try:
            cat = await g.create_category("🌾 Farms", reason="Categoria de tickets — Fazenda Handøx")
        except discord.Forbidden:
            return await inter.response.send_message(
                "🚫 Não tenho permissão para criar categorias/canais. Dê **Manage Channels** ao meu cargo.",
                ephemeral=True
            )

    # canal do ticket
    ch_name = f"ticket-farm-{u.name}".replace(" ", "-").lower()
    try:
        ch = await g.create_text_channel(
            ch_name, category=cat,
            overwrites={
                g.default_role: discord.PermissionOverwrite(view_channel=False),
                u: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
            },
            reason=f"Ticket de farm — {u}"
        )
    except discord.Forbidden:
        return await inter.response.send_message(
            "🚫 Falha ao criar canal. Verifique se meu cargo tem **Manage Channels** e está **acima** dos cargos necessários.",
            ephemeral=True
        )

    tickets[ch.id] = u.id
    get_user_farm(u.id)  # inicia estrutura

    e = discord.Embed(
        title="🌾 Fazenda Handøx — Painel de Produção",
        description=(
            f"👋 Olá {u.mention}!\n"
            "Use os **menus** abaixo para registrar suas **🌿 plantas** e **🐗 animais**.\n"
            "Após escolher, informe a **quantidade** e **envie o print** para confirmar.\n\n"
            "Se o painel sumir, reabra com **`/menu`** ou **`!menu`**."
        ),
        color=theme_color_green()
    )
    e.set_footer(text="🌾 Fazenda Handøx • Sistema de Farm")

    await ch.send(embed=e, view=FarmPanel(owner_id=u.id))
    await inter.response.send_message(f"✅ Ticket criado: {ch.mention}", ephemeral=True)

# ---------- /menu e !menu ----------
@bot.tree.command(name="menu", description="Reabre o painel do ticket atual.")
async def menu_slash(inter: discord.Interaction):
    owner = tickets.get(inter.channel.id)
    if owner is None:
        return await inter.response.send_message("⚠️ Este canal não é um ticket de farm.", ephemeral=True)
    if owner != inter.user.id:
        return await inter.response.send_message("🚫 Apenas o dono deste ticket pode reabrir o painel.", ephemeral=True)

    e = discord.Embed(
        title="🌾 Menu do Farm Reaberto!",
        description=(
            f"🌻 Bem-vindo de volta, {inter.user.mention}!\n\n"
            "Use os menus abaixo para registrar **🌿 plantas** e **🐗 animais**.\n\n"
            "✨ Você pode abrir este menu novamente a qualquer momento com:\n"
            "👉 **`/menu`** ou **`!menu`**"
        ),
        color=theme_color_green()
    )
    e.set_footer(text="🌾 Fazenda Handøx • Sistema de Produção")
    await inter.response.send_message(embed=e, view=FarmPanel(owner_id=owner))

@bot.command(name="menu")
async def menu_text(ctx: commands.Context):
    owner = tickets.get(ctx.channel.id)
    if owner is None:
        return await ctx.send("⚠️ Este canal não é um ticket de farm.", delete_after=6)
    if owner != ctx.author.id:
        return await ctx.send("🚫 Apenas o dono deste ticket pode reabrir o painel.", delete_after=6)

    e = discord.Embed(
        title="🌾 Menu do Farm Reaberto!",
        description=(
            f"🌻 Bem-vindo de volta, {ctx.author.mention}!\n\n"
            "Use os menus abaixo para registrar **🌿 plantas** e **🐗 animais**.\n\n"
            "✨ Você pode abrir este menu novamente a qualquer momento com:\n"
            "👉 **`/menu`** ou **`!menu`**"
        ),
        color=theme_color_green()
    )
    e.set_footer(text="🌾 Fazenda Handøx • Sistema de Produção")
    await ctx.send(embed=e, view=FarmPanel(owner_id=owner))

# ---------- Inicialização ----------
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"🌿 Slash commands sincronizados: {len(synced)}")
    except Exception as e:
        print("❌ Falha ao sincronizar slash commands:", repr(e))
    print(f"✅ Conectado como {bot.user} • Fazenda Handøx")


bot.run(TOKEN)