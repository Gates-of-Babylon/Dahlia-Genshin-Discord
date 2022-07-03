import discord
import asyncio
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
from utility.GenshinApp import genshin_app

class GenshinTool(commands.Cog, name='原神工具'):
    def __init__(self, bot):
        self.bot = bot
    
    # 為使用者使用指定的兌換碼
    @app_commands.command(
        name='redeem兌換',
        description='使用Hoyolab兌換碼')
    @app_commands.rename(code='兌換碼')
    @app_commands.describe(code='請輸入要使用的兌換碼')
    async def slash_redeem(self, interaction: discord.Interaction, code: str):
        asyncio.create_task(interaction.response.defer())
        try:
            msg = await genshin_app.redeemCode(str(interaction.user.id), code)
        except Exception as e:
            msg = str(e)
        # 兌換網頁無任何回應訊息時，則新增連結按鈕至官網兌換
        if len(msg) == 0:
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label=code, url=f"https://genshin.hoyoverse.com/gift?code={code}"))
            await interaction.edit_original_message(content='發生未知錯誤，請直接點擊按鈕至官網兌換', view=view)
        else:
            await interaction.edit_original_message(content=msg)

    # 為使用者在Hoyolab簽到
    @app_commands.command(
        name='daily每日簽到',
        description='領取Hoyolab每日簽到獎勵')
    @app_commands.rename(game='遊戲')
    @app_commands.choices(game=[
        Choice(name='原神', value=0), 
        Choice(name='原神 + 崩壞3', value=1)])
    async def slash_daily(self, interaction: discord.Interaction, game: int = 0):
        asyncio.create_task(interaction.response.defer())
        result = await genshin_app.claimDailyReward(str(interaction.user.id), honkai=bool(game))
        await interaction.edit_original_message(content=result)

async def setup(client: commands.Bot):
    await client.add_cog(GenshinTool(client))