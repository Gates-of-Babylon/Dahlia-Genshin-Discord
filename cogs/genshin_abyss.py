import asyncio
from typing import Literal, Optional, Sequence, Union
import discord
import genshin
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from data.database import SpiralAbyssData, db
from utility import EmbedTemplate, config, custom_log
from yuanshen import draw, genshin_app, parser


class SpiralAbyss:
    #Spiral abyss

    class AbyssRecordDropdown(discord.ui.Select):
        # 選擇深淵歷史紀錄的下拉選單 Spiral Abyss options

        def __init__(
            self,
            user: Union[discord.User, discord.Member],
            abyss_data_list: Sequence[SpiralAbyssData],
        ):
            def honor(abyss: genshin.models.SpiralAbyss) -> str:
                #判斷一些特殊紀錄，例如12通、單通、雙通 check if floor 12 cleared and 36 stars and check numvber of character
                if abyss.total_stars == 36:
                    if abyss.total_battles == 12:
                        return "(👑)"
                    last_battles = abyss.floors[-1].chambers[-1].battles
                    num_of_characters = max(
                        len(last_battles[0].characters), len(last_battles[1].characters)
                    )
                    if num_of_characters == 2:
                        return "two characters"
                    if num_of_characters == 1:
                        return "one character"
                return ""

            options = [
                discord.SelectOption(
                    label=f"[season: {abyss.season}] ★ {abyss.abyss.total_stars} {honor(abyss.abyss)}",
                    description=(
                        f"{abyss.abyss.start_time.astimezone().strftime('%Y.%m.%d')} ~ "
                        f"{abyss.abyss.end_time.astimezone().strftime('%Y.%m.%d')}"
                    ),
                    value=str(i),
                )
                for i, abyss in enumerate(abyss_data_list)
            ]
            super().__init__(placeholder="Choose season:", options=options)
            self.user = user
            self.abyss_data_list = abyss_data_list

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer()
            index = int(self.values[0])
            await SpiralAbyss.presentation(
                interaction, self.user, self.abyss_data_list[index], view_item=self
            )

    class AbyssFloorDropdown(discord.ui.Select):
        #選擇深淵樓層的下拉選單 abyss floor options

        def __init__(
            self,
            overview: discord.Embed,
            abyss_data: SpiralAbyssData,
            save_or_remove: Literal["SAVE", "REMOVE"],
        ):
            # 第一個選項依據參數顯示為保存或是刪除紀錄 show options save or delete buttons?
            _description = "Save data to database" if save_or_remove == "SAVE" else "Delete record from database"
            option = [
                discord.SelectOption(
                    label=f"{'📁 Sace Data' if save_or_remove == 'SAVE' else '❌ Delete Data'}",
                    description=_description,
                    value=save_or_remove,
                )
            ]
            options = option + [
                discord.SelectOption(
                    label=f"[★{floor.stars}] Floor #{floor.floor} ",
                    description=parser.parse_abyss_chamber(floor.chambers[-1]),
                    value=str(i),
                )
                for i, floor in enumerate(abyss_data.abyss.floors)
            ]
            super().__init__(placeholder="Choose a floor", options=options)
            self.embed = overview
            self.abyss_data = abyss_data
            self.save_or_remove = save_or_remove

        async def callback(self, interaction: discord.Interaction):
            # 儲存或刪除深淵資料 save or delete abyss data
            if self.values[0] == self.save_or_remove:
                # 檢查互動者是否為深淵資料本人 check if user has abyss saved data
                if interaction.user.id == self.abyss_data.id:
                    if self.save_or_remove == "SAVE":
                        await db.spiral_abyss.add(self.abyss_data)
                        await interaction.response.send_message(
                            embed=EmbedTemplate.normal("current abyss data saved"), ephemeral=True
                        )
                    else:  # self.save_or_remove == 'REMOVE'
                        await db.spiral_abyss.remove(self.abyss_data.id, self.abyss_data.season)
                        await interaction.response.send_message(
                            embed=EmbedTemplate.normal("current abyss data deketed"), ephemeral=True
                        )
                else:
                    await interaction.response.send_message(
                        embed=EmbedTemplate.error("Invalid User"), ephemeral=True
                    )
            else:  # 繪製樓層圖片 draw abyss card
                fp = draw.draw_abyss_card(
                    self.abyss_data.abyss.floors[int(self.values[0])],
                    self.abyss_data.characters,
                )
                fp.seek(0)
                self.embed.set_image(url="attachment://image.jpeg")
                await interaction.response.edit_message(
                    embed=self.embed, attachments=[discord.File(fp, "image.jpeg")]
                )

    @staticmethod
    async def presentation(
        interaction: discord.Interaction,
        user: Union[discord.User, discord.Member],
        abyss_data: SpiralAbyssData,
        *,
        view_item: Optional[discord.ui.Item] = None,
    ):
        embed = parser.parse_abyss_overview(abyss_data.abyss)
        embed.title = f"{user.display_name} Player Abyss record"
        embed.set_thumbnail(url=user.display_avatar.url)
        view = None
        if len(abyss_data.abyss.floors) > 0:
            view = discord.ui.View(timeout=config.discord_view_short_timeout)
            if view_item:  # 從歷史紀錄取得資料，所以第一個選項是刪除紀錄 fetch abyss data from database, display remove option
                view.add_item(SpiralAbyss.AbyssFloorDropdown(embed, abyss_data, "REMOVE"))
                view.add_item(view_item)
            else:  # 從Hoyolab取得資料，所以第一個選項是保存紀錄 fetch data from hoyolab and save to database
                view.add_item(SpiralAbyss.AbyssFloorDropdown(embed, abyss_data, "SAVE"))
        await interaction.edit_original_response(embed=embed, view=view, attachments=[])

    @staticmethod
    async def abyss(
        interaction: discord.Interaction,
        user: Union[discord.User, discord.Member],
        season_choice: Literal["THIS_SEASON", "PREVIOUS_SEASON", "HISTORICAL_RECORD"],
    ):
        if season_choice == "HISTORICAL_RECORD":  # 查詢歷史紀錄 check record
            abyss_data_list = await db.spiral_abyss.get(user.id)
            if len(abyss_data_list) == 0:
                await interaction.response.send_message(
                    embed=EmbedTemplate.normal("user does not have saved records")
                )
            else:
                view = discord.ui.View(timeout=config.discord_view_short_timeout)
                view.add_item(SpiralAbyss.AbyssRecordDropdown(user, abyss_data_list))
                await interaction.response.send_message(view=view)
        else:  # 查詢 Hoyolab 紀錄 (THIS_SEASON、PREVIOUS_SEASON) check hoyolab season record
            try:
                defer, abyss_data = await asyncio.gather(
                    interaction.response.defer(),
                    genshin_app.get_spiral_abyss(user.id, (season_choice == "PREVIOUS_SEASON")),
                )
            except Exception as e:
                await interaction.edit_original_response(embed=EmbedTemplate.error(e))
            else:
                await SpiralAbyss.presentation(interaction, user, abyss_data)


