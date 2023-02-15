import asyncio
import random
import typing
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks

from utility import SlashCommandLogger, config
from yuanshen import automation


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.presence_string: list[str] = ["genshin"]
        self.change_presence.start()

    # sync Slash commands to current server
    @app_commands.command(name="sync", description="sync Slash commands to current server")
    @app_commands.rename(area="area")
    @app_commands.choices(area=[Choice(name="current server", value=0), Choice(name="global server", value=1)])
    @SlashCommandLogger
    async def slash_sync(self, interaction: discord.Interaction, area: int = 0):
        await interaction.response.defer()
        if area == 0 and interaction.guild:  # 複製全域指令，同步到當前伺服器，不需等待 copy global command, sync to current server, no waiting required
            self.bot.tree.copy_global_to(guild=interaction.guild)
            result = await self.bot.tree.sync(guild=interaction.guild)
        else:  # 同步到全域，需等待一小時 sync to global, estimated 1 hour waiting time
            result = await self.bot.tree.sync()

        msg = f'command syncronized to{"all" if area == 1 else "current"}server:{",".join(cmd.name for cmd in result)}'
        await interaction.edit_original_response(content=msg)

    # 顯示機器人相關狀態 display bot's status
    @app_commands.command(name="status", description="display helper's status")
    @app_commands.choices(
        option=[
            Choice(name="ping", value=0),
            Choice(name="number of connected servers", value=1),
            Choice(name="server names", value=2),
        ]
    )
    @SlashCommandLogger
    async def slash_status(self, interaction: discord.Interaction, option: int):
        if option == 0:
            await interaction.response.send_message(f"ping: {round(self.bot.latency*1000)} ms")
        elif option == 1:
            await interaction.response.send_message(f"connected {len(self.bot.guilds)} servers")
        elif option == 2:
            await interaction.response.defer()
            names = [guild.name for guild in self.bot.guilds]
            for i in range(0, len(self.bot.guilds), 100):
                msg = ",".join(names[i : i + 100])
                embed = discord.Embed(title=f"server names({i + 1})", description=msg)
                await interaction.followup.send(embed=embed)

    # 使用系統命令 use system command
    @app_commands.command(name="system", description="use system command(control cog, change bot status)")
    @app_commands.rename(option="option", param="parameter")
    @app_commands.choices(
        option=[
            Choice(name="load", value="load"),
            Choice(name="unload", value="unload"),
            Choice(name="reload", value="reload"),
            Choice(name="presence", value="presence"),
            Choice(name="claimdailyreward", value="claimdailyreward"),
        ]
    )
    @SlashCommandLogger
    async def slash_system(
        self, interaction: discord.Interaction, option: str, param: typing.Optional[str] = None
    ):
        async def operateCogs(
            func: typing.Callable[[str], typing.Awaitable[None]],
            param: typing.Optional[str] = None,
            *,
            pass_self: bool = False,
        ):
            if param is None:  # control all cog
                for filepath in Path("./cogs").glob("**/*.py"):
                    cog_name = Path(filepath).stem
                    if pass_self and cog_name == "admin":
                        continue
                    await func(f"cogs.{cog_name}")
            else:  # sintrol one cog
                await func(f"cogs.{param}")

        if option == "load":  # Load cogs
            await operateCogs(self.bot.load_extension, param, pass_self=True)
            await interaction.response.send_message(f"{param or 'all'}command loaded succesfully")

        elif option == "unload":  # Unload cogs
            await operateCogs(self.bot.unload_extension, param, pass_self=True)
            await interaction.response.send_message(f"{param or 'all'}command unloaded succesfully")

        elif option == "reload":  # Reload cogs
            await operateCogs(self.bot.reload_extension, param)
            await interaction.response.send_message(f"{param or 'all'}command reloaded succesfully")

        elif option == "presence" and param is not None:  # Change presence string
            self.presence_string = param.split(",")
            await interaction.response.send_message(f"Presence listchanged to: {self.presence_string}")

        elif option == "claimdailyreward":  # start daily reward claim
            await interaction.response.send_message("Autoamaticaly claim daily rewards")
            asyncio.create_task(automation.claim_daily_reward(self.bot))

    # daily config values
    @app_commands.command(name="config", description="daily config values")
    @app_commands.rename(option="option", value="values")
    @app_commands.choices(
        option=[
            Choice(name="schedule_daily_reward_time", value="schedule_daily_reward_time"),
            Choice(
                name="schedule_check_resin_interval",
                value="schedule_check_resin_interval",
            ),
            Choice(name="schedule_loop_delay", value="schedule_loop_delay"),
            Choice(name="notification_channel_id", value="notification_channel_id"),
        ]
    )
    @SlashCommandLogger
    async def slash_config(self, interaction: discord.Interaction, option: str, value: str):
        if option in [
            "schedule_daily_reward_time",
            "schedule_check_resin_interval",
            "notification_channel_id",
        ]:
            setattr(config, option, int(value))
        elif option in ["schedule_loop_delay"]:
            setattr(config, option, float(value))
        await interaction.response.send_message(f"has been{option}changed to: {value}")

    @app_commands.command(name="maintenance", description="setup maintenance schuedle")
    @app_commands.rename(month="month", day="day", hour="hour", duration="duration")
    @SlashCommandLogger
    async def slash_maintenance(
        self,
        interaction: discord.Interaction,
        month: int,
        day: int,
        hour: int = 6,
        duration: int = 5,
    ):
        if month == 0 or day == 0:
            config.game_maintenance_time = None
            await interaction.response.send_message("maintenance schedule has been set to: off")
        else:
            now = datetime.now()
            start_time = datetime(
                (now.year if month >= now.month else now.year + 1), month, day, hour
            )
            end_time = start_time + timedelta(hours=duration)
            config.game_maintenance_time = (start_time, end_time)
            await interaction.response.send_message(f"maintenance schedule has been set to:{start_time} ~ {end_time}")

    # 每一定時間更改機器人狀態 change bot's status
    @tasks.loop(minutes=1)
    async def change_presence(self):
        length = len(self.presence_string)
        n = random.randint(0, length)
        if n < length:
            await self.bot.change_presence(activity=discord.Game(self.presence_string[n]))
        elif n == length:
            await self.bot.change_presence(activity=discord.Game(f"{len(self.bot.guilds)} servers"))

    @change_presence.before_loop
    async def before_change_presence(self):
        await self.bot.wait_until_ready()


async def setup(client: commands.Bot):
    await client.add_cog(Admin(client), guild=discord.Object(id=config.test_server_id))