class SpiralAbyssCog(commands.Cog, name="Spyral Abyss"):
    #斜線指令 slash commands

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------
    # 取得深境螺旋資訊 check spiral abyss records
    @app_commands.command(name="Abyss Record", description="Check Spiral Abyss Record")
    @app_commands.checks.cooldown(1, config.slash_cmd_cooldown)
    @app_commands.rename(season="Season", user="User")
    @app_commands.describe(season="Choose season or history", user="Check another user's data will check current user if no response")
    @app_commands.choices(
        season=[
            Choice(name="Currect season", value="THIS_SEASON"),
            Choice(name="Last Season", value="PREVIOUS_SEASON"),
            Choice(name="Season History", value="HISTORICAL_RECORD"),
        ]
    )
    @custom_log.SlashCommandLogger
    async def slash_abyss(
        self,
        interaction: discord.Interaction,
        season: Literal["THIS_SEASON", "PREVIOUS_SEASON", "HISTORICAL_RECORD"],
        user: Optional[discord.User] = None,
    ):
        await SpiralAbyss.abyss(interaction, user or interaction.user, season)

    @slash_abyss.error
    async def on_slash_abyss_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                embed=EmbedTemplate.error(f"Set cooldown{config.slash_cmd_cooldown}seonds, please try again later~"),
                ephemeral=True,
            )


async def setup(client: commands.Bot):
    await client.add_cog(SpiralAbyssCog(client))

    # -------------------------------------------------------------
    # 下面為Context Menu指令 button context menu commands?
    @client.tree.context_menu(name="PRevious season abyss record)")
    @custom_log.ContextCommandLogger
    async def context_abyss_previous(interaction: discord.Interaction, user: discord.User):
        await SpiralAbyss.abyss(interaction, user, "PREVIOUS_SEASON")

    @client.tree.context_menu(name="current season abyss record)")
    @custom_log.ContextCommandLogger
    async def context_abyss(interaction: discord.Interaction, user: discord.User):
        await SpiralAbyss.abyss(interaction, user, "THIS_SEASON")
